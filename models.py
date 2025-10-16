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

    @property
    def has_pin(self) -> bool:
        """Return whether the user configured a security PIN."""

        return bool(self.pin_hash)


# Message database model
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
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
    text = db.Column(db.String(500), nullable=False)
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
