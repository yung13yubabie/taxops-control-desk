"""Date input: typed ISO text, keyboard stepping, and a compact calendar popup.

The field is a single line edit carrying its own trailing icons. Typing
`yyyy-MM-dd` is the primary path; Up and Down step the segment under the cursor;
the calendar icon opens a 320px popup where one click on a day applies the date
and closes. There is no confirm step and no year-jump row — the popup shows a
month at a time, chevrons step the month, and the header spin box moves the year.

`DateField`'s public API is frozen by `.ai/UI_REDESIGN_SPEC.md`: `value_changed`,
`value`, `validated_value`, `raw_text`, `set_value`, `set_error`, `clear`, and
`set_date_range` keep their signatures and semantics. Everything below them is
internal.
"""
from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import QDate, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import tokens
from .buttons import make_button, make_icon_button

_log = logging.getLogger(__name__)

_ISO_FMT = "yyyy-MM-dd"
_PLACEHOLDER = "yyyy-MM-dd"

# Audit G14 remedy: a 300-340px popup, narrower than the dialog it opens over.
POPUP_WIDTH = 320

# QDate's own limits. Keeping the header spin box this wide means no date a
# caller can store is unreachable from the popup.
_MIN_YEAR = 1
_MAX_YEAR = 9999

_ERROR_FORMAT = "日期格式不正確，請輸入 yyyy-MM-dd（例：2026-05-21）"
_ERROR_REQUIRED = "必填日期"

# Gap between the trailing icons and the line edit's right border.
_ICON_GAP = 4

# Segment boundaries in "yyyy-MM-dd": 0-4 year, 5-7 month, 8-10 day.
_YEAR_END = 4
_MONTH_END = 7


def _parse_iso(text: str | None) -> datetime.date | None:
    """Parse a strict ISO date, or None. The single parser for this module."""
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text.strip())
    except ValueError:
        return None


def _to_qdate(date: datetime.date) -> QDate:
    return QDate(date.year, date.month, date.day)


def _popup_position(
    anchor_top_left: QPoint,
    anchor_bottom_left: QPoint,
    size: QSize,
    available: QRect,
) -> QPoint:
    """Where to put a popup of `size` under `anchor_bottom_left`.

    Flips above the anchor when the popup would run off the bottom, then clamps
    to every edge. An empty `available` means the screen is unknown, in which
    case the anchored position is used unchanged rather than clamped to a guess.
    """
    x = anchor_bottom_left.x()
    y = anchor_bottom_left.y()
    if available.isEmpty():
        return QPoint(x, y)

    left = available.x()
    top = available.y()
    right_edge = available.x() + available.width()
    bottom_edge = available.y() + available.height()

    if y + size.height() > bottom_edge:
        flipped = anchor_top_left.y() - size.height()
        y = flipped if flipped >= top else bottom_edge - size.height()
    if x + size.width() > right_edge:
        x = right_edge - size.width()

    return QPoint(max(x, left), max(y, top))


def _available_geometry(near: QPoint) -> QRect:
    """Available geometry of the screen holding `near`.

    Uses the screen under the anchor rather than the primary screen, so a field
    on a secondary monitor is not clamped against the wrong desktop.
    """
    screen = QApplication.screenAt(near) or QApplication.primaryScreen()
    if screen is None:
        _log.warning("DateField popup: no screen at %s; leaving position unclamped", near)
        return QRect()
    return screen.availableGeometry()


