"""Shared constants and helpers for dialogs."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit


def make_nullable_date_edit() -> QDateEdit:
    """Return a QDateEdit where minimumDate() signals 'not set'."""
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setSpecialValueText("（不設定）")
    w.setDate(w.minimumDate())
    return w


def date_edit_value(w: QDateEdit) -> str | None:
    """Return ISO date string from a nullable QDateEdit, or None if not set."""
    d = w.date()
    return d.toString("yyyy-MM-dd") if d != w.minimumDate() else None


def set_date_edit_value(w: QDateEdit, iso: str | None) -> None:
    """Pre-populate a nullable QDateEdit from an ISO date string or None."""
    if iso:
        parsed = QDate.fromString(iso, "yyyy-MM-dd")
        w.setDate(parsed if parsed.isValid() else w.minimumDate())


TAX_TYPE_CHOICES: list[tuple[str, str]] = [
    ("vat", "營業稅"),
    ("cit", "營利事業所得稅"),
    ("iit", "綜合所得稅"),
    ("stamp", "印花稅"),
    ("inheritance", "遺產稅"),
    ("other", "其他"),
]
