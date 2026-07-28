"""Real widget paths for the document-request item drill-down.

These tests deliberately drive the page buttons and the real dialog widgets.
Modal execution is replaced only to keep the offscreen run non-blocking; the
replacement still fills the production dialog and clicks its production OK
button, so no test double writes to the service directly.
"""

from __future__ import annotations

import json
import os

import pytest
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def request_with_item(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.services.engagements import CreateEngagementInput

    client = container.clients.create_client(
        CreateClientInput(client_code="DOC-REAL-001", client_name="真實路徑客戶")
    )
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="營業稅申報",
            tax_type="vat",
            period_name="2026-05",
        )
    )
    request, items = container.doc_requests.create_request(
        CreateDocumentRequestInput(
            engagement_id=engagement.id,
            tax_type="vat",
            period_name="2026-05",
            request_name="五月份憑證索取",
            item_names=("原始發票",),
        )
    )
    return request, items[0]


def _accept_template_with_custom_item(dialog, item_name: str) -> int:
    """Drive the production template dialog without writing through a fake."""
    dialog._select_none_btn.click()
    dialog._custom_input.setText(item_name)
    add_button = next(
        button for button in dialog.findChildren(QPushButton)
        if button.text() == "加入"
    )
    add_button.click()
    button_box = dialog.findChild(QDialogButtonBox)
    assert button_box is not None
    accept_button = next(
        button for button in button_box.buttons() if button.text() == "確定"
    )
    accept_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    return dialog.result()


@pytest.mark.usefixtures("qapp")
def test_document_requests_page_context_banner_stylesheet_parses_without_qt_warning(
    container,
):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    messages: list[str] = []
    previous = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        page = DocumentRequestsPage(container)
        page._context_banner.ensurePolished()
    finally:
        qInstallMessageHandler(previous)

    assert not [
        message
        for message in messages
        if "Could not parse stylesheet" in message
        and "DocRequestsContextBanner" in message
    ]


@pytest.mark.usefixtures("qapp")
def test_new_request_button_drives_real_template_fields_sqlite_and_audit(
    monkeypatch, qapp, container
):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    client = container.clients.create_client(
        CreateClientInput(client_code="DOC-NEW-001", client_name="新索件客戶")
    )
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="營業稅申報",
            tax_type="vat",
            period_name="2026-06",
        )
    )
    page = DocumentRequestsPage(container)
    page.refresh_context()
    page.load_engagement(engagement.id)
    page.show()
    qapp.processEvents()

    monkeypatch.setattr(
        DocumentItemTemplateDialog,
        "exec",
        lambda dialog: _accept_template_with_custom_item(dialog, "海關進口報單"),
    )

    assert page._new_req_btn.isVisible()
    assert page._new_req_btn.isEnabled()
    page._new_req_btn.click()

    row = container.conn.execute(
        "SELECT id, request_name, tax_type, period_name, status "
        "FROM document_requests WHERE engagement_id = ?",
        (engagement.id,),
    ).fetchone()
    assert tuple(row[1:]) == (
        "2026-06 vat request",
        "vat",
        "2026-06",
        "not_requested",
    )
    item_names = [
        item[0]
        for item in container.conn.execute(
            "SELECT item_name FROM document_request_items WHERE request_id = ? ORDER BY id",
            (row[0],),
        ).fetchall()
    ]
    assert item_names == ["海關進口報單"]
    actions = [
        audit[0]
        for audit in container.conn.execute(
            "SELECT action FROM audit_logs WHERE target_id = ? ORDER BY id", (row[0],)
        ).fetchall()
    ]
    assert "doc_request.create" in actions


@pytest.mark.usefixtures("qapp")
def test_items_only_add_button_uses_real_dialog_and_refreshes_exact_table(
    monkeypatch, container, request_with_item
):
    from taxops.ui.dialogs.add_document_item_dialog import AddDocumentItemDialog
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage, _ITEM_COLUMNS

    request, _ = request_with_item
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(request.id)

    def complete_real_dialog(dialog: AddDocumentItemDialog):
        dialog._text_edit.setPlainText("銀行存摺\n進項折讓單")
        button_box = dialog.findChild(QDialogButtonBox)
        assert button_box is not None
        button_box.button(QDialogButtonBox.StandardButton.Ok).click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        return dialog.result()

    monkeypatch.setattr(AddDocumentItemDialog, "exec", complete_real_dialog)

    assert page._add_item_btn.isEnabled()
    page._add_item_btn.click()

    names = [
        page._item_table.item(row, _ITEM_COLUMNS.index("item_name")).text()
        for row in range(page._item_table.rowCount())
    ]
    assert names == ["原始發票", "銀行存摺", "進項折讓單"]
    db_names = [
        row[0]
        for row in container.conn.execute(
            "SELECT item_name FROM document_request_items "
            "WHERE request_id = ? ORDER BY id",
            (request.id,),
        ).fetchall()
    ]
    assert db_names == names
    audits = container.conn.execute(
        "SELECT action FROM audit_logs WHERE target_type = 'document_request_item' "
        "ORDER BY id DESC LIMIT 2"
    ).fetchall()
    assert [row[0] for row in audits] == [
        "doc_request_item.create",
        "doc_request_item.create",
    ]


