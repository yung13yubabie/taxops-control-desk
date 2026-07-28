from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import QMessageBox, QScrollArea

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput


def _linked_item(container: object):
    client = container.clients.create_client(
        CreateClientInput(
            client_code="C-ANNUAL-COLLAB",
            client_name="年度協作真實路徑客戶",
        )
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    confirmed = container.annual_work.confirm_preview(
        client.id,
        2026,
        container.annual_work.preview(client.id, 2026),
    )
    item = confirmed.items[0]
    linked = container.annual_work.create_linked_request(
        item.id,
        request_name="年度結算索件",
        item_names=("結算申報書",),
    )
    return client, linked.item, linked.engagement, linked.request


def test_annual_collaboration_dialog_has_fixed_desktop_tabs(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "年度工作協作"
    assert dialog.minimumWidth() >= 900
    assert dialog.minimumHeight() >= 540
    assert [
        dialog.tabs.tabText(index) for index in range(dialog.tabs.count())
    ] == ["索件", "附件", "待辦"]
    assert "案件共用附件" in dialog.attachment_panel.scope_label.text()
    assert dialog.attachment_panel.isEnabled()
    assert dialog.task_panel.isEnabled()
    assert dialog.close_button.text() == "關閉協作管理"
    dialog.resize(900, 540)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.size() == QSize(900, 540)
    assert isinstance(dialog.request_scroll, QScrollArea)
    assert isinstance(dialog.attachment_scroll, QScrollArea)
    assert isinstance(dialog.task_scroll, QScrollArea)
    for index, (panel, buttons) in enumerate(
        (
            (
                dialog.attachment_panel,
                (
                    dialog.attachment_panel.upload_button,
                    dialog.attachment_panel.accept_button,
                    dialog.attachment_panel.reject_button,
                    dialog.attachment_panel.archive_button,
                    dialog.attachment_panel.previous_button,
                    dialog.attachment_panel.next_button,
                ),
            ),
            (
                dialog.task_panel,
                (
                    dialog.task_panel.create_button,
                    dialog.task_panel.complete_button,
                    dialog.task_panel.status_button,
                    dialog.task_panel.delete_button,
                    dialog.task_panel.previous_button,
                    dialog.task_panel.next_button,
                ),
            ),
        ),
        start=1,
    ):
        dialog.tabs.setCurrentIndex(index)
        qtbot.wait(1)
        for button in buttons:
            top_left = button.mapTo(panel, QPoint(0, 0))
            bottom_right = button.mapTo(
                panel, QPoint(button.width() - 1, button.height() - 1)
            )
            assert panel.rect().contains(top_left), button.text()
            assert panel.rect().contains(bottom_right), button.text()
            assert button.width() >= button.minimumSizeHint().width(), button.text()


def test_annual_attachment_upload_reads_back_exact_database_id(
    qtbot, container, monkeypatch, tmp_path: Path
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, engagement, request = _linked_item(container)
    source = tmp_path / "年度憑證.pdf"
    exact_bytes = b"real annual evidence"
    source.write_bytes(exact_bytes)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.attachment_panel
    request_index = panel.request_combo.findData(request.id)
    assert request_index >= 0
    panel.request_combo.setCurrentIndex(request_index)
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "PDF (*.pdf)"),
    )

    qtbot.mouseClick(panel.upload_button, Qt.MouseButton.LeftButton)

    rows = container.attachments.page_by_request(
        request.id, limit=50, offset=0
    )
    assert len(rows) == 1
    stored = rows[0]
    assert stored.engagement_id == engagement.id
    assert stored.request_id == request.id
    assert stored.original_filename == "年度憑證.pdf"
    assert panel.attachment_ids() == (stored.id,)
    assert panel.selected_attachment_id() == stored.id
    assert container.attachments.resolve_file_path(stored.id).read_bytes() == exact_bytes
    assert panel.pending_mutation_evidence is None
    assert panel.feedback_label.text() == "附件已上傳並完成資料核對。"
    assert dialog.has_committed_change


def test_committed_attachment_readback_failure_retries_without_duplicate_file(
    qtbot, container, monkeypatch, tmp_path: Path
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, request = _linked_item(container)
    source = tmp_path / "只應上傳一次.pdf"
    source.write_bytes(b"one upload only")
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.attachment_panel
    panel.request_combo.setCurrentIndex(panel.request_combo.findData(request.id))
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "PDF (*.pdf)"),
    )
    real_get = container.attachments.get
    calls = 0

    def fail_twice(attachment_id: int):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise RuntimeError("simulated readback failure")
        return real_get(attachment_id)

    monkeypatch.setattr(container.attachments, "get", fail_twice)

    qtbot.mouseClick(panel.upload_button, Qt.MouseButton.LeftButton)

    assert container.attachments.count_by_request(request.id) == 1
    assert panel.pending_mutation_evidence is not None
    assert not panel.retry_button.isHidden()
    assert not panel.upload_button.isEnabled()
    assert "資料可能已寫入，請勿重送" in panel.feedback_label.text()

    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)

    assert container.attachments.count_by_request(request.id) == 1
    assert panel.pending_mutation_evidence is not None
    assert "資料可能已寫入，請勿重送" in panel.feedback_label.text()

    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)

    assert container.attachments.count_by_request(request.id) == 1
    assert panel.pending_mutation_evidence is None
    assert panel.upload_button.isEnabled()
    assert panel.retry_button.isHidden()
    assert len(
        [path for path in container.paths.attachments_dir.rglob("*") if path.is_file()]
    ) == 1


