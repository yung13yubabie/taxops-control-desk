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


def _seed_request(container) -> int:
    conn = container.conn
    conn.execute(
        """
        INSERT INTO clients
            (client_code, client_name, created_at, updated_at)
        VALUES ('LF001', 'Late Fee Client',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO engagements
            (client_id, engagement_name, tax_type, period_name, status,
             created_at, updated_at)
        VALUES (?, 'Late Fee Engagement', 'vat', '2026Q1', 'draft',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """,
        (client_id,),
    )
    engagement_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO document_requests
            (engagement_id, period_name, tax_type, status, created_at, updated_at)
        VALUES (?, '2026Q1', 'vat', 'not_requested',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """,
        (engagement_id,),
    )
    request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return request_id


def _prepare_persisted_calculation(page: LateFeePage, request_id: int) -> None:
    page._req_combo.addItem("request", request_id)
    page._req_combo.setCurrentIndex(page._req_combo.count() - 1)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)


def test_calculate_reentry_writes_once(qapp, container) -> None:
    request_id = _seed_request(container)
    page = LateFeePage(container)
    _prepare_persisted_calculation(page, request_id)
    calls = 0
    reentered = False
    enabled_during_calls: list[bool] = []
    original_calculate = container.late_fee.calculate_and_save

    def calculate_and_save(_payload):
        nonlocal calls, reentered
        calls += 1
        enabled_during_calls.append(page._calc_btn.isEnabled())
        if not reentered:
            reentered = True
            page._on_calculate()
        return original_calculate(_payload)

    container.late_fee.calculate_and_save = calculate_and_save

    page._on_calculate()

    assert calls == 1
    assert enabled_during_calls == [False]
    assert page._calc_btn.isEnabled()
    record_count = container.conn.execute(
        "SELECT COUNT(*) FROM late_fee_records WHERE request_id = ?",
        (request_id,),
    ).fetchone()[0]
    audit_count = container.conn.execute(
        """
        SELECT COUNT(*)
        FROM audit_logs
        WHERE action = 'late_fee.calculate'
          AND target_type = 'late_fee_record'
        """
    ).fetchone()[0]
    assert record_count == 1
    assert audit_count == 1


def test_calculate_failure_restores_button(
    qapp, container, monkeypatch
) -> None:
    request_id = _seed_request(container)
    page = LateFeePage(container)
    _prepare_persisted_calculation(page, request_id)
    enabled_during_call: list[bool] = []

    def fail(_payload):
        enabled_during_call.append(page._calc_btn.isEnabled())
        raise RuntimeError("write failed")

    container.late_fee.calculate_and_save = fail
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "critical",
        lambda *_args, **_kwargs: None,
    )

    page._on_calculate()

    assert enabled_during_call == [False]
    assert page._calc_btn.isEnabled()