@pytest.mark.usefixtures("qapp")
def test_items_only_real_buttons_edit_status_and_delete_exact_sqlite_rows(
    monkeypatch, qapp, container, request_with_item
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.i18n.status_labels import status_to_label
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage, _ITEM_COLUMNS

    request, item = request_with_item
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(request.id)
    page.show()
    qapp.processEvents()
    page._item_table.selectRow(0)
    qapp.processEvents()

    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getText",
        lambda *args, **kwargs: ("已核對原始發票", True),
    )
    assert page._edit_item_btn.isVisible() and page._edit_item_btn.isEnabled()
    page._edit_item_btn.click()
    edited = container.conn.execute(
        "SELECT item_name, item_status FROM document_request_items WHERE id = ?",
        (item.id,),
    ).fetchone()
    assert tuple(edited) == ("已核對原始發票", "missing")
    assert page._item_table.item(0, _ITEM_COLUMNS.index("item_name")).text() == "已核對原始發票"

    page._item_table.selectRow(0)
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        lambda *args, **kwargs: (status_to_label("received"), True),
    )
    assert page._item_status_btn.isVisible() and page._item_status_btn.isEnabled()
    page._item_status_btn.click()
    status = container.conn.execute(
        "SELECT item_status FROM document_request_items WHERE id = ?", (item.id,)
    ).fetchone()[0]
    assert status == "received"
    assert page._item_table.item(0, _ITEM_COLUMNS.index("item_status")).text() == status_to_label("received")

    page._item_table.selectRow(0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    assert page._delete_item_btn.isVisible() and page._delete_item_btn.isEnabled()
    page._delete_item_btn.click()
    assert container.conn.execute(
        "SELECT COUNT(*) FROM document_request_items WHERE id = ?", (item.id,)
    ).fetchone()[0] == 0
    assert page._item_table.rowCount() == 0

    actions = [
        row[0]
        for row in container.conn.execute(
            "SELECT action FROM audit_logs WHERE target_type = 'document_request_item' "
            "AND target_id = ? ORDER BY id",
            (item.id,),
        ).fetchall()
    ]
    assert actions[-3:] == [
        "doc_request_item.update",
        "doc_request_item.status_change",
        "doc_request_item.delete",
    ]


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    ("failure_kind", "expected_title"),
    [("validation", "新增失敗"), ("unexpected", "新增失敗")],
)
def test_new_request_real_dialog_failure_is_visible_and_writes_no_request(
    monkeypatch, container, failure_kind, expected_title
):
    from taxops.services.clients import CreateClientInput
    from taxops.services.document_requests import DocumentRequestValidationError
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.document_item_template_dialog import DocumentItemTemplateDialog
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    client = container.clients.create_client(
        CreateClientInput(client_code=f"DOC-ERR-{failure_kind}", client_name="錯誤提示客戶")
    )
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="錯誤提示案件",
            tax_type="vat",
            period_name="2026-07",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(engagement.id)
    monkeypatch.setattr(
        DocumentItemTemplateDialog,
        "exec",
        lambda dialog: _accept_template_with_custom_item(dialog, "錯誤分支文件"),
    )
    if failure_kind == "validation":
        error = DocumentRequestValidationError("doc_request.items_required")
    else:
        error = RuntimeError("database is unavailable")
    monkeypatch.setattr(
        container.doc_requests,
        "create_request",
        lambda payload: (_ for _ in ()).throw(error),
    )
    visible_messages = []
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QMessageBox.warning",
        lambda parent, title, message: visible_messages.append((title, message)),
    )

    page._new_req_btn.click()

    assert len(visible_messages) == 1
    assert visible_messages[0][0] == expected_title
    assert visible_messages[0][1]
    assert container.conn.execute(
        "SELECT COUNT(*) FROM document_requests WHERE engagement_id = ?",
        (engagement.id,),
    ).fetchone()[0] == 0


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    ("button_attr", "service_method", "dialog_kind"),
    [
        ("_edit_req_btn", "update_request", "text"),
        ("_mark_requested_btn", "mark_requested", None),
        ("_request_status_btn", "set_request_status", "status"),
        ("_follow_up_btn", "add_follow_up", None),
        ("_delete_req_btn", "delete_request", "confirm"),
    ],
)
@pytest.mark.parametrize("failure_kind", ["validation", "unexpected"])
def test_request_action_unexpected_failures_from_real_buttons_are_visible(
    monkeypatch,
    container,
    request_with_item,
    button_attr,
    service_method,
    dialog_kind,
    failure_kind,
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.document_requests import DocumentRequestValidationError
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _ = request_with_item
    page = DocumentRequestsPage(container)
    page.load_engagement(request.engagement_id)
    page._req_table.selectRow(0)
    if dialog_kind == "text":
        monkeypatch.setattr(
            "taxops.ui.pages.document_requests_page.QInputDialog.getText",
            lambda *args, **kwargs: ("不會寫入的名稱", True),
        )
    elif dialog_kind == "status":
        monkeypatch.setattr(
            "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
            lambda *args, **kwargs: (status_to_label("requested"), True),
        )
    elif dialog_kind == "confirm":
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
    failure = (
        DocumentRequestValidationError("doc_request.not_found")
        if failure_kind == "validation"
        else RuntimeError("sqlite busy")
    )
    monkeypatch.setattr(
        container.doc_requests,
        service_method,
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    visible_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: visible_messages.append((title, message)),
    )

    button = getattr(page, button_attr)
    assert button.isEnabled()
    button.click()

    assert len(visible_messages) == 1
    assert all(visible_messages[0])
    row = container.conn.execute(
        "SELECT request_name, status, follow_up_count, deleted_at "
        "FROM document_requests WHERE id = ?",
        (request.id,),
    ).fetchone()
    assert tuple(row) == ("五月份憑證索取", "not_requested", 0, None)


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    ("button_attr", "service_method", "dialog_kind"),
    [
        ("_edit_item_btn", "update_item", "text"),
        ("_item_status_btn", "set_item_status", "status"),
        ("_delete_item_btn", "delete_item", "confirm"),
        ("_bulk_delete_items_btn", "delete_items_bulk", "confirm"),
    ],
)
@pytest.mark.parametrize("failure_kind", ["validation", "unexpected"])
def test_item_action_unexpected_failures_from_real_buttons_are_visible(
    monkeypatch,
    container,
    request_with_item,
    button_attr,
    service_method,
    dialog_kind,
    failure_kind,
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.document_requests import DocumentRequestValidationError
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, item = request_with_item
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(request.id)
    page._item_table.selectRow(0)
    if dialog_kind == "text":
        monkeypatch.setattr(
            "taxops.ui.pages.document_requests_page.QInputDialog.getText",
            lambda *args, **kwargs: ("不會寫入的項目", True),
        )
    elif dialog_kind == "status":
        monkeypatch.setattr(
            "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
            lambda *args, **kwargs: (status_to_label("received"), True),
        )
    else:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
    failure = (
        DocumentRequestValidationError("doc_request_item.not_found")
        if failure_kind == "validation"
        else RuntimeError("sqlite busy")
    )
    monkeypatch.setattr(
        container.doc_requests,
        service_method,
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    visible_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: visible_messages.append((title, message)),
    )

    button = getattr(page, button_attr)
    assert button.isEnabled()
    button.click()

    assert len(visible_messages) == 1
    assert all(visible_messages[0])
    row = container.conn.execute(
        "SELECT item_name, item_status FROM document_request_items WHERE id = ?",
        (item.id,),
    ).fetchone()
    assert tuple(row) == ("原始發票", "missing")


@pytest.mark.usefixtures("qapp")
def test_snapshot_validation_failure_is_visible_and_refreshes_stale_request(
    monkeypatch, container, request_with_item
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.document_requests import (
        DocumentRequestValidationError,
    )
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _item = request_with_item
    page = DocumentRequestsPage(container)
    assert page.load_engagement(request.engagement_id)
    page._req_table.selectRow(0)
    warnings = []
    refreshes = 0
    real_refresh = page._refresh_requests

    def counted_refresh():
        nonlocal refreshes
        refreshes += 1
        return real_refresh()

    monkeypatch.setattr(
        container.doc_requests,
        "read_request_snapshot",
        lambda _request_id: (_ for _ in ()).throw(
            DocumentRequestValidationError("doc_request.not_found")
        ),
    )
    monkeypatch.setattr(page, "_refresh_requests", counted_refresh)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append(
            (title, message)
        ),
    )

    page._follow_up_btn.click()

    assert warnings == [
        (
            "無法讀取索件資料",
            "找不到指定索件批次，可能已被刪除",
        )
    ]
    assert refreshes == 1
    assert (
        container.doc_requests.get_request(request.id).follow_up_count
        == 0
    )


@pytest.mark.usefixtures("qapp")
def test_snapshot_operational_failure_logs_root_cause_and_does_not_claim_not_found(
    monkeypatch, container, request_with_item
):
    import sqlite3

    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, item = request_with_item
    page = DocumentRequestsPage(
        container, embedded=True, view_mode="items_only"
    )
    assert page.load_request_items(request.id)
    page._item_table.selectRow(0)
    warnings = []
    monkeypatch.setattr(
        container.doc_requests,
        "read_request_snapshot",
        lambda _request_id: (_ for _ in ()).throw(
            sqlite3.OperationalError("database is locked")
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append(
            (title, message)
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    page._on_delete_item()

    assert warnings == [
        (
            "無法讀取索件資料",
            "索件資料讀取失敗，尚未進行任何變更，請重新整理後再試",
        )
    ]
    row = container.conn.execute(
        "SELECT item_name, item_status FROM document_request_items"
        " WHERE id = ?",
        (item.id,),
    ).fetchone()
    assert tuple(row) == ("原始發票", "missing")
    log_row = container.conn.execute(
        "SELECT message, detail_json FROM system_logs"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert log_row["message"] == "document request snapshot failed"
    detail = json.loads(log_row["detail_json"])
    assert detail["operation"] == "item.delete"
    assert detail["request_id"] == request.id
    assert detail["item_id"] == item.id
    assert detail["exc_type"] == "OperationalError"
    assert "database is locked" in detail["traceback"]


@pytest.mark.usefixtures("qapp")
def test_items_only_reload_clamps_page_after_last_page_shrinks(
    container
):
    from taxops.services.clients import CreateClientInput
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    client = container.clients.create_client(
        CreateClientInput(
            client_code="C-PAGE-CLAMP",
            client_name="分頁回夾測試客戶",
        )
    )
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="115 年度分頁案件",
            tax_type="cit",
            period_name="115",
        )
    )
    request, items = container.doc_requests.create_request(
        CreateDocumentRequestInput(
            engagement_id=engagement.id,
            tax_type="cit",
            period_name="115",
            request_name="跨頁縮減索件",
            item_names=tuple(
                f"文件項目 {index:02d}" for index in range(51)
            ),
        )
    )
    page = DocumentRequestsPage(
        container, embedded=True, view_mode="items_only"
    )
    assert page.load_request_items(request.id)
    page._item_next_btn.click()
    assert page.item_ids() == (items[-1].id,)
    assert page._item_page == 1

    container.doc_requests.delete_item(items[-1].id)
    assert page.load_request_items(request.id)

    assert page._item_page == 0
    assert page.item_ids() == tuple(item.id for item in items[:-1])
    assert "第 1 / 1 頁，共 50 筆" == page._item_page_label.text()


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("outcome", ["validation", "unexpected", "empty"])
def test_export_button_surfaces_exact_terminal_outcome(
    monkeypatch, tmp_path, container, outcome
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.export import ExportValidationError
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    page = DocumentRequestsPage(container)
    destination = tmp_path / "缺件清單.xlsx"
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Excel"),
    )
    if outcome == "validation":
        result = ExportValidationError("export.query_failed")
    elif outcome == "unexpected":
        result = RuntimeError("disk unavailable")
    else:
        result = 0

    def export(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(container.export, "export_missing_items_xlsx", export)
    terminal_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: terminal_messages.append(("critical", title, message)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, message: terminal_messages.append(("information", title, message)),
    )

    page._export_btn.click()

    assert len(terminal_messages) == 1
    expected_kind = "information" if outcome == "empty" else "critical"
    assert terminal_messages[0][0] == expected_kind
    assert terminal_messages[0][1]
    assert terminal_messages[0][2]


@pytest.mark.usefixtures("qapp")
def test_global_request_load_failure_is_visible_and_logged(monkeypatch, container):
    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    monkeypatch.setattr(
        container.doc_requests,
        "list_all",
        lambda: (_ for _ in ()).throw(RuntimeError("corrupt request index")),
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    page = DocumentRequestsPage(container)
    page.refresh_context()

    assert page._req_table.rowCount() == 0
    assert len(warnings) == 1 and all(warnings[0])
    log = container.conn.execute(
        "SELECT level, message FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(log) == ("ERROR", "doc_requests.list_all failed")


@pytest.mark.usefixtures("qapp")
def test_engagement_request_load_failure_is_visible_and_logged(
    monkeypatch, container, request_with_item
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _ = request_with_item
    page = DocumentRequestsPage(container)
    page.load_engagement(request.engagement_id)
    assert page._req_table.rowCount() == 1
    monkeypatch.setattr(
        container.doc_requests,
        "list_by_engagement",
        lambda engagement_id: (_ for _ in ()).throw(RuntimeError("sqlite locked")),
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    page.load_engagement(request.engagement_id)

    assert page._req_table.rowCount() == 1
    assert len(warnings) == 1 and all(warnings[0])
    log = container.conn.execute(
        "SELECT level, message FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(log) == ("ERROR", "doc_requests.list failed")


@pytest.mark.usefixtures("qapp")
def test_items_only_load_failure_clears_stale_rows_and_logs(
    monkeypatch, container, request_with_item
):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _ = request_with_item
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(request.id)
    assert page._item_table.rowCount() == 1
    monkeypatch.setattr(
        container.doc_requests,
        "list_items",
        lambda request_id: (_ for _ in ()).throw(RuntimeError("corrupt item index")),
    )

    page.load_request_items(request.id)

    assert page._item_table.rowCount() == 0
    log = container.conn.execute(
        "SELECT level, message FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(log) == ("ERROR", "doc_request_items.list failed")


@pytest.mark.usefixtures("qapp")
def test_request_buttons_cancel_real_modal_paths_without_mutation(
    monkeypatch, container, request_with_item
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.dialogs.document_item_template_dialog import DocumentItemTemplateDialog
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _ = request_with_item
    page = DocumentRequestsPage(container)
    page.load_engagement(request.engagement_id)
    page._req_table.selectRow(0)

    def reject_real_template(dialog: DocumentItemTemplateDialog):
        box = dialog.findChild(QDialogButtonBox)
        assert box is not None
        next(button for button in box.buttons() if button.text() == "取消").click()
        return dialog.result()

    monkeypatch.setattr(DocumentItemTemplateDialog, "exec", reject_real_template)
    page._new_req_btn.click()

    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getText",
        lambda *args, **kwargs: ("不採用", False),
    )
    page._edit_req_btn.click()
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        lambda *args, **kwargs: ("", False),
    )
    page._request_status_btn.click()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    page._delete_req_btn.click()

    row = container.conn.execute(
        "SELECT request_name, status, deleted_at FROM document_requests WHERE id = ?",
        (request.id,),
    ).fetchone()
    assert tuple(row) == ("五月份憑證索取", "not_requested", None)


@pytest.mark.usefixtures("qapp")
def test_item_buttons_cancel_modal_paths_without_mutation(
    monkeypatch, container, request_with_item
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, item = request_with_item
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(request.id)
    page._item_table.selectRow(0)
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getText",
        lambda *args, **kwargs: ("", True),
    )
    page._edit_item_btn.click()
    monkeypatch.setattr(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        lambda *args, **kwargs: ("", False),
    )
    page._item_status_btn.click()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    page._delete_item_btn.click()

    row = container.conn.execute(
        "SELECT item_name, item_status FROM document_request_items WHERE id = ?",
        (item.id,),
    ).fetchone()
    assert tuple(row) == ("原始發票", "missing")


@pytest.mark.usefixtures("qapp")
def test_generate_button_constructs_real_dialog_and_user_can_cancel(
    monkeypatch, container, request_with_item
):
    from taxops.ui.dialogs.generate_message_dialog import GenerateMessageDialog
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    request, _ = request_with_item
    page = DocumentRequestsPage(container)
    page.load_engagement(request.engagement_id)
    page._req_table.selectRow(0)
    seen_request_ids = []

    def cancel_real_dialog(dialog: GenerateMessageDialog):
        seen_request_ids.append(dialog._request_id)
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(GenerateMessageDialog, "exec", cancel_real_dialog)

    assert page._generate_btn.isEnabled()
    page._generate_btn.click()

    assert seen_request_ids == [request.id]
