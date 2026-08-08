"""Stage 5 — DateField rebuild.

Each assertion states a condition from the acceptance column of defect G14 in
`.ai/UI_REDESIGN_AUDIT.md`: click-to-select, a 300–340px popup, an in-field quiet
clear icon, month stepping separated from year adjustment, and no confirm step.

Visual and DPI acceptance are not covered here and cannot be: 100/125/150%
Windows scaling needs a human in front of the running application.
"""

from __future__ import annotations

import datetime
import inspect
import logging
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from taxops.ui import tokens
from taxops.ui.widgets.buttons import button_role
from taxops.ui.widgets.date_field import DateField, _CalendarPopup

_MODULE = "taxops.ui.widgets.date_field"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _popup_buttons(popup: _CalendarPopup) -> list[QPushButton]:
    return popup.findChildren(QPushButton)


# ---------------------------------------------------------------------------
# A. The popup stops reading as a debugging tool
# ---------------------------------------------------------------------------

def test_popup_has_no_year_jump_buttons(qapp: QApplication) -> None:
    """The ±1/5/10-year row named in G14 is gone, control and class alike."""
    popup = _CalendarPopup(current_iso=None)
    jump = re.compile(r"^[+−-]\s*\d+\s*年$")
    offenders = [b.text() for b in _popup_buttons(popup) if jump.match(b.text().strip())]
    assert offenders == []
    popup.close()

    import taxops.ui.widgets.date_field as mod

    assert not hasattr(mod, "_YearJumpBar")


def test_popup_has_no_confirm_button(qapp: QApplication) -> None:
    """Selecting a date is the confirmation; a separate 確認 click is removed."""
    popup = _CalendarPopup(current_iso="2026-05-21")
    labels = [b.text().strip() for b in _popup_buttons(popup)]
    assert "確認" not in labels
    assert "確定" not in labels
    popup.close()


def test_clicking_a_date_applies_it_and_closes_the_popup(qapp: QApplication) -> None:
    """One click is the whole interaction: emit the ISO date and close."""
    popup = _CalendarPopup(current_iso=None)
    received: list[str] = []
    popup.date_confirmed.connect(received.append)

    popup._cal.clicked.emit(QDate(2026, 3, 10))

    assert received == ["2026-03-10"]
    assert not popup.isVisible()


def test_activated_confirms_even_when_the_field_already_has_a_value(
    qapp: QApplication,
) -> None:
    """Regression: the old popup returned from __init__ before connecting
    `activated` whenever a date was pre-filled, so Enter and double-click were
    dead for every field that already held a value."""
    popup = _CalendarPopup(current_iso="2026-05-21")
    received: list[str] = []
    popup.date_confirmed.connect(received.append)

    popup._cal.activated.emit(QDate(2026, 5, 25))

    assert received == ["2026-05-25"]


def test_popup_width_is_within_the_audit_range(qapp: QApplication) -> None:
    """G14 remedy: 300–340px, so the popup is narrower than its host dialog."""
    popup = _CalendarPopup(current_iso=None)
    assert 300 <= popup.width() <= 340
    assert popup.minimumWidth() == popup.maximumWidth()  # fixed, cannot grow
    popup.close()


def test_popup_stays_short_enough_not_to_swallow_a_dialog(qapp: QApplication) -> None:
    """A popup taller than this occluded the host dialog's footer at 768px."""
    popup = _CalendarPopup(current_iso=None)
    assert popup.sizeHint().height() <= 400
    popup.close()


# ---------------------------------------------------------------------------
# B. Month stepping and year adjustment are separate controls
# ---------------------------------------------------------------------------

def test_month_chevrons_step_exactly_one_month(qapp: QApplication) -> None:
    popup = _CalendarPopup(current_iso="2026-05-21")
    assert popup._cal.monthShown() == 5

    popup._next_month_btn.click()
    assert (popup._cal.yearShown(), popup._cal.monthShown()) == (2026, 6)

    popup._prev_month_btn.click()
    popup._prev_month_btn.click()
    assert (popup._cal.yearShown(), popup._cal.monthShown()) == (2026, 4)
    popup.close()


def test_month_chevron_rolls_the_year_over(qapp: QApplication) -> None:
    popup = _CalendarPopup(current_iso="2026-12-01")
    popup._next_month_btn.click()
    assert (popup._cal.yearShown(), popup._cal.monthShown()) == (2027, 1)

    popup._prev_month_btn.click()
    assert (popup._cal.yearShown(), popup._cal.monthShown()) == (2026, 12)
    popup.close()


def test_year_is_adjustable_from_the_popup_header(qapp: QApplication) -> None:
    popup = _CalendarPopup(current_iso="2026-05-21")
    popup._year_spin.setValue(2019)
    assert popup._cal.yearShown() == 2019
    assert popup._cal.monthShown() == 5  # year moves, month does not
    popup.close()


