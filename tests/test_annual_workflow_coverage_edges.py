from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from taxops.services.annual_work import (
    AnnualWorkError,
    AnnualWorkValidationError,
)
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.engagements import CreateEngagementInput


def _work_item(container: object, suffix: str):
    client = container.clients.create_client(
        CreateClientInput(
            client_code=f"C-WORKFLOW-EDGE-{suffix}",
            client_name=f"年度工作台邊界客戶 {suffix}",
        )
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    result = container.annual_work.confirm_preview(
        client.id,
        2026,
        container.annual_work.preview(client.id, 2026),
    )
    return client, result.items[0]


def _engagement(container: object, client_id: int, suffix: str):
    return container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name=f"年度委任 {suffix}",
            tax_type="other",
            period_name="115 年度",
        )
    )


def test_create_dialog_real_clicks_keep_invalid_payload_and_recover_service_errors(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        CreateLinkedRequestDialog,
    )

    _client, item = _work_item(container, "CREATE")
    dialog = CreateLinkedRequestDialog(
        container,
        item.id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(False, False),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text()
    qtbot.waitUntil(dialog.request_name_input.hasFocus, timeout=1000)

    dialog.request_name_input.setText("年度申報資料")
    dialog.due_date_input.setText("2026-02-30")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text()
    qtbot.waitUntil(dialog.due_date_input.hasFocus, timeout=1000)

    dialog.due_date_input.clear()
    dialog.notes_input.setPlainText("保留使用者文字\x00")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.notes_input.toPlainText() == "保留使用者文字\x00"
    qtbot.waitUntil(dialog.notes_input.hasFocus, timeout=1000)

    dialog.notes_input.setPlainText("第一行\n第二行")
    dialog.items_input.setPlainText("有效項目\n\x00")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.items_input.toPlainText() == "有效項目\n\x00"
    qtbot.waitUntil(dialog.items_input.hasFocus, timeout=1000)

    dialog.items_input.setPlainText("營所稅申報書\n附件核對表")
    real_create = container.annual_work.create_linked_request
    monkeypatch.setattr(
        container.annual_work,
        "create_linked_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AnnualWorkValidationError("doc_request.name.required")
        ),
    )
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.save_button.isEnabled()
    assert dialog.cancel_button.isEnabled()
    qtbot.waitUntil(dialog.request_name_input.hasFocus, timeout=1000)

    monkeypatch.setattr(
        container.annual_work,
        "create_linked_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("sensitive create failure")
        ),
    )
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.save_button.isEnabled()
    assert dialog.cancel_button.isEnabled()
    assert dialog.feedback_label.text()
    assert "sensitive create failure" not in dialog.feedback_label.text()

    monkeypatch.setattr(
        container.annual_work, "create_linked_request", real_create
    )
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.committed_request_id is not None
    assert not dialog.evidence_handed_off
    assert dialog.feedback_label.text()
    assert (
        container.conn.execute(
            "SELECT COUNT(*) FROM document_requests WHERE deleted_at IS NULL"
        ).fetchone()[0]
        == 1
    )


