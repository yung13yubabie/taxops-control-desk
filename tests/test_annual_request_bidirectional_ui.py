from __future__ import annotations

import json
import pytest

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QDialog

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.engagements import CreateEngagementInput


def _work_item(container: object):
    client = container.clients.create_client(
        CreateClientInput(
            client_code="C-REQUEST-UI",
            client_name="年度索件雙向測試客戶",
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


def test_annual_workflow_dialog_is_available() -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    assert AnnualWorkflowDialog.__name__ == "AnnualWorkflowDialog"


def test_unlinked_item_creates_first_request_and_renders_same_database_ids(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualWorkflowDialog,
        CreateLinkedRequestDialog,
    )

    client, item = _work_item(container)
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)

    assert workflow.client_label.text() == client.client_name
    assert workflow.work_label.text() == item.title
    assert workflow.state_label.text() == "尚未連結案件"
    assert not workflow.request_page.isEnabled()
    assert workflow.create_button.isEnabled()
    assert workflow.link_button.isEnabled()

    exact_notes = "請先提供完整憑證\n第二行保留\t定位"
    exact_items = ("進項發票明細", "年度調節表附註")

    def submit(dialog: CreateLinkedRequestDialog) -> int:
        dialog.request_name_input.setText("115 年度結算索件")
        dialog.due_date_input.setText("2027-05-01")
        dialog.notes_input.setPlainText(exact_notes)
        dialog.items_input.setPlainText("\n".join(exact_items))
        qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        return dialog.result()

    monkeypatch.setattr(CreateLinkedRequestDialog, "exec", submit)
    qtbot.mouseClick(workflow.create_button, Qt.MouseButton.LeftButton)

    context = container.annual_work.get_item_context(item.id)
    assert context.item.engagement_id is not None
    requests = container.doc_requests.list_by_engagement(
        context.item.engagement_id, limit=200, offset=0
    )
    assert len(requests) == 1
    request = requests[0]
    stored_items = container.doc_requests.list_items(request.id)
    assert request.request_name == "115 年度結算索件"
    assert request.due_date == "2027-05-01"
    assert request.notes == exact_notes
    assert tuple(row.item_name for row in stored_items) == exact_items
    assert workflow.request_page.request_id_at(0) == request.id
    assert tuple(workflow.request_page.item_ids()) == tuple(
        row.id for row in stored_items
    )
    assert workflow.engagement_id_label.text() == str(context.item.engagement_id)
    assert workflow.summary_request_count.text() == "1"
    assert workflow.has_committed_change
    assert workflow.request_page.isEnabled()
    assert workflow.feedback_label.text() == "第一筆索件已建立並完成資料核對。"
    assert workflow.result() == QDialog.DialogCode.Rejected


def test_annual_item_dialog_opens_real_request_management_and_propagates_commit(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog

    _client, item = _work_item(container)
    opened: list[tuple[object, int, object]] = []

    class WorkflowSpy:
        has_committed_change = True

        def __init__(self, candidate_container, item_id, parent=None) -> None:
            opened.append((candidate_container, item_id, parent))

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.dialogs.annual_item_dialog.AnnualWorkflowDialog",
        WorkflowSpy,
        raising=False,
    )
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    audit_count = container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
    ).fetchone()[0]

    qtbot.mouseClick(dialog.request_management_button, Qt.MouseButton.LeftButton)

    assert opened == [(container, item.id, dialog)]
    assert (
        container.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        == audit_count
    )
    assert dialog.has_committed_change
    assert dialog.request_management_button.text() == "索件管理"


def test_request_management_saves_dirty_annual_detail_before_workflow_reload(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog

    _client, item = _work_item(container)
    seen_titles: list[str] = []

    class WorkflowSpy:
        has_committed_change = False

        def __init__(self, candidate_container, item_id, parent=None) -> None:
            seen_titles.append(
                candidate_container.annual_work.get_item_context(
                    item_id
                ).item.title
            )

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.dialogs.annual_item_dialog.AnnualWorkflowDialog",
        WorkflowSpy,
    )
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.detail.title_input.setText("開啟索件前先保存的工作名稱")

    qtbot.mouseClick(
        dialog.request_management_button, Qt.MouseButton.LeftButton
    )

    assert seen_titles == ["開啟索件前先保存的工作名稱"]
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.has_committed_change


