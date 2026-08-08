"""Stage 6 — annual workbench: actionable KPIs, five core columns, inspector.

Each test states one acceptance condition from the stage's row in
`.ai/UI_REDESIGN_AUDIT.md`: eight KPI tiles no longer render at zero, the core
table carries five columns so client and title stop being truncated, the four
detailed statuses move off the row into the inspector, and the selected row is no
longer repeated as a block of plain text underneath.
"""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QLabel

from taxops.i18n.status_labels import UNKNOWN_STATUS_TEXT
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.ui.pages.annual_workbench_page import (
    ACTIONABLE_METRIC_INDEXES,
    CORE_COLUMNS,
    AnnualWorkbenchPage,
)
from taxops.ui.widgets.annual_overview_table import AnnualOverviewTable
from taxops.ui.widgets.page_shell import MAX_VISIBLE_ACTIONS


def _work_item(container, *, code: str = "TW-STAGE6-001"):
    client = container.clients.create_client(
        CreateClientInput(client_code=code, client_name="嘉禾會計事務所股份有限公司")
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    annual_work = container.annual_work
    result = annual_work.confirm_preview(
        client.id, 2026, annual_work.preview(client.id, 2026)
    )
    item = result.items[0]
    container.conn.execute(
        "UPDATE annual_work_items SET title = ?, due_date = ?, "
        "suggested_due_date = ? WHERE id = ?",
        ("嘉禾 2026 年營所稅結算申報", "2026-05-31", "2026-05-01", item.id),
    )
    container.conn.commit()
    return client, item


def _with_open_risks(container):
    """A work item carrying an exception, a missing document, and unpaid tax."""
    client, item = _work_item(container)
    container.annual_work.set_work_status(item.id, "exception")
    container.annual_work.set_document_status(item.id, "missing")
    container.annual_transactions.add(item.id, "tax_liability", 62_000, "2026-05-10")
    container.annual_transactions.add(item.id, "tax_payment", 40_000, "2026-05-10")
    return client, item


# ── KPI tiles ───────────────────────────────────────────────────────────


def test_all_zero_metrics_state_the_all_clear_instead_of_eight_empty_tiles(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()

    assert page.visible_metric_titles() == ()
    assert not any(
        label.isVisibleTo(page) for label in page.metric_value_labels
    )
    assert page.metrics_clear_label.isVisibleTo(page)
    assert page.metrics_clear_label.text() == "目前沒有需要處理的年度工作風險。"


def test_only_actionable_non_zero_metrics_get_a_tile(qtbot, container) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()

    # 工作數 and 客戶數 are counts of what exists, not work that needs doing, so
    # they never occupy a tile even though both are non-zero here.
    assert page.visible_metric_titles() == (
        "異常數",
        "缺件風險數",
        "收款短缺",
        "未繳稅",
    )
    # 未收服務費 and 超收筆數 are actionable but zero here, so they stay hidden.
    assert "未收服務費" not in page.visible_metric_titles()
    assert "超收筆數" not in page.visible_metric_titles()
    assert not page.metrics_clear_label.isVisibleTo(page)
    for index, label in enumerate(page.metric_value_labels):
        expected = label.text().split(" ")[0] in page.visible_metric_titles()
        assert label.isVisibleTo(page) is expected, label.text()
        if index not in ACTIONABLE_METRIC_INDEXES:
            assert not label.isVisibleTo(page)


def test_informational_counts_stay_available_outside_the_tiles(
    qtbot, container
) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert "工作數" not in page.visible_metric_titles()
    assert "客戶數" not in page.visible_metric_titles()
    # The counts are still reported, in the result line rather than as tiles.
    assert "1 筆工作" in page.feedback_label.text()
    assert "1 家客戶" in page.feedback_label.text()


def test_metric_label_texts_and_order_are_unchanged(qtbot, container) -> None:
    """The eight labels keep their text contract; only visibility changed."""
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert [label.text() for label in page.metric_value_labels] == [
        "工作數 1",
        "客戶數 1",
        "異常數 1",
        "缺件風險數 1",
        "收款短缺 NT$ 62,000",
        "未繳稅 NT$ 22,000",
        "未收服務費 NT$ 0",
        "超收筆數 0",
    ]


def test_metrics_return_to_the_all_clear_when_risks_are_filtered_away(
    qtbot, container
) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    assert page.visible_metric_titles()

    page.client_search_input.setText("不存在的客戶名稱")
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)

    assert page.visible_metric_titles() == ()
    assert page.metrics_clear_label.isVisibleTo(page)


# ── Five core columns ───────────────────────────────────────────────────


def test_core_table_shows_exactly_five_columns(qtbot, container) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()

    table = page.overview_table
    visible = [
        column
        for column in range(table.columnCount())
        if not table.isColumnHidden(column)
    ]
    assert len(visible) == 5
    assert tuple(visible) == CORE_COLUMNS
    assert [
        table.horizontalHeaderItem(column).text() for column in visible
    ] == ["客戶", "標題", "工作類型", "期限", "作業狀態"]


def test_detailed_statuses_and_money_are_off_the_row(qtbot, container) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()

    table = page.overview_table
    for column in (
        AnnualOverviewTable.FILING_STATUS_COLUMN,
        AnnualOverviewTable.DOCUMENT_STATUS_COLUMN,
        AnnualOverviewTable.TAX_STATUS_COLUMN,
        AnnualOverviewTable.FEE_STATUS_COLUMN,
        AnnualOverviewTable.COLLECTION_SHORTFALL_COLUMN,
        AnnualOverviewTable.UNPAID_TAX_COLUMN,
        AnnualOverviewTable.OUTSTANDING_FEE_COLUMN,
        AnnualOverviewTable.YEAR_COLUMN,
    ):
        assert table.isColumnHidden(column)


def test_hidden_columns_keep_their_values_so_nothing_is_lost(
    qtbot, container
) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    table = page.overview_table
    assert table.item(0, AnnualOverviewTable.UNPAID_TAX_COLUMN).text() == (
        "NT$ 22,000"
    )
    assert table.item(0, AnnualOverviewTable.YEAR_COLUMN).text() == "2026"
    assert all(
        table.item(0, column).toolTip() == table.item(0, column).text()
        for column in range(table.columnCount())
    )


def test_no_horizontal_scrolling_at_1366_by_768(qtbot, container) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(1366, 768)
    page.show()
    QApplication.processEvents()

    # maximum() is 0 exactly when the visible columns fit the viewport.
    assert page.overview_table.horizontalScrollBar().maximum() == 0
    assert page.width() == 1366


# ── Inspector ───────────────────────────────────────────────────────────


def test_selection_fills_the_inspector_with_named_status_fields(
    qtbot, container
) -> None:
    client, _item = _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    page.overview_table.selectRow(0)
    QApplication.processEvents()

    assert not page.inspector.is_showing_placeholder()
    fields = page.inspector.field_values()
    for label in ("作業狀態", "申報狀態", "憑證狀態", "稅款狀態", "服務費狀態"):
        assert label in fields, label
    assert fields["作業狀態"] == "未開始"
    assert "各項狀態" in page.inspector.section_names()
    assert "帳款摘要" in page.inspector.section_names()
    assert fields["客戶"] == f"嘉禾會計事務所股份有限公司（{client.client_code}）"


def test_inspector_labels_the_adopted_and_suggested_deadlines_apart(
    qtbot, container
) -> None:
    """`docs/product_object_model.md`: the UI must say which deadline is which."""
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    QApplication.processEvents()

    fields = page.inspector.field_values()
    assert fields["採用期限"] == "2026-05-31"
    assert fields["建議期限"] == "2026-05-01"


def test_inspector_names_annual_work_as_the_compliance_authority(
    qtbot, container
) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    QApplication.processEvents()

    notes = [
        label.text()
        for label in page.inspector.findChildren(QLabel)
        if label.objectName() == "InspectorLabel"
    ]
    assert any("唯一依據" in text for text in notes)


def test_open_action_is_hidden_until_a_row_is_selected(qtbot, container) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    page.overview_table.clearSelection()
    QApplication.processEvents()

    assert page.inspector.is_showing_placeholder()
    assert not page.inspector.actions_are_exposed()
    assert not page.open_detail_button.isVisibleTo(page)

    page.overview_table.selectRow(0)
    QApplication.processEvents()

    assert page.inspector.actions_are_exposed()
    assert page.open_detail_button.isVisibleTo(page)
    assert page.open_detail_button.text() in page.inspector.action_texts()


def test_dropping_the_selection_returns_the_inspector_to_its_placeholder(
    qtbot, container
) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    QApplication.processEvents()
    assert not page.inspector.is_showing_placeholder()

    page.overview_table.clearSelection()
    QApplication.processEvents()

    assert page.inspector.is_showing_placeholder()
    assert page.inspector.field_values() == {}


def test_selected_row_is_not_repeated_as_one_plain_text_blob(
    qtbot, container
) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    page.overview_table.selectRow(0)
    QApplication.processEvents()

    for label in page.findChildren(QLabel):
        text = label.text()
        assert not ("客戶：" in text and "作業：" in text), text
        assert not ("申報：" in text and "憑證：" in text), text


def test_unknown_status_reaches_the_inspector_without_leaking_raw_code(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    raw = "future\nprivate-secret" + "x" * 200
    container.conn.execute(
        "UPDATE annual_work_items SET tax_status = ? WHERE id = ?", (raw, item.id)
    )
    container.conn.commit()

    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    QApplication.processEvents()

    fields = page.inspector.field_values()
    assert fields["稅款狀態"] == UNKNOWN_STATUS_TEXT
    assert all("private-secret" not in value for value in fields.values())


# ── Opening a work item ─────────────────────────────────────────────────


def test_double_click_opens_the_selected_work_item(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    opened: list[int] = []

    class DialogSpy:
        def __init__(self, _container, item_id, parent=None) -> None:
            opened.append(item_id)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.pages.annual_workbench_page.AnnualItemDialog", DialogSpy
    )
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(1366, 768)
    page.show()
    QApplication.processEvents()

    cell = page.overview_table.item(0, AnnualOverviewTable.CLIENT_COLUMN)
    position = page.overview_table.visualItemRect(cell).center()
    # The real path: the first press lands on the row, the second opens it. The
    # offscreen platform only promotes the second press to a double-click when a
    # click already preceded it.
    qtbot.mouseClick(
        page.overview_table.viewport(), Qt.MouseButton.LeftButton, pos=position
    )
    qtbot.mouseDClick(
        page.overview_table.viewport(), Qt.MouseButton.LeftButton, pos=position
    )

    assert opened == [item.id]
    assert page.feedback_label.objectName() != "ErrorText"


def test_open_action_without_a_selection_reports_the_next_step(
    qtbot, container
) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    page.overview_table.clearSelection()

    page._open_selected_detail()

    assert page.feedback_label.text() == "請先選取要開啟的年度工作。"


# ── Page structure ──────────────────────────────────────────────────────


def test_year_search_work_type_and_risk_share_one_filter_bar(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(1366, 768)
    page.show()
    QApplication.processEvents()

    controls = (
        page.operation_year_combo,
        page.client_search_input,
        page.work_type_combo,
        page.risk_combo,
    )
    # One bar, one row: all four share the filter bar as their direct parent, and
    # the filter bar itself lives in the action bar rather than in a 篩選條件 group.
    for control in controls:
        assert control.parent() is page.filter_bar, control.objectName()
        assert page.rect().contains(
            control.mapTo(page, control.rect().bottomRight())
        )
    assert page.filter_bar.parent() is page.action_bar
    assert page.findChild(QGroupBox) is None


def test_header_carries_one_primary_and_the_bar_stays_under_the_ceiling(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert page.header.actions_visible() == 2
    assert page.create_button.property("role") == "primary"
    assert page.profile_button.property("role") == "secondary"
    assert page.action_bar.visible_action_count() <= MAX_VISIBLE_ACTIONS


def test_page_title_and_create_label_stay_on_the_navigation_contract(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)

    assert page.title_label.text() == "年度工作檯"
    assert page.create_button.text() == "建立年度工作"
    assert page.future_action_button is page.create_button


def test_empty_result_replaces_the_table_rather_than_framing_an_empty_one(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.show()
    QApplication.processEvents()

    assert page.empty_state.isVisibleTo(page)
    assert not page.overview_table.isVisibleTo(page)

    _work_item(container)
    page.refresh_context()
    QApplication.processEvents()

    assert page.overview_table.isVisibleTo(page)
    assert not page.empty_state.isVisibleTo(page)


def test_refresh_failure_clears_the_inspector_and_the_tiles(
    qtbot, container, monkeypatch
) -> None:
    _with_open_risks(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    QApplication.processEvents()
    assert not page.inspector.is_showing_placeholder()

    monkeypatch.setattr(
        container.annual_work,
        "overview_metrics",
        Mock(side_effect=RuntimeError("RAW SECRET")),
    )
    page.refresh_context()

    assert page.inspector.is_showing_placeholder()
    assert page.visible_metric_titles() == ()
    assert "載入失敗" in page.feedback_label.text()
    assert "SECRET" not in page.feedback_label.text()
