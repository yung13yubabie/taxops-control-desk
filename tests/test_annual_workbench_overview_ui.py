from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from taxops.i18n import DISABLED_TOOLTIP
from taxops.i18n.status_labels import UNKNOWN_STATUS_TEXT
from taxops.repositories.annual_work import AnnualOverviewMetrics
from taxops.services.annual_work import AnnualWorkError
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.ui.pages.annual_workbench_page import AnnualWorkbenchPage
from taxops.ui.widgets.annual_overview_table import AnnualOverviewTable


def _create_unpaid_work(container: object) -> object:
    client = getattr(container, "clients").create_client(
        CreateClientInput(
            client_code="TW-ALPINE-001",
            client_name="青山精密工業股份有限公司",
        )
    )
    getattr(container, "compliance_profiles").upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
        ),
    )
    annual_work = getattr(container, "annual_work")
    result = annual_work.confirm_preview(
        client.id,
        2026,
        annual_work.preview(client.id, 2026),
    )
    item = result.items[0]
    getattr(container, "conn").execute(
        "UPDATE annual_work_items SET title = ? WHERE id = ?",
        ("青山精密 2026 年營所稅結算申報", item.id),
    )
    getattr(container, "conn").commit()
    transactions = getattr(container, "annual_transactions")
    transactions.add(item.id, "tax_liability", 62_000, "2026-05-10")
    transactions.add(item.id, "tax_payment", 40_000, "2026-05-10")
    return item


def test_apply_unpaid_tax_filter_shows_exact_chinese_row_and_money(
    qtbot, container
) -> None:
    _create_unpaid_work(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()

    risk_index = page.risk_combo.findData("unpaid_tax")
    assert risk_index >= 0
    page.risk_combo.setCurrentIndex(risk_index)
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)

    assert page.overview_table.rowCount() == 1
    assert page.overview_table.item(0, 0).text() == "青山精密工業股份有限公司"
    assert page.overview_table.item(0, 2).text() == "青山精密 2026 年營所稅結算申報"
    assert page.overview_table.item(0, 11).text() == "NT$ 22,000"
    assert page.metric_value_labels[5].text() == "未繳稅 NT$ 22,000"

    cell = page.overview_table.item(0, AnnualOverviewTable.TITLE_COLUMN)
    qtbot.mouseClick(
        page.overview_table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=page.overview_table.visualItemRect(cell).center(),
    )
    assert "青山精密 2026 年營所稅結算申報" in page.detail_label.text()
    assert "未繳稅：NT$ 22,000" in page.detail_label.text()
    assert all(
        page.overview_table.item(0, column).toolTip()
        == page.overview_table.item(0, column).text()
        for column in range(page.overview_table.columnCount())
    )


def test_each_refresh_calls_only_overview_and_metrics_once(
    qtbot, container, monkeypatch
) -> None:
    annual_work = getattr(container, "annual_work")
    search_spy = Mock(wraps=annual_work.search_overview)
    metrics_spy = Mock(wraps=annual_work.overview_metrics)
    monkeypatch.setattr(annual_work, "search_overview", search_spy)
    monkeypatch.setattr(annual_work, "overview_metrics", metrics_spy)

    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert search_spy.call_count == 1
    assert metrics_spy.call_count == 1
    search_spy.reset_mock()
    metrics_spy.reset_mock()

    page.refresh_context()

    assert search_spy.call_count == 1
    assert metrics_spy.call_count == 1


def test_status_presentation_uses_already_loaded_item_without_row_lookup(
    container, monkeypatch
) -> None:
    _create_unpaid_work(container)
    annual_work = getattr(container, "annual_work")
    row = annual_work.search_overview({"query": "TW-ALPINE-001"})[0]
    monkeypatch.setattr(
        annual_work.repository,
        "get_item",
        Mock(side_effect=AssertionError("逐列查詢")),
    )

    presentation = annual_work.present_statuses(row.item)

    assert presentation.work_status_label == "未開始"
    assert presentation.tax_status_label == "稅款未確認"