def test_invalid_dirty_detail_blocks_request_workflow_and_preserves_exact_input(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog

    _client, item = _work_item(container)
    opened: list[int] = []

    class WorkflowSpy:
        has_committed_change = False

        def __init__(self, _container, item_id, parent=None) -> None:
            opened.append(item_id)

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.dialogs.annual_item_dialog.AnnualWorkflowDialog",
        WorkflowSpy,
    )
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    invalid_title = "錯" * 501
    exact_notes = "驗證失敗仍保留第一行\n第二行\t定位  "
    dialog.detail.title_input.setText(invalid_title)
    dialog.detail.notes_input.setPlainText(exact_notes)
    audit_count = container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
    ).fetchone()[0]

    qtbot.mouseClick(
        dialog.request_management_button, Qt.MouseButton.LeftButton
    )

    assert opened == []
    assert container.annual_work.get_item_context(item.id).item == item
    assert dialog.detail.title_input.text() == invalid_title
    assert dialog.detail.notes_input.toPlainText() == exact_notes
    assert (
        container.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        == audit_count
    )
    qtbot.waitUntil(dialog.detail.title_input.hasFocus, timeout=2000)
    assert dialog.request_management_button.isEnabled()
    assert "annual_work." not in dialog.detail.feedback_label.text()


def test_link_existing_lists_only_same_client_and_reads_back_exact_id(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualWorkflowDialog,
        LinkExistingEngagementDialog,
    )

    client, item = _work_item(container)
    same_client = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="既有 115 年度結算案件",
            tax_type="cit",
            period_name="115 年度",
        )
    )
    other_client = container.clients.create_client(
        CreateClientInput(client_code="C-OTHER", client_name="其他客戶")
    )
    cross_client = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=other_client.id,
            engagement_name="不可連結的案件",
            tax_type="cit",
            period_name="115 年度",
        )
    )
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)

    def submit(dialog: LinkExistingEngagementDialog) -> int:
        ids = tuple(
            dialog.engagement_combo.itemData(index)
            for index in range(dialog.engagement_combo.count())
        )
        assert same_client.id in ids
        assert cross_client.id not in ids
        dialog.engagement_combo.setCurrentIndex(
            dialog.engagement_combo.findData(same_client.id)
        )
        qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)
        return dialog.result()

    monkeypatch.setattr(LinkExistingEngagementDialog, "exec", submit)
    qtbot.mouseClick(workflow.link_button, Qt.MouseButton.LeftButton)

    stored = container.annual_work.get_item_context(item.id).item
    assert stored.engagement_id == same_client.id
    assert workflow.engagement_id_label.text() == str(same_client.id)
    assert workflow.engagement_name_label.text() == same_client.engagement_name
    assert workflow.state_label.text() == "已連結案件"
    assert workflow.request_page.isEnabled()
    assert workflow.has_committed_change
    assert workflow.feedback_label.text() == "既有案件已連結並完成資料核對。"


def test_deleted_linked_engagement_never_falls_back_to_unlinked_happy_path(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container)
    created = container.annual_work.create_linked_request(
        item.id,
        request_name="刪除案件前的真實索件",
        item_names=("原始文件",),
    )
    container.engagements.delete_engagement(created.engagement.id)

    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)

    assert workflow.state_label.text() == "索件資料不可用"
    assert not workflow.request_page.isEnabled()
    assert not workflow.create_button.isEnabled()
    assert not workflow.link_button.isEnabled()
    assert not workflow.retry_button.isHidden()
    assert workflow.feedback_label.text() == (
        "索件資料讀取失敗，請按「重新讀取索件」再試。"
    )


