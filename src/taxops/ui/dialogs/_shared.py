"""Shared constants and helpers for dialogs."""

from __future__ import annotations

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit

_log = logging.getLogger(__name__)

_MIN_USER_DATE = QDate(2000, 1, 1)


def make_nullable_date_edit() -> QDateEdit:
    """Return a date edit whose minimum date acts as the 'not set' sentinel."""
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("yyyy-MM-dd")
    w.setMinimumDate(_MIN_USER_DATE)
    w.setSpecialValueText("（不設定）")
    w.setDate(_MIN_USER_DATE)  # default = "not set", not today
    return w


def date_edit_value(w: QDateEdit) -> str | None:
    """Return ISO date string from a nullable QDateEdit, or None if not set."""
    d = w.date()
    return d.toString("yyyy-MM-dd") if d != w.minimumDate() else None


def set_date_edit_value(w: QDateEdit, iso: str | None) -> None:
    """Pre-populate a nullable QDateEdit from an ISO date string or None."""
    if iso:
        parsed = QDate.fromString(iso, "yyyy-MM-dd")
        if not parsed.isValid():
            _log.warning("set_date_edit_value: invalid ISO date %r, leaving blank", iso)
            w.setDate(_MIN_USER_DATE)
            return
        w.setDate(parsed)
    else:
        w.setDate(_MIN_USER_DATE)  # None → "not set" sentinel, not today


TAX_TYPE_CHOICES: list[tuple[str, str]] = [
    ("vat", "營業稅"),
    ("cit", "營利事業所得稅"),
    ("iit", "綜合所得稅"),
    ("stamp", "印花稅"),
    ("inheritance", "遺產稅"),
    ("other", "其他"),
]