def test_annual_task_create_and_complete_use_same_database_id(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.task_panel
    panel.title_input.setText("完成 115 年度營所稅申報")
    panel.due_date_input.setText("2027-05-01")
    panel.notes_input.setPlainText("先覆核調節表\n再產出申報檔")

    qtbot.mouseClick(panel.create_button, Qt.MouseButton.LeftButton)

    rows = container.tasks.list_by_annual_work_item(
        item.id, limit=50, offset=0
    )
    assert len(rows) == 1
    task = rows[0]
    assert task.engagement_id == engagement.id
    assert task.annual_work_item_id == item.id
    assert task.notes == "先覆核調節表\n再產出申報檔"
    assert panel.task_ids() == (task.id,)
    assert panel.selected_task_id() == task.id
    assert panel.pending_mutation_evidence is None
    assert panel.feedback_label.text() == "待辦已建立並完成資料核對。"

    qtbot.mouseClick(panel.complete_button, Qt.MouseButton.LeftButton)

    completed = container.tasks.get_task(task.id)
    assert completed is not None
    assert completed.id == task.id
    assert completed.status == "done"
    assert panel.row_for_task_id(task.id).status == "done"
    assert panel.feedback_label.text() == "待辦已完成並完成資料核對。"
    assert dialog.has_committed_change


def test_annual_task_committed_readback_failure_retries_without_duplicate(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.task_panel
    panel.title_input.setText("只應建立一次的年度待辦")
    real_get = container.tasks.get_task
    calls = 0

    def fail_twice(task_id: int):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise RuntimeError("simulated task readback failure")
        return real_get(task_id)

    monkeypatch.setattr(container.tasks, "get_task", fail_twice)

    qtbot.mouseClick(panel.create_button, Qt.MouseButton.LeftButton)

    assert container.tasks.count_by_annual_work_item(item.id) == 1
    assert panel.pending_mutation_evidence is not None
    assert not panel.create_button.isEnabled()
    assert not panel.retry_button.isHidden()
    assert "資料可能已寫入，請勿重送" in panel.feedback_label.text()

    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)

    assert container.tasks.count_by_annual_work_item(item.id) == 1
    assert panel.pending_mutation_evidence is not None
    assert "資料可能已寫入，請勿重送" in panel.feedback_label.text()

    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)

    assert container.tasks.count_by_annual_work_item(item.id) == 1
    assert panel.pending_mutation_evidence is None
    assert panel.create_button.isEnabled()
    assert panel.retry_button.isHidden()