def test_link_picker_real_search_paging_failure_and_empty_recovery(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        LinkExistingEngagementDialog,
    )

    client, item = _work_item(container, "OPTIONS")
    target = _engagement(container, client.id, "唯一搜尋目標")
    for index in range(54):
        _engagement(container, client.id, f"分頁 {index:02d}")
    dialog = LinkExistingEngagementDialog(
        container,
        item.id,
        client_id=client.id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.next_button.isEnabled()
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.previous_button.isEnabled()
    qtbot.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
    assert not dialog.previous_button.isEnabled()

    real_count = container.engagements.count_by_client
    failed = False

    def fail_once(client_id: int) -> int:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("option read unavailable")
        return real_count(client_id)

    monkeypatch.setattr(container.engagements, "count_by_client", fail_once)
    dialog.search_input.clear()
    qtbot.mouseClick(dialog.search_button, Qt.MouseButton.LeftButton)
    assert not dialog.link_button.isEnabled()
    assert dialog.feedback_label.text()

    qtbot.mouseClick(dialog.search_button, Qt.MouseButton.LeftButton)
    assert dialog.link_button.isEnabled()
    assert dialog.engagement_combo.count() == 50

    dialog.search_input.setText("完全不存在的委任")
    qtbot.mouseClick(dialog.search_button, Qt.MouseButton.LeftButton)
    assert dialog.engagement_combo.count() == 0
    assert not dialog.link_button.isEnabled()
    assert dialog.feedback_label.text()

    dialog.search_input.setText("唯一搜尋目標")
    dialog.search_input.returnPressed.emit()
    assert dialog.engagement_combo.count() == 1
    assert dialog.engagement_combo.currentData() == target.id
    assert dialog.link_button.isEnabled()


def test_link_picker_real_clicks_surface_domain_and_unexpected_failures(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        LinkExistingEngagementDialog,
    )

    client, item = _work_item(container, "LINK")
    target = _engagement(container, client.id, "錯誤復原")
    dialog = LinkExistingEngagementDialog(
        container,
        item.id,
        client_id=client.id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(False, False),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.engagement_combo.clear()
    qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text()
    qtbot.waitUntil(dialog.engagement_combo.hasFocus, timeout=1000)
    qtbot.mouseClick(dialog.search_button, Qt.MouseButton.LeftButton)
    dialog.engagement_combo.setCurrentIndex(
        dialog.engagement_combo.findData(target.id)
    )
    real_link = container.annual_work.link_existing_engagement

    for code in (
        "annual_work.engagement.client_mismatch",
        "annual_work.engagement.relink_has_history",
        "annual_work.item_details.stale",
        "annual_work.workflow.page_read_failed",
    ):
        monkeypatch.setattr(
            container.annual_work,
            "link_existing_engagement",
            lambda *_args, _code=code, **_kwargs: (
                _ for _ in ()
            ).throw(AnnualWorkError(_code)),
        )
        qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)
        assert dialog.link_button.isEnabled()
        assert dialog.cancel_button.isEnabled()
        assert dialog.engagement_combo.currentData() == target.id
        assert dialog.feedback_label.text()

    monkeypatch.setattr(
        container.annual_work,
        "link_existing_engagement",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("sensitive link failure")
        ),
    )
    qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)
    assert dialog.link_button.isEnabled()
    assert dialog.cancel_button.isEnabled()
    assert dialog.feedback_label.text()
    assert "sensitive link failure" not in dialog.feedback_label.text()

    monkeypatch.setattr(
        container.annual_work, "link_existing_engagement", real_link
    )
    qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.committed_engagement_id == target.id
    assert not dialog.evidence_handed_off
    assert dialog.feedback_label.text()
    assert (
        container.annual_work.get_item_context(item.id).item.engagement_id
        == target.id
    )


