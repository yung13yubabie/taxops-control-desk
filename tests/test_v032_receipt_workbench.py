"""Document-led receipt UI preserves v0.31 ownership and manual reconciliation."""
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from taxops.services.attachments import UploadAttachmentInput
from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput
from taxops.services.document_requests import CreateDocumentRequestInput
from taxops.services.engagements import CreateEngagementInput
from taxops.ui.action_registry import PAGE_ENGAGEMENTS
from taxops.ui.pages.attachments_page import AttachmentsPage
from taxops.ui.style import apply as apply_style


@pytest.fixture
def records(container, tmp_path):
    client = container.clients.create_client(CreateClientInput(client_code="RECEIPT", client_name="同名客戶甲"))
    case = container.engagements.create_engagement(CreateEngagementInput(client_id=client.id, engagement_name="同名案件", tax_type="vat", period_name="2026-10", due_date="2026-11-15"))
    request, _ = container.doc_requests.create_request(CreateDocumentRequestInput(engagement_id=case.id, tax_type="vat", period_name="2026-10", request_name="同名索件", due_date="2026-10-12", item_names=("進項憑證", "銀行明細")))
    source = tmp_path / "長中文附件名稱.txt"
    source.write_text("合成測試附件\n字面文字", encoding="utf8")
    case_file = container.attachments.upload_attachment(UploadAttachmentInput(engagement_id=case.id, request_id=request.id, source_path=source))
    lease = container.client_leases.create_lease(client.id, LeaseInput(lease_name="辦公室租約", start_date="2026-01-01", end_date="2027-12-31"))
    lease_file = container.attachments.upload_lease_attachment(client.id, lease.id, source)
    return client, case, request, lease, case_file, lease_file


@pytest.fixture
def page(qtbot, qapp, container, records):
    widget = AttachmentsPage(container)
    qtbot.addWidget(widget)
    widget.resize(1366, 768)
    widget.show()
    qapp.processEvents()
    return widget


def _select(page, attachment):
    page._status_tabs.setCurrentIndex(3)
    page._select_attachment_id(attachment.id)


def test_receipt_owner_labels_distinguish_case_and_lease(page, records):
    client, case, _, lease, case_file, lease_file = records
    assert client.client_name in page._owner_labels[case_file.id]
    assert case.engagement_name in page._owner_labels[case_file.id]
    assert "租約" in page._owner_labels[lease_file.id]
    assert lease.lease_name in page._owner_labels[lease_file.id]
    page._owner_kind.setCurrentIndex(page._owner_kind.findData("lease"))
    assert not page._eng_combo.isEnabled()
    assert [row.id for row in page._attachments] == [lease_file.id]


def test_manual_reconciliation_exact_request_is_read_only(page, container, records):
    _, case, request, _, file, _ = records
    _select(page, file)
    before = [tuple(row) for row in container.conn.execute("SELECT * FROM document_request_items ORDER BY id")]
    targets = []
    page.navigate_requested.connect(targets.append)
    page._manual_btn.click()
    assert len(targets) == 1
    assert targets[0].page_id == PAGE_ENGAGEMENTS
    assert targets[0].engagement_id == case.id
    assert targets[0].request_id == request.id
    assert before == [tuple(row) for row in container.conn.execute("SELECT * FROM document_request_items ORDER BY id")]


def test_receipt_facts_show_deadline_missing_and_next_step(page, records):
    _select(page, records[4])
    assert "2026-10-12" in page._facts_label.text()
    assert "全案缺件 2" in page._facts_label.text()
    assert page._manual_btn.text() == "開啟索件核對"
    assert page._help_text.isHidden()
    page._help_btn.click()
    assert not page._help_text.isHidden()
    assert "尚未連結到個別索件項目" in page._help_text.text()


def test_no_batch_does_not_borrow_case_deadline(page, container, records, tmp_path):
    source = tmp_path / "無批次.txt"
    source.write_text("合成附件")
    file = container.attachments.upload_attachment(UploadAttachmentInput(engagement_id=records[1].id, request_id=None, source_path=source))
    page.refresh_context()
    _select(page, file)
    assert "索件期限 未設定" in page._facts_label.text()
    assert "2026-11-15" not in page._facts_label.text()
    targets = []
    page.navigate_requested.connect(targets.append)
    page._manual_btn.click()
    assert targets[0].request_id is None
    assert targets[0].engagement_id == records[1].id


def test_lease_preview_and_original_editor_keep_owner_and_cancel(page, records, container, monkeypatch):
    client, _, _, lease, _, file = records
    _select(page, file)
    assert "租約迄日：2027-12-31" in page._facts_label.text()
    assert page._manual_btn.text() == "管理此客戶租約"
    observed = []
    before = [tuple(row) for row in container.conn.execute("SELECT * FROM client_leases ORDER BY id")]
    def cancel(dialog):
        observed.append((dialog.windowTitle(), dialog.leases_editor._entries[dialog.leases_editor.table.currentRow()].lease_id))
        dialog.reject()
        return 0
    monkeypatch.setattr("taxops.ui.pages.attachments_page.EditClientDialog.exec", cancel)
    page._manual_btn.click()
    assert observed == [(f"租約管理：{client.client_name} / {lease.lease_name}", lease.id)]
    assert before == [tuple(row) for row in container.conn.execute("SELECT * FROM client_leases ORDER BY id")]