def test_cross_client_link_rejection_preserves_selection_and_writes_nothing(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        LinkExistingEngagementDialog,
    )

    client, item = _work_item(container)
    container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="合法案件",
            tax_type="other",
            period_name="115",
        )
    )
    other_client = container.clients.create_client(
        CreateClientInput(client_code="C-CROSS", client_name="跨客戶")
    )
    cross_client = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=other_client.id,
            engagement_name="跨客戶案件",
            tax_type="other",
            period_name="115",
        )
    )
    dialog = LinkExistingEngagementDialog(
        container,
        item.id,
        client_id=container.annual_work.get_item_context(item.id).client_id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.engagement_combo.addItem("惡意注入跨客戶案件", cross_client.id)
    dialog.engagement_combo.setCurrentIndex(
        dialog.engagement_combo.findData(cross_client.id)
    )

    qtbot.mouseClick(dialog.link_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.engagement_combo.currentData() == cross_client.id
    assert dialog.feedback_label.text() == "所選案件不屬於此年度工作的客戶，未進行連結。"
    qtbot.waitUntil(dialog.engagement_combo.hasFocus, timeout=500)
    assert container.annual_work.get_item_context(item.id).item.engagement_id is None


def test_embedded_real_follow_up_emits_once_and_workflow_rereads_same_row(
    qtbot, container
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container)
    created = container.annual_work.create_linked_request(
        item.id,
        request_name="營所稅補件",
        item_names=("總分類帳",),
        notes="請保留原始說明\n第二行",
    )
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)
    emitted: list[None] = []
    workflow.request_page.data_changed.connect(lambda: emitted.append(None))
    assert workflow.request_page.select_request_id(created.request.id)

    qtbot.mouseClick(
        workflow.request_page._follow_up_btn,
        Qt.MouseButton.LeftButton,
    )

    stored = container.doc_requests.get_request(created.request.id)
    assert stored is not None
    assert stored.follow_up_count == 1
    assert emitted == [None]
    assert workflow.has_committed_change
    assert workflow.request_page.request_id_at(0) == created.request.id
    follow_up_column = 6
    assert (
        workflow.request_page._req_table.item(0, follow_up_column).text()
        == "1"
    )
    assert workflow.feedback_label.text() == "索件資料已更新並重新核對。"
    assert workflow.request_page.isEnabled()


@pytest.mark.parametrize("failing_layer", ("context", "summary", "page"))
def test_committed_create_readback_failure_disables_then_retries_without_resubmit(
    qtbot, container, monkeypatch, failing_layer
) -> None:
    from taxops.services.annual_work import AnnualWorkError
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualWorkflowDialog,
        CreateLinkedRequestDialog,
    )

    _client, item = _work_item(container)
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)
    real_context = container.annual_work.get_item_context
    real_summary = container.annual_work.document_summary
    real_page_load = workflow.request_page.load_engagement
    failed = False

    def fail_context_once(item_id):
        nonlocal failed
        if not failed:
            failed = True
            raise AnnualWorkError("annual_work.item_details.read_failed")
        return real_context(item_id)

    def fail_summary_once(item_id):
        nonlocal failed
        if not failed:
            failed = True
            raise AnnualWorkError("annual_work.workflow.summary_read_failed")
        return real_summary(item_id)

    def fail_page_once(engagement_id):
        nonlocal failed
        if not failed:
            failed = True
            return False
        return real_page_load(engagement_id)

    def submit(dialog: CreateLinkedRequestDialog) -> int:
        dialog.request_name_input.setText("提交後讀回失敗測試")
        dialog.due_date_input.setText("2027-05-10")
        dialog.notes_input.setPlainText("已寫入\n不可重送")
        dialog.items_input.setPlainText("總帳\n申報書")
        if failing_layer == "context":
            monkeypatch.setattr(
                container.annual_work, "get_item_context", fail_context_once
            )
        elif failing_layer == "summary":
            monkeypatch.setattr(
                container.annual_work, "document_summary", fail_summary_once
            )
        else:
            monkeypatch.setattr(
                workflow.request_page, "load_engagement", fail_page_once
            )
        qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        assert dialog.committed_request_id is not None
        assert not dialog.save_button.isEnabled()
        return dialog.result()

    monkeypatch.setattr(CreateLinkedRequestDialog, "exec", submit)
    qtbot.mouseClick(workflow.create_button, Qt.MouseButton.LeftButton)

    count = container.conn.execute(
        "SELECT COUNT(*) FROM document_requests WHERE deleted_at IS NULL"
    ).fetchone()[0]
    assert count == 1
    assert workflow.has_committed_change
    assert not workflow.request_page.isEnabled()
    assert not workflow.retry_button.isHidden()
    assert workflow.feedback_label.text() == (
        "資料已寫入，但重新核對失敗；請按「重新讀取索件」，請勿再次送出。"
    )

    qtbot.mouseClick(workflow.retry_button, Qt.MouseButton.LeftButton)

    assert (
        container.conn.execute(
            "SELECT COUNT(*) FROM document_requests WHERE deleted_at IS NULL"
        ).fetchone()[0]
        == 1
    )
    assert workflow.request_page.isEnabled()
    assert workflow.retry_button.isHidden()
    assert workflow.feedback_label.text() == "索件資料已重新讀取。"


