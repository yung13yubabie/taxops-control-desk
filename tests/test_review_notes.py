"""Tests for ReviewNotesService + ReviewNotesRepository (Slice 8)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.review_notes import ReviewNotesRepository
from taxops.services.audit import AuditService
from taxops.services.review_notes import (
    CreateReviewNoteInput,
    ReviewNoteValidationError,
    ReviewNotesService,
    UpdateReviewNoteStatusInput,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def audit(conn):
    return AuditService(AuditLogRepository(conn), actor="test_user")


@pytest.fixture()
def svc(conn, audit):
    return ReviewNotesService(
        repo=ReviewNotesRepository(conn),
        engagements_repo=EngagementsRepository(conn),
        audit=audit,
    )


def _seed_engagement(conn):
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) VALUES ('C001', '測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO engagements
           (client_id, engagement_name, tax_type, period_name, status, created_at, updated_at)
           VALUES (?, '2024年度案件', 'vat', '2024Q1', 'draft', '2026-01-01T00:00:00', '2026-01-01T00:00:00')""",
        (client_id,),
    )
    eng_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return eng_id


# ── schema ────────────────────────────────────────────────────────────────────

def test_review_notes_table_exists(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "review_notes" in tables


def test_review_notes_fk_columns(conn):
    fk_rows = conn.execute("PRAGMA foreign_key_list(review_notes)").fetchall()
    tables = {row["table"] for row in fk_rows}
    assert "engagements" in tables


def test_review_notes_status_default(conn):
    eng_id = _seed_engagement(conn)
    repo = ReviewNotesRepository(conn)
    row = repo.insert(engagement_id=eng_id, severity="minor", comment="Test")
    assert row.status == "open"


# ── create ────────────────────────────────────────────────────────────────────

def test_create_review_note_ok(conn, svc):
    eng_id = _seed_engagement(conn)
    row = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="major", comment="檢查憑證"
    ))
    assert row.id > 0
    assert row.severity == "major"
    assert row.comment == "檢查憑證"
    assert row.status == "open"


def test_create_review_note_strips_comment(conn, svc):
    eng_id = _seed_engagement(conn)
    row = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="  白邊  "
    ))
    assert row.comment == "白邊"


def test_create_invalid_severity(conn, svc):
    eng_id = _seed_engagement(conn)
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.create(CreateReviewNoteInput(
            engagement_id=eng_id, severity="blocker", comment="X"
        ))
    assert exc.value.code == "review_note.invalid_severity"


def test_create_empty_comment(conn, svc):
    eng_id = _seed_engagement(conn)
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.create(CreateReviewNoteInput(
            engagement_id=eng_id, severity="minor", comment="   "
        ))
    assert exc.value.code == "review_note.comment_required"


def test_create_engagement_not_found(conn, svc):
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.create(CreateReviewNoteInput(
            engagement_id=99999, severity="minor", comment="X"
        ))
    assert exc.value.code == "review_note.engagement_not_found"


def test_create_records_audit(conn, svc):
    eng_id = _seed_engagement(conn)
    svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="critical", comment="嚴重問題"
    ))
    row = conn.execute(
        "SELECT action FROM audit_logs WHERE action='review_note.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


# ── status transitions ─────────────────────────────────────────────────────────

def test_open_to_responded(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    updated = svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="responded", response="已處理"
    ))
    assert updated.status == "responded"
    assert updated.response == "已處理"


def test_open_to_waived_with_reason(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="major", comment="X"
    ))
    updated = svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="waived", waive_reason="不適用"
    ))
    assert updated.status == "waived"
    assert updated.waive_reason == "不適用"


def test_critical_cannot_waive(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="critical", comment="嚴重"
    ))
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.update_status(UpdateReviewNoteStatusInput(
            note_id=note.id, new_status="waived", waive_reason="試試"
        ))
    assert exc.value.code == "review_note.critical_cannot_waive"


def test_waive_requires_reason(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.update_status(UpdateReviewNoteStatusInput(
            note_id=note.id, new_status="waived", waive_reason="  "
        ))
    assert exc.value.code == "review_note.waive_reason_required"


def test_invalid_transition(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.update_status(UpdateReviewNoteStatusInput(
            note_id=note.id, new_status="resolved"
        ))
    assert exc.value.code == "review_note.invalid_transition"


def test_responded_to_resolved(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="responded", response="A"
    ))
    updated = svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="resolved"
    ))
    assert updated.status == "resolved"


def test_resolved_to_reopened(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="responded", response="A"
    ))
    svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="resolved"
    ))
    reopened = svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="reopened"
    ))
    assert reopened.status == "reopened"


def test_update_status_not_found(conn, svc):
    with pytest.raises(ReviewNoteValidationError) as exc:
        svc.update_status(UpdateReviewNoteStatusInput(
            note_id=99999, new_status="responded"
        ))
    assert exc.value.code == "review_note.not_found"


def test_transition_records_audit(conn, svc):
    eng_id = _seed_engagement(conn)
    note = svc.create(CreateReviewNoteInput(
        engagement_id=eng_id, severity="minor", comment="X"
    ))
    svc.update_status(UpdateReviewNoteStatusInput(
        note_id=note.id, new_status="responded", response="Done"
    ))
    row = conn.execute(
        "SELECT action FROM audit_logs WHERE action='review_note.status_change' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


# ── list / get ─────────────────────────────────────────────────────────────────

def test_list_by_engagement(conn, svc):
    eng_id = _seed_engagement(conn)
    svc.create(CreateReviewNoteInput(engagement_id=eng_id, severity="minor", comment="A"))
    svc.create(CreateReviewNoteInput(engagement_id=eng_id, severity="major", comment="B"))
    notes = svc.list_by_engagement(eng_id)
    assert len(notes) == 2


def test_list_by_engagement_empty(conn, svc):
    eng_id = _seed_engagement(conn)
    assert svc.list_by_engagement(eng_id) == []


def test_get_returns_none_for_missing(conn, svc):
    assert svc.get(99999) is None
