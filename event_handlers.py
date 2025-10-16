# Description: This file contains the event handlers for the SocketIO events.


# import
import base64
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Optional

from flask import session
from flask_socketio import emit, join_room, leave_room

from achievements import apply_progress
from models import (
    BlockedWord,
    GroupMembership,
    GroupMessage,
    GroupMessageAttachment,
    MediaUploadToken,
    Message,
    MessageAttachment,
    TranslatedTranscript,
    User,
    db,
)

try:  # pragma: no cover - optional cloud dependencies
    from google.api_core.exceptions import GoogleAPIError
    from google.cloud import speech
    from google.cloud import translate_v2 as translate
except Exception:  # pragma: no cover - gracefully handle missing deps
    GoogleAPIError = Exception
    speech = None
    translate = None


logger = logging.getLogger(__name__)


_speech_client: Optional["speech.SpeechClient"] = None
_translate_client: Optional["translate.Client"] = None
_translation_preferences: Dict[str, Dict[int, Dict[str, object]]] = defaultdict(dict)
_rate_limiter: Dict[int, deque] = defaultdict(deque)
_PREFERENCE_TTL_SECONDS = 60 * 60  # 1 hour cache
_RATE_LIMIT_WINDOW_SECONDS = 5
_RATE_LIMIT_MAX_EVENTS = 20


def _get_speech_client() -> Optional["speech.SpeechClient"]:
    global _speech_client
    if _speech_client is not None:
        return _speech_client
    if speech is None:  # pragma: no cover - dependency missing
        logger.warning("Google Cloud Speech dependency is not installed; transcription disabled.")
        return None
    try:
        _speech_client = speech.SpeechClient()
    except Exception as exc:  # pragma: no cover - runtime configuration issue
        logger.warning("Unable to instantiate Speech client: %s", exc)
        _speech_client = None
    return _speech_client


def _get_translate_client() -> Optional["translate.Client"]:
    global _translate_client
    if _translate_client is not None:
        return _translate_client
    if translate is None:  # pragma: no cover - dependency missing
        logger.warning("Google Cloud Translate dependency is not installed; translation disabled.")
        return None
    try:
        _translate_client = translate.Client()
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to instantiate Translate client: %s", exc)
        _translate_client = None
    return _translate_client


def _allow_transcription_request(user_id: int) -> bool:
    bucket = _rate_limiter[user_id]
    now = time.time()
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX_EVENTS:
        return False
    bucket.append(now)
    return True


def _prune_preferences(call_id: str) -> Dict[int, Dict[str, object]]:
    prefs = _translation_preferences.get(call_id, {})
    if not prefs:
        return {}
    now = time.time()
    expired = [
        user_id
        for user_id, value in prefs.items()
        if now - float(value.get("updated_at", now)) > _PREFERENCE_TTL_SECONDS
    ]
    for user_id in expired:
        prefs.pop(user_id, None)
    if not prefs:
        _translation_preferences.pop(call_id, None)
        return {}
    return prefs


