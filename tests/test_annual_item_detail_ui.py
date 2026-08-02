from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import (
    AnnualWorkError,
    UpdateAnnualWorkItemInput,
)
from taxops.ui.action_registry import (
    PAGE_ANNUAL_WORKBENCH,
    actions_for_page,
)
from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog
from taxops.ui.pages.annual_workbench_page import AnnualWorkbenchPage
from taxops.ui.widgets.annual_item_detail import AnnualItemDetail


def _work_item(container: object):
    client = container.clients.create_client(
        CreateClientInput(
            client_code="C-DETAIL-UI",
            client_name="年度工作明細介面測試",
        )
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )
    result = container.annual_work.confirm_preview(
        client.id,
        2026,
        container.annual_work.preview(client.id, 2026),
    )
    return client, result.items[0]


def test_detail_loads_real_item_context_and_saves_exact_multiline(
    qtbot, container
) -> None:
    client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.show()
    detail.activateWindow()

    assert detail.client_label.text() == client.client_name
    assert detail.operation_year_input.text() == "2026"
    assert detail.operation_year_input.isReadOnly()
    assert detail.suggested_due_date_input.isReadOnly()

    notes = "第一行：客戶要求保留原始說明\n第二行：勿裁切；保留\t定位"
    detail.title_input.setText("營業稅 01–02 月（人工調整）")
    detail.tax_year_input.setText("2027")
    detail.period_code_input.setText("01–02")
    detail.due_date_input.setText("2026-03-16")
    detail.notes_input.setPlainText(notes)
    for combo, value in (
        (detail.work_status_combo, "in_progress"),
        (detail.filing_status_combo, "filed"),
        (detail.document_status_combo, "complete"),
        (detail.tax_status_combo, "paid"),
        (detail.fee_status_combo, "awaiting_payment"),
    ):
        combo.setCurrentIndex(combo.findData(value))

    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored.title == "營業稅 01–02 月（人工調整）"
    assert stored.tax_year == 2027
    assert stored.period_code == "01–02"
    assert stored.due_date == "2026-03-16"
    assert stored.notes == notes
    assert detail.notes_input.toPlainText() == notes
    assert detail.feedback_label.text() == "年度工作明細已儲存。"
    assert detail.updated_at_token == stored.updated_at