def test_header_year_follows_a_month_step_across_the_year_boundary(
    qapp: QApplication,
) -> None:
    popup = _CalendarPopup(current_iso="2026-01-15")
    popup._prev_month_btn.click()
    assert popup._cal.yearShown() == 2025
    assert popup._year_spin.value() == 2025
    popup.close()


def test_month_chevrons_are_labelled_for_keyboard_and_screen_readers(
    qapp: QApplication,
) -> None:
    popup = _CalendarPopup(current_iso=None)
    for button in (popup._prev_month_btn, popup._next_month_btn):
        assert button.accessibleName()
        assert button.toolTip()
        assert not button.icon().isNull()
        assert button_role(button) != tokens.ROLE_PRIMARY
    popup.close()


def test_popup_header_names_the_month_in_chinese(qapp: QApplication) -> None:
    popup = _CalendarPopup(current_iso="2026-05-21")
    assert popup._month_label.text() == "5月"
    popup._next_month_btn.click()
    assert popup._month_label.text() == "6月"
    popup.close()


# ---------------------------------------------------------------------------
# C. In-field quiet icons
# ---------------------------------------------------------------------------

def test_clear_and_calendar_icons_sit_inside_the_field(qapp: QApplication) -> None:
    """G14 remedy: in-field quiet clear. Both icons are children of the line
    edit, so the control reads as one input rather than input plus toolbar."""
    field = DateField(required=False)
    assert field._clear_btn.parent() is field._edit
    assert field._cal_btn.parent() is field._edit


def test_in_field_icons_are_quiet(qapp: QApplication) -> None:
    field = DateField(required=False)
    for button in (field._cal_btn, field._clear_btn):
        assert button_role(button) == tokens.ROLE_ICON
        assert button_role(button) != tokens.ROLE_PRIMARY


def test_line_edit_reserves_text_room_for_its_trailing_icons(
    qapp: QApplication,
) -> None:
    """Without a right text margin the typed date runs under the icons."""
    field = DateField(required=False)
    reserved = field._edit.textMargins().right()
    assert reserved >= field._cal_btn.width() + field._clear_btn.width()


def test_required_field_reserves_less_room_than_an_optional_one(
    qapp: QApplication,
) -> None:
    """A required field has no clear icon, so it must not reserve its width."""
    optional = DateField(required=False)
    required = DateField(required=True)
    assert required._edit.textMargins().right() < optional._edit.textMargins().right()


def test_optional_field_keeps_a_clear_icon_and_required_does_not(
    qapp: QApplication,
) -> None:
    assert not DateField(required=False)._clear_btn.isHidden()
    assert DateField(required=True)._clear_btn.isHidden()


def test_field_is_wide_enough_for_the_date_and_both_icons(
    qapp: QApplication,
) -> None:
    """DESIGN.md: no enabled element may be clipped. Ten glyphs plus two 32px
    icons do not fit the old 180px floor once the icons moved in-field."""
    field = DateField(required=False)
    icons_width = field._cal_btn.width() + field._clear_btn.width()
    text_width = field._edit.fontMetrics().horizontalAdvance("2026-05-21")
    assert field.minimumWidth() >= icons_width + text_width


def test_field_width_floor_follows_the_font(qapp: QApplication) -> None:
    """The floor is derived from the live font, not a fixed number.

    Regression guard for an order-dependent failure: a hard-coded 200px floor held
    while the same ten glyphs measured 136px, and clipped once they measured 140px
    under a larger font. The field passed alone and failed inside the full suite.
    A derived floor holds at any scaling, which is what 125% and 150% need.

    The global font is restored in `finally` so this test cannot become the next
    suite's pollution source.
    """
    original = QFont(qapp.font())
    try:
        enlarged = QFont(original)
        enlarged.setPointSizeF(original.pointSizeF() * 1.6)
        qapp.setFont(enlarged)

        field = DateField(required=False)
        icons_width = field._cal_btn.width() + field._clear_btn.width()
        text_width = field._edit.fontMetrics().horizontalAdvance("2026-05-21")
        assert field.minimumWidth() >= icons_width + text_width
        # The maximum must not sit below the minimum, or Qt silently clamps it.
        assert field.maximumWidth() >= field.minimumWidth()
    finally:
        qapp.setFont(original)


def test_required_and_optional_fields_share_a_width_floor(
    qapp: QApplication,
) -> None:
    """Both icons are counted even when the clear icon is hidden, so a required
    field does not sit narrower than the optional one beside it."""
    assert DateField(required=True).minimumWidth() == DateField(
        required=False
    ).minimumWidth()


