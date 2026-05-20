"""Shared constants and helpers for dialogs."""

from __future__ import annotations

import logging

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDateEdit,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

_log = logging.getLogger(__name__)

_SENTINEL_DATE = QDate(2000, 1, 1)


class _YearJumpCalendar(QCalendarWidget):
    """Calendar popup with year-jump buttons and today-snap when sentinel is active."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inject_jump_bar()

    def _inject_jump_bar(self) -> None:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)
        for delta, label in ((-10, "−10年"), (-5, "−5年"), (-1, "−1年"), (1, "+1年"), (5, "+5年"), (10, "+10年")):
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked=False, d=delta: self._jump_years(d))
            row.addWidget(btn)
        row.addStretch()
        main = self.layout()
        if main:
            main.insertWidget(1, bar)

    def _jump_years(self, delta: int) -> None:
        new_year = self.yearShown() + delta
        if 1 <= new_year <= 9999:
            self.setCurrentPage(new_year, self.monthShown())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        p = self.parent()
        if isinstance(p, QDateEdit) and p.date() == p.minimumDate():
            today = QDate.currentDate()
            self.setCurrentPage(today.year(), today.month())


def make_nullable_date_edit() -> QDateEdit:
    """Return a date edit whose minimum date acts as the 'not set' sentinel."""
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setCalendarWidget(_YearJumpCalendar(w))
    w.setDisplayFormat("yyyy-MM-dd")
    w.setMinimumDate(_SENTINEL_DATE)
    w.setSpecialValueText("（不設定）")
    w.setDate(_SENTINEL_DATE)
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
            w.setDate(_SENTINEL_DATE)
            return
        w.setDate(parsed)
    else:
        w.setDate(_SENTINEL_DATE)


TAX_TYPE_CHOICES: list[tuple[str, str]] = [
    ("vat", "營業稅"),
    ("cit", "營利事業所得稅"),
    ("iit", "綜合所得稅"),
    ("stamp", "印花稅"),
    ("inheritance", "遺產稅"),
    ("other", "其他"),
]