def test_page_opens_selected_real_item_and_refreshes_only_after_accept(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    opened: list[tuple[object, int, object]] = []

    class DialogSpy:
        result = QDialog.DialogCode.Accepted

        def __init__(self, candidate_container, item_id, parent=None) -> None:
            opened.append((candidate_container, item_id, parent))

        def exec(self):
            return self.result

    monkeypatch.setattr(
        "taxops.ui.pages.annual_workbench_page.AnnualItemDialog",
        DialogSpy,
    )
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    refresh_spy = Mock()
    page._refresh = refresh_spy

    qtbot.mouseClick(page.open_detail_button, Qt.MouseButton.LeftButton)

    assert opened == [(container, item.id, page)]
    refresh_spy.assert_called_once_with()


def test_page_refreshes_after_real_commit_even_when_dialog_cannot_reread(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    real_get = container.annual_work.get_item_context

    class CommittedRejectedDialog(AnnualItemDialog):
        def __init__(self, candidate_container, item_id, parent=None) -> None:
            super().__init__(candidate_container, item_id, parent)

        def exec(self):
            self.detail.title_input.setText("關閉前已真實寫入")
            monkeypatch.setattr(
                container.annual_work,
                "get_item_context",
                Mock(
                    side_effect=AnnualWorkError(
                        "annual_work.item_details.read_failed"
                    )
                ),
            )
            self.detail.save()
            assert real_get(item.id).item.title == "關閉前已真實寫入"
            assert not self.detail.save_button.isEnabled()
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.pages.annual_workbench_page.AnnualItemDialog",
        CommittedRejectedDialog,
    )
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.overview_table.selectRow(0)
    refresh_spy = Mock()
    page._refresh = refresh_spy

    qtbot.mouseClick(page.open_detail_button, Qt.MouseButton.LeftButton)

    refresh_spy.assert_called_once_with()
    assert real_get(item.id).item.title == "關閉前已真實寫入"


def test_no_selection_shows_visible_error_and_focuses_overview(
    qtbot, container
) -> None:
    _work_item(container)
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(1100, 700)
    page.show()
    page.overview_table.clearSelection()

    qtbot.mouseClick(page.open_detail_button, Qt.MouseButton.LeftButton)

    assert page.feedback_label.text() == "請先選取要開啟的年度工作。"
    qtbot.waitUntil(page.overview_table.hasFocus, timeout=500)


def test_native_double_click_opens_same_row_id_once_without_false_refresh(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    opened: list[int] = []
    page: AnnualWorkbenchPage

    class RejectedDialog:
        def __init__(self, candidate_container, item_id, parent=None) -> None:
            assert candidate_container is container
            assert parent is page
            opened.append(item_id)

        def exec(self):
            page._open_selected_detail()
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.pages.annual_workbench_page.AnnualItemDialog",
        RejectedDialog,
    )
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.resize(1100, 700)
    page.show()
    refresh_spy = Mock()
    page._refresh = refresh_spy
    cell = page.overview_table.item(0, 0)
    position = page.overview_table.visualItemRect(cell).center()

    qtbot.mouseClick(
        page.overview_table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )
    qtbot.mouseDClick(
        page.overview_table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position,
    )

    assert opened == [item.id]
    refresh_spy.assert_not_called()


def test_dialog_900_by_540_keeps_actions_and_full_warning_reachable(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.resize(900, 540)
    dialog.show()

    assert dialog.minimumWidth() <= 900
    assert dialog.minimumHeight() <= 540
    warning = dialog.detail.transition_hint
    assert warning.wordWrap()
    assert warning.text() == (
        "有風險時，完成工作會由系統記為例外完成；無風險時記為已完成。"
        "取消與重新開啟請使用專用操作。"
    )
    for button in (
        dialog.detail.complete_button,
        dialog.detail.cancel_button,
        dialog.detail.save_button,
    ):
        assert button.isVisible()
        top_left = button.mapTo(dialog, button.rect().topLeft())
        bottom_right = button.mapTo(dialog, button.rect().bottomRight())
        assert dialog.rect().contains(top_left)
        assert dialog.rect().contains(bottom_right)
    assert dialog.detail.fontMetrics().height() >= 14


def test_busy_dialog_refuses_close_with_visible_processing_feedback(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.detail._busy = True

    dialog.reject()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert dialog.detail.feedback_label.text() == "處理中，請等待操作完成。"


@pytest.mark.parametrize(
    ("field_name", "value", "expected_code"),
    [
        ("title_input", "x" * 501, "annual_work.title.invalid"),
        ("tax_year_input", "不是年度", "annual_work.tax_year.invalid"),
        ("period_code_input", "x" * 51, "annual_work.period_code.invalid"),
        ("due_date_input", "2026-02-29", "annual_work.due_date.invalid"),
        ("notes_input", "x" * 100_001, "annual_work.notes.invalid"),
    ],
    ids=["title", "tax-year", "period", "due-date", "notes"],
)
def test_invalid_detail_focuses_first_relevant_field_without_writing(
    qtbot, container, field_name, value, expected_code
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    detail = dialog.detail
    field = getattr(detail, field_name)
    if field_name == "notes_input":
        field.setPlainText(value)
    else:
        field.setText(value)

    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    assert container.annual_work.get_item_context(item.id).item == item
    qtbot.waitUntil(field.hasFocus, timeout=2000)
    assert expected_code not in detail.feedback_label.text()
    assert detail.feedback_label.text()


def test_stale_save_preserves_every_unsaved_input_and_focuses_title(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    detail = dialog.detail
    external = replace(
        UpdateAnnualWorkItemInput(
            title=item.title,
            tax_year=item.tax_year,
            period_code=item.period_code,
            due_date=item.due_date,
            notes=item.notes,
            work_status=item.work_status,
            filing_status=item.filing_status,
            document_status=item.document_status,
            tax_status=item.tax_status,
            fee_status=item.fee_status,
            expected_updated_at=item.updated_at,
        ),
        title="另一個視窗已更新",
    )
    container.annual_work.update_item_details(item.id, external)
    notes = "尚未儲存第一行\n尚未儲存第二行"
    detail.title_input.setText("本視窗尚未儲存")
    detail.notes_input.setPlainText(notes)

    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    assert detail.title_input.text() == "本視窗尚未儲存"
    assert detail.notes_input.toPlainText() == notes
    qtbot.waitUntil(detail.title_input.hasFocus, timeout=500)
    assert container.annual_work.get_item_context(item.id).item.title == "另一個視窗已更新"
    assert "annual_work." not in detail.feedback_label.text()


def test_nested_double_submit_calls_update_service_once(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.title_input.setText("防止重複提交")
    real_update = container.annual_work.update_item_details
    calls = 0

    def nested_submit(item_id, payload):
        nonlocal calls
        calls += 1
        detail.save()
        return real_update(item_id, payload)

    monkeypatch.setattr(
        container.annual_work, "update_item_details", nested_submit
    )
    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    assert calls == 1
    assert container.annual_work.get_item_context(item.id).item.title == "防止重複提交"


def test_real_audit_failure_rolls_back_and_preserves_exact_inputs(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    container.conn.execute(
        "CREATE TRIGGER fail_annual_ui_audit BEFORE INSERT ON audit_logs "
        "BEGIN SELECT RAISE(ABORT, 'PRIVATE audit detail'); END"
    )
    container.conn.commit()
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    detail = dialog.detail
    notes = "審核失敗也不能遺失\n第二行\t定位"
    detail.title_input.setText("尚未寫入的工作名稱")
    detail.notes_input.setPlainText(notes)

    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored == item
    assert detail.title_input.text() == "尚未寫入的工作名稱"
    assert detail.notes_input.toPlainText() == notes
    assert detail.feedback_label.text() == "儲存年度工作明細失敗，原有資料保持不變"
    assert "PRIVATE" not in detail.feedback_label.text()
    qtbot.waitUntil(detail.title_input.hasFocus, timeout=500)


def test_save_exposes_processing_state_before_real_service_call(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    real_update = container.annual_work.update_item_details
    observed: list[tuple[str, bool]] = []

    def observed_update(item_id, payload):
        observed.append(
            (detail.feedback_label.text(), detail.save_button.isEnabled())
        )
        return real_update(item_id, payload)

    monkeypatch.setattr(
        container.annual_work, "update_item_details", observed_update
    )
    detail.title_input.setText("處理狀態可見")
    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    assert observed == [("處理中，正在儲存年度工作明細。", False)]
    assert container.annual_work.get_item_context(item.id).item.title == "處理狀態可見"


def test_risk_completion_requires_reason_then_rereads_exception_completion(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    detail = dialog.detail

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "not_started"
    qtbot.waitUntil(detail.transition_reason_input.hasFocus, timeout=500)

    reason = "憑證仍待客戶補齊\n主管同意先例外完成"
    detail.transition_reason_input.setPlainText(reason)
    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored.work_status == "completed_with_exception"
    assert stored.exception_reason == reason
    assert detail.updated_at_token == stored.updated_at
    assert detail.feedback_label.text() == "年度工作已例外完成。"
    reopened_dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(reopened_dialog)
    reopened_dialog.show()
    assert reopened_dialog.detail.reopen_button.isVisible()
    assert reopened_dialog.detail.work_status_combo.currentText() == "例外完成"
    assert (
        reopened_dialog.detail.transition_reason_input.toPlainText()
        == reason
    )


@pytest.mark.parametrize(
    ("database_tax_status", "ui_tax_status", "reason", "expected_status"),
    [
        ("unconfirmed", "paid", "", "completed"),
        (
            "paid",
            "unpaid",
            "客戶尚未繳納\n第二行保留  ",
            "completed_with_exception",
        ),
    ],
    ids=["database-risk-ui-safe", "database-safe-ui-risk"],
)
def test_dirty_completion_persists_full_form_before_transition(
    qtbot,
    container,
    database_tax_status,
    ui_tax_status,
    reason,
    expected_status,
) -> None:
    _client, item = _work_item(container)
    if database_tax_status != item.tax_status:
        container.annual_work.set_tax_status(item.id, database_tax_status)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    notes = "完成前修改明細\n保留換行與尾端空白  "
    detail.title_input.setText("完成前更新標題")
    detail.notes_input.setPlainText(notes)
    detail.tax_status_combo.setCurrentIndex(
        detail.tax_status_combo.findData(ui_tax_status)
    )
    detail.transition_reason_input.setPlainText(reason)

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored.title == "完成前更新標題"
    assert stored.notes == notes
    assert stored.tax_status == ui_tax_status
    assert stored.work_status == expected_status
    assert stored.exception_reason == (reason or None)
    assert detail.transition_reason_input.toPlainText() == reason


def test_committed_save_with_failed_reread_disables_mutations_and_is_retryable(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    detail = dialog.detail
    detail.title_input.setText("已寫入但重新讀取失敗")
    real_get = container.annual_work.get_item_context
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        Mock(side_effect=AnnualWorkError("annual_work.item_details.read_failed")),
    )

    qtbot.mouseClick(detail.save_button, Qt.MouseButton.LeftButton)

    assert real_get(item.id).item.title == "已寫入但重新讀取失敗"
    assert dialog.has_committed_change is True
    assert "資料已寫入但重新讀取失敗" in detail.feedback_label.text()
    assert not detail.save_button.isEnabled()
    assert not detail.complete_button.isEnabled()
    monkeypatch.setattr(container.annual_work, "get_item_context", real_get)
    qtbot.mouseClick(detail.retry_read_button, Qt.MouseButton.LeftButton)
    assert detail.save_button.isEnabled()
    assert detail.title_input.text() == "已寫入但重新讀取失敗"


def test_plain_reload_recovers_all_controls_after_transient_read_failure(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    real_get = container.annual_work.get_item_context
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        Mock(side_effect=AnnualWorkError("annual_work.item_details.read_failed")),
    )
    detail.reload()
    assert not detail.save_button.isEnabled()

    monkeypatch.setattr(container.annual_work, "get_item_context", real_get)
    detail.reload()

    assert detail.save_button.isEnabled()
    assert detail.complete_button.isEnabled()


def test_transition_failure_after_detail_commit_is_honest_and_retryable(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    detail = dialog.detail
    notes = "先寫入的明細\n原樣保留  "
    reason = "完成失敗後仍可重試"
    detail.title_input.setText("明細已先寫入")
    detail.notes_input.setPlainText(notes)
    detail.transition_reason_input.setPlainText(reason)
    monkeypatch.setattr(
        container.annual_work,
        "complete_item",
        Mock(side_effect=AnnualWorkError("annual_work.complete.failed")),
    )

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored.title == "明細已先寫入"
    assert stored.notes == notes
    assert stored.work_status == "not_started"
    assert detail.updated_at_token == stored.updated_at
    assert detail.title_input.text() == "明細已先寫入"
    assert detail.notes_input.toPlainText() == notes
    assert detail.transition_reason_input.toPlainText() == reason
    assert detail.feedback_label.text() == (
        "明細已儲存，但完成年度工作失敗；目前內容已保留，請確認後重試。"
    )
    assert dialog.has_committed_change is True
    assert detail.complete_button.isEnabled()


def test_invalid_dirty_transition_never_calls_dedicated_operation(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.show()
    detail.activateWindow()
    detail.title_input.setText("x" * 501)
    operation = Mock()
    monkeypatch.setattr(container.annual_work, "complete_item", operation)

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    operation.assert_not_called()
    assert container.annual_work.get_item_context(item.id).item == item
    assert detail.title_input.text() == "x" * 501
    qtbot.waitUntil(detail.title_input.hasFocus, timeout=500)


def test_stale_dirty_transition_preserves_inputs_and_never_transitions(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.show()
    detail.activateWindow()
    container.annual_work.update_item_details(
        item.id,
        replace(
            detail.fields.payload(item.updated_at),
            title="其他視窗已更新",
        ),
    )
    notes = "本視窗尚未儲存\n完整保留  "
    detail.title_input.setText("本視窗標題")
    detail.notes_input.setPlainText(notes)
    operation = Mock()
    monkeypatch.setattr(container.annual_work, "complete_item", operation)

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    operation.assert_not_called()
    assert detail.title_input.text() == "本視窗標題"
    assert detail.notes_input.toPlainText() == notes
    qtbot.waitUntil(detail.title_input.hasFocus, timeout=500)
    stored = container.annual_work.get_item_context(item.id).item
    assert stored.title == "其他視窗已更新"
    assert stored.work_status == "not_started"


def test_nested_dirty_transition_submits_each_service_operation_once(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.transition_reason_input.setPlainText("仍有風險")
    real_update = container.annual_work.update_item_details
    real_complete = container.annual_work.complete_item
    calls = {"update": 0, "complete": 0}

    def nested_update(item_id, payload):
        calls["update"] += 1
        detail.complete()
        return real_update(item_id, payload)

    def counted_complete(item_id, *, exception_reason=None):
        calls["complete"] += 1
        return real_complete(item_id, exception_reason=exception_reason)

    monkeypatch.setattr(
        container.annual_work, "update_item_details", nested_update
    )
    monkeypatch.setattr(
        container.annual_work, "complete_item", counted_complete
    )

    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)

    assert calls == {"update": 1, "complete": 1}
    assert (
        container.annual_work.get_item_context(item.id).item.work_status
        == "completed_with_exception"
    )


def test_cancel_restore_and_reopen_persist_dirty_details_first(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)

    detail.title_input.setText("取消前標題")
    detail.transition_reason_input.setPlainText("取消理由\n第二行  ")
    qtbot.mouseClick(detail.cancel_button, Qt.MouseButton.LeftButton)
    cancelled = container.annual_work.get_item_context(item.id).item
    assert cancelled.title == "取消前標題"
    assert cancelled.work_status == "cancelled"
    assert detail.transition_reason_input.toPlainText() == "取消理由\n第二行  "

    detail.notes_input.setPlainText("還原前備註\n第二行")
    qtbot.mouseClick(detail.restore_button, Qt.MouseButton.LeftButton)
    restored = container.annual_work.get_item_context(item.id).item
    assert restored.notes == "還原前備註\n第二行"
    assert restored.work_status == "not_started"

    detail.tax_status_combo.setCurrentIndex(
        detail.tax_status_combo.findData("paid")
    )
    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "completed"
    assert detail.work_status_combo.findData("completed") >= 0
    assert not detail.cancel_button.isVisible()

    detail.title_input.setText("重開前標題")
    qtbot.mouseClick(detail.reopen_button, Qt.MouseButton.LeftButton)
    reopened = container.annual_work.get_item_context(item.id).item
    assert reopened.title == "重開前標題"
    assert reopened.work_status == "in_progress"
    assert detail.work_status_combo.findData("completed") == -1
    assert detail.work_status_combo.findData("completed_with_exception") == -1
    assert detail.work_status_combo.findData("cancelled") == -1


def test_focus_timer_ignores_widget_deleted_before_callback(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.deleteLater()
    detail._pending_focus = detail.title_input
    detail._set_busy(False)

    qtbot.wait(20)


def test_cancel_restore_complete_and_reopen_use_dedicated_service_paths(
    qtbot, container
) -> None:
    _client, item = _work_item(container)
    detail = AnnualItemDetail(container, item.id)
    qtbot.addWidget(detail)
    detail.show()
    detail.transition_reason_input.setPlainText("客戶停止委任\n保留紀錄")

    qtbot.mouseClick(detail.cancel_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "cancelled"
    assert detail.restore_button.isVisible()

    qtbot.mouseClick(detail.restore_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "not_started"

    container.annual_work.set_tax_status(item.id, "paid")
    detail.reload()
    detail.transition_reason_input.setPlainText("")
    qtbot.mouseClick(detail.complete_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "completed"

    qtbot.mouseClick(detail.reopen_button, Qt.MouseButton.LeftButton)
    assert container.annual_work.get_item_context(item.id).item.work_status == "in_progress"


def test_failed_transition_keeps_dialog_open_and_reason(
    qtbot, container, monkeypatch
) -> None:
    _client, item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    reason = "這段內容不能遺失\n第二行"
    dialog.detail.transition_reason_input.setPlainText(reason)
    monkeypatch.setattr(
        container.annual_work,
        "cancel_item",
        Mock(side_effect=AnnualWorkError("annual_work.cancel.failed")),
    )

    qtbot.mouseClick(dialog.detail.cancel_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.detail.transition_reason_input.toPlainText() == reason
    assert "annual_work." not in dialog.detail.feedback_label.text()


def test_detail_action_contracts_point_to_real_handlers_and_markers() -> None:
    by_label = {
        action.button_label: action
        for action in actions_for_page(PAGE_ANNUAL_WORKBENCH)
    }
    expected = {
        "開啟明細": "test_page_opens_selected_real_item_and_refreshes_only_after_accept",
        "儲存明細": "test_detail_loads_real_item_context_and_saves_exact_multiline",
        "完成工作": "test_risk_completion_requires_reason_then_rereads_exception_completion",
        "取消此工作": "test_cancel_restore_complete_and_reopen_use_dedicated_service_paths",
        "還原": "test_cancel_restore_complete_and_reopen_use_dedicated_service_paths",
        "重新開啟": "test_cancel_restore_complete_and_reopen_use_dedicated_service_paths",
    }
    for label, marker in expected.items():
        assert by_label[label].enabled is True
        assert by_label[label].handler != "placeholder"
        assert by_label[label].test_marker == marker
