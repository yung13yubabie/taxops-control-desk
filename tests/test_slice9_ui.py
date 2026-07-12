"""Slice 9 UI smoke tests: AttachmentsPage and action registry contracts."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton

from taxops.core.paths import resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.i18n import error_message
from taxops.repositories.attachments import AttachmentsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.system_logs import SystemLogRepository
from taxops.services.attachments import (
    AttachmentValidationError,
    AttachmentsService,
    UploadAttachmentInput,
)
from taxops.services.audit import AuditService
from taxops.services.engagements import EngagementsService
from taxops.services.system_log import SystemLogService
from PySide6.QtCore import Qt, QUrl

from taxops.repositories.attachments import AttachmentRow
from taxops.ui.action_registry import PAGE_ATTACHMENTS, actions_for_page
from taxops.ui.pages.attachments_page import (
    QPdfDocument,
    _AttachmentInfoDialog,
    _PREVIEW_META,
    _PREVIEW_PDF,
    AttachmentsPage,
)


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
    assert not page._location_btn.isEnabled()
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


def test_image_preview_rejects_unsafe_dimensions_before_pixmap_decode(
    qapp, tmp_path, monkeypatch
):
    from taxops.security.image_guard import ImageGuardError

    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    source = tmp_path / "oversized.png"
    source.write_bytes(b"not decoded")
    attachment = SimpleNamespace(
        id=999,
        extension=".png",
        original_filename="oversized.png",
        file_size=source.stat().st_size,
        mime_type="image/png",
        status="uploaded",
        uploaded_at="2026-06-07T00:00:00",
    )
    monkeypatch.setattr(page, "_resolve_att_file_path", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.validate_image_file",
        lambda _path: (_ for _ in ()).throw(
            ImageGuardError("image.pixel_count_too_large")
        ),
    )

    page._update_preview(attachment)

    assert page._preview_stack.currentIndex() == _PREVIEW_META
    assert "oversized.png" in page._preview_meta.text()
    assert page._preview_image.pixmap().isNull()
    conn.close()


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


def _minimal_pdf() -> bytes:
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 40 120 Td (TaxOps PDF) Tj ET\nendstream\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def test_pdf_attachment_uses_embedded_preview(qapp, tmp_path):
    if QPdfDocument is None:
        pytest.skip("QtPdf unavailable in this environment")

    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "preview.pdf"
    src.write_bytes(_minimal_pdf())
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(1)
    page._load_attachments()
    page._table.selectRow(0)
    assert page._preview_stack.currentIndex() == _PREVIEW_PDF
    conn.close()


def test_location_button_opens_attachment_folder(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QUrl

    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "location.pdf"
    src.write_bytes(b"PDF content")
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=src,
    ))
    opened: list[QUrl] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(1)
    page._load_attachments()
    page._table.selectRow(0)
    page._on_open_location()
    assert opened
    assert Path(opened[0].toLocalFile()).is_dir()
    conn.close()


def test_location_button_right_click_copies_file_url(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    src = tmp_path / "ctx.pdf"
    src.write_bytes(b"PDF content")
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
    att = page._selected_attachment()
    assert att is not None
    page._copy_file_url(att)
    expected = QUrl.fromLocalFile(str(attachments_dir / row.stored_filename)).toString()
    assert QApplication.clipboard().text() == expected
    conn.close()


def test_malicious_stored_filename_cannot_preview_open_or_copy(
    qapp, monkeypatch, tmp_path
):
    conn, attachments_dir = _make_conn(tmp_path)
    eng_id = _seed(conn)
    source = tmp_path / "safe.txt"
    source.write_text("safe", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=source,
    ))
    outside = attachments_dir.parent / "outside.txt"
    outside.write_text("must not be exposed", encoding="utf-8")
    conn.execute(
        "UPDATE attachments SET stored_filename = ? WHERE id = ?",
        ("../outside.txt", row.id),
    )
    conn.commit()

    opened: list[QUrl] = []
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    QApplication.clipboard().setText("unchanged")

    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(1)
    page._load_attachments()
    page._table.selectRow(0)
    assert "must not be exposed" not in page._preview_text.toPlainText()

    page._on_open_system()
    page._on_open_location()
    att = page._selected_attachment()
    assert att is not None
    page._copy_file_url(att)

    assert opened == []
    assert QApplication.clipboard().text() == "unchanged"
    assert warnings
    conn.close()


def test_attachment_toolbar_click_path_uploads_reviews_opens_and_deletes(
    qapp, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QDialog, QMessageBox

    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    source = tmp_path / "使用者路徑.txt"
    source.write_text("附件預覽內容", encoding="utf-8")
    opened = []
    info_calls = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )
    monkeypatch.setattr(
        _AttachmentInfoDialog,
        "exec",
        lambda _dialog: info_calls.append(True) or QDialog.DialogCode.Accepted,
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))

    page._upload_btn.click()
    assert page._table.rowCount() == 1
    page._table.selectRow(0)
    assert "附件預覽內容" in page._preview_text.toPlainText()

    page._accept_btn.click()
    page._table.selectRow(0)
    assert page._selected_attachment().status == "accepted"
    page._reject_btn.click()
    page._table.selectRow(0)
    assert page._selected_attachment().status == "rejected"

    page._info_btn.click()
    page._open_btn.click()
    page._location_btn.click()
    assert info_calls == [True]
    assert len(opened) == 2

    page._delete_btn.click()
    assert page._table.rowCount() == 0
    conn.close()


def test_location_button_has_context_menu_policy(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    assert (
        page._location_btn.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )
    conn.close()


def test_attachment_location_contract_is_registered():
    location = [
        c for c in actions_for_page(PAGE_ATTACHMENTS)
        if c.button_label == "檔案位置"
    ]
    assert len(location) == 1
    assert location[0].handler == "AttachmentsPage._on_open_location"
    assert location[0].enabled


def test_text_preview_reads_only_bounded_prefix(qapp, tmp_path, monkeypatch):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    source = tmp_path / "large.txt"
    source.write_text("A" * 5000, encoding="utf-8")
    attachment = SimpleNamespace(
        id=999,
        extension=".txt",
        original_filename="large.txt",
        file_size=source.stat().st_size,
        mime_type="text/plain",
        status="uploaded",
        uploaded_at="2026-07-11T00:00:00",
    )
    monkeypatch.setattr(
        page, "_resolve_att_file_path", lambda *_args, **_kwargs: source
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("preview must not load the complete file")
        ),
    )

    page._update_preview(attachment)

    assert page._preview_text.toPlainText() == "A" * 4096
    conn.close()


def test_upload_button_without_engagement_warns_before_opening_picker(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: pytest.fail("file picker must not open"),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    page = AttachmentsPage(container)

    page._upload_btn.click()

    assert warnings == [("提示", "請先選擇案件")]
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    conn.close()


def test_upload_picker_cancel_leaves_database_and_audit_unchanged(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    audit_before = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]

    page._upload_btn.click()

    assert page._table.rowCount() == 0
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == audit_before
    conn.close()


def test_upload_invalid_file_shows_domain_error_and_writes_nothing(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    source = tmp_path / "惡意程式.exe"
    source.write_bytes(b"not allowed")
    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))

    page._upload_btn.click()

    assert criticals == [("上傳失敗", error_message("attachment.extension_not_allowed"))]
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert not [path for path in attachments_dir.rglob("*") if path.is_file()]
    conn.close()


def test_upload_unexpected_failure_shows_generic_error_and_preserves_database(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    source = tmp_path / "申報資料.txt"
    source.write_text("內容", encoding="utf-8")
    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    monkeypatch.setattr(
        container.attachments,
        "upload_attachment",
        lambda _data: (_ for _ in ()).throw(RuntimeError("disk offline")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))

    page._upload_btn.click()

    assert criticals == [("上傳失敗", error_message("attachment.upload.failed"))]
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize(
    ("button_name", "service_name", "error_code"),
    [
        ("_accept_btn", "accept_attachment", "attachment.not_found"),
        ("_reject_btn", "reject_attachment", "attachment.not_found"),
        ("_delete_btn", "delete_attachment", "attachment.not_found"),
    ],
)
def test_selected_attachment_domain_failure_is_visible_and_does_not_mutate_row(
    qapp, tmp_path, monkeypatch, button_name, service_name, error_code
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "待審附件.txt"
    source.write_text("待審", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    criticals: list[str] = []
    monkeypatch.setattr(
        container.attachments,
        service_name,
        lambda _attachment_id: (_ for _ in ()).throw(
            AttachmentValidationError(error_code)
        ),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.critical",
        lambda _parent, _title, message: criticals.append(message),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)

    getattr(page, button_name).click()

    assert criticals == [error_message(error_code)]
    db_row = conn.execute(
        "SELECT status FROM attachments WHERE id = ?", (row.id,)
    ).fetchone()
    assert db_row["status"] == "uploaded"
    conn.close()


@pytest.mark.parametrize(
    ("button_name", "service_name", "error_code"),
    [
        ("_accept_btn", "accept_attachment", "attachment.accept.failed"),
        ("_reject_btn", "reject_attachment", "attachment.reject.failed"),
        ("_delete_btn", "delete_attachment", "attachment.delete.failed"),
    ],
)
def test_selected_attachment_unexpected_failure_is_visible_and_does_not_mutate_row(
    qapp, tmp_path, monkeypatch, button_name, service_name, error_code
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "待審附件.txt"
    source.write_text("待審", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    criticals: list[str] = []
    monkeypatch.setattr(
        container.attachments,
        service_name,
        lambda _attachment_id: (_ for _ in ()).throw(RuntimeError("sqlite unavailable")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.critical",
        lambda _parent, _title, message: criticals.append(message),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)

    getattr(page, button_name).click()

    assert criticals == [error_message(error_code)]
    db_row = conn.execute(
        "SELECT status FROM attachments WHERE id = ?", (row.id,)
    ).fetchone()
    assert db_row["status"] == "uploaded"
    conn.close()


def test_delete_confirmation_cancel_preserves_attachment_and_audit(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "不可誤刪.txt"
    source.write_text("保留", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)

    page._delete_btn.click()

    db_row = conn.execute(
        "SELECT status FROM attachments WHERE id = ?", (row.id,)
    ).fetchone()
    assert db_row["status"] == "uploaded"
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'attachment.delete'"
    ).fetchone()[0] == 0
    assert page._table.rowCount() == 1
    conn.close()


def test_stale_selected_row_disables_actions_instead_of_silent_noop(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "稍後被移除.txt"
    source.write_text("內容", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)
    page._attachments = []

    page._on_selection_changed()

    assert not page._accept_btn.isEnabled()
    assert not page._reject_btn.isEnabled()
    assert not page._delete_btn.isEnabled()
    assert not page._open_btn.isEnabled()
    conn.close()


def test_failed_system_open_is_reported_to_user(qapp, tmp_path, monkeypatch):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "無關聯程式.txt"
    source.write_text("內容", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QDesktopServices.openUrl", lambda _url: False
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)

    page._open_btn.click()
    page._location_btn.click()

    assert warnings == [
        ("開啟失敗", "系統無法開啟附件，請確認檔案關聯與存取權限"),
        ("開啟失敗", "系統無法開啟附件資料夾，請確認存取權限"),
    ]
    conn.close()


def test_info_dialog_renders_optional_review_fields_and_real_close_button(qapp):
    att = AttachmentRow(
        id=7,
        engagement_id=1,
        request_id=None,
        original_filename="已驗收附件.pdf",
        stored_filename="2026/07/reviewed.pdf",
        file_hash_sha256="b" * 64,
        file_size=2048,
        mime_type="application/pdf",
        extension=".pdf",
        uploaded_by="會計甲",
        uploaded_at="2026-07-12T08:00:00",
        source="manual",
        status="accepted",
        notes="已核對申報期間",
        accepted_by="覆核乙",
        accepted_at="2026-07-12T09:00:00",
    )
    dialog = _AttachmentInfoDialog(att)
    values = [label.text() for label in dialog.findChildren(QLabel)]
    close_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "關閉"
    )

    close_button.click()

    assert "覆核乙" in values
    assert "2026-07-12T09:00:00" in values
    assert "已核對申報期間" in values
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_page_builds_metadata_preview_when_qtpdf_is_unavailable(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    container = _FakeContainer(conn, attachments_dir)
    monkeypatch.setattr("taxops.ui.pages.attachments_page.QPdfDocument", None)
    monkeypatch.setattr("taxops.ui.pages.attachments_page.QPdfView", None)

    page = AttachmentsPage(container)

    assert page._preview_pdf_doc is None
    assert page._preview_pdf is None
    conn.close()


def test_refresh_preserves_engagement_and_clear_filter_returns_to_all(qapp, tmp_path):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))

    page.refresh_context()

    assert page._eng_combo.currentData() == engagement_id
    page.clear_filter()
    assert page._eng_combo.currentData() == -1
    conn.close()


def test_refresh_engagement_failure_is_logged_and_leaves_safe_all_filter(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    _seed(conn)
    container = _FakeContainer(conn, attachments_dir)
    page = AttachmentsPage(container)
    monkeypatch.setattr(
        container.engagements,
        "list_all",
        lambda: (_ for _ in ()).throw(RuntimeError("database locked")),
    )

    page.refresh_context()

    assert page._eng_combo.count() == 1
    assert page._eng_combo.currentData() == -1
    log = conn.execute(
        "SELECT level, message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (log["level"], log["message"]) == (
        "WARN",
        "attachments: failed to load engagements",
    )
    assert "RuntimeError" in log["detail_json"]
    conn.close()


def test_attachment_list_failure_is_logged_and_clears_stale_rows(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "原本可見.txt"
    source.write_text("內容", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    page = AttachmentsPage(container)
    assert page._table.rowCount() == 1
    monkeypatch.setattr(
        container.attachments,
        "list_all",
        lambda: (_ for _ in ()).throw(RuntimeError("database locked")),
    )

    page.clear_filter()

    assert page._table.rowCount() == 0
    assert page._attachments == []
    log = conn.execute(
        "SELECT level, message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (log["level"], log["message"]) == (
        "WARN",
        "attachments: failed to load attachments",
    )
    assert "database locked" in log["detail_json"]
    conn.close()


def test_unexpected_file_resolution_failure_is_logged_and_visible(
    qapp, tmp_path, monkeypatch
):
    conn, attachments_dir = _make_conn(tmp_path)
    engagement_id = _seed(conn)
    source = tmp_path / "稍後離線.txt"
    source.write_text("內容", encoding="utf-8")
    container = _FakeContainer(conn, attachments_dir)
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id=engagement_id, request_id=None, source_path=source)
    )
    warnings: list[str] = []
    page = AttachmentsPage(container)
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(engagement_id))
    page._table.selectRow(0)
    monkeypatch.setattr(
        container.attachments,
        "resolve_file_path",
        lambda _attachment_id: (_ for _ in ()).throw(OSError("volume offline")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.attachments_page.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )

    page._open_btn.click()

    assert warnings == [error_message("attachment.not_found")]
    log = conn.execute(
        "SELECT message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert log["message"] == "attachments: failed to resolve stored file"
    assert f'"attachment_id": {row.id}' in log["detail_json"]
    assert "OSError" in log["detail_json"]
    conn.close()