def test_annual_attachment_accept_reject_archive_and_failure_feedback(
    qtbot, container, monkeypatch, tmp_path: Path
) -> None:
    from taxops.services.attachments import AttachmentValidationError
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    source = tmp_path / "案件層級附件.pdf"
    source.write_bytes(b"attachment status path")
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.attachment_panel
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "PDF (*.pdf)"),
    )
    qtbot.mouseClick(panel.upload_button, Qt.MouseButton.LeftButton)
    attachment_id = panel.selected_attachment_id()
    assert attachment_id is not None

    qtbot.mouseClick(panel.accept_button, Qt.MouseButton.LeftButton)
    accepted = container.attachments.get(attachment_id)
    assert accepted is not None
    assert accepted.status == "accepted"
    assert panel.row_for_attachment_id(attachment_id) == accepted

    real_reject = container.attachments.reject_attachment
    monkeypatch.setattr(
        container.attachments,
        "reject_attachment",
        lambda _attachment_id: (_ for _ in ()).throw(
            AttachmentValidationError("attachment.not_found")
        ),
    )
    qtbot.mouseClick(panel.reject_button, Qt.MouseButton.LeftButton)
    assert container.attachments.get(attachment_id) == accepted
    assert "附件狀態更新失敗，資料未變更" in panel.feedback_label.text()
    monkeypatch.setattr(
        container.attachments, "reject_attachment", real_reject
    )

    qtbot.mouseClick(panel.reject_button, Qt.MouseButton.LeftButton)
    rejected = container.attachments.get(attachment_id)
    assert rejected is not None
    assert rejected.status == "rejected"
    assert panel.feedback_label.text() == "附件已標記退回並完成資料核對。"

    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    qtbot.mouseClick(panel.archive_button, Qt.MouseButton.LeftButton)
    assert container.attachments.get(attachment_id) == rejected

    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(panel.archive_button, Qt.MouseButton.LeftButton)
    archived = container.attachments.get(attachment_id)
    assert archived is not None
    assert archived.status == "archived"
    assert panel.attachment_ids() == ()
    assert panel.feedback_label.text() == "附件已封存並完成資料核對。"
    audit_rows = container.conn.execute(
        "SELECT action, target_id FROM audit_logs "
        "WHERE target_type = 'attachment' AND target_id = ? ORDER BY id",
        (str(attachment_id),),
    ).fetchall()
    assert [tuple(row) for row in audit_rows] == [
        ("attachment.upload", str(attachment_id)),
        ("attachment.accept", str(attachment_id)),
        ("attachment.reject", str(attachment_id)),
        ("attachment.delete", str(attachment_id)),
    ]


