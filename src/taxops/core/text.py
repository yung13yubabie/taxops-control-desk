"""Text sanitization.

Used at UI boundaries to prevent leaking raw enum values, DB field names,
or exception text into the UI surface.
"""

from __future__ import annotations

import unicodedata


def sanitize_user_text(value: str | None, *, max_length: int = 2000) -> str:
    """Return a user-safe trimmed string.

    Strips control characters except newline and tab. Truncates over-long
    input to ``max_length`` to enforce resource limits at the boundary.
    """

    if value is None:
        return ""
    cleaned = []
    for ch in value:
        if ch in ("\n", "\t"):
            cleaned.append(ch)
            continue
        if unicodedata.category(ch).startswith("C"):
            continue
        cleaned.append(ch)
    text = "".join(cleaned).strip()
    if len(text) > max_length:
        text = text[:max_length]
    return text


def is_safe_for_ui(value: str) -> bool:
    """Return True if the value contains no obvious raw exception or HTML."""
    if not value:
        return True
    lowered = value.lower()
    suspect_substrings = (
        "<script",
        "</script",
        "traceback",
        "sqlite3.",
        "psycopg2.",
        "exception:",
        "stacktrace",
    )
    return not any(token in lowered for token in suspect_substrings)
