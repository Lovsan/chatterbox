# Description: This file contains the event handlers for the SocketIO events.


# import
import base64
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Optional

from flask import session, url_for
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

from security_utils import (
    conversation_identifier_for_direct,
    conversation_identifier_for_group,
    encrypt_conversation_message,
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


def _contains_blocked_language(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for entry in BlockedWord.query.all():
        if entry.word and entry.word.lower() in lowered:
            return True
    return False


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
        now = datetime.now(timezone.utc)
        if sender and sender.muted_until:
            if sender.muted_until > now:
                emit("error", {"error": "You are muted by a moderator."})
                return
            sender.muted_until = None
            db.session.commit()

        if _contains_blocked_language(message):
            emit("error", {"error": "Your message contains blocked language."})
            return

        conversation_id = conversation_identifier_for_direct(session["user_id"], recipient_db.id)
        nonce, ciphertext = encrypt_conversation_message(conversation_id, message)

        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient_db.id,
            text="" if ciphertext else message,
            ciphertext=ciphertext,
            nonce=nonce,
            is_encrypted=bool(ciphertext),
            timestamp=datetime.now(timezone.utc),
        )
        db.session.add(new_message)
        if sender:
            apply_progress(sender, 5)
        db.session.commit()

        payload = {
            "message_id": new_message.id,
            "username": username,
            "sender_id": session["user_id"],
            "recipient": recipient_db.username,
            "recipient_id": recipient_db.id,
            "message": None if ciphertext else message,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "is_encrypted": bool(ciphertext),
            "conversation": conversation_id,
            "timestamp": new_message.timestamp.isoformat() if new_message.timestamp else None,
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

        sender = User.query.get(session["user_id"])
        now = datetime.now(timezone.utc)
        if sender and sender.muted_until:
            if sender.muted_until > now:
                emit("error", {"error": "You are muted by a moderator."})
                return
            sender.muted_until = None
            db.session.commit()

        if _contains_blocked_language(message):
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

        conversation_id = conversation_identifier_for_group(group_id)
        nonce, ciphertext = encrypt_conversation_message(conversation_id, message)

        group_message = GroupMessage(
            group_id=group_id,
            membership_id=membership.id,
            alias=membership.alias,
            text="" if ciphertext else message,
            ciphertext=ciphertext,
            nonce=nonce,
            is_encrypted=bool(ciphertext),
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
            "message": None if ciphertext else message,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "is_encrypted": bool(ciphertext),
            "conversation": conversation_id,
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
        if caption and _contains_blocked_language(caption):
            emit("error", {"error": "Your caption contains blocked language."})
            return

        media_payload = {
            "media_type": upload_token.media_type,
            "storage_path": upload_token.storage_path,
            "duration_seconds": upload_token.duration_seconds,
            "mime_type": upload_token.mime_type,
        }

        sender = User.query.get(session["user_id"])
        now = datetime.now(timezone.utc)
        if sender and sender.muted_until:
            if sender.muted_until > now:
                emit("error", {"error": "You are muted by a moderator."})
                return
            sender.muted_until = None
            db.session.commit()

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

            conversation_id = conversation_identifier_for_group(group_id)
            nonce, ciphertext = encrypt_conversation_message(conversation_id, caption)

            group_message = GroupMessage(
                group_id=group_id,
                membership_id=membership.id,
                alias=membership.alias,
                text="" if ciphertext else caption,
                ciphertext=ciphertext,
                nonce=nonce,
                is_encrypted=bool(ciphertext),
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
                "message": None if ciphertext else caption,
                "ciphertext": ciphertext,
                "nonce": nonce,
                "is_encrypted": bool(ciphertext),
                "conversation": conversation_id,
                "timestamp": group_message.timestamp.isoformat(),
                "attachments": [
                    {
                        "media_type": media_payload["media_type"],
                        "storage_path": media_payload["storage_path"],
                        "duration_seconds": media_payload["duration_seconds"],
                        "mime_type": media_payload["mime_type"],
                        "url": url_for("serve_upload", filename=media_payload["storage_path"]),
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

        conversation_id = conversation_identifier_for_direct(session["user_id"], recipient.id)
        nonce, ciphertext = encrypt_conversation_message(conversation_id, caption)

        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient.id,
            text="" if ciphertext else caption,
            ciphertext=ciphertext,
            nonce=nonce,
            is_encrypted=bool(ciphertext),
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
            "message_id": new_message.id,
            "username": username,
            "sender_id": session["user_id"],
            "recipient": recipient.username,
            "recipient_id": recipient.id,
            "message": None if ciphertext else caption,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "is_encrypted": bool(ciphertext),
            "conversation": conversation_id,
            "timestamp": new_message.timestamp.isoformat(),
            "attachments": [
                {
                    "media_type": media_payload["media_type"],
                    "storage_path": media_payload["storage_path"],
                    "duration_seconds": media_payload["duration_seconds"],
                    "mime_type": media_payload["mime_type"],
                    "url": url_for("serve_upload", filename=media_payload["storage_path"]),
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

    @socketio.on("call_request")
    def handle_call_request(data):
        """Initiate a WebRTC call."""

        user_id = session.get("user_id")
        if not user_id:
            emit("call_error", {"error": "Login required."})
            return

        target_username = (data or {}).get("target")
        offer = (data or {}).get("offer")
        mode = ((data or {}).get("mode") or "audio").lower()
        if mode not in {"audio", "video"}:
            mode = "audio"
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
                "mode": mode,
            },
        )
        socketio.emit(
            "call_incoming",
            {
                "sessionId": session_obj.id,
                "roomId": session_obj.room_id,
                "caller": caller.username,
                "offer": offer,
                "mode": mode,
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
        mode = ((data or {}).get("mode") or "audio").lower()
        if mode not in {"audio", "video"}:
            mode = "audio"
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
                    {
                        "sessionId": session_obj.id,
                        "roomId": session_obj.room_id,
                        "mode": mode,
                    },
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
                "mode": mode,
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