def test_annual_task_status_delete_invalid_input_and_failure_feedback(
    qtbot, container, monkeypatch
) -> None:
    from taxops.services.tasks import TaskValidationError
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.task_panel

    qtbot.mouseClick(panel.create_button, Qt.MouseButton.LeftButton)
    assert container.tasks.count_by_annual_work_item(item.id) == 0
    assert "建立年度待辦失敗，資料未變更" in panel.feedback_label.text()

    panel.title_input.setText("更新狀態後刪除的年度待辦")
    qtbot.mouseClick(panel.create_button, Qt.MouseButton.LeftButton)
    task_id = panel.selected_task_id()
    assert task_id is not None
    doing_index = panel.status_combo.findData("doing")
    assert doing_index >= 0
    panel.status_combo.setCurrentIndex(doing_index)
    qtbot.mouseClick(panel.status_button, Qt.MouseButton.LeftButton)
    doing = container.tasks.get_task(task_id)
    assert doing is not None
    assert doing.status == "doing"
    assert panel.row_for_task_id(task_id) == doing

    real_set_status = container.tasks.set_status
    monkeypatch.setattr(
        container.tasks,
        "set_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TaskValidationError("task.status.transition_invalid")
        ),
    )
    status_index = panel.status_combo.findData("waiting_client")
    assert status_index >= 0
    panel.status_combo.setCurrentIndex(status_index)
    qtbot.mouseClick(panel.status_button, Qt.MouseButton.LeftButton)
    assert container.tasks.get_task(task_id) == doing
    assert "更新待辦狀態失敗，資料未變更" in panel.feedback_label.text()
    monkeypatch.setattr(container.tasks, "set_status", real_set_status)

    monkeypatch.setattr(
        "taxops.ui.widgets.annual_task_panel.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    qtbot.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)
    assert container.tasks.get_task(task_id) == doing

    monkeypatch.setattr(
        "taxops.ui.widgets.annual_task_panel.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)
    assert container.tasks.get_task(task_id) is None
    assert panel.task_ids() == ()
    assert panel.feedback_label.text() == "待辦已刪除並完成資料核對。"
    audit_rows = container.conn.execute(
        "SELECT action, target_id FROM audit_logs "
        "WHERE target_type = 'task' AND target_id = ? ORDER BY id",
        (str(task_id),),
    ).fetchall()
    assert [tuple(row) for row in audit_rows] == [
        ("task.create", str(task_id)),
        ("task.status_change", str(task_id)),
        ("task.delete", str(task_id)),
    ]
    annual_audit = container.conn.execute(
        "SELECT action, target_id, detail_json FROM audit_logs "
        "WHERE action = 'annual_work.task.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert annual_audit is not None
    assert annual_audit["target_id"] == str(item.id)
    assert f'"task_id": {task_id}' in annual_audit["detail_json"]


def test_collaboration_panel_initial_read_failure_has_read_only_retry(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    attachment_panel = dialog.attachment_panel
    task_panel = dialog.task_panel
    real_attachment_count = container.attachments.count_by_engagement
    real_task_count = container.tasks.count_by_annual_work_item

    monkeypatch.setattr(
        container.attachments,
        "count_by_engagement",
        lambda _engagement_id: (_ for _ in ()).throw(
            RuntimeError("attachment read unavailable")
        ),
    )
    monkeypatch.setattr(
        container.tasks,
        "count_by_annual_work_item",
        lambda _item_id: (_ for _ in ()).throw(
            RuntimeError("task read unavailable")
        ),
    )
    assert not attachment_panel.reload()
    assert not task_panel.reload()
    assert attachment_panel.pending_mutation_evidence is None
    assert task_panel.pending_mutation_evidence is None
    assert attachment_panel.attachment_ids() == ()
    assert task_panel.task_ids() == ()
    assert "附件讀取失敗" in attachment_panel.feedback_label.text()
    assert "待辦讀取失敗" in task_panel.feedback_label.text()
    assert not attachment_panel.upload_button.isEnabled()
    assert not task_panel.create_button.isEnabled()
    assert not attachment_panel.retry_button.isHidden()
    assert not task_panel.retry_button.isHidden()

    monkeypatch.setattr(
        container.attachments,
        "count_by_engagement",
        real_attachment_count,
    )
    monkeypatch.setattr(
        container.tasks,
        "count_by_annual_work_item",
        real_task_count,
    )
    qtbot.mouseClick(
        attachment_panel.retry_button, Qt.MouseButton.LeftButton
    )
    qtbot.mouseClick(task_panel.retry_button, Qt.MouseButton.LeftButton)
    assert attachment_panel.attachment_ids() == ()
    assert task_panel.task_ids() == ()
    assert attachment_panel.retry_button.isHidden()
    assert task_panel.retry_button.isHidden()
    assert attachment_panel.feedback_label.text() == "附件已重新讀取。"
    assert task_panel.feedback_label.text() == "待辦已重新讀取。"


def test_attachment_filter_failure_clears_old_scope_and_locks_mutations(
    qtbot, container, monkeypatch, tmp_path: Path
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, request = _linked_item(container)
    source = tmp_path / "舊範圍附件.pdf"
    source.write_bytes(b"old scope must not remain actionable")
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.attachment_panel
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "PDF (*.pdf)"),
    )
    qtbot.mouseClick(panel.upload_button, Qt.MouseButton.LeftButton)
    old_id = panel.selected_attachment_id()
    assert old_id is not None
    real_count = container.attachments.count_by_request
    monkeypatch.setattr(
        container.attachments,
        "count_by_request",
        lambda _request_id: (_ for _ in ()).throw(
            RuntimeError("new request scope unavailable")
        ),
    )

    panel.request_combo.setCurrentIndex(panel.request_combo.findData(request.id))

    assert panel.attachment_ids() == ()
    assert panel.selected_attachment_id() is None
    assert not panel.upload_button.isEnabled()
    assert not panel.accept_button.isEnabled()
    assert not panel.reject_button.isEnabled()
    assert not panel.archive_button.isEnabled()
    assert not panel.next_button.isEnabled()
    assert not panel.retry_button.isHidden()
    assert container.attachments.get(old_id) is not None

    monkeypatch.setattr(
        container.attachments, "count_by_request", real_count
    )
    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)
    assert panel.upload_button.isEnabled()
    assert panel.retry_button.isHidden()
    assert panel.attachment_ids() == ()


def test_parent_context_failure_disables_all_tabs_until_read_only_retry(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, _engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    real_get_context = container.annual_work.get_item_context
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        lambda _item_id: (_ for _ in ()).throw(
            RuntimeError("annual context unavailable")
        ),
    )

    qtbot.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)

    assert not dialog.request_page.isEnabled()
    assert not dialog.attachment_panel.isEnabled()
    assert not dialog.task_panel.isEnabled()
    assert not dialog.retry_button.isHidden()
    assert "索件資料讀取失敗" in dialog.feedback_label.text()

    monkeypatch.setattr(
        container.annual_work, "get_item_context", real_get_context
    )
    qtbot.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)

    assert dialog.request_page.isEnabled()
    assert dialog.attachment_panel.isEnabled()
    assert dialog.task_panel.isEnabled()
    assert dialog.retry_button.isHidden()


