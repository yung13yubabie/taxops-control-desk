"""Explicit date validation guides correction without changing date semantics."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from taxops.ui.widgets.date_field import DateField


def _form(qtbot):
    form = QWidget()
    qtbot.addWidget(form)
    layout = QVBoxLayout(form)
    field = DateField(required=False)
    other = QLineEdit()
    layout.addWidget(field)
    layout.addWidget(other)
    form.show()
    form.activateWindow()
    other.setFocus()
    qtbot.waitUntil(other.hasFocus)
    return form, field, other


@pytest.mark.parametrize("raw", ["2026-02-30", "not-a-date"])
def test_explicit_invalid_date_validation_focuses_input_without_changing_raw(qtbot, raw):
    form, field, other = _form(qtbot)
    field._edit.setText(raw)
    assert other.hasFocus()
    with pytest.raises(DateField.InvalidInput):
        field.validated_value()
    assert field._edit.hasFocus()
    assert field.raw_text() == raw
    assert not field._error_label.isHidden()
    assert field.value() is None
    assert form.isVisible()


@pytest.mark.parametrize("raw, expected", [("2026-02-28", "2026-02-28"), ("", None)])
def test_valid_or_optional_empty_date_validation_keeps_current_focus(qtbot, raw, expected):
    form, field, other = _form(qtbot)
    field._edit.setText(raw)
    assert field.validated_value() == expected
    assert other.hasFocus()
    assert field.raw_text() == raw
    assert form.isVisible()


def test_passive_date_error_and_blur_validation_do_not_steal_focus(qtbot):
    form, field, other = _form(qtbot)
    field._edit.setText("2026-99-99")
    field.set_error("請修正日期")
    assert other.hasFocus()
    field.set_error(None)
    assert other.hasFocus()
    field._on_editing_finished()
    assert other.hasFocus()
    assert not field._error_label.isHidden()
    assert field.raw_text() == "2026-99-99"
    assert form.isVisible()


def test_late_fee_submit_focuses_first_invalid_date_then_next_after_correction(qtbot, container):
    from taxops.ui.pages.late_fee_page import LateFeePage

    page = LateFeePage(container)
    qtbot.addWidget(page)
    page._source_manual_radio.setChecked(True)
    page._unlock_check.setChecked(True)
    page._last_payment_date._edit.setText("2026-02-30")
    page._actual_payment_date._edit.setText("2026-99-99")
    page.show()
    page.activateWindow()
    page._base_spin.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is page._base_spin)

    page._on_calculate()

    assert page._last_payment_date._edit.hasFocus()
    assert page._last_payment_date.raw_text() == "2026-02-30"
    assert page._actual_payment_date.raw_text() == "2026-99-99"
    assert page._actual_payment_date._error_label.isHidden()
    assert page._calc_btn.isEnabled()

    page._last_payment_date.set_value("2026-02-28")
    page._base_spin.setFocus()
    page._on_calculate()

    assert page._actual_payment_date._edit.hasFocus()
    assert page._actual_payment_date.raw_text() == "2026-99-99"
    assert page._calc_btn.isEnabled()


@pytest.mark.parametrize("hint", ["日期", "西元年-月-日", "請輸入西元日期（年-月-日）"])
def test_localized_date_hint_never_replaces_space_for_the_numeric_value(qapp, qtbot, monkeypatch, hint):
    from PySide6.QtGui import QFont
    from taxops.ui.widgets import date_field

    # Real font metrics with a short/long translated hint, not a fixed pixel guess.
    original = QFont(qapp.font())
    enlarged = QFont(original)
    enlarged.setPointSize(24)
    monkeypatch.setattr(date_field, "_PLACEHOLDER", hint)
    qapp.setFont(enlarged)
    try:
        field = DateField(required=False)
        qtbot.addWidget(field)
        field.set_value("2026-05-21")
        metrics = field._edit.fontMetrics()
        icons = field._cal_btn.width() + field._clear_btn.width()
        assert field.minimumWidth() >= icons + max(
            metrics.horizontalAdvance(hint), metrics.horizontalAdvance(field.raw_text())
        )
        assert field.maximumWidth() >= field.minimumWidth()
        assert field.value() == "2026-05-21"
    finally:
        qapp.setFont(original)
