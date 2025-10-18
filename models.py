# Description: This file contains the database models for the application.

# import
from datetime import datetime, timedelta, timezone
import uuid
from flask_sqlalchemy import SQLAlchemy


LEVELS = [
    (1, "Newcomer", 0),
    (2, "Conversationalist", 50),
    (3, "Connector", 150),
    (4, "Luminary", 300),
    (5, "Oracle", 500),
]

# create the database object
db = SQLAlchemy()


# User database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    xp = db.Column(db.Integer, nullable=False, default=0)
    level = db.Column(db.Integer, nullable=False, default=1)
    badge = db.Column(db.String(50), nullable=False, default="Newcomer")
    last_arrival_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    pin_hash = db.Column(db.String(200), nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    profile_features_enabled = db.Column(db.Boolean, nullable=False, default=False)
    allow_file_uploads = db.Column(db.Boolean, nullable=False, default=False)
    marketplace_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    muted_until = db.Column(db.DateTime, nullable=True)
    banned_until = db.Column(db.DateTime, nullable=True)
    warning_count = db.Column(db.Integer, nullable=False, default=0)

    @property
    def has_pin(self) -> bool:
        """Return whether the user configured a security PIN."""

        return bool(self.pin_hash)

    @property
    def is_moderator(self) -> bool:
        return bool(getattr(self, "moderator_assignment", None))


# Message database model
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False, default="")
    ciphertext = db.Column(db.Text, nullable=True)
    nonce = db.Column(db.String(48), nullable=True)
    is_encrypted = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    sender = db.relationship('User', foreign_keys=[user_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')
    attachments = db.relationship(
        'MessageAttachment', cascade='all, delete-orphan', backref='message'
    )


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    hidden = db.Column(db.Boolean, default=True, nullable=False)
    expire_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    owner = db.relationship('User', backref='owned_groups')
    memberships = db.relationship('GroupMembership', cascade='all, delete-orphan', backref='group')
    messages = db.relationship('GroupMessage', cascade='all, delete-orphan', backref='group')


class GroupMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    alias = db.Column(db.String(30), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref='group_memberships')


class GroupMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    membership_id = db.Column(db.Integer, db.ForeignKey('group_membership.id'), nullable=False)
    alias = db.Column(db.String(30), nullable=False)
    text = db.Column(db.String(500), nullable=False, default="")
    ciphertext = db.Column(db.Text, nullable=True)
    nonce = db.Column(db.String(48), nullable=True)
    is_encrypted = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    membership = db.relationship('GroupMembership', backref='messages')
    attachments = db.relationship(
        'GroupMessageAttachment', cascade='all, delete-orphan', backref='group_message'
    )


class BannedIP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(100), unique=True, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class BannedCountry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(db.String(5), unique=True, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class BlockedWord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class CommunicationHub(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class ModeratorAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref=db.backref('moderator_assignment', uselist=False))


class MessageAttachment(db.Model):
    """Attachment associated with a direct message."""

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    media_type = db.Column(db.String(30), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    duration_seconds = db.Column(db.Float, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class GroupMessageAttachment(db.Model):
    """Attachment associated with a group message."""

    id = db.Column(db.Integer, primary_key=True)
    group_message_id = db.Column(
        db.Integer, db.ForeignKey('group_message.id'), nullable=False
    )
    media_type = db.Column(db.String(30), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    duration_seconds = db.Column(db.Float, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class MediaUploadToken(db.Model):
    """Temporary upload record awaiting attachment assignment."""

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    media_type = db.Column(db.String(30), nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='pending_uploads')

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @property
    def is_expired(self) -> bool:
        expiration = self.created_at + timedelta(hours=1)
        return datetime.now(timezone.utc) > expiration

    def mark_consumed(self) -> None:
        self.consumed_at = datetime.now(timezone.utc)


class TranslatedTranscript(db.Model):
    """Persisted translated captions for call replays."""

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.String(64), nullable=False, index=True)
    speaker_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    original_language = db.Column(db.String(10), nullable=True)
    target_language = db.Column(db.String(10), nullable=False)
    transcript_text = db.Column(db.Text, nullable=False)
    translated_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)


class UserProfile(db.Model):
    """Extended profile information that can be toggled by moderators."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    favorite_languages = db.Column(db.String(120), nullable=True)
    social_links = db.Column(db.Text, nullable=True)
    theme_color = db.Column(db.String(20), nullable=True)
    avatar_path = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", backref=db.backref("profile", uselist=False))


class DisciplinaryAction(db.Model):
    """Administrative warnings, mutes, and bans with durations."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    issued_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action_type = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    duration_hours = db.Column(db.Integer, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref="disciplinary_actions")
    moderator = db.relationship("User", foreign_keys=[issued_by])


class MarketplaceListing(db.Model):
    """Product listing within the escrow marketplace."""

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="USD")
    expires_at = db.Column(db.DateTime, nullable=True)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    seller = db.relationship("User", backref="marketplace_listings")


class EscrowTransaction(db.Model):
    """Escrow workflow for marketplace purchases."""

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("marketplace_listing.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="held")
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    released_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(30), nullable=True)

    listing = db.relationship("MarketplaceListing", backref="escrows")
    buyer = db.relationship("User", foreign_keys=[buyer_id])


class MarketplaceRequest(db.Model):
    """Buyer requests for specific products or services."""

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    budget_cents = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", backref="purchase_requests")

    speaker = db.relationship("User", backref="translated_transcripts")


class CallSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(64), nullable=False, unique=True)
    caller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    callee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='initiated')
    started_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    ended_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    terminated_by_moderator = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)

    caller = db.relationship('User', foreign_keys=[caller_id], backref='initiated_calls')
    callee = db.relationship('User', foreign_keys=[callee_id], backref='received_calls')
    ended_by = db.relationship('User', foreign_keys=[ended_by_id], backref='ended_calls')