def test_attachment_panel_defensive_evidence_and_no_context_guards(
    qtbot, container, monkeypatch, tmp_path: Path
) -> None:
    from taxops.services.attachments import (
        AttachmentValidationError,
        UploadAttachmentInput,
    )
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog
    from taxops.ui.widgets.annual_attachment_panel import (
        AttachmentMutationEvidence,
    )

    _client, item, engagement, request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.attachment_panel
    panel.set_context(None)
    assert panel._read_count(None) == 0
    assert panel._read_page(None, offset=0) == ()
    panel._upload()
    panel._previous_page()
    panel._next_page()
    assert container.attachments.count_by_engagement(engagement.id) == 0

    panel.set_context(engagement.id)
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    panel._upload()
    source = tmp_path / "防禦核對.pdf"
    source.write_bytes(b"defensive attachment evidence")
    monkeypatch.setattr(
        "taxops.ui.widgets.annual_attachment_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "PDF (*.pdf)"),
    )
    real_upload = container.attachments.upload_attachment
    monkeypatch.setattr(
        container.attachments,
        "upload_attachment",
        lambda _payload: (_ for _ in ()).throw(
            AttachmentValidationError("attachment.engagement_not_found")
        ),
    )
    panel._upload()
    assert "附件上傳失敗，資料未變更" in panel.feedback_label.text()
    monkeypatch.setattr(
        container.attachments, "upload_attachment", real_upload
    )
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(
            engagement_id=engagement.id,
            request_id=None,
            source_path=source,
        )
    )
    assert panel.reload()
    exact = AttachmentMutationEvidence("accept", row, 1, None)
    with pytest.raises(RuntimeError, match="count mismatch"):
        panel._verify_pending(replace(exact, count_before=99))
    monkeypatch.setattr(container.attachments, "get", lambda _id: None)
    with pytest.raises(RuntimeError, match="row readback mismatch"):
        panel._verify_pending(exact)
    archived = replace(row, status="archived")
    with pytest.raises(RuntimeError, match="archive readback mismatch"):
        panel._verify_pending(
            AttachmentMutationEvidence(
                "archive", archived, 2, None, archived=True
            )
        )
    assert not panel._select_id(999_999)