# ---------------------------------------------------------------------------
# D. Keyboard arrows
# ---------------------------------------------------------------------------

def _field_with(text: str, cursor: int) -> DateField:
    field = DateField(required=False)
    field._edit.setText(text)
    field._edit.setCursorPosition(cursor)
    return field


def test_up_arrow_on_the_day_segment_adds_one_day(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 9)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.value() == "2026-05-22"


def test_down_arrow_on_the_day_segment_subtracts_one_day(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 9)
    QTest.keyClick(field._edit, Qt.Key.Key_Down)
    assert field.value() == "2026-05-20"


def test_arrow_on_the_month_segment_steps_the_month(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 6)
    QTest.keyClick(field._edit, Qt.Key.Key_Down)
    assert field.value() == "2026-04-21"


def test_arrow_on_the_year_segment_steps_the_year(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 2)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.value() == "2027-05-21"


def test_month_step_clamps_into_a_shorter_month(qapp: QApplication) -> None:
    """31 January plus one month is the last day of February, not an invalid date."""
    field = _field_with("2026-01-31", 6)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.value() == "2026-02-28"


def test_day_step_crosses_the_month_boundary(qapp: QApplication) -> None:
    field = _field_with("2026-05-31", 9)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.value() == "2026-06-01"


def test_arrow_on_an_empty_field_inserts_today(qapp: QApplication) -> None:
    field = DateField(required=False)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.value() == datetime.date.today().isoformat()


def test_arrow_emits_value_changed_with_the_new_date(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 9)
    received: list = []
    field.value_changed.connect(received.append)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert received == ["2026-05-22"]


def test_arrow_on_unparsable_text_reports_the_format_error(qapp: QApplication) -> None:
    """Loud: stepping text that is not a date says why instead of doing nothing."""
    field = _field_with("not-a-date", 4)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field.raw_text() == "not-a-date"  # input preserved
    assert not field._error_label.isHidden()
    assert "日期格式不正確" in field._error_label.text()


def test_arrow_keeps_the_cursor_in_the_segment_it_stepped(qapp: QApplication) -> None:
    field = _field_with("2026-05-21", 6)
    QTest.keyClick(field._edit, Qt.Key.Key_Up)
    assert field._edit.cursorPosition() == 6


# ---------------------------------------------------------------------------
# E. Error presentation
# ---------------------------------------------------------------------------

def test_error_text_meets_the_type_floor(qapp: QApplication) -> None:
    """DESIGN.md and tokens set the error floor at 14px; the field hard-coded 11."""
    field = DateField(required=False)
    sheet = field._error_label.styleSheet()
    assert f"{tokens.FONT_ERROR}px" in sheet
    assert "11px" not in sheet
    assert tokens.DANGER in sheet


def test_error_marks_the_line_edit_invalid_for_the_stylesheet(
    qapp: QApplication,
) -> None:
    """`style.py` styles QLineEdit[invalid="true"]; the field must set it or the
    red border the design system provides never appears."""
    field = DateField(required=False)
    assert field._edit.property("invalid") == "false"

    field.set_error("日期格式不正確")
    assert field._edit.property("invalid") == "true"

    field.set_error(None)
    assert field._edit.property("invalid") == "false"


def test_invalid_typed_date_marks_the_field_invalid(qapp: QApplication) -> None:
    field = DateField(required=False)
    field._edit.setText("2026-99-99")
    field._on_editing_finished()
    assert field._edit.property("invalid") == "true"
    assert "日期格式不正確" in field._error_label.text()


# ---------------------------------------------------------------------------
# F. Popup placement near a screen edge
# ---------------------------------------------------------------------------

_AVAIL = QRect(0, 0, 1366, 768)
_SIZE = QSize(320, 320)


