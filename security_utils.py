"""Utilities for deriving conversation identifiers and encrypting chat payloads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Iterable, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from flask import current_app


_DIRECT_PREFIX = "direct"
_GROUP_PREFIX = "group"


class ConversationIdentifierError(ValueError):
    """Raised when a conversation identifier cannot be parsed."""


def _get_secret_bytes() -> bytes:
    secret = current_app.config.get("CONVERSATION_KEY_SECRET") or current_app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("Conversation key secret is not configured.")
    if isinstance(secret, bytes):
        return secret
    return str(secret).encode("utf-8")


def conversation_identifier_for_direct(user_a: int, user_b: int) -> str:
    """Return a normalized identifier for a direct conversation."""

    participants = sorted([int(user_a), int(user_b)])
    return f"{_DIRECT_PREFIX}:{participants[0]}:{participants[1]}"


def conversation_identifier_for_group(group_id: int) -> str:
    """Return a normalized identifier for a group conversation."""

    return f"{_GROUP_PREFIX}:{int(group_id)}"


def parse_conversation_identifier(identifier: str) -> Tuple[str, Tuple[int, ...]]:
    """Parse a conversation identifier into its type and participants."""

    if not identifier:
        raise ConversationIdentifierError("Conversation identifier is required.")
    parts = identifier.split(":")
    prefix = parts[0]
    if prefix == _DIRECT_PREFIX and len(parts) == 3:
        try:
            first = int(parts[1])
            second = int(parts[2])
        except (TypeError, ValueError) as exc:
            raise ConversationIdentifierError("Direct conversation participant identifiers must be integers.") from exc
        return _DIRECT_PREFIX, tuple(sorted((first, second)))
    if prefix == _GROUP_PREFIX and len(parts) == 2:
        try:
            group_id = int(parts[1])
        except (TypeError, ValueError) as exc:
            raise ConversationIdentifierError("Group conversation identifier must include a numeric id.") from exc
        return _GROUP_PREFIX, (group_id,)
    raise ConversationIdentifierError("Conversation identifier format is invalid.")


def derive_conversation_key_material(identifier: str) -> bytes:
    """Derive deterministic key material for a conversation identifier."""

    secret = _get_secret_bytes()
    message = identifier.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).digest()


def export_conversation_key(identifier: str) -> str:
    """Return a base64 encoded conversation key."""

    key_bytes = derive_conversation_key_material(identifier)
    return base64.b64encode(key_bytes).decode("utf-8")


def encrypt_conversation_message(identifier: str, plaintext: str) -> Tuple[str | None, str | None]:
    """Encrypt plaintext for a conversation, returning nonce and ciphertext."""

    if plaintext is None:
        return None, None
    text = plaintext.strip()
    if not text:
        return None, None

    key = derive_conversation_key_material(identifier)
    nonce = secrets.token_bytes(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(text.encode("utf-8")) + encryptor.finalize()
    payload = ciphertext + encryptor.tag
    return (
        base64.b64encode(nonce).decode("utf-8"),
        base64.b64encode(payload).decode("utf-8"),
    )


def decrypt_conversation_message(identifier: str, nonce_b64: str, payload_b64: str) -> str:
    """Decrypt a ciphertext payload for a conversation."""

    if not nonce_b64 or not payload_b64:
        raise ValueError("Nonce and payload are required for decryption.")

    key = derive_conversation_key_material(identifier)
    nonce = base64.b64decode(nonce_b64)
    payload = base64.b64decode(payload_b64)
    if len(payload) < 16:
        raise ValueError("Ciphertext payload is too short.")
    ciphertext, tag = payload[:-16], payload[-16:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext.decode("utf-8")


def ensure_user_in_conversation(identifier: str, user_id: int) -> bool:
    """Return whether the user participates in the conversation."""

    conversation_type, participants = parse_conversation_identifier(identifier)
    if conversation_type == _DIRECT_PREFIX:
        return int(user_id) in participants
    if conversation_type == _GROUP_PREFIX:
        return True  # membership is validated separately for groups
    return False


def iter_direct_participants(identifier: str) -> Iterable[int]:
    """Yield participant identifiers for a direct conversation."""

    conversation_type, participants = parse_conversation_identifier(identifier)
    if conversation_type != _DIRECT_PREFIX:
        raise ConversationIdentifierError("Not a direct conversation identifier.")
    return participants


def get_group_id(identifier: str) -> int:
    """Return the group id for a group conversation identifier."""

    conversation_type, participants = parse_conversation_identifier(identifier)
    if conversation_type != _GROUP_PREFIX:
        raise ConversationIdentifierError("Not a group conversation identifier.")
    return participants[0]