class _DateLineEdit(QLineEdit):
    """Line edit that hosts trailing icon buttons and steps the date on arrows.

    The buttons are real focusable children rather than `QLineEdit` actions so
    they keep an accessible name, a shortcut, and a keyboard focus policy.
    """

    step_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._trailing: tuple[QPushButton, ...] = ()

    def set_trailing_buttons(self, *buttons: QPushButton) -> None:
        """Adopt `buttons` as in-field icons, left to right."""
        self._trailing = buttons
        for button in buttons:
            button.setParent(self)
            # A line edit shows an I-beam cursor and children inherit it.
            button.setCursor(Qt.CursorShape.ArrowCursor)
            # setParent() hides a widget; without this the button reports
            # isHidden() even for a field that should show it.
            button.show()
        self.layout_trailing()

    def layout_trailing(self) -> None:
        """Reserve text room for the visible icons and right-align them."""
        visible = [b for b in self._trailing if not b.isHidden()]
        reserve = sum(b.width() for b in visible) + _ICON_GAP * (len(visible) + 1)
        self.setTextMargins(0, 0, reserve if visible else 0, 0)

        x = self.width() - _ICON_GAP
        for button in reversed(visible):
            y = max((self.height() - button.height()) // 2, 0)
            button.move(x - button.width(), y)
            button.raise_()
            x -= button.width() + _ICON_GAP

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.layout_trailing()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        # Alt+Down belongs to the calendar button's shortcut, not to stepping.
        if not event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Up:
                self.step_requested.emit(1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down:
                self.step_requested.emit(-1)
                event.accept()
                return
        super().keyPressEvent(event)


class _CalendarPopup(QDialog):
    """One month at a time. Clicking a day emits its ISO date and closes.

    The calendar's own painting is left to the platform style: styling
    `QCalendarWidget` internals through a stylesheet is how the checkbox
    indicator was silently erased earlier in this rebuild, and nothing here can
    be verified without a human at the screen.
    """

    date_confirmed = Signal(str)

    def __init__(
        self,
        current_iso: str | None = None,
        *,
        min_iso: str | None = None,
        max_iso: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("DatePopup")
        self.setFixedWidth(POPUP_WIDTH)
        self.setStyleSheet(
            f"QDialog#DatePopup {{"
            f" background-color: {tokens.SURFACE_CONTENT};"
            f" border: 1px solid {tokens.BORDER_STRONG};"
            f" border-radius: {tokens.RADIUS_LG}px; }}"
        )
        self._syncing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACING_SM, tokens.SPACING_SM, tokens.SPACING_SM, tokens.SPACING_SM
        )
        outer.setSpacing(tokens.SPACING_SM)

        self._cal = QCalendarWidget()
        self._cal.setNavigationBarVisible(False)  # replaced by the header below
        self._cal.setGridVisible(False)
        self._cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self._cal.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer.addLayout(self._build_header())
        outer.addWidget(self._cal)
        outer.addLayout(self._build_footer())

        self._prev_month_btn.clicked.connect(lambda: self._step_month(-1))
        self._next_month_btn.clicked.connect(lambda: self._step_month(1))
        self._year_spin.valueChanged.connect(self._on_year_spin_changed)
        self._today_btn.clicked.connect(self._select_today)
        self._cal.currentPageChanged.connect(self._sync_header)
        # Both paths apply immediately: single click, and Enter or double-click.
        self._cal.clicked.connect(self._on_day_chosen)
        self._cal.activated.connect(self._on_day_chosen)

        self._apply_range(min_iso, max_iso)

        current = _parse_iso(current_iso)
        if current is not None:
            selected = _to_qdate(current)
            self._cal.setSelectedDate(selected)
            self._cal.setCurrentPage(selected.year(), selected.month())
        else:
            # Empty field: show today's month but leave the field's value alone.
            today = QDate.currentDate()
            self._cal.setCurrentPage(today.year(), today.month())

        self._sync_header(self._cal.yearShown(), self._cal.monthShown())

    # ── construction ──────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        self._prev_month_btn = make_icon_button(
            "chevron-left", tooltip="上一個月", accessible_name="上一個月"
        )
        self._next_month_btn = make_icon_button(
            "chevron-right", tooltip="下一個月", accessible_name="下一個月"
        )

        self._year_spin = QSpinBox()
        self._year_spin.setRange(_MIN_YEAR, _MAX_YEAR)
        self._year_spin.setSuffix("年")
        self._year_spin.setAccessibleName("年份")
        self._year_spin.setToolTip("調整年份")
        self._year_spin.setProperty("density", "compact")
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._month_label = QLabel()
        self._month_label.setAccessibleName("月份")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(tokens.SPACING_XS)
        header.addWidget(self._prev_month_btn)
        header.addStretch()
        header.addWidget(self._year_spin)
        header.addWidget(self._month_label)
        header.addStretch()
        header.addWidget(self._next_month_btn)
        return header

    def _build_footer(self) -> QHBoxLayout:
        self._today_btn = make_button(
            "今天",
            role=tokens.ROLE_QUIET,
            icon_role="today",
            tooltip="選擇今天",
        )
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self._today_btn)
        footer.addStretch()
        return footer

    def _apply_range(self, min_iso: str | None, max_iso: str | None) -> None:
        minimum = _parse_iso(min_iso)
        maximum = _parse_iso(max_iso)
        if minimum is not None:
            self._cal.setMinimumDate(_to_qdate(minimum))
        if maximum is not None:
            self._cal.setMaximumDate(_to_qdate(maximum))
        self._year_spin.setRange(
            max(self._cal.minimumDate().year(), _MIN_YEAR),
            min(self._cal.maximumDate().year(), _MAX_YEAR),
        )
        # DESIGN.md: no fake enabled actions.
        today = QDate.currentDate()
        self._today_btn.setEnabled(
            self._cal.minimumDate() <= today <= self._cal.maximumDate()
        )

    # ── header behaviour ──────────────────────────────────────────────────

    def _step_month(self, delta: int) -> None:
        shown = QDate(self._cal.yearShown(), self._cal.monthShown(), 1).addMonths(delta)
        if shown.isValid():
            self._cal.setCurrentPage(shown.year(), shown.month())

    def _on_year_spin_changed(self, year: int) -> None:
        if self._syncing:
            return
        self._cal.setCurrentPage(year, self._cal.monthShown())

    def _sync_header(self, year: int, month: int) -> None:
        self._syncing = True
        try:
            self._year_spin.setValue(year)
        finally:
            self._syncing = False
        self._month_label.setText(f"{month}月")

    # ── selection ─────────────────────────────────────────────────────────

    def _on_day_chosen(self, date: QDate) -> None:
        if date.isValid():
            self._cal.setSelectedDate(date)
        self._confirm()

    def _select_today(self) -> None:
        self._cal.setSelectedDate(QDate.currentDate())
        self._confirm()

    def _confirm(self) -> None:
        selected = self._cal.selectedDate()
        if selected.isValid():
            self.date_confirmed.emit(selected.toString(_ISO_FMT))
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm()
        else:
            super().keyPressEvent(event)

    def show_near(self, anchor: QWidget) -> None:
        """Position below `anchor`, flipping and clamping to stay on screen."""
        self.adjustSize()
        below = anchor.mapToGlobal(anchor.rect().bottomLeft())
        above = anchor.mapToGlobal(anchor.rect().topLeft())
        self.move(_popup_position(above, below, self.size(), _available_geometry(below)))
        self.show()
        self._cal.setFocus()


