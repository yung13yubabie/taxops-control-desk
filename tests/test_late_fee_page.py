"""UI smoke tests for LateFeePage period half-lock + penalty schedule (v0.21 SLOP)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import taxops.ui.pages.late_fee_page as late_fee_page_module
from taxops.ui.pages.late_fee_page import LateFeePage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _select_period(page: LateFeePage, code: str) -> None:
    page._period_combo.setCurrentIndex(page._period_combo.findData(code))


def test_default_year_uses_project_clock(qapp, container, monkeypatch) -> None:
    monkeypatch.setattr(late_fee_page_module, "today_iso", lambda: "2031-06-02")
    page = LateFeePage(container)
    assert page._year_spin.value() == 2031


def test_period_autofills_last_payment_date(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    assert page._last_payment_date.value() == "2026-03-15"
    # half-lock: field disabled until the user unlocks it
    assert not page._last_payment_date.isEnabled()


def test_period_11_12_rolls_to_next_year(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "11-12")
    assert page._last_payment_date.value() == "2027-01-15"


def test_unlock_enables_manual_last_payment_date(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    assert not page._last_payment_date.isEnabled()
    page._unlock_check.setChecked(True)
    assert page._last_payment_date.isEnabled()
    page._last_payment_date.set_value("2026-04-01")
    assert page._last_payment_date.value() == "2026-04-01"
    assert "已手動調整" in page._manual_date_hint.text()


def test_relock_recomputes_last_payment_date(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    page._unlock_check.setChecked(True)
    page._last_payment_date.set_value("2026-04-01")
    page._unlock_check.setChecked(False)  # re-lock
    assert page._last_payment_date.value() == "2026-03-15"


def test_schedule_display_highlights_hit_band(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")  # last payment = 2026-03-15
    page._actual_payment_date.set_value("2026-03-20")  # 5 days late -> 1%
    page._refresh_schedule_display()
    assert page._schedule_table.rowCount() == 11
    highlighted = [
        page._schedule_table.item(r, 0).text()
        for r in range(page._schedule_table.rowCount())
        if page._schedule_table.item(r, 0).background().color().name() == "#fef3c7"
    ]
    assert highlighted == ["1%"]


def test_schedule_display_over_30_days_warns(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")  # last payment = 2026-03-15
    page._actual_payment_date.set_value("2026-05-01")  # ~47 days late
    page._refresh_schedule_display()
    assert "人工確認" in page._schedule_note.text()