def test_refresh_error_clears_stale_truth_and_preserves_filters(
    qtbot, container, monkeypatch
) -> None:
    _create_unpaid_work(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    assert page.overview_table.rowCount() == 1

    page.client_search_input.setText("青山精密")
    monkeypatch.setattr(
        getattr(container, "annual_work"),
        "overview_metrics",
        Mock(side_effect=AnnualWorkError("private database failure SECRET")),
    )
    qtbot.mouseClick(page.refresh_button, Qt.MouseButton.LeftButton)

    assert page.overview_table.rowCount() == 0
    assert all(label.text().endswith("0") for label in page.metric_value_labels)
    assert page.client_search_input.text() == "青山精密"
    assert "載入失敗" in page.feedback_label.text()
    assert "SECRET" not in page.feedback_label.text()


def test_all_metrics_are_exact_and_apply_clear_send_allowlisted_filters(
    qtbot, container, monkeypatch
) -> None:
    item = _create_unpaid_work(container)
    annual_work = getattr(container, "annual_work")
    annual_work.set_work_status(item.id, "exception")
    annual_work.set_document_status(item.id, "missing")
    getattr(container, "annual_transactions").add(
        item.id, "client_tax_collection", 43_400, "2026-05-10"
    )
    getattr(container, "annual_transactions").add(
        item.id, "fee_receivable", 5_000, "2026-05-10"
    )
    getattr(container, "annual_transactions").add(
        item.id, "fee_receipt", 2_000, "2026-05-10"
    )
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    search_spy = Mock(wraps=annual_work.search_overview)
    metrics_spy = Mock(wraps=annual_work.overview_metrics)
    monkeypatch.setattr(annual_work, "search_overview", search_spy)
    monkeypatch.setattr(annual_work, "overview_metrics", metrics_spy)

    page.operation_year_combo.setCurrentIndex(
        page.operation_year_combo.findData(2026)
    )
    page.client_search_input.setText("青山精密")
    page.work_type_combo.setCurrentIndex(
        page.work_type_combo.findData("corporate_income_tax")
    )
    page.risk_combo.setCurrentIndex(page.risk_combo.findData("unpaid_tax"))
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)

    expected_filters = {
        "order_by": "due_date",
        "order_dir": "ASC",
        "operation_year": 2026,
        "work_type": "corporate_income_tax",
        "risk": "unpaid_tax",
        "query": "青山精密",
    }
    search_spy.assert_called_once_with(expected_filters, limit=100, offset=0)
    metrics_spy.assert_called_once_with(expected_filters)
    assert [label.text() for label in page.metric_value_labels] == [
        "工作數 1",
        "客戶數 1",
        "異常數 1",
        "缺件風險數 1",
        "收款短缺 NT$ 18,600",
        "未繳稅 NT$ 22,000",
        "未收服務費 NT$ 3,000",
        "超收筆數 0",
    ]

    search_spy.reset_mock()
    metrics_spy.reset_mock()
    qtbot.mouseClick(page.clear_button, Qt.MouseButton.LeftButton)
    assert page.operation_year_combo.currentData() is None
    assert page.client_search_input.text() == ""
    assert page.work_type_combo.currentData() is None
    assert page.risk_combo.currentData() is None
    search_spy.assert_called_once_with(
        {"order_by": "due_date", "order_dir": "ASC"}, limit=100, offset=0
    )
    assert "已更新" in page.feedback_label.text()


def test_pagination_is_capped_at_100_and_apply_resets_to_first_page(
    qtbot, container, monkeypatch
) -> None:
    _create_unpaid_work(container)
    annual_work = getattr(container, "annual_work")
    base = annual_work.search_overview({"query": "TW-ALPINE-001"})[0]
    rows = [
        replace(
            base,
            item=replace(base.item, id=index + 1, title=f"年度測試工作 {index + 1}"),
        )
        for index in range(101)
    ]
    search_spy = Mock(
        side_effect=lambda _filters, *, limit, offset: rows[offset : offset + limit]
    )
    metrics_spy = Mock(
        return_value=AnnualOverviewMetrics(item_count=101, client_count=1)
    )
    monkeypatch.setattr(annual_work, "search_overview", search_spy)
    monkeypatch.setattr(annual_work, "overview_metrics", metrics_spy)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert page.overview_table.rowCount() == 100
    assert page.page_label.text() == "第 1 頁 / 共 2 頁"
    assert page.next_button.isEnabled()
    qtbot.mouseClick(page.next_button, Qt.MouseButton.LeftButton)
    assert page.overview_table.rowCount() == 1
    assert page.page_label.text() == "第 2 頁 / 共 2 頁"
    assert search_spy.call_args.kwargs == {"limit": 100, "offset": 100}

    page.risk_combo.setCurrentIndex(page.risk_combo.findData("unpaid_tax"))
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)
    assert page.page_label.text() == "第 1 頁 / 共 2 頁"
    assert search_spy.call_args.kwargs == {"limit": 100, "offset": 0}