def test_popup_sits_below_the_field_when_there_is_room(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import _popup_position

    pos = _popup_position(QPoint(100, 200), QPoint(100, 236), _SIZE, _AVAIL)
    assert pos == QPoint(100, 236)


def test_popup_flips_above_the_field_when_there_is_no_room_below(
    qapp: QApplication,
) -> None:
    from taxops.ui.widgets.date_field import _popup_position

    pos = _popup_position(QPoint(100, 700), QPoint(100, 736), _SIZE, _AVAIL)
    assert pos.y() == 700 - 320
    assert pos.y() >= _AVAIL.y()


def test_popup_clamps_to_the_right_edge(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import _popup_position

    pos = _popup_position(QPoint(1300, 200), QPoint(1300, 236), _SIZE, _AVAIL)
    assert pos.x() + _SIZE.width() <= _AVAIL.x() + _AVAIL.width()


def test_popup_never_starts_left_of_the_screen(qapp: QApplication) -> None:
    """The old code clamped right and bottom only, so a field on a secondary
    monitor to the left could push the popup off-screen."""
    from taxops.ui.widgets.date_field import _popup_position

    pos = _popup_position(QPoint(-400, 200), QPoint(-400, 236), _SIZE, _AVAIL)
    assert pos.x() >= _AVAIL.x()


def test_popup_stays_on_screen_when_it_fits_neither_above_nor_below(
    qapp: QApplication,
) -> None:
    from taxops.ui.widgets.date_field import _popup_position

    short = QRect(0, 0, 1366, 400)
    pos = _popup_position(QPoint(0, 120), QPoint(0, 156), _SIZE, short)
    assert pos.y() >= short.y()
    assert pos.y() + _SIZE.height() <= short.y() + short.height()


def test_popup_position_is_left_alone_when_no_screen_is_known(
    qapp: QApplication,
) -> None:
    from taxops.ui.widgets.date_field import _popup_position

    pos = _popup_position(QPoint(50, 60), QPoint(50, 96), _SIZE, QRect())
    assert pos == QPoint(50, 96)


def test_show_near_lands_inside_the_real_available_geometry(
    qapp: QApplication,
) -> None:
    field = DateField(required=False)
    field.show()
    popup = _CalendarPopup(current_iso=None, parent=field)
    popup.show_near(field)

    screen = QApplication.screenAt(field.mapToGlobal(QPoint(0, 0)))
    screen = screen or QApplication.primaryScreen()
    avail = screen.availableGeometry()
    assert popup.x() >= avail.x()
    assert popup.y() >= avail.y()
    popup.close()
    field.close()


# ---------------------------------------------------------------------------
# G. Frozen public API and the stored date range
# ---------------------------------------------------------------------------

def test_public_api_signatures_are_frozen(qapp: QApplication) -> None:
    """Six screens call these. `.ai/UI_REDESIGN_SPEC.md` freezes them."""
    expected = {
        "value": "(self)",
        "validated_value": "(self)",
        "raw_text": "(self)",
        "set_value": "(self, iso: 'str | None') -> 'None'",
        "set_error": "(self, message: 'str | None') -> 'None'",
        "clear": "(self)",
        "set_date_range": (
            "(self, min_date: 'str | None' = None, max_date: 'str | None' = None)"
            " -> 'None'"
        ),
    }
    for name, signature in expected.items():
        actual = str(inspect.signature(getattr(DateField, name)))
        assert actual.startswith(signature.split(")")[0] + ")"), (name, actual)

    assert hasattr(DateField, "value_changed")
    assert issubclass(DateField.InvalidInput, Exception)


def test_set_date_range_constrains_the_popup_calendar(qapp: QApplication) -> None:
    """The range was stored and never used — a constraint that did nothing."""
    field = DateField(required=False)
    field.set_date_range("2026-01-01", "2026-12-31")
    popup = field._build_popup()

    assert popup._cal.minimumDate() == QDate(2026, 1, 1)
    assert popup._cal.maximumDate() == QDate(2026, 12, 31)
    popup.close()


def test_set_date_range_none_leaves_the_calendar_unconstrained(
    qapp: QApplication,
) -> None:
    field = DateField(required=False)
    field.set_date_range(None, None)
    popup = field._build_popup()
    assert popup._cal.minimumDate() < QDate(1800, 1, 1)
    popup.close()


def test_set_date_range_logs_a_warning_for_unparsable_input(
    qapp: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    """Loud: a range the widget cannot read is reported, not silently stored."""
    field = DateField(required=False)
    with caplog.at_level(logging.WARNING, logger=_MODULE):
        field.set_date_range("not-a-date", None)
    assert any("not-a-date" in r.getMessage() for r in caplog.records)


def test_today_button_is_disabled_when_today_is_outside_the_range(
    qapp: QApplication,
) -> None:
    """DESIGN.md: no fake enabled actions."""
    field = DateField(required=False)
    field.set_date_range("1990-01-01", "1990-12-31")
    popup = field._build_popup()
    assert not popup._today_btn.isEnabled()
    popup.close()


def test_today_button_is_enabled_and_confirms_today_by_default(
    qapp: QApplication,
) -> None:
    popup = _CalendarPopup(current_iso=None)
    assert popup._today_btn.isEnabled()
    received: list[str] = []
    popup.date_confirmed.connect(received.append)
    popup._today_btn.click()
    assert received == [datetime.date.today().isoformat()]


def test_module_uses_no_qt_standard_pixmaps(qapp: QApplication) -> None:
    """G6: the shared inline SVG set is the only icon source."""
    import taxops.ui.widgets.date_field as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "StandardPixmap" not in source
    assert "standardIcon" not in source