def test_task_panel_defensive_evidence_and_no_context_guards(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog
    from taxops.ui.widgets.annual_task_panel import TaskMutationEvidence

    _client, item, engagement, _request = _linked_item(container)
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)
    panel = dialog.task_panel
    panel.set_context(None)
    panel._create()
    panel._previous_page()
    panel._next_page()
    assert container.tasks.count_by_annual_work_item(item.id) == 0

    panel.set_context(engagement.id)
    task = container.annual_work.create_linked_task(
        item.id, title="待辦防禦核對"
    )
    assert panel.reload()
    exact = TaskMutationEvidence("status", task, task, 1)
    with pytest.raises(RuntimeError, match="count mismatch"):
        panel._verify_pending(replace(exact, count_before=99))
    with pytest.raises(RuntimeError, match="evidence missing"):
        panel._verify_pending(
            TaskMutationEvidence("status", None, None, 1)
        )
    monkeypatch.setattr(container.tasks, "get_task", lambda _id: None)
    with pytest.raises(RuntimeError, match="row readback mismatch"):
        panel._verify_pending(exact)
    monkeypatch.setattr(container.tasks, "get_task", lambda _id: task)
    with pytest.raises(RuntimeError, match="delete readback mismatch"):
        panel._verify_pending(
            TaskMutationEvidence("delete", task, None, 2)
        )
    assert not panel._select_id(999_999)


def test_annual_collaboration_panels_reach_201st_rows(
    qtbot, container
) -> None:
    from taxops.repositories.attachments import AttachmentsRepository
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item, engagement, _request = _linked_item(container)
    repo: AttachmentsRepository = container.attachments._repo
    with container.conn:
        attachment_ids = [
            repo.insert_with_version(
                engagement_id=engagement.id,
                request_id=None,
                original_filename=f"年度附件-{index:03d}.pdf",
                stored_filename=f"2026/01/annual-{index:03d}.pdf",
                file_hash_sha256=f"{index:064x}",
                file_size=index + 1,
                mime_type="application/pdf",
                extension=".pdf",
            ).id
            for index in range(201)
        ]
    task_ids = [
        container.annual_work.create_linked_task(
            item.id, title=f"年度待辦-{index:03d}"
        ).id
        for index in range(201)
    ]
    dialog = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(dialog)

    assert "共 201 筆" in dialog.attachment_panel.page_label.text()
    seen_attachments = list(dialog.attachment_panel.attachment_ids())
    while dialog.attachment_panel.next_button.isEnabled():
        qtbot.mouseClick(
            dialog.attachment_panel.next_button, Qt.MouseButton.LeftButton
        )
        seen_attachments.extend(dialog.attachment_panel.attachment_ids())
    assert len(seen_attachments) == 201
    assert set(seen_attachments) == set(attachment_ids)
    qtbot.mouseClick(
        dialog.attachment_panel.previous_button, Qt.MouseButton.LeftButton
    )
    assert len(dialog.attachment_panel.attachment_ids()) == 50

    assert "共 201 筆" in dialog.task_panel.page_label.text()
    seen_tasks = list(dialog.task_panel.task_ids())
    while dialog.task_panel.next_button.isEnabled():
        qtbot.mouseClick(dialog.task_panel.next_button, Qt.MouseButton.LeftButton)
        seen_tasks.extend(dialog.task_panel.task_ids())
    assert len(seen_tasks) == 201
    assert set(seen_tasks) == set(task_ids)
    qtbot.mouseClick(
        dialog.task_panel.previous_button, Qt.MouseButton.LeftButton
    )
    assert len(dialog.task_panel.task_ids()) == 50
