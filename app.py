"""Main Flask application for Chatterbox."""

import io
import logging
import mimetypes
import os
import secrets
import string
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_session import Session
from flask_socketio import SocketIO
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import OperationalError
from werkzeug.security import check_password_hash, generate_password_hash

from call_sessions import CallSessionManager
from event_handlers import register_event_handlers
from helpers import admin_required, login_required, logout_required
from flask import send_from_directory

from models import (
    db,
    BannedCountry,
    BannedIP,
    BlockedWord,
    CommunicationHub,
    Group,
    GroupMembership,
    GroupMessage,
    GroupMessageAttachment,
    MediaUploadToken,
    Message,
    MessageAttachment,
    ModeratorAssignment,
    TranslatedTranscript,
    User,
    CallSession,
    UserProfile,
    DisciplinaryAction,
    MarketplaceListing,
    EscrowTransaction,
    MarketplaceRequest,
)

from security_utils import (
    ConversationIdentifierError,
    conversation_identifier_for_direct,
    conversation_identifier_for_group,
    export_conversation_key,
    parse_conversation_identifier,
)

from translation_utils import TranslationError, translate_text


app = Flask(__name__)

logger = logging.getLogger(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config.setdefault("CONVERSATION_KEY_SECRET", os.environ.get("CONVERSATION_KEY_SECRET"))
if not app.config.get("CONVERSATION_KEY_SECRET"):
    app.config["CONVERSATION_KEY_SECRET"] = app.config["SECRET_KEY"]

# reload templates
app.config["TEMPLATES_AUTO_RELOAD"] = True

# configure uploads
uploads_path = Path(app.instance_path) / "uploads"
uploads_path.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(uploads_path)
app.config.setdefault("MAX_UPLOAD_SIZE", 25 * 1024 * 1024)  # 25 MB default

# configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatterbox.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# initialize SocketIO
socketio = SocketIO(app)
call_manager = CallSessionManager()
register_event_handlers(socketio, app, call_manager)


def generate_group_code(length: int = 8) -> str:
    """Generate a unique invite code for a hidden group."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not Group.query.filter_by(code=code).first():
            return code


def purge_expired_groups() -> None:
    """Remove expired hidden groups and their related data."""
    now = datetime.now(timezone.utc)
    expired_groups = Group.query.filter(
        Group.expire_at.isnot(None), Group.expire_at < now
    ).all()
    if not expired_groups:
        return
    for group in expired_groups:
        db.session.delete(group)
    db.session.commit()


def get_membership(user_id: int, group_id: int):
    """Return membership for a user in a group."""
    return GroupMembership.query.filter_by(
        user_id=user_id, group_id=group_id
    ).first()


def get_client_ip() -> str:
    """Return the originating IP for the current request."""

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def get_client_country() -> str:
    """Return the two-letter country code from headers when available."""

    country_code = request.headers.get("X-Country-Code", "")
    return country_code.strip().upper()


LOCK_TIMEOUT_MINUTES = 6


def _normalize_ip(candidate: str) -> str | None:
    """Return a canonical IP address string or ``None`` when invalid."""

    if not candidate:
        return None
    try:
        return str(ip_address(candidate.strip()))
    except ValueError:
        return None


def _load_watchlist_from_file(path: Path) -> set[str]:
    """Load IP addresses from a local watchlist file."""

    ips: set[str] = set()
    if not path.exists():
        return ips
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to read police watchlist file %s: %s", path, exc)
        return ips
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        normalized = _normalize_ip(line)
        if normalized:
            ips.add(normalized)
    return ips


def _load_watchlist_from_url(url: str) -> set[str]:
    """Fetch IP addresses from an external watchlist URL."""

    ips: set[str] = set()
    if not url:
        return ips
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - network
        logger.warning("Police IP feed request failed for %s: %s", url, exc)
        return ips
    if not response.ok:
        logger.warning(
            "Police IP feed %s returned status %s", url, response.status_code
        )
        return ips
    for raw_line in response.text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        normalized = _normalize_ip(line)
        if normalized:
            ips.add(normalized)
    return ips


def refresh_police_watchlist(force: bool = False) -> None:
    """Refresh the banned IP table with the police watchlist."""

    global _police_watchlist_last_sync

    interval_seconds = POLICE_IP_REFRESH_INTERVAL.total_seconds()
    now = time.monotonic()
    with _police_watchlist_lock:
        if (
            not force
            and interval_seconds > 0
            and now - _police_watchlist_last_sync < interval_seconds
        ):
            return

        watch_ips: set[str] = set()
        watch_ips.update(_load_watchlist_from_file(POLICE_WATCHLIST_PATH))
        for url in DEFAULT_POLICE_IP_FEEDS:
            watch_ips.update(_load_watchlist_from_url(url))

        if not watch_ips:
            _police_watchlist_last_sync = now
            return

        new_entries = 0
        for ip_value in watch_ips:
            try:
                exists = (
                    BannedIP.query.filter(
                        func.lower(BannedIP.ip_address) == ip_value.lower()
                    ).first()
                )
            except OperationalError:
                db.create_all()
                exists = (
                    BannedIP.query.filter(
                        func.lower(BannedIP.ip_address) == ip_value.lower()
                    ).first()
                )
            if exists:
                continue
            db.session.add(
                BannedIP(
                    ip_address=ip_value,
                    reason="Law-enforcement watchlist auto-ban",
                )
            )
            new_entries += 1

        if new_entries:
            try:
                db.session.commit()
            except Exception as exc:  # pragma: no cover - database error
                db.session.rollback()
                logger.exception("Failed to persist police watchlist bans: %s", exc)
            else:
                logger.info("Added %s police watchlist IP bans", new_entries)
        _police_watchlist_last_sync = now


@app.route("/uploads/<path:filename>")
def serve_upload(filename: str):
    """Serve media uploads from the instance storage directory."""

    uploads_dir = Path(app.config["UPLOAD_FOLDER"])
    return send_from_directory(uploads_dir, filename)


@app.route("/api/uploads", methods=["POST"])
def create_upload():
    """Accept an uploaded media blob and issue a token for later attachment."""

    if not session.get("user_id"):
        return jsonify({"error": "Authentication required."}), 401

    if request.content_length and request.content_length > app.config["MAX_UPLOAD_SIZE"]:
        return jsonify({"error": "Upload exceeds size limit."}), 413

    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename is None:
        return jsonify({"error": "No media file provided."}), 400

    provided_mime = request.form.get("mime_type") or uploaded_file.mimetype
    if not provided_mime:
        provided_mime = mimetypes.guess_type(uploaded_file.filename)[0]

    media_category = categorize_mime_type(provided_mime or "")
    if not media_category:
        return jsonify({"error": "Unsupported media type."}), 400

    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"error": "User not found."}), 404

    privilege_code = (request.form.get("privilege_code") or "").strip() or None
    if media_category == "file" and not has_file_privilege(user, privilege_code):
        return (
            jsonify(
                {
                    "error": "File uploads are limited to elevated members or holders of a special access code.",
                }
            ),
            403,
        )

    duration_seconds = None
    if request.form.get("duration"):
        try:
            duration_seconds = float(request.form["duration"])
        except (TypeError, ValueError):
            duration_seconds = None

    extension = Path(uploaded_file.filename or "").suffix
    if not extension:
        extension = mimetypes.guess_extension(provided_mime or "") or ""
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    filename = f"{uuid.uuid4().hex}{extension or ''}"
    file_path = Path(app.config["UPLOAD_FOLDER"]) / filename

    blur_faces = request.form.get("blur_faces") == "1"

    try:
        if media_category == "image":
            processed_bytes, provided_mime = normalize_image_upload(
                uploaded_file, provided_mime, blur_faces=blur_faces
            )
            with open(file_path, "wb") as output_handle:
                output_handle.write(processed_bytes)
        else:
            uploaded_file.stream.seek(0)
            uploaded_file.save(file_path)
    except ValueError as exc:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)}), 400
    except OSError:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        return jsonify({"error": "Unable to save uploaded file."}), 500

    upload_token = MediaUploadToken(
        user_id=session["user_id"],
        storage_path=filename,
        media_type=media_category,
        mime_type=provided_mime,
        duration_seconds=duration_seconds,
    )
    db.session.add(upload_token)
    db.session.flush()
    token_value = upload_token.token
    db.session.commit()

    return (
        jsonify(
            {
                "token": token_value,
                "media_type": upload_token.media_type,
                "mime_type": upload_token.mime_type,
                "url": url_for("serve_upload", filename=filename),
                "duration_seconds": upload_token.duration_seconds,
            }
        ),
        201,
    )


def ensure_schema() -> None:
    """Ensure upgraded installations have the required database schema."""

    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        if "user" not in existing_tables:
            db.create_all()
            return

        user_columns = {column["name"] for column in inspector.get_columns("user")}
        alter_statements = []

        if "xp" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN xp INTEGER NOT NULL DEFAULT 0"
            )
        if "level" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
            )
        if "badge" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN badge VARCHAR(50) NOT NULL DEFAULT 'Newcomer'"
            )
        if "last_arrival_at" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN last_arrival_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        if "pin_hash" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN pin_hash VARCHAR(200)"
            )
        if "is_admin" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
            )
        if "is_blocked" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT 0"
            )
        if "profile_features_enabled" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN profile_features_enabled BOOLEAN NOT NULL DEFAULT 0"
            )
        if "allow_file_uploads" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN allow_file_uploads BOOLEAN NOT NULL DEFAULT 0"
            )
        if "marketplace_enabled" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN marketplace_enabled BOOLEAN NOT NULL DEFAULT 0"
            )
        if "created_at" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            )
        if "muted_until" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN muted_until DATETIME"
            )
        if "banned_until" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN banned_until DATETIME"
            )
        if "warning_count" not in user_columns:
            alter_statements.append(
                "ALTER TABLE user ADD COLUMN warning_count INTEGER NOT NULL DEFAULT 0"
            )

        for statement in alter_statements:
            db.session.execute(text(statement))

        if alter_statements:
            db.session.commit()

        updates_performed = False
        if "message" in existing_tables:
            db.session.execute(text("UPDATE message SET text='' WHERE text IS NULL"))
            updates_performed = True
        if "group_message" in existing_tables:
            db.session.execute(
                text("UPDATE group_message SET text='' WHERE text IS NULL")
            )
            updates_performed = True
        if updates_performed:
            db.session.commit()

        # Ensure any newly introduced tables are created.
        db.create_all()


ensure_schema()


ALLOWED_MEDIA_TYPES = {
    "image": {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    },
    "audio": {
        "audio/mpeg",
        "audio/ogg",
        "audio/webm",
        "audio/wav",
    },
    "video": {
        "video/webm",
        "video/mp4",
        "video/ogg",
    },
    "file": {
        "application/pdf",
        "application/zip",
        "application/x-zip-compressed",
        "application/x-7z-compressed",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
    },
}

PAYMENT_METHODS = [
    "PayPal",
    "Stripe",
    "Wise",
    "Bank Transfer",
    "MobilePay",
    "Vipps",
    "Cash App",
    "Venmo",
    "Apple Pay",
    "Google Pay",
    "Bitcoin",
    "Ethereum",
    "USDC",
]

FILE_PRIVILEGE_CODES = {
    code.strip()
    for code in os.environ.get("FILE_PRIVILEGE_CODES", "").split(",")
    if code.strip()
}

MAX_IMAGE_DIMENSION = 1280
ELEVATED_LEVEL_THRESHOLD = 3

FACE_CASCADE = cv2.CascadeClassifier(
    str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
)

POLICE_IP_REFRESH_INTERVAL = timedelta(
    hours=int(os.environ.get("POLICE_IP_REFRESH_HOURS", "12"))
)
POLICE_WATCHLIST_PATH = Path(__file__).resolve().parent / "misc" / "police_watchlist.txt"
DEFAULT_POLICE_IP_FEEDS = [
    url.strip()
    for url in os.environ.get("POLICE_IP_SOURCES", "").split(",")
    if url.strip()
]
if not DEFAULT_POLICE_IP_FEEDS:
    DEFAULT_POLICE_IP_FEEDS = [
        "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/iblocklist_policia.netset",
    ]

_police_watchlist_lock = threading.Lock()
_police_watchlist_last_sync = 0.0


def categorize_mime_type(mime_type: str) -> str | None:
    """Return the media category for a MIME type."""

    if not mime_type:
        return None
    normalized = mime_type.lower()
    for category, allowed_set in ALLOWED_MEDIA_TYPES.items():
        if normalized in allowed_set or normalized.startswith(f"{category}/"):
            return category
    return None


def has_file_privilege(user: User | None, provided_code: str | None) -> bool:
    """Return whether a user can upload arbitrary files."""

    if not user:
        return False
    if user.allow_file_uploads or user.is_admin or user.is_moderator:
        return True
    if user.level >= ELEVATED_LEVEL_THRESHOLD:
        return True
    if provided_code and provided_code in FILE_PRIVILEGE_CODES:
        return True
    return False


def normalize_image_upload(
    file_storage, mime_type: str | None, blur_faces: bool = False
) -> tuple[bytes, str]:
    """Normalize uploaded images by stripping metadata and optionally blurring faces."""

    try:
        payload = file_storage.read()
    except Exception as exc:  # pragma: no cover - handled gracefully
        raise ValueError("Unable to read image payload.") from exc

    if not payload:
        raise ValueError("Empty image payload.")

    try:
        image = Image.open(io.BytesIO(payload))
    except (OSError, ValueError) as exc:  # pragma: no cover - invalid images
        raise ValueError("Unsupported or corrupted image data.") from exc

    image = image.convert("RGB")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image dimensions.")

    scale = min(MAX_IMAGE_DIMENSION / float(width), MAX_IMAGE_DIMENSION / float(height), 1.0)
    if scale < 1.0:
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size, Image.LANCZOS)

    if blur_faces and not FACE_CASCADE.empty():
        np_image = np.array(image)
        gray = cv2.cvtColor(np_image, cv2.COLOR_RGB2GRAY)
        faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5)
        for (x, y, w, h) in faces:
            roi = np_image[y : y + h, x : x + w]
            kernel = max(15, (max(w, h) // 6) | 1)
            np_image[y : y + h, x : x + w] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
        image = Image.fromarray(np_image)

    output = io.BytesIO()
    image.save(output, format="JPEG", optimize=True, quality=85)
    output.seek(0)
    return output.read(), "image/jpeg"


def price_to_cents(value: str) -> int:
    """Convert a decimal string to cents."""

    try:
        quantized = Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid price value.")
    cents = int(quantized * 100)
    if cents < 0:
        raise ValueError("Price must be positive.")
    return cents


@app.before_request
def enforce_bans():
    """Prevent banned IP addresses or countries from accessing the site."""

    if request.endpoint and request.endpoint.startswith("static"):
        return

    refresh_police_watchlist()

    ip_address = get_client_ip()
    country_code = get_client_country()

    try:
        ip_ban = (
            BannedIP.query.filter(
                func.lower(BannedIP.ip_address) == ip_address.lower()
            ).first()
            if ip_address
            else None
        )
        country_ban = (
            BannedCountry.query.filter(
                func.upper(BannedCountry.country_code) == country_code
            ).first()
            if country_code
            else None
        )
    except OperationalError:
        db.create_all()
        ip_ban = (
            BannedIP.query.filter(
                func.lower(BannedIP.ip_address) == ip_address.lower()
            ).first()
            if ip_address
            else None
        )
        country_ban = (
            BannedCountry.query.filter(
                func.upper(BannedCountry.country_code) == country_code
            ).first()
            if country_code
            else None
        )

    if ip_ban:
        session.clear()
        return render_template(
            "access_denied.html",
            title="Access blocked",
            reason="Your IP address has been banned by an administrator.",
        ), 403

    if country_ban:
        session.clear()
        return render_template(
            "access_denied.html",
            title="Access blocked",
            reason="Connections from your country have been blocked by an administrator.",
        ), 403

    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        if user and user.banned_until:
            if user.banned_until > datetime.now(timezone.utc):
                session.clear()
                return render_template(
                    "access_denied.html",
                    title="Account suspended",
                    reason="Your account access is temporarily suspended by an administrator.",
                ), 403
            if user.banned_until <= datetime.now(timezone.utc):
                user.banned_until = None
                db.session.commit()


@app.before_first_request
def bootstrap_watchlists() -> None:
    """Prime the police watchlist bans when the server boots."""

    refresh_police_watchlist(force=True)


@app.context_processor
def inject_profile():
    """Expose the logged-in user's profile to templates."""
    user_id = session.get("user_id")
    if not user_id:
        return {}
    user = User.query.get(user_id)
    if not user:
        return {}
    session["is_admin"] = user.is_admin
    return {"current_user_profile": user}


@app.context_processor
def inject_lock_settings():
    """Expose security lock settings globally."""

    return {"lock_timeout_minutes": LOCK_TIMEOUT_MINUTES}


@app.context_processor
def inject_payment_methods():
    """Expose supported payment options to templates."""

    return {"supported_payment_methods": PAYMENT_METHODS}


@app.route("/")
def home():
    """Home page."""

    return render_template("home.html")


@app.route("/author")
def author():
    """Author page."""

    return render_template("author.html")


@app.route("/login", methods=["GET", "POST"])
@logout_required
def login():
    """Handle user login. Logout required."""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Username and password are required!")
            return redirect(url_for("login"))

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid username or password!")
            return redirect(url_for("login"))

        if user.banned_until and user.banned_until > datetime.now(timezone.utc):
            flash("Your account is temporarily suspended. Please contact support for assistance.")
            return redirect(url_for("login"))

        ip_address = get_client_ip()
        country_code = get_client_country()
        if ip_address and BannedIP.query.filter(
            func.lower(BannedIP.ip_address) == ip_address.lower()
        ).first():
            flash("This IP address is banned. Contact support if you believe this is an error.")
            return redirect(url_for("login"))
        if country_code and BannedCountry.query.filter(
            func.upper(BannedCountry.country_code) == country_code
        ).first():
            flash("Connections from your region are currently blocked.")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["username"] = user.username
        session["is_admin"] = user.is_admin
        user.last_arrival_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Logged in successfully!")
        return redirect(url_for("chat"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Handle user logout."""

    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for("home"))


@app.route("/security/update-pin", methods=["POST"])
@login_required
def update_pin():
    """Allow users to set or update their security PIN."""

    new_pin = (request.form.get("pin") or "").strip()
    confirm_pin = (request.form.get("confirm-pin") or "").strip()
    current_pin = (request.form.get("current-pin") or "").strip()
    user = User.query.get(session["user_id"])

    if not new_pin.isdigit() or len(new_pin) != 4:
        flash("PIN must be a 4-digit number.")
        return redirect(request.referrer or url_for("chat"))

    if confirm_pin and new_pin != confirm_pin:
        flash("PIN confirmation does not match.")
        return redirect(request.referrer or url_for("chat"))

    if user.pin_hash:
        if not current_pin:
            flash("Enter your current PIN before updating it.")
            return redirect(request.referrer or url_for("chat"))
        if not check_password_hash(user.pin_hash, current_pin):
            flash("Current PIN is incorrect.")
            return redirect(request.referrer or url_for("chat"))

    user.pin_hash = generate_password_hash(new_pin)
    db.session.commit()
    flash("Security PIN updated successfully.")
    return redirect(request.referrer or url_for("chat"))


@app.route("/security/verify-pin", methods=["POST"])
@login_required
def verify_pin():
    """Verify the provided PIN and unlock the interface if valid."""

    payload = request.get_json(silent=True) or {}
    pin = (payload.get("pin") or "").strip()
    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    if not user.pin_hash:
        return jsonify({"success": True, "message": "No PIN configured."})
    if not pin:
        return jsonify({"success": False, "message": "PIN is required."}), 400
    if not check_password_hash(user.pin_hash, pin):
        return jsonify({"success": False, "message": "Incorrect PIN."}), 403
    return jsonify({"success": True})


@app.route("/api/translate", methods=["POST"])
@login_required
def api_translate():
    """Translate text snippets for chat or caption workflows."""

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text is required."}), 400

    target_language = (payload.get("target_language") or "en").strip()
    source_language = (payload.get("source_language") or "auto").strip() or "auto"

    try:
        translated = translate_text(text, target_language, source_language)
    except TranslationError as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"translation": translated})


@app.route("/admin/discipline", methods=["POST"])
@admin_required
def admin_discipline():
    """Allow administrators to warn, mute, or ban a user for a duration."""

    payload = request.get_json(silent=True) or request.form.to_dict()
    user_id = payload.get("user_id")
    action_type = (payload.get("action") or "").strip().lower()
    reason = (payload.get("reason") or "").strip() or None
    duration_hours = payload.get("duration_hours") or payload.get("hours")

    try:
        duration_hours = int(duration_hours) if duration_hours is not None else 0
        if duration_hours < 0:
            raise ValueError
    except (TypeError, ValueError):
        duration_hours = 0

    if not user_id:
        return jsonify({"error": "User ID is required."}), 400

    target_user = User.query.get(int(user_id))
    if not target_user:
        return jsonify({"error": "User not found."}), 404

    expires_at = None
    if duration_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

    if action_type == "warn":
        target_user.warning_count += 1
    elif action_type == "mute":
        target_user.muted_until = expires_at
    elif action_type == "ban":
        target_user.banned_until = expires_at
    else:
        return jsonify({"error": "Unsupported action."}), 400

    record = DisciplinaryAction(
        user_id=target_user.id,
        issued_by=session["user_id"],
        action_type=action_type,
        reason=reason,
        duration_hours=duration_hours or None,
        expires_at=expires_at,
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({
        "success": True,
        "action": action_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "warning_count": target_user.warning_count,
    })


@app.route("/profile/details", methods=["POST"])
@login_required
def update_profile_details():
    """Allow eligible users to update extended profile information."""

    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"error": "User not found."}), 404
    if not (user.profile_features_enabled or user.is_admin or user.is_moderator):
        return jsonify({"error": "Profile customization is disabled for this account."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    display_name = (payload.get("display_name") or "").strip()
    bio = (payload.get("bio") or "").strip()
    favorite_languages = (payload.get("favorite_languages") or "").strip()
    social_links = (payload.get("social_links") or "").strip()
    theme_color = (payload.get("theme_color") or "").strip()

    profile = user.profile
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)

    profile.display_name = display_name or None
    profile.bio = bio or None
    profile.favorite_languages = favorite_languages or None
    profile.social_links = social_links or None
    profile.theme_color = theme_color or None
    profile.updated_at = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify({"success": True})


@app.route("/register", methods=["GET", "POST"])
@logout_required
def register():
    """Handle user registration. Logout required."""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm-password")
        license = request.form.get("license")

        if not username or not password:
            flash("Username and password are required!")
            return redirect(url_for("register"))

        if not username.isalnum() or len(username) > 20:
            flash(
                "Username must contain only letters and digits and be at most 20 characters long!"
            )
            return redirect(url_for("register"))

        if (
            len(password) < 8
            or len(password) > 200
            or not any(char.isupper() for char in password)
            or not any(char.islower() for char in password)
            or not any(char.isdigit() for char in password)
        ):
            flash(
                "Password must be between 8 and 200 characters long and contain at least one uppercase letter, one lowercase letter, and one digit!"
            )
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for("register"))

        if not license:
            flash("You must agree to the license agreement!")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists!")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/chat")
@login_required
def chat():
    """Render the chat page with direct or group conversations."""

    current_user = User.query.get(session["user_id"])
    purge_expired_groups()
    recipient_id = request.args.get("recipient_id", type=int)
    group_id = request.args.get("group_id", type=int)

    if recipient_id and group_id:
        flash("Select either a direct chat or a hidden group chat, not both.")
        return redirect(url_for("chat"))

    recipient = None
    messages = []
    group = None
    membership = None
    group_messages = []
    translated_captions = []
    call_identifier = None
    conversation_identifier = None
    active_hubs = (
        CommunicationHub.query.filter_by(is_enabled=True)
        .order_by(CommunicationHub.name.asc())
        .all()
    )

    if recipient_id:
        recipient = User.query.get(recipient_id)
        if not recipient:
            flash("Recipient not found!")
            return redirect(url_for("chat"))
        messages = (
            Message.query.filter(
                ((Message.user_id == session["user_id"]) & (Message.recipient_id == recipient_id))
                | ((Message.user_id == recipient_id) & (Message.recipient_id == session["user_id"]))
            )
            .order_by(Message.timestamp.asc())
            .all()
        )
        participants = sorted([session["user_id"], recipient_id])
        call_identifier = f"direct-{participants[0]}-{participants[1]}"
        conversation_identifier = conversation_identifier_for_direct(participants[0], participants[1])
        translated_captions = (
            TranslatedTranscript.query.filter_by(call_id=call_identifier)
            .order_by(TranslatedTranscript.created_at.asc())
            .limit(200)
            .all()
        )

    if group_id:
        group = Group.query.get(group_id)
        if not group:
            flash("Hidden group not found or already removed.")
            return redirect(url_for("chat"))
        if group.expire_at and group.expire_at < datetime.now(timezone.utc):
            db.session.delete(group)
            db.session.commit()
            flash("That hidden group has expired and was removed.")
            return redirect(url_for("chat"))
        membership = get_membership(session["user_id"], group_id)
        if not membership:
            flash("You are not part of this hidden group.")
            return redirect(url_for("chat"))
        group_messages = (
            GroupMessage.query.filter_by(group_id=group_id)
            .order_by(GroupMessage.timestamp.asc())
            .all()
        )
        call_identifier = f"group-{group_id}"
        conversation_identifier = conversation_identifier_for_group(group_id)
        translated_captions = (
            TranslatedTranscript.query.filter_by(call_id=call_identifier)
            .order_by(TranslatedTranscript.created_at.asc())
            .limit(200)
            .all()
        )

    allow_files = False
    marketplace_access = False
    if current_user:
        allow_files = (
            current_user.allow_file_uploads
            or current_user.is_admin
            or current_user.is_moderator
            or current_user.level >= ELEVATED_LEVEL_THRESHOLD
        )
        marketplace_access = (
            current_user.marketplace_enabled
            or current_user.is_admin
            or current_user.is_moderator
        )

    now = datetime.now(timezone.utc)
    marketplace_listings = (
        MarketplaceListing.query.filter(
            MarketplaceListing.is_active.is_(True),
            (MarketplaceListing.expires_at.is_(None)) | (MarketplaceListing.expires_at >= now),
        )
        .order_by(MarketplaceListing.expires_at.asc().nullslast(), MarketplaceListing.view_count.desc())
        .limit(12)
        .all()
    )
    marketplace_requests = (
        MarketplaceRequest.query.filter(
            (MarketplaceRequest.expires_at.is_(None)) | (MarketplaceRequest.expires_at >= now)
        )
        .order_by(MarketplaceRequest.created_at.desc())
        .limit(20)
        .all()
    )

    soon_threshold = now + timedelta(hours=24)
    for listing in marketplace_listings:
        listing.closing_soon = bool(
            listing.expires_at and listing.expires_at <= soon_threshold
        )
        listing.popular = listing.view_count >= 25
    for request_item in marketplace_requests:
        request_item.closing_soon = bool(
            request_item.expires_at and request_item.expires_at <= soon_threshold
        )

    return render_template(
        "chat.html",
        recipient=recipient,
        recipient_id=recipient_id,
        group=group,
        group_messages=group_messages,
        membership=membership,
        hubs=active_hubs,
        translated_captions=translated_captions,
        call_identifier=call_identifier,
        conversation_identifier=conversation_identifier,
        messages=messages,
        marketplace_listings=marketplace_listings,
        marketplace_requests=marketplace_requests,
        allow_files=1 if allow_files else 0,
        marketplace_access=marketplace_access,
    )


@app.route("/chat/start", methods=["POST"])
@login_required
def chat_start():
    """Handle starting a chat with a new user. Login required."""

    payload = request.get_json(silent=True)
    if payload:
        username = (payload.get("username") or "").strip()
    else:
        username = (request.form.get("username") or "").strip()

    if not username:
        message = "Recipient username is required!"
        if payload is not None:
            return jsonify({"message": message}), 400
        flash(message)
        return redirect(url_for("chat"))

    if username == session["username"]:
        message = "You cannot start a chat with yourself!"
        if payload is not None:
            return jsonify({"message": message}), 400
        flash(message)
        return redirect(url_for("chat"))

    recipient = User.query.filter_by(username=username).first()
    if not recipient:
        message = "User not found!"
        if payload is not None:
            return jsonify({"message": message}), 404
        flash(message)
        return redirect(url_for("chat"))

    if payload is not None:
        return jsonify({
            "conversation": {
                "id": recipient.id,
                "name": recipient.username,
                "display_name": recipient.username,
                "type": "direct"
            }
        }), 201

    return redirect(url_for("chat", recipient_id=recipient.id))


def _current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


@app.route("/marketplace/listings", methods=["POST"])
@login_required
def create_listing():
    """Create a marketplace listing with escrow support."""

    user = _current_user()
    if not user or not (user.marketplace_enabled or user.is_admin or user.is_moderator):
        return jsonify({"error": "Marketplace access is disabled for this account."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    currency = (payload.get("currency") or "USD").strip().upper()[:10]
    price_value = (payload.get("price") or payload.get("price_cents") or "").strip()
    expires_at_value = (payload.get("expires_at") or "").strip()

    if not title or not description:
        return jsonify({"error": "Title and description are required."}), 400

    try:
        price_cents = (
            int(price_value)
            if price_value.isdigit()
            else price_to_cents(price_value)
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    expires_at = None
    if expires_at_value:
        try:
            expires_at = datetime.fromisoformat(expires_at_value)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expires_at = expires_at.astimezone(timezone.utc)
        except ValueError:
            return jsonify({"error": "Invalid expiry date."}), 400

    listing = MarketplaceListing(
        seller_id=user.id,
        title=title,
        description=description,
        price_cents=price_cents,
        currency=currency,
        expires_at=expires_at,
    )
    db.session.add(listing)
    db.session.commit()

    return jsonify({"success": True, "listing_id": listing.id})


@app.route("/marketplace/requests", methods=["POST"])
@login_required
def create_marketplace_request():
    """Allow users to post purchase requests."""

    user = _current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    payload = request.get_json(silent=True) or request.form.to_dict()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    budget_value = (payload.get("budget") or "").strip()
    expires_at_value = (payload.get("expires_at") or "").strip()

    if not title or not description:
        return jsonify({"error": "Title and description are required."}), 400

    budget_cents = None
    if budget_value:
        try:
            budget_cents = price_to_cents(budget_value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    expires_at = None
    if expires_at_value:
        try:
            expires_at = datetime.fromisoformat(expires_at_value)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expires_at = expires_at.astimezone(timezone.utc)
        except ValueError:
            return jsonify({"error": "Invalid expiry date."}), 400

    purchase_request = MarketplaceRequest(
        requester_id=user.id,
        title=title,
        description=description,
        budget_cents=budget_cents,
        expires_at=expires_at,
    )
    db.session.add(purchase_request)
    db.session.commit()

    return jsonify({"success": True, "request_id": purchase_request.id})


@app.route("/marketplace/escrow/<int:listing_id>", methods=["POST"])
@login_required
def start_escrow(listing_id: int):
    """Initiate an escrow transaction for a listing."""

    user = _current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    listing = MarketplaceListing.query.get(listing_id)
    if not listing or not listing.is_active:
        return jsonify({"error": "Listing not available."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    payment_method = (payload.get("payment_method") or "").strip()
    if payment_method and payment_method not in PAYMENT_METHODS:
        return jsonify({"error": "Unsupported payment method."}), 400

    transaction = EscrowTransaction(
        listing_id=listing.id,
        buyer_id=user.id,
        amount_cents=listing.price_cents,
        payment_method=payment_method or None,
    )
    db.session.add(transaction)
    db.session.commit()

    return jsonify({"success": True, "escrow_id": transaction.id})


@app.route("/chat/user-list")
@login_required
def user_list():
    """Return the list of users the current user chatted with."""

    recent_users = (
        db.session.query(User, func.max(Message.timestamp).label("last_message_time"))
        .join(Message, (Message.user_id == User.id) | (Message.recipient_id == User.id))
        .filter((Message.user_id == session["user_id"]) | (Message.recipient_id == session["user_id"]))
        .filter(User.id != session["user_id"])
        .group_by(User.id)
        .order_by(func.max(Message.timestamp).desc())
        .all()
    )

    users = [
        {
            "id": user.id,
            "username": user.username,
            "is_admin": bool(user.is_admin),
            "is_moderator": bool(user.is_moderator),
        }
        for user, _ in recent_users
    ]
    return jsonify({"users": users})


@app.route("/api/conversations/key")
@login_required
def conversation_key():
    """Return a symmetric key for encrypting and decrypting conversation payloads."""

    conversation = (request.args.get("conversation") or "").strip()
    if not conversation:
        return jsonify({"error": "Conversation identifier is required."}), 400

    try:
        conversation_type, participants = parse_conversation_identifier(conversation)
    except ConversationIdentifierError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = session.get("user_id")
    normalized_identifier = None

    if conversation_type == "direct":
        if user_id not in participants:
            return jsonify({"error": "You are not part of this conversation."}), 403
        other_id = participants[0] if participants[1] == user_id else participants[1]
        other_user = User.query.get(other_id)
        if not other_user:
            return jsonify({"error": "Recipient not found."}), 404
        normalized_identifier = conversation_identifier_for_direct(participants[0], participants[1])
    elif conversation_type == "group":
        group_id = participants[0]
        membership = GroupMembership.query.filter_by(group_id=group_id, user_id=user_id).first()
        if not membership:
            return jsonify({"error": "You are not part of this conversation."}), 403
        normalized_identifier = conversation_identifier_for_group(group_id)
    else:
        return jsonify({"error": "Unsupported conversation type."}), 400

    key_b64 = export_conversation_key(normalized_identifier)
    return jsonify(
        {
            "conversation": normalized_identifier,
            "key": key_b64,
            "algorithm": "AES-GCM",
        }
    )


@app.route("/groups/create", methods=["POST"])
@login_required
def create_group():
    """Create a new hidden group chat."""

    purge_expired_groups()
    name = request.form.get("group-name", "").strip()
    alias = request.form.get("group-alias", "").strip()
    expiry = request.form.get("group-expiry", "").strip()

    if not name:
        flash("Group name is required!")
        return redirect(url_for("chat"))

    if not alias:
        flash("Alias is required to keep the chat anonymized!")
        return redirect(url_for("chat"))

    expire_at = None
    if expiry:
        try:
            minutes = int(expiry)
            if minutes <= 0:
                raise ValueError
            expire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        except ValueError:
            flash("Expiry must be a positive number of minutes.")
            return redirect(url_for("chat"))

    code = generate_group_code()
    group = Group(name=name, code=code, owner_id=session["user_id"], expire_at=expire_at)
    membership = GroupMembership(group=group, user_id=session["user_id"], alias=alias)
    db.session.add(group)
    db.session.add(membership)
    db.session.commit()

    flash(f"Hidden group created. Share the invite code: {code}")
    return redirect(url_for("chat", group_id=group.id))


@app.route("/groups/join", methods=["POST"])
@login_required
def join_group():
    """Join an existing hidden group by code."""

    purge_expired_groups()
    code = request.form.get("join-code", "").strip().upper()
    alias = request.form.get("join-alias", "").strip()

    if not code or not alias:
        flash("Invite code and alias are required!")
        return redirect(url_for("chat"))

    group = Group.query.filter_by(code=code).first()
    if not group:
        flash("Hidden group not found!")
        return redirect(url_for("chat"))

    if group.expire_at and group.expire_at < datetime.now(timezone.utc):
        db.session.delete(group)
        db.session.commit()
        flash("That hidden group has expired and was removed.")
        return redirect(url_for("chat"))

    if get_membership(session["user_id"], group.id):
        flash("You are already part of this hidden group.")
        return redirect(url_for("chat", group_id=group.id))

    membership = GroupMembership(group=group, user_id=session["user_id"], alias=alias)
    db.session.add(membership)
    db.session.commit()

    flash("Joined hidden group successfully.")
    return redirect(url_for("chat", group_id=group.id))


@app.route("/groups/<int:group_id>/delete", methods=["POST"])
@login_required
def delete_group(group_id: int):
    """Delete a hidden group on request."""

    group = Group.query.get_or_404(group_id)
    if group.owner_id != session["user_id"]:
        flash("Only the creator can delete this hidden group.")
        return redirect(url_for("chat", group_id=group_id))

    db.session.delete(group)
    db.session.commit()
    flash("Hidden group deleted.")
    return redirect(url_for("chat"))


@app.route("/groups/list")
@login_required
def group_list():
    """Return the hidden groups the user belongs to."""

    purge_expired_groups()
    memberships = (
        GroupMembership.query.filter_by(user_id=session["user_id"])
        .join(Group, GroupMembership.group_id == Group.id)
        .order_by(Group.created_at.desc())
        .all()
    )

    groups = []
    for membership in memberships:
        group = membership.group
        groups.append(
            {
                "id": group.id,
                "name": group.name,
                "alias": membership.alias,
                "is_owner": group.owner_id == session["user_id"],
                "code": group.code if group.owner_id == session["user_id"] else None,
                "expires_at": group.expire_at.isoformat() if group.expire_at else None,
            }
        )

    return jsonify({"groups": groups})


@app.route("/admin/dashboard", methods=["GET", "POST"])
@login_required
@admin_required
def admin_dashboard():
    """Render the administrator control center."""

    def parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "ban_ip":
                ip_address = (request.form.get("ip-address") or "").strip()
                reason = (request.form.get("ip-reason") or "").strip() or None
                if ip_address:
                    exists = BannedIP.query.filter(
                        func.lower(BannedIP.ip_address) == ip_address.lower()
                    ).first()
                    if exists:
                        flash("That IP address is already banned.")
                    else:
                        db.session.add(BannedIP(ip_address=ip_address, reason=reason))
                        db.session.commit()
                        flash("IP address banned successfully.")
                else:
                    flash("Enter an IP address to ban.")
            elif action == "unban_ip":
                entry_id = parse_int(request.form.get("entry-id"))
                entry = BannedIP.query.get(entry_id)
                if entry:
                    db.session.delete(entry)
                    db.session.commit()
                    flash("IP address unbanned.")
            elif action == "ban_country":
                country_code = (request.form.get("country-code") or "").strip().upper()
                reason = (request.form.get("country-reason") or "").strip() or None
                if country_code:
                    exists = BannedCountry.query.filter(
                        func.upper(BannedCountry.country_code) == country_code
                    ).first()
                    if exists:
                        flash("That country is already blocked.")
                    else:
                        db.session.add(BannedCountry(country_code=country_code, reason=reason))
                        db.session.commit()
                        flash("Country blocked successfully.")
                else:
                    flash("Enter a valid country code (e.g. US).")
            elif action == "unban_country":
                entry_id = parse_int(request.form.get("entry-id"))
                entry = BannedCountry.query.get(entry_id)
                if entry:
                    db.session.delete(entry)
                    db.session.commit()
                    flash("Country unblocked.")
            elif action == "block_word":
                word = (request.form.get("blocked-word") or "").strip().lower()
                if word:
                    exists = BlockedWord.query.filter(func.lower(BlockedWord.word) == word).first()
                    if exists:
                        flash("That word is already blocked.")
                    else:
                        db.session.add(BlockedWord(word=word))
                        db.session.commit()
                        flash("Word blocked successfully.")
                else:
                    flash("Enter a word or phrase to block.")
            elif action == "unblock_word":
                entry_id = parse_int(request.form.get("entry-id"))
                entry = BlockedWord.query.get(entry_id)
                if entry:
                    db.session.delete(entry)
                    db.session.commit()
                    flash("Word removed from block list.")
            elif action == "create_hub":
                name = (request.form.get("hub-name") or "").strip()
                description = (request.form.get("hub-description") or "").strip() or None
                if name:
                    exists = CommunicationHub.query.filter(
                        func.lower(CommunicationHub.name) == name.lower()
                    ).first()
                    if exists:
                        flash("A hub with that name already exists.")
                    else:
                        db.session.add(CommunicationHub(name=name, description=description))
                        db.session.commit()
                        flash("Hub created successfully.")
                else:
                    flash("Provide a hub name.")
            elif action == "toggle_hub":
                hub_id = parse_int(request.form.get("hub-id"))
                hub = CommunicationHub.query.get(hub_id)
                if hub:
                    hub.is_enabled = not hub.is_enabled
                    db.session.commit()
                    flash("Hub status updated.")
            elif action == "delete_hub":
                hub_id = parse_int(request.form.get("hub-id"))
                hub = CommunicationHub.query.get(hub_id)
                if hub:
                    db.session.delete(hub)
                    db.session.commit()
                    flash("Hub removed.")
            elif action == "promote_moderator":
                user_id = parse_int(request.form.get("moderator-user-id"))
                if user_id:
                    user = User.query.get(user_id)
                    if not user:
                        flash("User not found.")
                    elif ModeratorAssignment.query.filter_by(user_id=user_id).first():
                        flash("User is already a moderator.")
                    else:
                        db.session.add(ModeratorAssignment(user_id=user_id))
                        db.session.commit()
                        flash("Moderator promoted.")
                else:
                    flash("Select a user to promote.")
            elif action == "demote_moderator":
                assignment_id = parse_int(request.form.get("entry-id"))
                assignment = ModeratorAssignment.query.get(assignment_id)
                if assignment:
                    db.session.delete(assignment)
                    db.session.commit()
                    flash("Moderator removed.")
            elif action == "terminate_call":
                session_id = parse_int(request.form.get("session-id"))
                call_session = CallSession.query.get(session_id)
                if call_session:
                    moderator_user = User.query.get(session["user_id"]) if session.get("user_id") else None
                    call_manager.end_call(call_session, moderator_user, moderator=True)
                    socketio.emit(
                        "call_ended",
                        {
                            "sessionId": call_session.id,
                            "roomId": call_session.room_id,
                            "endedBy": moderator_user.username if moderator_user else "Moderator",
                        },
                        room=call_session.room_id,
                    )
                    flash("Call terminated.")
            elif action == "toggle_call_block":
                user_id = parse_int(request.form.get("target-user-id"))
                target = User.query.get(user_id)
                if target:
                    call_manager.set_user_blocked(target, not target.is_blocked)
                    status = "blocked" if target.is_blocked else "unblocked"
                    flash(f"{target.username} {status} for calls.")
        except Exception as error:  # pragma: no cover
            db.session.rollback()
            flash(f"Action failed: {error}")

        return redirect(url_for("admin_dashboard"))

    users = User.query.order_by(User.username.asc()).all()
    banned_ips = BannedIP.query.order_by(BannedIP.created_at.desc()).all()
    banned_countries = BannedCountry.query.order_by(BannedCountry.created_at.desc()).all()
    blocked_words = BlockedWord.query.order_by(BlockedWord.created_at.desc()).all()
    hubs = CommunicationHub.query.order_by(CommunicationHub.created_at.desc()).all()
    moderators = ModeratorAssignment.query.order_by(ModeratorAssignment.assigned_at.desc()).all()
    live_calls = (
        call_manager.get_active_sessions()
        .order_by(CallSession.started_at.desc())
        .all()
    )
    call_history = (
        CallSession.query.order_by(CallSession.started_at.desc()).limit(20).all()
    )

    return render_template(
        "admin/dashboard.html",
        users=users,
        banned_ips=banned_ips,
        banned_countries=banned_countries,
        blocked_words=blocked_words,
        hubs=hubs,
        moderators=moderators,
        live_calls=live_calls,
        call_history=call_history,
    )


def serialize_call_session(entry: CallSession) -> dict:
    """Return a JSON-serializable representation of a call session."""

    return {
        "id": entry.id,
        "roomId": entry.room_id,
        "caller": entry.caller.username if entry.caller else None,
        "callee": entry.callee.username if entry.callee else None,
        "status": entry.status,
        "startedAt": entry.started_at.isoformat() if entry.started_at else None,
        "acceptedAt": entry.accepted_at.isoformat() if entry.accepted_at else None,
        "endedAt": entry.ended_at.isoformat() if entry.ended_at else None,
        "endedBy": entry.ended_by.username if entry.ended_by else None,
        "terminatedByModerator": entry.terminated_by_moderator,
        "notes": entry.notes,
    }


@app.route("/api/calls/history", methods=["GET", "POST"])
@admin_required
def api_call_history():
    """Return or update call history entries."""

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        session_id = data.get("sessionId")
        if not session_id:
            return jsonify({"error": "sessionId is required"}), 400
        call_session = CallSession.query.get_or_404(session_id)
        notes = (data.get("notes") or "").strip() or None
        if notes is not None:
            call_manager.mark_notes(call_session, notes)
        return jsonify({"call": serialize_call_session(call_session)})

    limit = request.args.get("limit", default=50, type=int)
    entries = (
        CallSession.query.order_by(CallSession.started_at.desc()).limit(limit).all()
    )
    return jsonify({"calls": [serialize_call_session(entry) for entry in entries]})


@app.route("/api/calls/live", methods=["GET"])
@admin_required
def api_live_calls():
    """Return currently active call sessions."""

    entries = (
        call_manager.get_active_sessions()
        .order_by(CallSession.started_at.desc())
        .all()
    )
    return jsonify({"calls": [serialize_call_session(entry) for entry in entries]})


@app.route("/api/calls/<int:session_id>/terminate", methods=["POST"])
@admin_required
def api_terminate_call(session_id: int):
    """Allow moderators to terminate a live call."""

    call_session = CallSession.query.get_or_404(session_id)
    moderator_user = User.query.get(session["user_id"]) if session.get("user_id") else None
    call_manager.end_call(call_session, moderator_user, moderator=True)
    socketio.emit(
        "call_ended",
        {
            "sessionId": call_session.id,
            "roomId": call_session.room_id,
            "endedBy": moderator_user.username if moderator_user else "Moderator",
        },
        room=call_session.room_id,
    )
    return jsonify({"call": serialize_call_session(call_session)})


@app.route("/api/users/<int:user_id>/call-access", methods=["PATCH"])
@admin_required
def api_update_call_access(user_id: int):
    """Toggle whether a user is allowed to place calls."""

    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    blocked = bool(data.get("blocked"))
    call_manager.set_user_blocked(user, blocked)
    return jsonify({"userId": user.id, "blocked": user.is_blocked})


@app.route("/chat/open-conversations")
@login_required
def open_conversations():
    """Return a list of conversations for the tab bar."""

    current_user_id = session["user_id"]

    messages = Message.query.filter(
        (Message.user_id == current_user_id) | (Message.recipient_id == current_user_id)
    ).order_by(Message.timestamp.desc()).all()

    conversations = {}
    user_cache = {}
    for message in messages:
        other_id = message.recipient_id if message.user_id == current_user_id else message.user_id
        if other_id in conversations:
            continue
        other_user = message.recipient if message.user_id == current_user_id else message.sender
        if other_user is None:
            other_user = user_cache.get(other_id)
            if other_user is None:
                other_user = User.query.get(other_id)
                user_cache[other_id] = other_user
        if not other_user:
            continue
        conversations[other_id] = {
            "id": other_user.id,
            "name": other_user.username,
            "display_name": other_user.username,
            "type": "direct",
            "last_message": message.text,
            "last_timestamp": message.timestamp.isoformat() if message.timestamp else None
        }

    return jsonify({"conversations": list(conversations.values())})


@app.route("/chat/conversation/<int:partner_id>/messages")
@login_required
def conversation_messages(partner_id):
    """Return the message history for a conversation."""

    current_user_id = session["user_id"]
    partner = User.query.get_or_404(partner_id)

    messages = Message.query.filter(
        ((Message.user_id == current_user_id) & (Message.recipient_id == partner_id)) |
        ((Message.user_id == partner_id) & (Message.recipient_id == current_user_id))
    ).order_by(Message.timestamp.asc()).all()

    serialized = []
    for message in messages:
        serialized.append({
            "id": message.id,
            "text": message.text,
            "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            "sender": {
                "id": message.user_id,
                "username": message.sender.username if message.sender else None
            },
            "recipient": {
                "id": message.recipient_id,
                "username": message.recipient.username if message.recipient else None
            }
        })

    return jsonify({
        "conversation": {
            "id": partner.id,
            "name": partner.username,
            "display_name": partner.username,
            "type": "direct"
        },
        "messages": serialized
    })


# verify async mode
print(f"SocketIO async mode: {socketio.async_mode}")


if __name__ == "__main__":
    socketio.run(app, debug=True)
