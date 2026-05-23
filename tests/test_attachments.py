"""Tests for AttachmentsRepository, AttachmentsService, and attachment_versions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from taxops.core.paths import resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.attachments import AttachmentsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.security.file_guard import MAX_FILE_SIZE
from taxops.services.attachments import (
    AttachmentValidationError,
    AttachmentsService,
    UploadAttachmentInput,
)
from taxops.services.audit import AuditService


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path):
    paths = resolve_paths(override_root=tmp_path / "data")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    c = open_connection(paths.db_path)
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def attachments_dir(tmp_path):
    d = tmp_path / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def audit(conn):
    return AuditService(AuditLogRepository(conn), actor="test")


@pytest.fixture
def repo(conn):
    return AttachmentsRepository(conn)


@pytest.fixture
def svc(repo, attachments_dir, audit):
    return AttachmentsService(repo=repo, attachments_dir=attachments_dir, audit=audit)


def _seed(conn) -> tuple[int, int]:
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
    return client_id, eng_id


def _make_file(tmp_path: Path, name: str = "report.pdf", content: bytes = b"PDF content") -> Path:
    f = tmp_path / name
    f.write_bytes(content)
    return f


# ── schema tests ───────────────────────────────────────────────────────────────

def test_attachments_table_exists(conn):
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "attachments" in tables


def test_attachment_versions_table_exists(conn):
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "attachment_versions" in tables


def test_attachments_fk_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(attachments)").fetchall()}
    assert "engagement_id" in cols
    assert "request_id" in cols
    assert "file_hash_sha256" in cols
    assert "stored_filename" in cols


def test_attachment_versions_fk_columns(conn):
    cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(attachment_versions)"
    ).fetchall()}
    assert "attachment_id" in cols
    assert "supersedes_id" in cols


def test_attachments_default_status_uploaded(conn):
    _, eng_id = _seed(conn)
    repo = AttachmentsRepository(conn)
    row = repo.insert(
        engagement_id=eng_id,
        request_id=None,
        original_filename="a.pdf",
        stored_filename="2026/05/abc.pdf",
        file_hash_sha256="aabbcc",
        file_size=1024,
        mime_type="application/pdf",
        extension=".pdf",
    )
    assert row.status == "uploaded"


# ── upload_attachment ──────────────────────────────────────────────────────────

def test_upload_attachment_ok(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=f,
    ))
    assert row.engagement_id == eng_id
    assert row.original_filename == "report.pdf"
    assert row.extension == ".pdf"
    assert row.status == "uploaded"
    assert len(row.file_hash_sha256) == 64


def test_upload_copies_to_attachments_dir(conn, svc, attachments_dir, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=f,
    ))
    stored = attachments_dir / row.stored_filename
    assert stored.exists()


def test_upload_stored_filename_not_original(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path, "original_name.pdf")
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=f,
    ))
    assert "original_name" not in row.stored_filename


def test_upload_creates_version_record(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=f,
    ))
    versions = conn.execute(
        "SELECT * FROM attachment_versions WHERE attachment_id = ?", (row.id,)
    ).fetchall()
    assert len(versions) == 1
    assert versions[0]["supersedes_id"] is None


def test_upload_records_audit(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id,
        request_id=None,
        source_path=f,
    ))
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.upload' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None


def test_upload_wrong_extension_rejected(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path, "malware.exe", b"MZ")
    with pytest.raises(AttachmentValidationError) as exc:
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id,
            request_id=None,
            source_path=f,
        ))
    assert exc.value.code == "attachment.extension_not_allowed"


def test_upload_file_too_large_rejected(conn, svc, tmp_path, monkeypatch):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)

    class _FakeStat:
        st_size = MAX_FILE_SIZE + 1

    monkeypatch.setattr(Path, "stat", lambda self: _FakeStat())

    with pytest.raises(AttachmentValidationError) as exc:
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id,
            request_id=None,
            source_path=f,
        ))
    assert exc.value.code == "attachment.file_too_large"


def test_upload_engagement_not_found_rejected(conn, svc, tmp_path):
    f = _make_file(tmp_path)
    with pytest.raises(AttachmentValidationError) as exc:
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=9999,
            request_id=None,
            source_path=f,
        ))
    assert exc.value.code == "attachment.engagement_not_found"


# ── accept_attachment ──────────────────────────────────────────────────────────

def test_accept_attachment_ok(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))
    updated = svc.accept_attachment(row.id)
    assert updated.status == "accepted"
    assert updated.accepted_by == "local_user"
    assert updated.accepted_at is not None


def test_accept_attachment_records_audit(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))
    svc.accept_attachment(row.id)
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.accept' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None


def test_accept_attachment_not_found(conn, svc):
    with pytest.raises(AttachmentValidationError) as exc:
        svc.accept_attachment(9999)
    assert exc.value.code == "attachment.not_found"


# ── reject_attachment ──────────────────────────────────────────────────────────

def test_reject_attachment_ok(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))
    updated = svc.reject_attachment(row.id)
    assert updated.status == "rejected"


def test_reject_attachment_records_audit(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))
    svc.reject_attachment(row.id)
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.reject' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None


def test_reject_attachment_not_found(conn, svc):
    with pytest.raises(AttachmentValidationError) as exc:
        svc.reject_attachment(9999)
    assert exc.value.code == "attachment.not_found"


# ── list / get ─────────────────────────────────────────────────────────────────

def test_list_by_engagement(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    for name in ("a.pdf", "b.pdf"):
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id,
            request_id=None,
            source_path=_make_file(tmp_path, name),
        ))
    results = svc.list_by_engagement(eng_id)
    assert len(results) == 2


def test_list_by_engagement_empty(conn, svc):
    results = svc.list_by_engagement(9999)
    assert results == []


def test_get_returns_none_for_missing(conn, svc):
    assert svc.get(9999) is None


# ── upload atomicity ───────────────────────────────────────────────────────────

def test_upload_db_failure_no_orphan_file(conn, svc, attachments_dir, tmp_path, monkeypatch):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)

    def _fail(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(svc._repo, "insert_with_version", _fail)

    with pytest.raises(RuntimeError):
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id, request_id=None, source_path=f,
        ))

    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM attachment_versions").fetchone()[0] == 0
    stored_files = [p for p in attachments_dir.rglob("*") if p.is_file()]
    assert stored_files == [], "No orphan files should remain"


def test_upload_audit_failure_no_orphan_file(conn, svc, attachments_dir, tmp_path, monkeypatch):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)

    def _fail(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(svc._audit, "record", _fail)

    with pytest.raises(RuntimeError):
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id, request_id=None, source_path=f,
        ))

    stored_files = [p for p in attachments_dir.rglob("*") if p.is_file()]
    assert stored_files == [], "No orphan files should remain after audit failure"


# ── request_id cross-engagement validation ─────────────────────────────────────

def _seed_two_engagements(conn) -> tuple[int, int, int]:
    """Returns (eng_id_a, eng_id_b, request_id_b)."""
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) "
        "VALUES ('C001', '客戶甲', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for name in ("案件A", "案件B"):
        conn.execute(
            "INSERT INTO engagements (client_id, engagement_name, tax_type, period_name, "
            "status, created_at, updated_at) "
            "VALUES (?, ?, 'vat', '202501', 'draft', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (client_id, name),
        )
    eng_id_a = conn.execute(
        "SELECT id FROM engagements WHERE engagement_name = '案件A'"
    ).fetchone()[0]
    eng_id_b = conn.execute(
        "SELECT id FROM engagements WHERE engagement_name = '案件B'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO document_requests (engagement_id, tax_type, period_name, status, created_at, updated_at) "
        "VALUES (?, 'vat', '202501', 'not_requested', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (eng_id_b,),
    )
    request_id_b = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return eng_id_a, eng_id_b, request_id_b


def test_upload_request_wrong_engagement_rejected(conn, svc, attachments_dir, tmp_path):
    eng_id_a, _eng_id_b, request_id_b = _seed_two_engagements(conn)
    f = _make_file(tmp_path)

    with pytest.raises(AttachmentValidationError) as exc:
        svc.upload_attachment(UploadAttachmentInput(
            engagement_id=eng_id_a,
            request_id=request_id_b,
            source_path=f,
        ))
    assert exc.value.code == "attachment.request_not_found"

    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    stored_files = [p for p in attachments_dir.rglob("*") if p.is_file()]
    assert stored_files == [], "No file should be copied when request belongs to wrong engagement"


def test_upload_request_correct_engagement_allowed(conn, svc, tmp_path):
    _eng_id_a, eng_id_b, request_id_b = _seed_two_engagements(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id_b,
        request_id=request_id_b,
        source_path=f,
    ))
    assert row.request_id == request_id_b
    assert row.engagement_id == eng_id_b


def test_delete_attachment_archives_and_hides_from_default_list(
    conn, svc, repo, tmp_path
):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))

    updated = svc.delete_attachment(row.id)

    assert updated.status == "archived"
    assert svc.list_by_engagement(eng_id) == []
    archived = repo.list_by_engagement(eng_id, include_archived=True)
    assert len(archived) == 1
    assert archived[0].id == row.id


def test_delete_attachment_records_audit(conn, svc, tmp_path):
    _, eng_id = _seed(conn)
    f = _make_file(tmp_path)
    row = svc.upload_attachment(UploadAttachmentInput(
        engagement_id=eng_id, request_id=None, source_path=f
    ))

    svc.delete_attachment(row.id)

    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'attachment.delete' AND target_id = ?",
        (str(row.id),),
    ).fetchone()
    assert log is not None


def test_delete_attachment_not_found(conn, svc):
    with pytest.raises(AttachmentValidationError) as exc:
        svc.delete_attachment(9999)
    assert exc.value.code == "attachment.not_found"
