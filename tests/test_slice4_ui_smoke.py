"""Smoke tests for Slice 4 UI pages and dialogs."""

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
    paths = resolve_paths(override_root=tmp / "TestSlice4Smoke")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


def _seed_client(container):
    conn = container.conn
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("SMOKE001", "煙霧測試公司"),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# EngagementsPage
# ---------------------------------------------------------------------------


def test_engagements_page_instantiates() -> None:
    _make_app()
    container = _fresh_container()
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    assert page is not None
    container.close()


def test_engagements_page_has_required_buttons() -> None:
    _make_app()
    container = _fresh_container()
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    btn_texts = {btn.text() for btn in page.findChildren(QPushButton)}
    assert "新增案件" in btn_texts
    assert "切換狀態" in btn_texts
    assert "刪除案件" in btn_texts
    # Slice 21B: "管理索件批次" button removed — doc requests are now
    # embedded directly below the case list in the merged page.
    container.close()


def test_engagements_page_new_btn_enabled_when_client_present() -> None:
    _make_app()
    container = _fresh_container()
    _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    new_btn = next(
        b for b in page.findChildren(QPushButton) if b.text() == "新增案件"
    )
    # Default selection is "全部客戶"; select the specific client to enable the button
    page._client_combo.setCurrentIndex(1)
    assert new_btn.isEnabled(), "新增案件 must be enabled when a client exists"
    container.close()


def test_engagements_page_toolbar_disabled_with_no_selection() -> None:
    _make_app()
    container = _fresh_container()
    _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    for label in ("切換狀態", "刪除案件"):
        btn = next(
            (b for b in page.findChildren(QPushButton) if b.text() == label), None
        )
        assert btn is not None, f"button '{label}' not found"
        assert not btn.isEnabled(), f"'{label}' must be disabled with no row selected"
    container.close()


# ---------------------------------------------------------------------------
# NewEngagementDialog
# ---------------------------------------------------------------------------


def test_new_engagement_dialog_instantiates() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog

    dlg = NewEngagementDialog(container.engagements, client_id)
    assert dlg is not None
    container.close()


def test_new_engagement_dialog_has_required_fields() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QLabel
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog

    dlg = NewEngagementDialog(container.engagements, client_id)
    labels = {lbl.text() for lbl in dlg.findChildren(QLabel)}
    assert any("案件名稱" in t for t in labels), "dialog must have 案件名稱 field"
    assert any("稅種" in t for t in labels), "dialog must have 稅種 field"
    assert any("期間名稱" in t for t in labels), "dialog must have 期間名稱 field"
    container.close()


def test_new_engagement_dialog_has_save_button() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog

    dlg = NewEngagementDialog(container.engagements, client_id)
    btn_texts = {b.text() for b in dlg.findChildren(QPushButton)}
    assert "建立案件" in btn_texts
    assert "取消" in btn_texts
    container.close()


# ---------------------------------------------------------------------------
# DocumentRequestsPage
# ---------------------------------------------------------------------------


def test_document_requests_page_instantiates() -> None:
    _make_app()
    container = _fresh_container()
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    page = DocumentRequestsPage(container)
    assert page is not None
    container.close()


def test_document_requests_page_has_required_buttons() -> None:
    _make_app()
    container = _fresh_container()
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    page = DocumentRequestsPage(container)
    btn_texts = {b.text() for b in page.findChildren(QPushButton)}
    assert "新增索件批次" in btn_texts
    assert "標記已發出" in btn_texts
    assert "催件 +1" in btn_texts
    assert "刪除批次" in btn_texts
    assert "← 返回案件" in btn_texts
    container.close()


def test_document_requests_page_buttons_disabled_before_load() -> None:
    """Row-dependent buttons stay disabled before any request row is selected.

    Slice 20A change: 新增索件批次 is now always enabled because global mode
    opens an engagement picker; only row-dependent actions remain gated.
    """
    _make_app()
    container = _fresh_container()
    from PySide6.QtWidgets import QPushButton
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    page = DocumentRequestsPage(container)
    for label in ("標記已發出", "催件 +1", "刪除批次"):
        btn = next(
            (b for b in page.findChildren(QPushButton) if b.text() == label), None
        )
        assert btn is not None, f"button '{label}' not found"
        assert not btn.isEnabled(), (
            f"'{label}' must be disabled before a request row is selected"
        )
    container.close()


def test_document_requests_page_load_engagement_enables_new_btn() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QPushButton
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="Smoke 2024Q1",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)

    new_btn = next(
        b for b in page.findChildren(QPushButton) if b.text() == "新增索件批次"
    )
    assert new_btn.isEnabled(), "新增索件批次 must be enabled after load_engagement()"
    container.close()


# ---------------------------------------------------------------------------
# Handler integration tests — verify DB writes + audit trail
# ---------------------------------------------------------------------------