def test_create_double_submit_calls_service_once_and_creates_one_request(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        CreateLinkedRequestDialog,
    )

    _client, item = _work_item(container)
    real_create = container.annual_work.create_linked_request
    calls = 0

    def counted_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_create(*args, **kwargs)

    monkeypatch.setattr(
        container.annual_work, "create_linked_request", counted_create
    )
    dialog = CreateLinkedRequestDialog(
        container,
        item.id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
    )
    qtbot.addWidget(dialog)
    dialog.request_name_input.setText("雙擊防重")
    dialog.due_date_input.setText("2027-05-20")
    dialog.notes_input.setPlainText("同一筆")
    dialog.items_input.setPlainText("文件一")

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    dialog.save()

    assert calls == 1
    assert (
        container.conn.execute(
            "SELECT COUNT(*) FROM document_requests WHERE deleted_at IS NULL"
        ).fetchone()[0]
        == 1
    )


def test_atomic_create_failure_preserves_exact_form_and_writes_nothing(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import (
        AnnualRequestCommitAck,
        CreateLinkedRequestDialog,
    )

    _client, item = _work_item(container)
    dialog = CreateLinkedRequestDialog(
        container,
        item.id,
        commit_handler=lambda _evidence: AnnualRequestCommitAck(True, True),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    exact_name = "原始索件名稱"
    exact_notes = "原始說明\n第二行\t保留"
    exact_items = "文件甲\n文件乙"
    dialog.request_name_input.setText(exact_name)
    dialog.due_date_input.setText("2027-05-30")
    dialog.notes_input.setPlainText(exact_notes)
    dialog.items_input.setPlainText(exact_items)
    monkeypatch.setattr(
        container.audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("sensitive payload")),
    )

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.request_name_input.text() == exact_name
    assert dialog.notes_input.toPlainText() == exact_notes
    assert dialog.items_input.toPlainText() == exact_items
    assert (
        container.conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE deleted_at IS NULL"
        ).fetchone()[0]
        == 0
    )
    assert (
        container.conn.execute(
            "SELECT COUNT(*) FROM document_requests WHERE deleted_at IS NULL"
        ).fetchone()[0]
        == 0
    )
    assert dialog.feedback_label.text() == "建立索件失敗，資料未變更，請稍後再試。"
    log_row = container.conn.execute(
        "SELECT detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert log_row is not None
    detail = json.loads(log_row["detail_json"])
    assert detail == {
        "operation": "create",
        "code": "annual_work.request.create_failed",
        "item_id": item.id,
    }
    assert "sensitive payload" not in log_row["detail_json"]


def test_embedded_mutation_commit_with_summary_failure_locks_until_retry(
    qtbot, container, monkeypatch
) -> None:
    from taxops.services.annual_work import AnnualWorkError
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container)
    created = container.annual_work.create_linked_request(
        item.id,
        request_name="催件後核對失敗",
        item_names=("帳冊",),
    )
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)
    assert workflow.request_page.select_request_id(created.request.id)
    real_summary = container.annual_work.document_summary
    failed = False

    def fail_once(item_id):
        nonlocal failed
        if not failed:
            failed = True
            raise AnnualWorkError("annual_work.workflow.summary_read_failed")
        return real_summary(item_id)

    monkeypatch.setattr(container.annual_work, "document_summary", fail_once)
    qtbot.mouseClick(
        workflow.request_page._follow_up_btn, Qt.MouseButton.LeftButton
    )

    assert container.doc_requests.get_request(created.request.id).follow_up_count == 1
    assert workflow.has_committed_change
    assert not workflow.request_page.isEnabled()
    assert workflow.feedback_label.text() == (
        "資料已寫入，但重新核對失敗；請按「重新讀取索件」，請勿再次送出。"
    )

    qtbot.mouseClick(workflow.retry_button, Qt.MouseButton.LeftButton)

    assert container.doc_requests.get_request(created.request.id).follow_up_count == 1
    assert workflow.request_page.isEnabled()
    assert workflow.request_page.request_id_at(0) == created.request.id


def test_global_item_status_change_is_reread_by_annual_workflow_same_ids(
    qtbot, container, monkeypatch
) -> None:
    from taxops.i18n.status_labels import status_to_label
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    _client, item = _work_item(container)
    created = container.annual_work.create_linked_request(
        item.id,
        request_name="雙向狀態測試",
        item_names=("原始缺件",),
    )
    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)
    assert workflow.summary_item_counts.text().startswith("缺件 1")

    global_page = DocumentRequestsPage(container)
    qtbot.addWidget(global_page)
    assert global_page.load_engagement(created.engagement.id)
    assert global_page.select_request_id(created.request.id)
    global_page._item_table.selectRow(0)
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        lambda *_args, **_kwargs: (status_to_label("received"), True),
    )
    qtbot.mouseClick(
        global_page._item_status_btn, Qt.MouseButton.LeftButton
    )

    stored_items = container.doc_requests.list_items(created.request.id)
    assert stored_items[0].id == created.items[0].id
    assert stored_items[0].item_status == "received"
    assert workflow.summary_item_counts.text().startswith("缺件 1")

    qtbot.mouseClick(
        workflow.refresh_button, Qt.MouseButton.LeftButton
    )

    assert workflow.request_page.request_id_at(0) == created.request.id
    assert workflow.summary_item_counts.text().startswith("缺件 0、已收 1")