def test_case_accept_does_not_complete_request_items(page, container, records):
    _select(page, records[4])
    before = [tuple(row) for row in container.conn.execute("SELECT * FROM document_request_items ORDER BY id")]
    page._accept_btn.click()
    assert container.attachments.get(records[4].id).status == "accepted"
    assert before == [tuple(row) for row in container.conn.execute("SELECT * FROM document_request_items ORDER BY id")]
    assert "索件項目需另行人工確認" in page._feedback.text()


@pytest.mark.parametrize("field", ["engagement_id", "request_id", "client_id", "lease_id"])
def test_changed_attachment_ownership_blocks_stale_action(page, container, records, monkeypatch, field):
    file = records[4]
    _select(page, file)
    monkeypatch.setattr(container.attachments, "get", lambda _: replace(file, **{field: 9999}))
    warnings, targets = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    page.navigate_requested.connect(targets.append)
    page._manual_btn.click()
    assert not targets
    assert warnings and "歸屬已變更" in warnings[0]


def test_deleted_case_scope_never_broadens_to_other_owners(page, container, records):
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(records[1].id))
    container.engagements.delete_engagement(records[1].id)
    page.refresh_context()
    assert page._eng_combo.currentData() == records[1].id
    assert page._table.rowCount() == 0
    assert not page._error_label.isHidden()
    assert page._empty_state.isHidden()


def test_lease_upload_cancel_has_no_effect(page, container, records, monkeypatch):
    _select(page, records[5])
    before = list(container.attachments.list_all())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    page._upload_btn.click()
    assert container.attachments.list_all() == before


def test_lease_upload_uses_lease_service_without_case(page, container, records, tmp_path, monkeypatch):
    _select(page, records[5])
    source = tmp_path / "追加租約.txt"
    source.write_text("合成附件")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    page._upload_btn.click()
    rows = container.attachments.list_by_lease(records[3].id)
    assert len(rows) == 2
    assert all(row.engagement_id is None and row.client_id == records[0].id for row in rows)


def test_single_primary_changes_with_selection(page, records):
    def primaries():
        return [b for b in page.findChildren(QPushButton) if b.property("role") == "primary"]
    assert primaries() == [page._upload_btn]
    _select(page, records[4])
    assert primaries() == [page._manual_btn]
    page._table.clearSelection()
    assert primaries() == [page._upload_btn]


def test_read_failure_shows_error_and_clears_old_rows(page, container, monkeypatch):
    monkeypatch.setattr(container.attachments, "list_all", lambda: (_ for _ in ()).throw(RuntimeError("read failed")))
    page.refresh_context()
    assert page._table.rowCount() == 0
    assert not page._error_label.isHidden()
    assert page._empty_state.isHidden()
    assert page._selected_attachment() is None


def test_literal_customer_filename_and_facts(page, records):
    _select(page, records[4])
    assert page._inspector.title_label.textFormat() == Qt.TextFormat.PlainText
    assert page._inspector.subtitle_label.textFormat() == Qt.TextFormat.PlainText
    assert page._facts_label.textFormat() == Qt.TextFormat.PlainText


@pytest.mark.parametrize("size", [(1366, 768), (1093, 614), (900, 540)])
def test_compact_geometry_keeps_summary_and_actions(qapp, page, records, size):
    old = qapp.styleSheet()
    try:
        apply_style(qapp)
        _select(page, records[4])
        page.resize(*size)
        qapp.processEvents()
        assert page.width() == size[0]
        assert page._today_btn.text() == page._today_panel.compact_summary
        assert page._today_btn.isVisible()
        assert page._today_panel.isVisible() == (size[0] >= 1180)
        if size[0] < 1000:
            page._preview_btn.click()
            qapp.processEvents()
        assert page._manual_btn.isVisible()
        for button in (page._today_btn, page._upload_btn, page._manual_btn, page._accept_btn, page._reject_btn):
            assert page.rect().contains(button.mapTo(page, button.rect().center()))
        assert page._preview_stack.height() > 50
    finally:
        qapp.setStyleSheet(old)


def test_local_pages_and_exact_attachment_ignore_old_filters(page, records):
    page._page_size = 1
    page._search.setText("no match")
    page._status_tabs.setCurrentIndex(1)
    page.open_context(engagement_id=records[1].id, attachment_id=records[4].id)
    assert page._selected_attachment().id == records[4].id
    assert page._search.text() == ""
    assert page._table.rowCount() == 1


@pytest.mark.parametrize("record_index", [4, 5])
def test_archived_selected_case_or_lease_file_blocks_manual_review(page, container, records, monkeypatch, record_index):
    file = records[record_index]
    _select(page, file)
    container.attachments.delete_attachment(file.id)
    warnings, targets, editors = [], [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(page, "_open_lease_owner", lambda row: editors.append(row.id))
    page.navigate_requested.connect(targets.append)
    page._manual_btn.click()
    assert not targets and not editors
    assert warnings and "附件已失效" in warnings[0]