class DateField(QWidget):
    """
    Date input: typed ISO text, arrow stepping, and a calendar popup.

    required=True  -- initializes to local today, no clear icon
    required=False -- initializes empty, has a clear icon, value() returns None
                      when empty

    API:
        value() -> str | None          ISO date string or None (None for empty OR invalid)
        validated_value() -> str | None  same but raises InvalidInput if text is non-empty
                                         and not a valid date; also marks the field with error
        set_value(str | None)
        set_error(str | None)
        clear()                        only effective for optional fields
        set_date_range(min, max)
    """

    class InvalidInput(Exception):
        """Raised by validated_value() when raw_text is non-empty but not a valid ISO date."""

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
        # Wide enough for ten glyphs plus both in-field icons at every scaling.
        self.setMinimumWidth(200)
        self.setMaximumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(tokens.SPACING_XS)

        self._edit = _DateLineEdit()
        self._edit.setPlaceholderText(_PLACEHOLDER)
        self._edit.setMaxLength(10)
        self._edit.setMinimumHeight(tokens.INPUT_HEIGHT)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main.addWidget(self._edit)

        # Quiet in-field icons from the shared SVG set. Keeping them as buttons
        # preserves the keyboard shortcut and accessible name a QLineEdit action
        # cannot carry.
        self._clear_btn = make_icon_button(
            "clear", tooltip="清除日期", accessible_name="清除日期"
        )
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._clear_btn.setShortcut(QKeySequence("Alt+Backspace"))
        self._clear_btn.clicked.connect(self.clear)

        self._cal_btn = make_icon_button(
            "nav-calendar", tooltip="開啟日曆", accessible_name="開啟日期選擇器"
        )
        self._cal_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cal_btn.setShortcut(QKeySequence("Alt+Down"))
        self._cal_btn.clicked.connect(self._open_calendar)

        self._edit.set_trailing_buttons(self._clear_btn, self._cal_btn)
        if required:
            self._clear_btn.setVisible(False)
            self._edit.layout_trailing()

        self._error_label = QLabel()
        self._error_label.setObjectName("FieldError")
        self._error_label.setStyleSheet(
            f"color: {tokens.DANGER}; font-size: {tokens.FONT_ERROR}px;"
        )
        self._error_label.setVisible(False)
        self._error_label.setWordWrap(True)
        main.addWidget(self._error_label)

        self._set_invalid(False)
        if required:
            self._edit.setText(QDate.currentDate().toString(_ISO_FMT))

        self._edit.editingFinished.connect(self._on_editing_finished)
        self._edit.step_requested.connect(self._step)

    # ── public API ────────────────────────────────────────────────────────

    def value(self) -> str | None:
        """Return normalized ISO string, or None if empty OR invalid (silent)."""
        parsed = _parse_iso(self._edit.text())
        return parsed.isoformat() if parsed is not None else None

    def validated_value(self) -> str | None:
        """Return normalized ISO string or None (if empty).

        Raises DateField.InvalidInput if raw_text is non-empty but not a valid
        date. Also marks the field with an inline error message so the user
        sees exactly which field is wrong.
        """
        text = self._edit.text().strip()
        if not text:
            return None
        parsed = _parse_iso(text)
        if parsed is None:
            self.set_error(_ERROR_FORMAT)
            raise DateField.InvalidInput(f"invalid date text: {text!r}")
        return parsed.isoformat()

    def raw_text(self) -> str:
        """Return raw text from the line edit (may be invalid)."""
        return self._edit.text().strip()

    def set_value(self, iso: str | None) -> None:
        """Set field from ISO string or None. Logs and clears on unrecognised input."""
        if iso:
            parsed = _parse_iso(iso)
            if parsed is not None:
                self._edit.setText(parsed.isoformat())
                self.set_error(None)
                return
            _log.warning("DateField.set_value: unrecognised %r -- clearing", iso)
        self._edit.setText("")
        self.set_error(None)

    def set_error(self, message: str | None) -> None:
        if message:
            self._error_label.setText(message)
            self._error_label.setVisible(True)
            self._set_invalid(True)
        else:
            self._error_label.setText("")
            self._error_label.setVisible(False)
            self._set_invalid(False)

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
        for label, given in (("min_date", min_date), ("max_date", max_date)):
            if given and _parse_iso(given) is None:
                _log.warning(
                    "DateField.set_date_range: unrecognised %s %r -- ignoring", label, given
                )
        self._min_date = min_date
        self._max_date = max_date

    # ── private ───────────────────────────────────────────────────────────

    def _set_invalid(self, invalid: bool) -> None:
        """Toggle the stylesheet's invalid state on the line edit.

        Qt does not repaint on a dynamic property change, so a property set
        without unpolish/polish has no visual effect at all.
        """
        wanted = "true" if invalid else "false"
        if self._edit.property("invalid") == wanted:
            return
        self._edit.setProperty("invalid", wanted)
        style = self._edit.style()
        if style is not None:
            style.unpolish(self._edit)
            style.polish(self._edit)
        self._edit.update()

    def _on_editing_finished(self) -> None:
        text = self._edit.text().strip()
        if not text:
            self.set_error(_ERROR_REQUIRED if self._required else None)
            return
        parsed = _parse_iso(text)
        if parsed is None:
            self.set_error(_ERROR_FORMAT)
            return
        normalized = parsed.isoformat()
        if normalized != text:
            self._edit.setText(normalized)
        self.set_error(None)
        self.value_changed.emit(normalized)

    def _step(self, delta: int) -> None:
        """Adjust the segment under the cursor by `delta`.

        Empty field steps to today. Text that is not a date says so rather than
        doing nothing.
        """
        cursor = self._edit.cursorPosition()
        text = self._edit.text().strip()
        if not text:
            self._apply_stepped(QDate.currentDate(), len(_PLACEHOLDER))
            return

        parsed = _parse_iso(text)
        if parsed is None:
            self.set_error(_ERROR_FORMAT)
            return

        current = _to_qdate(parsed)
        if cursor <= _YEAR_END:
            stepped = current.addYears(delta)
        elif cursor <= _MONTH_END:
            stepped = current.addMonths(delta)
        else:
            stepped = current.addDays(delta)
        if stepped.isValid():
            self._apply_stepped(stepped, cursor)

    def _apply_stepped(self, date: QDate, cursor: int) -> None:
        iso = date.toString(_ISO_FMT)
        self._edit.setText(iso)
        self._edit.setCursorPosition(min(cursor, len(iso)))
        self.set_error(None)
        self.value_changed.emit(iso)

    def _build_popup(self) -> _CalendarPopup:
        popup = _CalendarPopup(
            self.value(),
            min_iso=self._min_date,
            max_iso=self._max_date,
            parent=self,
        )
        popup.date_confirmed.connect(self._on_date_confirmed)
        return popup

    def _open_calendar(self) -> None:
        # Anchored on the field so the popup lines up with the input's left edge.
        self._build_popup().show_near(self)

    def _on_date_confirmed(self, iso: str) -> None:
        self._edit.setText(iso)
        self.set_error(None)
        self.value_changed.emit(iso)
        self._edit.setFocus()