def test_new_engagement_dialog_on_save_creates_db_record_and_audit() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog

    dlg = NewEngagementDialog(container.engagements, client_id)
    dlg._name.setText("整合測試案件")
    dlg._period.setText("2024Q1")
    # _tax_type defaults to first item (vat)
    dlg.on_save()

    rows = container.conn.execute(
        "SELECT status FROM engagements WHERE client_id = ?", (client_id,)
    ).fetchall()
    assert len(rows) == 1, "one engagement should be created"
    assert rows[0][0] == "draft", "created engagement must be draft"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.create'"
    ).fetchone()
    assert audit is not None, "audit_logs must have engagement.create entry"
    container.close()


def test_document_requests_page_new_request_handler_creates_db_record() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="IndexTest 2024Q1",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()

    rows = container.conn.execute(
        "SELECT id FROM document_requests WHERE engagement_id = ?", (eng.id,)
    ).fetchall()
    assert len(rows) == 1, "one document_request should be created"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.create'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request.create entry"
    container.close()


def test_document_requests_page_mark_requested_handler_updates_status_and_audit() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="MarkTest 2024Q1",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()

    # Select the first row so _on_mark_requested sees a valid id
    page._req_table.selectRow(0)
    page._on_mark_requested()

    row = container.conn.execute(
        "SELECT status, requested_at FROM document_requests WHERE engagement_id = ?",
        (eng.id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "requested", "status must be 'requested' after mark_requested"
    assert row[1] is not None, "requested_at must be set"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.mark_requested'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request.mark_requested entry"
    container.close()


def test_engagements_page_set_status_handler_changes_status_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.engagements_page import EngagementsPage

    container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="狀態切換測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = EngagementsPage(container)
    page._table.selectRow(0)

    with patch(
        "taxops.ui.pages.engagements_page.QInputDialog.getItem",
        return_value=("待客戶確認", True),
    ):
        page._on_set_status()

    row = container.conn.execute(
        "SELECT status FROM engagements WHERE client_id = ? AND deleted_at IS NULL",
        (client_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "pending_acceptance", "status must change to pending_acceptance"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.status_change'"
    ).fetchone()
    assert audit is not None, "audit_logs must have engagement.status_change entry"
    container.close()


def test_engagements_page_delete_handler_soft_deletes_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.engagements_page import EngagementsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="刪除測試案件",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = EngagementsPage(container)
    page._table.selectRow(0)

    with patch(
        "taxops.ui.pages.engagements_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        page._on_delete()

    row = container.conn.execute(
        "SELECT deleted_at FROM engagements WHERE id = ?", (eng.id,)
    ).fetchone()
    assert row is not None
    assert row[0] is not None, "deleted_at must be set after soft-delete"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.delete'"
    ).fetchone()
    assert audit is not None, "audit_logs must have engagement.delete entry"
    container.close()


def test_document_requests_page_follow_up_handler_increments_count_and_audit() -> None:
    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="催件測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()
    page._req_table.selectRow(0)
    page._on_follow_up()

    row = container.conn.execute(
        "SELECT follow_up_count FROM document_requests WHERE engagement_id = ?",
        (eng.id,),
    ).fetchone()
    assert row is not None
    assert row[0] == 1, "follow_up_count must be 1 after one follow-up"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.follow_up'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request.follow_up entry"
    container.close()


def test_document_requests_page_delete_request_handler_soft_deletes_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="刪除索件測試",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()
    page._req_table.selectRow(0)

    with patch(
        "taxops.ui.pages.document_requests_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        page._on_delete_request()

    rows = container.conn.execute(
        "SELECT id FROM document_requests"
        " WHERE engagement_id = ? AND deleted_at IS NULL",
        (eng.id,),
    ).fetchall()
    assert len(rows) == 0, "document_request must be soft-deleted"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.delete'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request.delete entry"
    container.close()


def test_document_requests_page_set_progress_handler_updates_status_and_audit() -> None:
    from unittest.mock import patch

    _make_app()
    container = _fresh_container()
    client_id = _seed_client(container)
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.engagements import CreateEngagementInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="ProgressTest 2024Q1",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    page = DocumentRequestsPage(container)
    page.load_engagement(eng.id)
    page._on_new_request()
    page._req_table.selectRow(0)

    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=(status_to_label("pending_confirm"), True),
    ):
        page._on_set_request_status()

    row = container.conn.execute(
        "SELECT status FROM document_requests WHERE engagement_id = ?",
        (eng.id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "pending_confirm"

    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.status_change'"
    ).fetchone()
    assert audit is not None, "audit_logs must have doc_request.status_change entry"
    container.close()


def test_document_request_progress_contract_registered() -> None:
    from taxops.ui.action_registry import PAGE_DOC_REQUESTS, actions_for_page

    progress = [
        c for c in actions_for_page(PAGE_DOC_REQUESTS)
        if c.button_label == "設定進度"
    ]
    assert len(progress) == 1
    assert progress[0].service == "DocumentRequestsService.set_request_status"
    assert progress[0].audit_action == "doc_request.status_change"
