"""Slice 9 UI smoke tests: AttachmentsPage and action registry contracts."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from taxops.core.paths import resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.attachments import AttachmentsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.system_logs import SystemLogRepository
from taxops.services.attachments import AttachmentsService, UploadAttachmentInput
from taxops.services.audit import AuditService
from taxops.services.engagements import EngagementsService
from taxops.services.system_log import SystemLogService
from PySide6.QtCore import Qt

from taxops.repositories.attachments import AttachmentRow
from taxops.ui.action_registry import PAGE_ATTACHMENTS, actions_for_page
from taxops.ui.pages.attachments_page import _AttachmentInfoDialog, AttachmentsPage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeContainer:
    def __init__(self, conn, attachments_dir: Path):
        self.paths = SimpleNamespace(attachments_dir=attachments_dir)
        audit_repo = AuditLogRepository(conn)
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.system_log = SystemLogService(SystemLogRepository(conn))
        self.engagements = EngagementsService(EngagementsRepository(conn), self._audit)
        attachments_repo = AttachmentsRepository(conn)
        self.attachments = AttachmentsService(
            repo=attachments_repo,
            attachments_dir=attachments_dir,
            audit=self._audit,
        )


def _make_conn(tmp_path: Path):
    paths = resolve_paths(override_root=tmp_path / "data")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return conn, paths.attachments_dir


def _seed(conn) -> int:
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) "
        "VALUES ('C001', '測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO engagements (client_id, engagement_name, tax_type, period_name, "
        "status, created_at, updated_at) "
        "VALUES (?, '測試案件', 'vat', '202501', 'draft', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (client_id,),
    )
    eng_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return eng_id


# ── render ─────────────────────────────────────────────────────────────────────

def test_attachments_page_renders(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert page is not None
    conn.close()


def test_attachments_page_has_six_columns(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert page._table.columnCount() == 6
    conn.close()


def test_attachments_page_empty_initially(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert page._table.rowCount() == 0
    conn.close()


# ── button state ───────────────────────────────────────────────────────────────

def test_upload_button_always_enabled(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert page._upload_btn.isEnabled()
    conn.close()


def test_action_buttons_disabled_without_selection(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert not page._accept_btn.isEnabled()
    assert not page._reject_btn.isEnabled()
    assert not page._delete_btn.isEnabled()
    assert not page._info_btn.isEnabled()
    conn.close()


def test_open_button_always_disabled(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert not page._open_btn.isEnabled()
    conn.close()


# ── data load ──────────────────────────────────────────────────────────────────

def test_page_loads_with_data(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"PDF content")
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(1)
    page._load_attachments()
    assert page._table.rowCount() == 1
    conn.close()


# ── upload persists ────────────────────────────────────────────────────────────

def test_upload_persists_to_db_and_creates_version(tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "invoice.pdf"
    src.write_bytes(b"invoice data")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    # DB record exists
    db_row = conn.execute(
        "SELECT * FROM attachments WHERE id = ?", (row.id,)
    ).fetchone()
    assert db_row is not None
    assert db_row["status"] == "uploaded"
    # version record exists
    versions = conn.execute(
        "SELECT * FROM attachment_versions WHERE attachment_id = ?", (row.id,)
    ).fetchall()
    assert len(versions) == 1
    assert versions[0]["supersedes_id"] is None
    conn.close()


# ── accept persists ────────────────────────────────────────────────────────────

def test_accept_persists_to_db_and_audits(tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "report.pdf"
    src.write_bytes(b"report")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    updated = container.attachments.accept_attachment(row.id)
    assert updated.status == "accepted"
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.accept' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None
    conn.close()


# ── action registry contracts ──────────────────────────────────────────────────

def test_attachments_page_contracts_enabled():
    contracts = actions_for_page(PAGE_ATTACHMENTS)
    enabled = [c for c in contracts if c.enabled]
    labels = {c.button_label for c in enabled}
    assert "新增附件" in labels
    assert "標記已驗收" in labels
    assert "標記退回" in labels


def test_attachments_page_contracts_have_audit_action():
    for contract in actions_for_page(PAGE_ATTACHMENTS):
        if contract.enabled and contract.button_label in ("新增附件", "標記已驗收", "標記退回"):
            assert contract.audit_action is not None, (
                f"{contract.button_label} must declare audit_action"
            )


def test_attachments_page_contracts_have_service_and_repo():
    for contract in actions_for_page(PAGE_ATTACHMENTS):
        if contract.enabled and contract.button_label in ("新增附件", "標記已驗收", "標記退回"):
            assert contract.service is not None
            assert contract.repository is not None


# ── info dialog plain-text safety ─────────────────────────────────────────────

def test_info_dialog_labels_plain_text(qapp):
    att = AttachmentRow(
        id=1,
        engagement_id=1,
        request_id=None,
        original_filename="<img src=x onerror=alert(1)>.pdf",
        stored_filename="2026/05/abc.pdf",
        file_hash_sha256="a" * 64,
        file_size=1024,
        mime_type="application/pdf",
        extension=".pdf",
        uploaded_by="local_user",
        uploaded_at="2026-05-17T00:00:00",
        source="manual",
        status="uploaded",
        notes="<script>alert(1)</script>",
        accepted_by=None,
        accepted_at=None,
    )
    dlg = _AttachmentInfoDialog(att)
    from PySide6.QtWidgets import QFormLayout, QLabel
    form = dlg.layout()
    assert isinstance(form, QFormLayout)
    for i in range(form.rowCount()):
        item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
        if item is not None:
            widget = item.widget()
            if isinstance(widget, QLabel):
                assert widget.textFormat() == Qt.TextFormat.PlainText, (
                    f"Row {i} label must use PlainText format"
                )


def test_delete_button_archives_row_and_audits(qapp, tmp_path):
    from unittest.mock import patch

    from PySide6.QtWidgets import QMessageBox

    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "delete_me.pdf"
    src.write_bytes(b"delete me")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(1)
    page._load_attachments()
    page._table.selectRow(0)

    with patch(
        "taxops.ui.pages.attachments_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        page._on_delete()

    db_row = conn.execute("SELECT status FROM attachments WHERE id = ?", (row.id,)).fetchone()
    assert db_row is not None
    assert db_row["status"] == "archived"
    assert page._table.rowCount() == 0
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.delete' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None
    conn.close()


def test_attachment_delete_contract_is_registered():
    delete = [
        c for c in actions_for_page(PAGE_ATTACHMENTS)
        if c.button_label == "刪除附件"
    ]
    assert len(delete) == 1
    assert delete[0].service == "AttachmentsService.delete_attachment"
    assert delete[0].audit_action == "attachment.delete"
