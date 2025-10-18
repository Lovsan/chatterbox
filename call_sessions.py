"""Call session state management utilities."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from flask import current_app

from models import CallSession, User, db


class CallSessionManager:
    """Manage lifecycle of voice/video call sessions."""

    def __init__(self) -> None:
        self._active_by_room: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _generate_room_id(self) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(24))

    def _mark_active(self, session: CallSession) -> None:
        self._active_by_room[session.room_id] = session.id

    def _clear_active(self, session: CallSession) -> None:
        self._active_by_room.pop(session.room_id, None)

    # ------------------------------------------------------------------
    # lookups
    # ------------------------------------------------------------------
    def get_session(self, session_id: int) -> Optional[CallSession]:
        return CallSession.query.get(session_id)

    def get_session_by_room(self, room_id: str) -> Optional[CallSession]:
        session_id = self._active_by_room.get(room_id)
        if session_id:
            return CallSession.query.get(session_id)
        return CallSession.query.filter_by(room_id=room_id).first()

    def get_active_sessions(self):
        return CallSession.query.filter(CallSession.status.in_(["ringing", "active"]))

    # ------------------------------------------------------------------
    # permissions
    # ------------------------------------------------------------------
    @staticmethod
    def _can_call(user: User) -> bool:
        return not user.is_blocked

    def _is_user_busy(self, user_id: int) -> bool:
        return (
            CallSession.query.filter(
                CallSession.status.in_(["ringing", "active"]),
                (CallSession.caller_id == user_id) | (CallSession.callee_id == user_id),
            ).first()
            is not None
        )

    # ------------------------------------------------------------------
    # lifecycle actions
    # ------------------------------------------------------------------
    def start_call(self, caller: User, callee: User) -> Tuple[Optional[CallSession], Optional[str]]:
        """Attempt to start a call. Returns the session and an error message."""

        if not self._can_call(caller):
            return None, "You are blocked from placing calls."
        if not self._can_call(callee):
            return None, "The selected user cannot receive calls."
        if caller.id == callee.id:
            return None, "You cannot call yourself."
        if self._is_user_busy(caller.id):
            return None, "You already have an active call."
        if self._is_user_busy(callee.id):
            return None, "That user is busy in another call."

        room_id = self._generate_room_id()
        session = CallSession(
            room_id=room_id,
            caller_id=caller.id,
            callee_id=callee.id,
            status="ringing",
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(session)
        db.session.commit()
        self._mark_active(session)
        current_app.logger.debug("Created call session %s", session.id)
        return session, None

    def accept_call(self, session: CallSession, callee: User) -> Optional[str]:
        if session.callee_id != callee.id:
            return "You are not allowed to answer this call."
        if session.status not in {"ringing", "active"}:
            return "Call is no longer available."

        session.status = "active"
        session.accepted_at = datetime.now(timezone.utc)
        db.session.commit()
        self._mark_active(session)
        return None

    def decline_call(self, session: CallSession, callee: User) -> Optional[str]:
        if session.callee_id != callee.id:
            return "You are not allowed to decline this call."
        if session.status != "ringing":
            return "Call is no longer available."

        session.status = "declined"
        session.ended_at = datetime.now(timezone.utc)
        session.ended_by_id = callee.id
        db.session.commit()
        self._clear_active(session)
        return None

    def end_call(self, session: CallSession, user: Optional[User], *, moderator: bool = False) -> None:
        if session.status not in {"ringing", "active"}:
            return

        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc)
        if user:
            session.ended_by_id = user.id
        session.terminated_by_moderator = moderator
        db.session.commit()
        self._clear_active(session)

    def mark_notes(self, session: CallSession, notes: Optional[str]) -> None:
        session.notes = notes
        db.session.commit()

    def set_user_blocked(self, user: User, blocked: bool) -> None:
        user.is_blocked = blocked
        db.session.commit()

    def is_user_blocked(self, user_id: int) -> bool:
        user = User.query.get(user_id)
        return bool(user and user.is_blocked)
