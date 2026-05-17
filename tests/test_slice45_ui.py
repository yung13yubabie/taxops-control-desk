"""Slice 4.5 UI handler integration tests: engagement edit + item status."""

from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fresh_container():
    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "TestSlice45")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


def _seed_client(container):
    cur = container.conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("S45001", "Slice45測試公司"),
    )
    container.conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# EditEngagementDialog — instantiation and pre-fill
# ---------------------------------------------------------------------------


def test_edit_engagement_dialog_instantiates_with_prefilled_fields() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="預填測試",
            tax_type="cit",
            period_name="2024",
            owner="王大明",
        )
    )
    dlg = EditEngagementDialog(container.engagements, eng)
    assert dlg._name.text() == "預填測試"
    assert dlg._tax_type.currentData() == "cit"
    assert dlg._period.text() == "2024"
    assert dlg._owner.text() == "王大明"
    container.close()


def test_edit_engagement_dialog_on_save_updates_db_and_audit() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="舊名稱",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    dlg = EditEngagementDialog(container.engagements, eng)
    dlg._name.setText("新名稱")
    dlg._owner.setText("李小花")
    dlg.on_save()

    row = container.conn.execute(
        "SELECT engagement_name, owner FROM engagements WHERE id = ?", (eng.id,)
    ).fetchone()
    assert row is not None
    assert row[0] == "新名稱", "engagement_name must be updated"
    assert row[1] == "李小花", "owner must be updated"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.update'"
    ).fetchone()
    assert audit is not None, "audit_logs must have engagement.update entry"
    container.close()


def test_edit_engagement_dialog_has_required_buttons() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="按鈕測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    dlg = EditEngagementDialog(container.engagements, eng)
    btn_texts = {b.text() for b in dlg.findChildren(QPushButton)}
    assert "儲存編輯" in btn_texts
    assert "取消" in btn_texts
    container.close()


# ---------------------------------------------------------------------------
# EngagementsPage — edit button wiring
# ---------------------------------------------------------------------------


def test_engagements_page_has_edit_button() -> None:
    _make_app()
    container = _fresh_container()
    _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    btn_texts = {b.text() for b in page.findChildren(QPushButton)}
    assert "編輯案件" in btn_texts
    container.close()


def test_engagements_page_edit_btn_disabled_without_selection() -> None:
    _make_app()
    container = _fresh_container()
    _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    btn = next(b for b in page.findChildren(QPushButton) if b.text() == "編輯案件")
    assert not btn.isEnabled(), "編輯案件 must be disabled with no selection"
    container.close()


def test_engagements_page_edit_handler_updates_db_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog
    from taxops.ui.pages.engagements_page import EngagementsPage

    container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="編輯前名稱",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = EngagementsPage(container)
    page._table.selectRow(0)

    def patched_exec(self):
        self._name.setText("編輯後名稱")
        self.on_save()
        return EditEngagementDialog.DialogCode.Accepted

    with patch.object(EditEngagementDialog, "exec", patched_exec):
        page._on_edit_engagement()

    row = container.conn.execute(
        "SELECT engagement_name FROM engagements"
        " WHERE client_id = ? AND deleted_at IS NULL",
        (client_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "編輯後名稱", "engagement name must be updated via edit dialog"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.update'"
    ).fetchone()
    assert audit is not None, "audit_logs must have engagement.update entry"
    container.close()


# ---------------------------------------------------------------------------
# DocumentRequestsPage — item status switching
# ---------------------------------------------------------------------------


def test_document_requests_page_has_item_status_button() -> None:
    _make_app()
    container = _fresh_container()
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    page = DocumentRequestsPage(container)
    btn_texts = {b.text() for b in page.findChildren(QPushButton)}
    assert "切換項目狀態" in btn_texts
    container.close()


def test_document_requests_page_item_status_btn_disabled_before_item_selection() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="項目狀態測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()

    btn = next(
        b for b in page.findChildren(QPushButton) if b.text() == "切換項目狀態"
    )
    assert not btn.isEnabled(), "切換項目狀態 must be disabled before item row selected"
    container.close()


def test_document_requests_page_set_item_status_handler_updates_db_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="項目狀態切換測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()
    # Select the request row so item table loads
    page._req_table.selectRow(0)
    # Select the first item row
    page._item_table.selectRow(0)

    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=("已收到", True),
    ):
        page._on_set_item_status()

    item_row = container.conn.execute(
        "SELECT id FROM document_request_items"
        " WHERE request_id = (SELECT id FROM document_requests WHERE engagement_id = ?)"
        " LIMIT 1",
        (eng.id,),
    ).fetchone()
    assert item_row is not None

    status_row = container.conn.execute(
        "SELECT item_status FROM document_request_items WHERE id = ?", (item_row[0],)
    ).fetchone()
    assert status_row is not None
    assert status_row[0] == "received", "item_status must be updated to received"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request_item.status_change'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request_item.status_change entry"
    container.close()