def _transcribe_audio(content: bytes, language_code: Optional[str]) -> Optional[Dict[str, str]]:
    client = _get_speech_client()
    if not client:
        return None
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
        language_code=language_code or "en-US",
        enable_automatic_punctuation=True,
        sample_rate_hertz=48000,
    )
    audio = speech.RecognitionAudio(content=content)
    try:
        response = client.recognize(config=config, audio=audio)
    except GoogleAPIError as exc:
        logger.warning("Speech recognition failed: %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - network failure
        logger.exception("Unexpected speech recognition error: %s", exc)
        return None
    for result in response.results:
        if result.alternatives:
            alternative = result.alternatives[0]
            detected_language = getattr(result, "language_code", None) or config.language_code
            return {
                "transcript": alternative.transcript,
                "language_code": detected_language,
            }
    return None


def _translate_text(
    text: str,
    target_language: str,
    source_language: Optional[str] = None,
) -> Optional[str]:
    if not text:
        return None
    client = _get_translate_client()
    if not client:
        return text
    try:
        result = client.translate(
            text,
            target_language=target_language,
            source_language=source_language,
            format_="text",
        )
    except GoogleAPIError as exc:
        logger.warning("Translation failed: %s", exc)
        return None
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected translation error: %s", exc)
        return None
    return result.get("translatedText") if isinstance(result, dict) else None


def register_event_handlers(socketio, app):
    """Register SocketIO event handlers."""

    @socketio.on("send_message")
    def handle_send_message(data):
        """Handle direct message sending."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to send messages!"})
            return

        username = data.get("username")
        recipient = data.get("recipient")
        message = (data.get("message") or "").strip()

        if not username:
            emit("error", {"error": "Username is required!"})
            return
        if username != session.get("username"):
            emit("error", {"error": "You are not authorized to send messages on behalf of other users!"})
            return
        if not message:
            emit("error", {"error": "Message cannot be empty!"})
            return
        if len(message) > 500:
            emit("error", {"error": "Message must be at most 500 characters long!"})
            return
        if not recipient:
            emit("error", {"error": "Recipient is required!"})
            return

        recipient_db = User.query.filter_by(username=recipient).first()
        if not recipient_db:
            emit("error", {"error": "Recipient not found!"})
            return

        sender = User.query.get(session["user_id"])
        blocked_word = next(
            (
                entry
                for entry in BlockedWord.query.all()
                if entry.word and entry.word.lower() in message.lower()
            ),
            None,
        )
        if blocked_word:
            emit("error", {"error": "Your message contains blocked language."})
            return

        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient_db.id,
            text=message,
            timestamp=datetime.now(timezone.utc),
        )
        db.session.add(new_message)
        if sender:
            apply_progress(sender, 5)
        db.session.commit()

        payload = {
            "username": username,
            "recipient": recipient_db.username,
            "message": message,
            "timestamp": new_message.timestamp.isoformat(),
            "attachments": [],
        }
        recipient_room = f"user_{recipient_db.id}"
        sender_room = f"user_{session['user_id']}"
        emit("receive_message", payload, room=recipient_room)
        emit("receive_message", payload, room=sender_room)

        if sender:
            socketio.emit(
                "progress_update",
                {"xp": sender.xp, "level": sender.level, "badge": sender.badge},
                room=f"user_{sender.id}",
            )

    @socketio.on("send_group_message")
    def handle_send_group_message(data):
        """Handle sending messages in hidden group chats."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to send messages!"})
            return

        group_id = data.get("group_id")
        message = (data.get("message") or "").strip()
        alias = data.get("alias")

        if not group_id:
            emit("error", {"error": "Group is required!"})
            return
        if not message:
            emit("error", {"error": "Message cannot be empty!"})
            return
        if len(message) > 500:
            emit("error", {"error": "Message must be at most 500 characters long!"})
            return

        blocked_word = next(
            (
                entry
                for entry in BlockedWord.query.all()
                if entry.word and entry.word.lower() in message.lower()
            ),
            None,
        )
        if blocked_word:
            emit("error", {"error": "Your message contains blocked language."})
            return

        membership = GroupMembership.query.filter_by(
            group_id=group_id, user_id=session["user_id"]
        ).first()
        if not membership:
            emit("error", {"error": "You are not a member of this hidden group."})
            return
        if alias != membership.alias:
            emit("error", {"error": "Alias mismatch detected."})
            return

        group = membership.group
        if group.expire_at and group.expire_at < datetime.now(timezone.utc):
            db.session.delete(group)
            db.session.commit()
            emit("error", {"error": "This hidden group has expired."})
            return

        group_message = GroupMessage(
            group_id=group_id,
            membership_id=membership.id,
            alias=membership.alias,
            text=message,
            timestamp=datetime.now(timezone.utc),
        )
        db.session.add(group_message)
        sender = membership.user
        if sender:
            apply_progress(sender, 8)
        db.session.commit()

        payload = {
            "group_id": group_id,
            "alias": membership.alias,
            "message": message,
            "timestamp": group_message.timestamp.isoformat(),
            "attachments": [],
        }
        emit("receive_group_message", payload, room=f"group_{group_id}")

        if sender:
            socketio.emit(
                "progress_update",
                {"xp": sender.xp, "level": sender.level, "badge": sender.badge},
                room=f"user_{sender.id}",
            )

    @socketio.on("send_media_message")
    def handle_send_media_message(data):
        """Handle sending messages with media attachments."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to send messages!"})
            return

        upload_token_value = (data or {}).get("upload_token")
        if not upload_token_value:
            emit("error", {"error": "Missing media upload token."})
            return

        upload_token = MediaUploadToken.query.filter_by(
            token=upload_token_value, user_id=session["user_id"]
        ).first()
        if not upload_token or upload_token.is_consumed or upload_token.is_expired:
            emit("error", {"error": "Media token is invalid or expired."})
            return

        caption = (data.get("caption") or "").strip()
        blocked_word = None
        if caption:
            blocked_word = next(
                (
                    entry
                    for entry in BlockedWord.query.all()
                    if entry.word and entry.word.lower() in caption.lower()
                ),
                None,
            )
        if blocked_word:
            emit("error", {"error": "Your caption contains blocked language."})
            return

        media_payload = {
            "media_type": upload_token.media_type,
            "storage_path": upload_token.storage_path,
            "duration_seconds": upload_token.duration_seconds,
            "mime_type": upload_token.mime_type,
        }

        sender = User.query.get(session["user_id"])
        chat_type = (data.get("chat_type") or "direct").lower()

        if chat_type == "group":
            group_id = data.get("group_id")
            alias = data.get("alias")
            if not group_id:
                emit("error", {"error": "Group is required for media message."})
                return

            membership = GroupMembership.query.filter_by(
                group_id=group_id, user_id=session["user_id"]
            ).first()
            if not membership:
                emit("error", {"error": "You are not a member of this hidden group."})
                return
            if alias != membership.alias:
                emit("error", {"error": "Alias mismatch detected."})
                return

            group = membership.group
            if group.expire_at and group.expire_at < datetime.now(timezone.utc):
                db.session.delete(group)
                db.session.commit()
                emit("error", {"error": "This hidden group has expired."})
                return

            group_message = GroupMessage(
                group_id=group_id,
                membership_id=membership.id,
                alias=membership.alias,
                text=caption,
                timestamp=datetime.now(timezone.utc),
            )
            db.session.add(group_message)
            db.session.flush()

            attachment = GroupMessageAttachment(
                group_message_id=group_message.id,
                media_type=upload_token.media_type,
                storage_path=upload_token.storage_path,
                duration_seconds=upload_token.duration_seconds,
                mime_type=upload_token.mime_type,
            )
            db.session.add(attachment)

            if sender:
                apply_progress(sender, 10)

            upload_token.mark_consumed()
            db.session.commit()

            payload = {
                "group_id": group_id,
                "alias": membership.alias,
                "message": caption,
                "timestamp": group_message.timestamp.isoformat(),
                "attachments": [
                    {
                        "media_type": media_payload["media_type"],
                        "storage_path": media_payload["storage_path"],
                        "duration_seconds": media_payload["duration_seconds"],
                        "mime_type": media_payload["mime_type"],
                    }
                ],
            }
            emit("receive_group_message", payload, room=f"group_{group_id}")

            if sender:
                socketio.emit(
                    "progress_update",
                    {"xp": sender.xp, "level": sender.level, "badge": sender.badge},
                    room=f"user_{sender.id}",
                )
            return

        username = data.get("username")
        recipient_username = data.get("recipient")
        if not username or username != session.get("username"):
            emit("error", {"error": "You are not authorized to send this media."})
            return
        if not recipient_username:
            emit("error", {"error": "Recipient is required."})
            return

        recipient = User.query.filter_by(username=recipient_username).first()
        if not recipient:
            emit("error", {"error": "Recipient not found!"})
            return

        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient.id,
            text=caption,
            timestamp=datetime.now(timezone.utc),
        )
        db.session.add(new_message)
        db.session.flush()

        attachment = MessageAttachment(
            message_id=new_message.id,
            media_type=upload_token.media_type,
            storage_path=upload_token.storage_path,
            duration_seconds=upload_token.duration_seconds,
            mime_type=upload_token.mime_type,
        )
        db.session.add(attachment)

        if sender:
            apply_progress(sender, 8)

        upload_token.mark_consumed()
        db.session.commit()

        payload = {
            "username": username,
            "recipient": recipient.username,
            "message": caption,
            "timestamp": new_message.timestamp.isoformat(),
            "attachments": [
                {
                    "media_type": media_payload["media_type"],
                    "storage_path": media_payload["storage_path"],
                    "duration_seconds": media_payload["duration_seconds"],
                    "mime_type": media_payload["mime_type"],
                }
            ],
        }
        recipient_room = f"user_{recipient.id}"
        sender_room = f"user_{session['user_id']}"
        emit("receive_message", payload, room=recipient_room)
        emit("receive_message", payload, room=sender_room)

        if sender:
            socketio.emit(
                "progress_update",
                {"xp": sender.xp, "level": sender.level, "badge": sender.badge},
                room=f"user_{sender.id}",
            )

    @socketio.on("join_call_room")
    def handle_join_call_room_event(data):
        """Allow callers to subscribe to translated caption broadcasts."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to join calls."})
            return

        call_id = (data or {}).get("call_id")
        if not call_id:
            emit("error", {"error": "Call identifier is required."})
            return

        join_room(f"call_{call_id}")
        emit("call_room_joined", {"call_id": call_id})

    @socketio.on("set_translation_preferences")
    def handle_set_translation_preferences(data):
        """Persist participant translation preferences during a call."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to configure translation."})
            return

        call_id = (data or {}).get("call_id")
        if not call_id:
            emit("error", {"error": "Call identifier is required."})
            return

        target_language = (data or {}).get("target_language") or "en"
        enabled = bool((data or {}).get("enabled"))
        source_language = (data or {}).get("source_language") or None

        preferences = _translation_preferences[call_id]
        preferences[session["user_id"]] = {
            "language": target_language,
            "enabled": enabled,
            "source_language": source_language,
            "updated_at": time.time(),
        }

        emit(
            "translation_preferences_updated",
            {
                "call_id": call_id,
                "enabled": enabled,
                "target_language": target_language,
            },
        )

    @socketio.on("call_transcription_chunk")
    def handle_call_transcription_chunk(data):
        """Process audio samples, transcribe them, and broadcast translations."""

        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to stream audio."})
            return

        if not _allow_transcription_request(session["user_id"]):
            emit(
                "translation_error",
                {
                    "call_id": (data or {}).get("call_id"),
                    "message": "Transcription rate limit exceeded. Please pause briefly.",
                },
            )
            return

        call_id = (data or {}).get("call_id")
        audio_chunk = (data or {}).get("audio_chunk")
        preferred_language = (data or {}).get("source_language")

        if not call_id or not audio_chunk:
            emit("error", {"error": "Audio chunk and call identifier are required."})
            return

        try:
            audio_bytes = base64.b64decode(audio_chunk)
        except (TypeError, ValueError):
            emit("error", {"error": "Invalid audio payload."})
            return

        transcription = _transcribe_audio(audio_bytes, preferred_language)
        if not transcription or not transcription.get("transcript"):
            return

        transcript_text = transcription["transcript"].strip()
        detected_language = transcription.get("language_code") or preferred_language

        preferences = _prune_preferences(call_id)

        translated_entries = []
        if preferences:
            for user_id, preference in preferences.items():
                if not preference.get("enabled"):
                    continue
                target_language = (preference.get("language") or "en").split("-")[0]
                translation = _translate_text(
                    transcript_text,
                    target_language=target_language,
                    source_language=detected_language,
                )
                if translation is None:
                    continue
                entry = TranslatedTranscript(
                    call_id=call_id,
                    speaker_user_id=session.get("user_id"),
                    original_language=detected_language,
                    target_language=target_language,
                    transcript_text=transcript_text,
                    translated_text=translation,
                )
                db.session.add(entry)
                translated_entries.append(
                    {
                        "call_id": call_id,
                        "target_language": target_language,
                        "translation": translation,
                        "transcript": transcript_text,
                        "original_language": detected_language,
                        "speaker_user_id": session.get("user_id"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

        if translated_entries:
            try:
                db.session.commit()
            except Exception as exc:  # pragma: no cover - database error
                db.session.rollback()
                logger.exception("Failed to persist translated transcripts: %s", exc)
            else:
                for payload in translated_entries:
                    emit("translated_caption", payload, room=f"call_{call_id}")

        else:
            fallback_language = detected_language or (preferred_language or "en")
            try:
                fallback_entry = TranslatedTranscript(
                    call_id=call_id,
                    speaker_user_id=session.get("user_id"),
                    original_language=detected_language,
                    target_language=fallback_language,
                    transcript_text=transcript_text,
                    translated_text=transcript_text,
                )
                db.session.add(fallback_entry)
                db.session.commit()
            except Exception as exc:  # pragma: no cover - database error
                db.session.rollback()
                logger.exception("Failed to persist fallback transcript: %s", exc)
            emit(
                "translated_caption",
                {
                    "call_id": call_id,
                    "target_language": fallback_language,
                    "translation": transcript_text,
                    "transcript": transcript_text,
                    "original_language": detected_language,
                    "speaker_user_id": session.get("user_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                room=f"call_{call_id}",
            )

    @socketio.on("join_group_room")
    def handle_join_group_room(data):
        """Allow clients to join group rooms dynamically."""

        user_id = session.get("user_id")
        group_id = data.get("group_id") if data else None
        if not user_id or not group_id:
            return
        membership = GroupMembership.query.filter_by(
            group_id=group_id, user_id=user_id
        ).first()
        if membership:
            join_room(f"group_{group_id}")

    @socketio.on("connect")
    def handle_connect():
        """Handle the "connect" event."""

        user_id = session.get("user_id")
        if user_id:
            join_room(f"user_{user_id}")
            for membership in GroupMembership.query.filter_by(user_id=user_id).all():
                join_room(f"group_{membership.group_id}")

    @socketio.on("disconnect")
    def handle_disconnect():
        """Handle the "disconnect" event."""

        user_id = session.get("user_id")
        if user_id:
            leave_room(f"user_{user_id}")
            for membership in GroupMembership.query.filter_by(user_id=user_id).all():
                leave_room(f"group_{membership.group_id}")
