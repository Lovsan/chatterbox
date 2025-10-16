# Description: This file contains the event handlers for the SocketIO events.


# import
from datetime import datetime, timezone

from flask import session
from flask_socketio import emit, join_room, leave_room

from achievements import apply_progress
from models import (
    BlockedWord,
    CallSession,
    GroupMembership,
    GroupMessage,
    Message,
    User,
    db,
)


def register_event_handlers(socketio, app, call_manager):
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

    @socketio.on("call_request")
    def handle_call_request(data):
        """Initiate a WebRTC call."""

        user_id = session.get("user_id")
        if not user_id:
            emit("call_error", {"error": "Login required."})
            return

        target_username = (data or {}).get("target")
        offer = (data or {}).get("offer")
        if not target_username:
            emit("call_error", {"error": "Select someone to call."})
            return
        if not offer:
            emit("call_error", {"error": "Missing WebRTC offer."})
            return

        caller = User.query.get(user_id)
        callee = User.query.filter_by(username=target_username).first()
        if not callee:
            emit("call_error", {"error": "Recipient not found."})
            return

        session_obj, error = call_manager.start_call(caller, callee)
        if error:
            emit("call_error", {"error": error})
            return

        join_room(session_obj.room_id)
        emit(
            "call_outgoing",
            {
                "sessionId": session_obj.id,
                "roomId": session_obj.room_id,
                "recipient": callee.username,
            },
        )
        socketio.emit(
            "call_incoming",
            {
                "sessionId": session_obj.id,
                "roomId": session_obj.room_id,
                "caller": caller.username,
                "offer": offer,
            },
            room=f"user_{callee.id}",
        )

    @socketio.on("call_answer")
    def handle_call_answer(data):
        """Handle callee response to a call."""

        user_id = session.get("user_id")
        if not user_id:
            emit("call_error", {"error": "Login required."})
            return

        session_id = (data or {}).get("sessionId")
        accepted = bool((data or {}).get("accepted"))
        answer = (data or {}).get("answer")
        session_obj = call_manager.get_session(session_id)
        if not session_obj:
            emit("call_error", {"error": "Call not found."})
            return

        callee = User.query.get(user_id)
        if session_obj.callee_id != callee.id:
            emit("call_error", {"error": "You are not part of this call."})
            return

        if not accepted:
            error = call_manager.decline_call(session_obj, callee)
            if error:
                emit("call_error", {"error": error})
            else:
                socketio.emit(
                    "call_declined",
                    {"sessionId": session_obj.id, "roomId": session_obj.room_id},
                    room=f"user_{session_obj.caller_id}",
                )
            return

        if not answer:
            emit("call_error", {"error": "Missing WebRTC answer."})
            return

        error = call_manager.accept_call(session_obj, callee)
        if error:
            emit("call_error", {"error": error})
            return

        join_room(session_obj.room_id)
        socketio.emit(
            "call_answered",
            {
                "sessionId": session_obj.id,
                "roomId": session_obj.room_id,
                "answer": answer,
            },
            room=session_obj.room_id,
        )

    @socketio.on("ice_candidate")
    def handle_ice_candidate(data):
        """Relay ICE candidates between peers."""

        user_id = session.get("user_id")
        if not user_id:
            return

        session_id = (data or {}).get("sessionId")
        candidate = (data or {}).get("candidate")
        session_obj = call_manager.get_session(session_id)
        if not session_obj or not candidate:
            return

        if user_id not in {session_obj.caller_id, session_obj.callee_id}:
            return

        socketio.emit(
            "ice_candidate",
            {"sessionId": session_obj.id, "candidate": candidate},
            room=session_obj.room_id,
            include_self=False,
        )

    @socketio.on("call_hangup")
    def handle_call_hangup(data):
        """Terminate a call initiated by a participant."""

        user_id = session.get("user_id")
        if not user_id:
            return

        session_id = (data or {}).get("sessionId")
        session_obj = call_manager.get_session(session_id)
        if not session_obj:
            return

        if user_id not in {session_obj.caller_id, session_obj.callee_id}:
            return

        user = User.query.get(user_id)
        call_manager.end_call(session_obj, user)
        socketio.emit(
            "call_ended",
            {
                "sessionId": session_obj.id,
                "roomId": session_obj.room_id,
                "endedBy": user.username if user else None,
            },
            room=session_obj.room_id,
        )
        leave_room(session_obj.room_id)

    @socketio.on("disconnect")
    def handle_disconnect():
        """Handle the "disconnect" event."""

        user_id = session.get("user_id")
        if user_id:
            leave_room(f"user_{user_id}")
            for membership in GroupMembership.query.filter_by(user_id=user_id).all():
                leave_room(f"group_{membership.group_id}")

            active_sessions = (
                call_manager.get_active_sessions()
                .filter(
                    (CallSession.caller_id == user_id)
                    | (CallSession.callee_id == user_id)
                )
                .all()
            )
            user = User.query.get(user_id)
            for session_obj in active_sessions:
                call_manager.end_call(session_obj, user)
                socketio.emit(
                    "call_ended",
                    {
                        "sessionId": session_obj.id,
                        "roomId": session_obj.room_id,
                        "endedBy": user.username if user else None,
                    },
                    room=session_obj.room_id,
                )
                leave_room(session_obj.room_id)