def test_unexpected_workflow_load_logs_only_sanitized_ids(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container)
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        lambda _item_id: (_ for _ in ()).throw(
            RuntimeError("秘密索件名稱與說明不得進log")
        ),
    )

    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)

    row = container.conn.execute(
        "SELECT message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    detail = json.loads(row["detail_json"])
    assert row["message"] == "annual request workflow read failed"
    assert detail == {
        "operation": "load",
        "code": "system.unexpected",
        "item_id": item.id,
    }
    serialized = json.dumps(detail, ensure_ascii=False)
    assert "秘密" not in serialized
    assert "request_name" not in serialized
    assert "notes" not in serialized


def test_workflow_failure_does_not_log_or_commit_caller_owned_transaction(
    qtbot, container, monkeypatch
) -> None:
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    _client, item = _work_item(container)
    before = container.conn.execute(
        "SELECT COUNT(*) FROM system_logs"
    ).fetchone()[0]
    container.conn.execute("BEGIN")
    monkeypatch.setattr(
        container.annual_work,
        "get_item_context",
        lambda _item_id: (_ for _ in ()).throw(RuntimeError("caller tx")),
    )

    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)

    assert container.conn.in_transaction
    assert (
        container.conn.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0]
        == before
    )
    container.conn.rollback()


def test_fixed_desktop_geometry_keeps_entry_header_retry_and_embedded_actions_reachable(
    qtbot, container
) -> None:
    from taxops.services.annual_work import AnnualWorkError
    from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog

    def inside(parent, child) -> bool:
        top_left = child.mapTo(parent, QPoint(0, 0))
        rect = QRect(top_left, child.size())
        return parent.rect().contains(rect.topLeft()) and parent.rect().contains(
            rect.bottomRight()
        )

    def at_least_14px(font) -> bool:
        return font.pixelSize() >= 14 or font.pointSizeF() >= 10.5

    def at_least_13px(font) -> bool:
        return font.pixelSize() >= 13 or font.pointSizeF() >= 10.0

    _client, item = _work_item(container)
    container.annual_work.create_linked_request(
        item.id,
        request_name="版面驗收索件",
        item_names=("憑證一", "憑證二"),
    )

    item_dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(item_dialog)
    item_dialog.resize(900, 540)
    item_dialog.show()
    qtbot.waitExposed(item_dialog)
    assert item_dialog.request_management_button.isVisible()
    assert inside(item_dialog, item_dialog.request_management_button)
    assert at_least_14px(item_dialog.request_management_button.font())

    workflow = AnnualWorkflowDialog(container, item.id)
    qtbot.addWidget(workflow)
    workflow.resize(1100, 680)
    workflow.show()
    qtbot.waitExposed(workflow)
    for button in (
        workflow.create_button,
        workflow.link_button,
        workflow.refresh_button,
        workflow.close_button,
    ):
        assert button.isVisible()
        assert inside(workflow, button)
    for button in (
        workflow.request_page._new_req_btn,
        workflow.request_page._edit_req_btn,
        workflow.request_page._mark_requested_btn,
        workflow.request_page._request_status_btn,
        workflow.request_page._follow_up_btn,
        workflow.request_page._delete_req_btn,
        workflow.request_page._add_item_btn,
        workflow.request_page._edit_item_btn,
        workflow.request_page._delete_item_btn,
        workflow.request_page._bulk_delete_items_btn,
        workflow.request_page._item_status_btn,
        workflow.request_page._generate_btn,
        workflow.request_page._export_btn,
    ):
        assert button.isVisible()
        assert inside(workflow, button)
    assert at_least_13px(workflow.request_page._req_table.font())
    assert at_least_14px(workflow.feedback_label.font())

    workflow._set_failed(
        operation="layout_test",
        exc=AnnualWorkError("annual_work.workflow.page_read_failed"),
    )
    qtbot.waitUntil(lambda: workflow.retry_button.isVisible(), timeout=500)
    assert inside(workflow, workflow.retry_button)