def test_commit_callback_failures_never_turn_committed_requests_into_fake_success(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        CreateLinkedRequestDialog,
    )

    for suffix, handler in (
        (
            "CALLBACK-RAISE",
            lambda _evidence: (_ for _ in ()).throw(
                RuntimeError("parent callback unavailable")
            ),
        ),
        ("CALLBACK-MALFORMED", lambda _evidence: object()),
    ):
        _client, item = _work_item(container, suffix)
        dialog = CreateLinkedRequestDialog(
            container,
            item.id,
            commit_handler=handler,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.request_name_input.setText(f"交接驗證 {suffix}")
        dialog.items_input.setPlainText("年度申報書")

        qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

        assert dialog.committed_request_id is not None
        assert not dialog.evidence_handed_off
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.feedback_label.text()


def test_escape_is_visibly_refused_while_dialog_is_busy_then_cancel_closes(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        CreateLinkedRequestDialog,
        LinkExistingEngagementDialog,
    )

    client, item = _work_item(container, "BUSY-CANCEL")
    _engagement(container, client.id, "取消")
    dialogs = (
        CreateLinkedRequestDialog(
            container,
            item.id,
            commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
        ),
        LinkExistingEngagementDialog(
            container,
            item.id,
            client_id=client.id,
            commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
        ),
    )
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog._busy = True

        qtbot.keyClick(dialog, Qt.Key.Key_Escape)

        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.isVisible()
        assert dialog.feedback_label.text()
        dialog._busy = False
        qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        assert not dialog.isVisible()


def test_workflow_missing_client_locks_all_actions_then_real_retry_recovers(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container, "NOCLIENT")
    real_get_client = container.clients.get_client
    monkeypatch.setattr(
        container.clients, "get_client", lambda _client_id: None
    )

    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert not dialog.create_button.isEnabled()
    assert not dialog.link_button.isEnabled()
    assert not dialog.request_page.isEnabled()
    assert dialog.retry_button.isVisible()
    assert dialog.feedback_label.text()

    monkeypatch.setattr(container.clients, "get_client", real_get_client)
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isHidden()
    assert dialog.create_button.isEnabled()
    assert dialog.link_button.isEnabled()


def test_workflow_link_entry_read_failure_is_visible_and_retryable(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container, "LINK-LOAD")
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    real_context = container.annual_work.get_item_context
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        lambda _item_id: (_ for _ in ()).throw(
            AnnualWorkError("annual_work.item_details.read_failed")
        ),
    )

    qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)

    assert dialog.retry_button.isVisible()
    assert not dialog.create_button.isEnabled()
    assert not dialog.link_button.isEnabled()
    assert dialog.feedback_label.text()

    monkeypatch.setattr(
        container.annual_work, "get_item_context", real_context
    )
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isHidden()
    assert dialog.create_button.isEnabled()
    assert dialog.link_button.isEnabled()


def test_workflow_rejects_cross_client_overview_then_real_retry_recovers(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    client, item = _work_item(container, "MISMATCH")
    linked = container.annual_work.create_linked_request(
        item.id,
        request_name="年度核對請求",
        item_names=("營所稅申報書",),
    )
    other = container.clients.create_client(
        CreateClientInput(
            client_code="C-WORKFLOW-EDGE-OTHER",
            client_name="其他客戶",
        )
    )
    real_overview = container.annual_work.linked_overview

    def mismatched_overview(*args, **kwargs):
        overview = real_overview(*args, **kwargs)
        return replace(
            overview,
            engagement=replace(
                overview.engagement,
                client_id=other.id,
            ),
        )

    monkeypatch.setattr(
        container.annual_work, "linked_overview", mismatched_overview
    )
    dialog = AnnualWorkflowDialog(container, linked.item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert not dialog.request_page.isEnabled()
    assert dialog.retry_button.isVisible()
    assert dialog.feedback_label.text()
    assert client.id != other.id

    monkeypatch.setattr(
        container.annual_work, "linked_overview", real_overview
    )
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isHidden()
    assert dialog.request_page.isEnabled()
    assert dialog.engagement_id_label.text() == str(linked.engagement.id)


def test_workflow_panel_read_failures_keep_stale_tabs_locked_until_retry(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container, "PANELS")
    linked = container.annual_work.create_linked_request(
        item.id,
        request_name="面板讀取復原",
        item_names=("附件清單",),
    )
    dialog = AnnualWorkflowDialog(container, linked.item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    real_attachment_context = dialog.attachment_panel.set_context
    real_task_context = dialog.task_panel.set_context

    monkeypatch.setattr(
        dialog.attachment_panel,
        "set_context",
        lambda _engagement_id: False,
    )
    qtbot.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isVisible()
    assert not dialog.request_page.isEnabled()
    assert not dialog.attachment_panel.isEnabled()
    assert not dialog.task_panel.isEnabled()

    monkeypatch.setattr(
        dialog.attachment_panel, "set_context", real_attachment_context
    )
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isHidden()
    assert dialog.request_page.isEnabled()

    monkeypatch.setattr(
        dialog.task_panel,
        "set_context",
        lambda _engagement_id: False,
    )
    qtbot.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isVisible()
    assert not dialog.request_page.isEnabled()

    monkeypatch.setattr(dialog.task_panel, "set_context", real_task_context)
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    assert dialog.retry_button.isHidden()
    assert dialog.request_page.isEnabled()
