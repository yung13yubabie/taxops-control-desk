"""UI smoke tests for LateFeePage period half-lock + penalty schedule (v0.21 SLOP)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QGridLayout

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


def test_parameters_use_two_column_grid(qapp, container) -> None:
    """年份/期別 pair on one row; the three sequential fields stack below it.

    Stage 13 moved 實際繳款日 out of column 3 and onto its own row, so the form
    reads 法定期限 → 實際繳款日 → 申報稅額 downwards. This asserts the whole
    order, not only the two paired cells it used to check.
    """
    page = LateFeePage(container)
    layout = page._form_layout
    assert isinstance(layout, QGridLayout)

    def cell(widget):
        return layout.getItemPosition(layout.indexOf(widget))

    assert cell(page._year_spin)[1:] == (1, 1, 1)
    assert cell(page._period_combo)[1:] == (3, 1, 1)
    assert cell(page._last_payment_date)[1:] == (1, 1, 1)
    assert cell(page._actual_payment_date)[1:] == (1, 1, 1)

    year_row = cell(page._year_spin)[0]
    deadline_row = cell(page._last_payment_date)[0]
    actual_row = cell(page._actual_payment_date)[0]
    assert year_row == cell(page._period_combo)[0]
    assert year_row < deadline_row < actual_row


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

    # Stage 13 widened the breakdown to start / end / days / rate / amount, so
    # the rate is column 3. The whole hit row is marked, not just one cell.
    rate_col = late_fee_page_module.RATE_COLUMN
    assert page._schedule_table.horizontalHeaderItem(rate_col).text() == "適用滯納金率"
    highlighted = [
        page._schedule_table.item(r, rate_col).text()
        for r in range(page._schedule_table.rowCount())
        if page._schedule_table.item(r, rate_col).background().color().name()
        == "#fef3c7"
    ]
    assert highlighted == ["1%"]
    hit_row = next(
        r
        for r in range(page._schedule_table.rowCount())
        if page._schedule_table.item(r, rate_col).text() == "1%"
    )
    assert all(
        page._schedule_table.item(hit_row, c).background().color().name() == "#fef3c7"
        for c in range(page._schedule_table.columnCount())
    )


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


def test_mode_toggle_clears_result_and_switches_filter_visibility(qapp, container) -> None:
    """`_manual_check` is now the 手動輸入 radio, so returning to case mode is a
    click on 從案件帶入 rather than unchecking a box. The stale result card is
    cleared as well as the stale sentence, and the whole history section hides."""
    page = LateFeePage(container)
    page._result_label.setText("stale result")
    page._result_penalty_value.setText("NT$ 999")
    page._table.setRowCount(1)

    page._manual_check.setChecked(True)
    assert page._filter_widget.isHidden()
    assert page._history_block.isHidden()
    assert page._result_label.text() == ""
    assert page._result_penalty_value.text() == "—"
    assert page._table.rowCount() == 0

    page._source_case_radio.setChecked(True)
    assert not page._manual_check.isChecked()
    assert not page._filter_widget.isHidden()
    assert not page._history_block.isHidden()


def test_load_failures_are_visible_and_clear_stale_history(
    qapp, container, monkeypatch
) -> None:
    request_id = _seed_request(container)
    page = LateFeePage(container)
    monkeypatch.setattr(
        container.engagements,
        "list_all",
        lambda: (_ for _ in ()).throw(RuntimeError("engagements locked")),
    )
    page.refresh_context()
    assert page._eng_combo.itemText(1) == "（載入案件失敗，請重新整理）"

    engagement_id = container.conn.execute(
        "SELECT engagement_id FROM document_requests WHERE id = ?", (request_id,)
    ).fetchone()[0]
    page._eng_combo.addItem("broken engagement", engagement_id)
    monkeypatch.setattr(
        container.doc_requests,
        "list_by_engagement",
        lambda _eng_id: (_ for _ in ()).throw(RuntimeError("requests locked")),
    )
    page._eng_combo.setCurrentIndex(page._eng_combo.count() - 1)
    assert page._req_combo.itemText(1) == "（載入批次失敗，請重新整理）"

    page._req_combo.addItem("broken request", request_id)
    page._history = [object()]
    monkeypatch.setattr(
        container.late_fee,
        "list_by_request",
        lambda _request_id: (_ for _ in ()).throw(RuntimeError("history locked")),
    )
    page._req_combo.setCurrentIndex(page._req_combo.count() - 1)
    assert page._history == []
    assert page._table.rowCount() == 0
    assert page._result_label.text() == "試算記錄載入失敗，請重新整理頁面"


def test_calculate_missing_inputs_and_request_show_exact_guidance(
    qapp, container, monkeypatch
) -> None:
    page = LateFeePage(container)
    warnings: list[str] = []
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    # Both messages now name the field and the control as the page labels them:
    # 法定期限 rather than 最後繳款日, and 手動輸入 rather than 手動試算模式.
    page._calc_btn.click()
    assert warnings[-1] == "請輸入法定期限與實際繳款日"
    deadline_row = page._form_layout.getItemPosition(
        page._form_layout.indexOf(page._last_payment_date)
    )[0]
    assert (
        page._form_layout.itemAtPosition(deadline_row, 0).widget().text() == "法定期限"
    )
    assert page._unlock_check.text() == "自行輸入法定期限"
    assert page._result_penalty_value.text() == "—"  # nothing was calculated

    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._calc_btn.click()
    assert warnings[-1] == "請先選擇索件批次，或切換為手動輸入"
    assert page._source_manual_radio.text() == "手動輸入"
    assert page._result_penalty_value.text() == "—"


def test_manual_calculation_real_button_renders_exact_result(qapp, container) -> None:
    """The result is four labelled values plus the not-stored note, replacing the
    single run-on sentence. Every number the sentence carried is still asserted,
    and 應繳總額 — which the sentence never showed — is asserted too."""
    page = LateFeePage(container)
    page._manual_check.setChecked(True)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)

    page._calc_btn.click()

    assert page._result_days_value.text() == "5 天"
    assert page._result_rate_value.text() == "1%"
    assert page._result_penalty_value.text() == "NT$ 100"
    assert page._result_total_value.text() == "NT$ 10,100"
    assert page._result_label.text() == "手動試算結果未儲存。"


def test_manual_calculation_domain_failure_is_visible(
    qapp, container, monkeypatch
) -> None:
    from taxops.services.late_fee import LateFeeValidationError

    page = LateFeePage(container)
    page._manual_check.setChecked(True)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    criticals: list[str] = []
    monkeypatch.setattr(
        late_fee_page_module,
        "calculate_overdue_days",
        lambda *_args: (_ for _ in ()).throw(LateFeeValidationError("late_fee.date.invalid")),
    )
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "critical",
        lambda _parent, _title, body: criticals.append(body),
    )

    page._calc_btn.click()

    assert len(criticals) == 1
    assert criticals[0].strip()


def test_persisted_calculation_domain_failure_is_visible(
    qapp, container, monkeypatch
) -> None:
    from taxops.services.late_fee import LateFeeValidationError

    request_id = _seed_request(container)
    page = LateFeePage(container)
    _prepare_persisted_calculation(page, request_id)
    criticals: list[str] = []
    monkeypatch.setattr(
        container.late_fee,
        "calculate_and_save",
        lambda *_args: (_ for _ in ()).throw(LateFeeValidationError("late_fee.date.invalid")),
    )
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "critical",
        lambda _parent, _title, body: criticals.append(body),
    )

    page._calc_btn.click()

    assert len(criticals) == 1
    assert criticals[0].strip()