def test_empty_state_and_processing_feedback_are_visible(
    qtbot, container, monkeypatch
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    assert page.overview_table.rowCount() == 0
    assert page.detail_label.text() == "目前沒有符合篩選條件的年度工作。"

    real_search = getattr(container, "annual_work").search_overview

    def assert_processing(*args, **kwargs):
        assert "處理中" in page.feedback_label.text()
        assert not page.refresh_button.isEnabled()
        return real_search(*args, **kwargs)

    monkeypatch.setattr(
        getattr(container, "annual_work"), "search_overview", assert_processing
    )
    qtbot.mouseClick(page.refresh_button, Qt.MouseButton.LeftButton)
    assert "已更新" in page.feedback_label.text()


def test_unknown_status_uses_canonical_label_logs_safely_and_never_leaks_raw(
    qtbot, container
) -> None:
    item = _create_unpaid_work(container)
    raw = "future\nprivate-secret" + "x" * 200
    conn = getattr(container, "conn")
    conn.execute(
        "UPDATE annual_work_items SET tax_status = ? WHERE id = ?", (raw, item.id)
    )
    conn.commit()
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    displayed = page.overview_table.item(
        0, AnnualOverviewTable.TAX_STATUS_COLUMN
    ).text()
    assert displayed == UNKNOWN_STATUS_TEXT
    page.overview_table.selectRow(0)
    QApplication.processEvents()
    assert UNKNOWN_STATUS_TEXT in page.detail_label.text()
    assert raw not in page.detail_label.text()
    assert "future" not in displayed
    log = conn.execute(
        "SELECT message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    detail = json.loads(log["detail_json"])
    assert log["message"] == "annual_work.unknown_status"
    assert detail["dimension"] == "tax_status"
    assert "\n" not in detail["raw_code"]
    assert len(detail["raw_code"]) <= 120


def test_refresh_sql_has_two_bounded_overview_queries_and_no_row_balance_lookup(
    qtbot, container, monkeypatch
) -> None:
    _create_unpaid_work(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    annual_work = getattr(container, "annual_work")
    search_spy = Mock(wraps=annual_work.search_overview)
    metrics_spy = Mock(wraps=annual_work.overview_metrics)
    monkeypatch.setattr(annual_work, "search_overview", search_spy)
    monkeypatch.setattr(annual_work, "overview_metrics", metrics_spy)
    monkeypatch.setattr(
        annual_work.repository,
        "get_item",
        Mock(side_effect=AssertionError("逐列狀態查詢")),
    )
    balance_spy = Mock(side_effect=AssertionError("逐列餘額查詢"))
    monkeypatch.setattr(
        getattr(container, "annual_transactions"), "balance", balance_spy
    )
    statements: list[str] = []
    getattr(container, "conn").set_trace_callback(statements.append)
    try:
        page.refresh_context()
    finally:
        getattr(container, "conn").set_trace_callback(None)

    assert search_spy.call_count == 1
    assert metrics_spy.call_count == 1
    assert balance_spy.call_count == 0
    ledger_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        and "ANNUAL_WORK_TRANSACTIONS" in statement.upper()
    ]
    assert len(ledger_selects) == 2


def test_fixed_desktop_layout_works_at_900_by_540_with_legible_controls(
    qtbot, qapp, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(900, 540)
    page.show()
    QApplication.processEvents()

    assert page.minimumSizeHint().width() <= 900
    assert page.minimumSizeHint().height() <= 540
    assert page.overview_table.font().pixelSize() >= 13
    controls = (
        page.operation_year_combo,
        page.client_search_input,
        page.work_type_combo,
        page.risk_combo,
        page.apply_button,
        page.clear_button,
        page.refresh_button,
        page.create_button,
        page.previous_button,
        page.next_button,
        page.page_label,
        page.feedback_label,
    )
    assert all(control.font().pixelSize() >= 14 for control in controls)
    for button in (
        page.apply_button,
        page.clear_button,
        page.refresh_button,
        page.create_button,
    ):
        top_left = button.mapTo(page, button.rect().topLeft())
        bottom_right = button.mapTo(page, button.rect().bottomRight())
        assert page.rect().contains(top_left)
        assert page.rect().contains(bottom_right)
    assert page.overview_table.horizontalScrollBarPolicy() != (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )


def test_only_real_actions_are_enabled_and_create_remains_canonical_disabled(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    assert not page.create_button.isEnabled()
    assert page.create_button.toolTip() == DISABLED_TOOLTIP
    enabled_text = {
        button.text()
        for button in page.findChildren(QPushButton)
        if button.isEnabled()
    }
    assert enabled_text == {"套用", "清除", "重新整理"}
