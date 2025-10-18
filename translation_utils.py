"""Utilities for performing lightweight text translations."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

try:
    from googletrans import Translator  # type: ignore
except Exception as exc:  # pragma: no cover - import guard
    Translator = None  # type: ignore
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class TranslationError(RuntimeError):
    """Raised when translation is unavailable or fails."""


@lru_cache(maxsize=1)
def _get_translator() -> Translator:
    if Translator is None or IMPORT_ERROR is not None:
        raise TranslationError("Translation service is unavailable: googletrans not installed.")
    return Translator()


def translate_text(text: str, target_language: str, source_language: Optional[str] = None) -> str:
    """Translate text to a target language using googletrans."""

    if not text:
        return ""

    translator = _get_translator()
    try:
        result = translator.translate(text, dest=target_language, src=source_language or "auto")
    except Exception as exc:  # pragma: no cover - network related
        raise TranslationError("Unable to complete translation request.") from exc
    return result.text
