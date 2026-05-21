"""Proper date input widget -- no sentinel values, clean optional/required semantics."""
from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)

_ISO_FMT = "yyyy-MM-dd"
_PLACEHOLDER = "yyyy-MM-dd"


class _YearJumpBar(QWidget):
    """Row of year-jump buttons for the calendar popup."""

    def __init__(self, calendar: QCalendarWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cal = calendar
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)
        for delta, label in (
            (-10, "−10年"), (-5, "−5年"), (-1, "−1年"),
            (1, "+1年"), (5, "+5年"), (10, "+10年"),
        ):
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _=False, d=delta: self._jump(d))
            row.addWidget(btn)
        row.addStretch()

    def _jump(self, delta: int) -> None:
        new_year = self._cal.yearShown() + delta
        if 1 <= new_year <= 9999:
            self._cal.setCurrentPage(new_year, self._cal.monthShown())


class _CalendarPopup(QDialog):
    """Popup calendar: emits ISO string on confirm; never auto-writes to the field."""

    date_confirmed = Signal(str)

    def __init__(self, current_iso: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        self._cal = QCalendarWidget()
        self._cal.setGridVisible(True)
        self._cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self._cal.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        outer.addWidget(_YearJumpBar(self._cal))
        outer.addWidget(self._cal)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        today_btn = QPushButton("今天")
        today_btn.setFixedHeight(28)
        today_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        today_btn.clicked.connect(self._select_today)
        confirm_btn = QPushButton("確認")
        confirm_btn.setFixedHeight(28)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(today_btn)
        btn_row.addStretch()
        btn_row.addWidget(confirm_btn)
        outer.addLayout(btn_row)

        if current_iso:
            parsed = QDate.fromString(current_iso, _ISO_FMT)
            if parsed.isValid():
                self._cal.setSelectedDate(parsed)
                self._cal.setCurrentPage(parsed.year(), parsed.month())
                return
        # Field is empty: navigate to today but do NOT pre-select any date
        today = QDate.currentDate()
        self._cal.setCurrentPage(today.year(), today.month())

        self._cal.activated.connect(self._confirm)  # double-click confirms

    def _select_today(self) -> None:
        today = QDate.currentDate()
        self._cal.setSelectedDate(today)
        self._confirm()

    def _confirm(self) -> None:
        d = self._cal.selectedDate()
        if d.isValid():
            self.date_confirmed.emit(d.toString(_ISO_FMT))
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def show_near(self, anchor: QWidget) -> None:
        """Position popup below anchor, clamped to screen boundaries."""
        self.adjustSize()
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            ph, pw = self.sizeHint().height(), self.sizeHint().width()
            if pos.y() + ph > avail.bottom():
                pos.setY(anchor.mapToGlobal(anchor.rect().topLeft()).y() - ph)
            if pos.x() + pw > avail.right():
                pos.setX(avail.right() - pw)
        self.move(pos)
        self.show()


class DateField(QWidget):
    """
    Clean date input: QLineEdit + calendar popup + optional clear button.

    required=True  -- initializes to local today, no clear button
    required=False -- initializes empty, has clear button, value() returns None when empty

    API:
        value() -> str | None          ISO date string or None
        set_value(str | None)
        set_error(str | None)
        clear()                        only effective for optional fields
        set_date_range(min, max)
    """

    value_changed = Signal(object)  # str | None

    def __init__(
        self,
        *,
        required: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._required = required
        self._min_date: str | None = None
        self._max_date: str | None = None

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(_PLACEHOLDER)
        self._edit.setMaxLength(10)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self._edit)

        self._cal_btn = QPushButton("\U0001f4c5")
        self._cal_btn.setFixedSize(28, 28)
        self._cal_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cal_btn.setToolTip("開啟日曆")
        self._cal_btn.clicked.connect(self._open_calendar)
        row.addWidget(self._cal_btn)

        self._clear_btn = QPushButton("×")
        self._clear_btn.setFixedSize(28, 28)
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_btn.setToolTip("清除日期")
        self._clear_btn.clicked.connect(self.clear)
        self._clear_btn.setVisible(not required)
        row.addWidget(self._clear_btn)

        main.addLayout(row)

        self._error_label = QLabel()
        self._error_label.setObjectName("FieldError")
        self._error_label.setStyleSheet("color: red; font-size: 11px;")
        self._error_label.setVisible(False)
        self._error_label.setWordWrap(True)
        main.addWidget(self._error_label)

        if required:
            self._edit.setText(QDate.currentDate().toString(_ISO_FMT))

        self._edit.editingFinished.connect(self._on_editing_finished)

    # ── public API ────────────────────────────────────────────────────────

    def value(self) -> str | None:
        """Return normalized ISO string, or None if empty/invalid."""
        text = self._edit.text().strip()
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text).isoformat()
        except ValueError:
            return None

    def raw_text(self) -> str:
        """Return raw text from the line edit (may be invalid)."""
        return self._edit.text().strip()

    def set_value(self, iso: str | None) -> None:
        """Set field from ISO string or None. Logs and clears on unrecognised input."""
        if iso:
            parsed = QDate.fromString(iso, _ISO_FMT)
            if parsed.isValid():
                self._edit.setText(iso)
                self.set_error(None)
                return
            _log.warning("DateField.set_value: unrecognised %r -- clearing", iso)
        self._edit.setText("")
        self.set_error(None)

    def set_error(self, message: str | None) -> None:
        if message:
            self._error_label.setText(message)
            self._error_label.setVisible(True)
        else:
            self._error_label.setText("")
            self._error_label.setVisible(False)

    def clear(self) -> None:
        """Clear to empty. Only effective for optional fields."""
        if not self._required:
            self._edit.setText("")
            self.set_error(None)
            self.value_changed.emit(None)

    def set_date_range(
        self,
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> None:
        self._min_date = min_date
        self._max_date = max_date

    # ── private ───────────────────────────────────────────────────────────

    def _on_editing_finished(self) -> None:
        text = self._edit.text().strip()
        if not text:
            self.set_error("必填日期" if self._required else None)
            return
        try:
            d = datetime.date.fromisoformat(text)
            normalized = d.isoformat()
            if normalized != text:
                self._edit.setText(normalized)
            self.set_error(None)
            self.value_changed.emit(normalized)
        except ValueError:
            self.set_error(
                "日期格式不正確，請輸入 yyyy-MM-dd"
                "（例：2026-05-21）"
            )

    def _open_calendar(self) -> None:
        popup = _CalendarPopup(self.value(), parent=self)
        popup.date_confirmed.connect(self._on_date_confirmed)
        popup.show_near(self._cal_btn)

    def _on_date_confirmed(self, iso: str) -> None:
        self._edit.setText(iso)
        self.set_error(None)
        self.value_changed.emit(iso)
        self._edit.setFocus()
