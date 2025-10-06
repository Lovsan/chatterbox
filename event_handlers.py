# Description: This file contains the event handlers for the SocketIO events.


# import
from datetime import datetime, timezone

from flask import session
from flask_socketio import emit, join_room, leave_room

from achievements import apply_progress
from models import BlockedWord, GroupMembership, GroupMessage, Message, User, db


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
        }
        emit("receive_group_message", payload, room=f"group_{group_id}")

        if sender:
            socketio.emit(
                "progress_update",
                {"xp": sender.xp, "level": sender.level, "badge": sender.badge},
                room=f"user_{sender.id}",
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
