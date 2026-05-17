"""i18n labels: nav, primary buttons, table headers, error messages.

Per slice 1 scope: nav / status enum / table column / primary buttons /
error messages must not leak raw enum, DB field name, or exception text
into the UI surface. We do NOT require every internal string to be in a
label map.
"""

from __future__ import annotations

import re

from taxops.i18n import (
    BUTTON_LABELS,
    ERROR_MESSAGES,
    NAV_LABELS,
    TABLE_HEADERS,
)
from taxops.ui.action_registry import NAV_ORDER

_FORBIDDEN_SUBSTRINGS = (
    "exception",
    "traceback",
    "sqlite3",
    "psycopg2",
    "<script",
    "stacktrace",
)

_RAW_ENUM_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _has_chinese(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_nav_labels_cover_all_pages() -> None:
    for page_id in NAV_ORDER:
        label = NAV_LABELS.get(page_id)
        assert label, f"missing nav label for {page_id}"
        assert _has_chinese(label), label
        assert not _RAW_ENUM_RE.match(label)


def test_primary_button_labels_are_chinese() -> None:
    for key, label in BUTTON_LABELS.items():
        assert label, key
        assert _has_chinese(label), (key, label)
        for token in _FORBIDDEN_SUBSTRINGS:
            assert token not in label.lower(), (key, label)


def test_table_headers_no_raw_field_names() -> None:
    headers = TABLE_HEADERS["clients"]
    raw_field_names = {
        "id",
        "client_code",
        "tax_id",
        "client_name",
        "short_name",
        "contact_name",
        "contact_phone",
        "contact_email",
        "updated_at",
    }
    assert set(headers.keys()) == raw_field_names
    for field, label in headers.items():
        assert label != field, f"raw field name leaked as header: {field}"
        assert _has_chinese(label), (field, label)


def test_error_messages_dont_expose_internals() -> None:
    for code, message in ERROR_MESSAGES.items():
        for token in _FORBIDDEN_SUBSTRINGS:
            assert token not in message.lower(), (code, message)
        assert _has_chinese(message), (code, message)
