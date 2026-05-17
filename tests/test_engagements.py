"""Tests for EngagementsService + EngagementsRepository (Slice 4)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.services.audit import AuditService
from taxops.services.engagements import (
    CreateEngagementInput,
    EngagementValidationError,
    EngagementsService,
    UpdateEngagementInput,
)


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def svc(conn):
    audit_repo = AuditLogRepository(conn)
    audit = AuditService(audit_repo, actor="test_user")
    repo = EngagementsRepository(conn)
    return EngagementsService(repo, audit)


@pytest.fixture()
def client_id(conn):
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("CL001", "測試客戶"),
    )
    conn.commit()
    return cur.lastrowid


def _create_input(client_id: int, **kwargs) -> CreateEngagementInput:
    defaults = dict(
        client_id=client_id,
        engagement_name="2024 營業稅申報",
        tax_type="vat",
        period_name="2024Q1",
    )
    defaults.update(kwargs)
    return CreateEngagementInput(**defaults)


# ── create ──────────────────────────────────────────────────────────────────


def test_create_engagement_returns_row(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    assert row.id > 0
    assert row.engagement_name == "2024 營業稅申報"
    assert row.tax_type == "vat"
    assert row.period_name == "2024Q1"
    assert row.status == "draft"


def test_create_engagement_with_optional_fields(svc, client_id):
    row = svc.create_engagement(
        _create_input(client_id, owner="Alice", due_date="2024-04-30", notes="Note")
    )
    assert row.owner == "Alice"
    assert row.due_date == "2024-04-30"
    assert row.notes == "Note"


def test_create_engagement_name_required(svc, client_id):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.create_engagement(_create_input(client_id, engagement_name="   "))
    assert exc_info.value.code == "engagement.name.required"


def test_create_engagement_invalid_tax_type(svc, client_id):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.create_engagement(_create_input(client_id, tax_type="unknown_type"))
    assert exc_info.value.code == "engagement.tax_type.invalid"


def test_create_engagement_period_required(svc, client_id):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.create_engagement(_create_input(client_id, period_name=""))
    assert exc_info.value.code == "engagement.period_name.required"


def test_create_engagement_records_audit(svc, client_id, conn):
    svc.create_engagement(_create_input(client_id))
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.create'"
    ).fetchall()
    assert len(rows) == 1


# ── update ───────────────────────────────────────────────────────────────────


def test_update_engagement(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    updated = svc.update_engagement(
        row.id,
        UpdateEngagementInput(
            engagement_name="2024 更新案件",
            tax_type="cit",
            period_name="2024",
            status="in_progress",
            owner="Bob",
        ),
    )
    assert updated.engagement_name == "2024 更新案件"
    assert updated.tax_type == "cit"
    assert updated.status == "in_progress"
    assert updated.owner == "Bob"


def test_update_engagement_not_found_raises(svc):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.update_engagement(
            99999,
            UpdateEngagementInput(
                engagement_name="X", tax_type="vat", period_name="2024Q1", status="draft"
            ),
        )
    assert exc_info.value.code == "engagement.not_found"


def test_update_engagement_invalid_status(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.update_engagement(
            row.id,
            UpdateEngagementInput(
                engagement_name="X", tax_type="vat", period_name="2024Q1", status="bad_status"
            ),
        )
    assert exc_info.value.code == "engagement.status.invalid"


# ── set_status ────────────────────────────────────────────────────────────────


def test_set_status(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    updated = svc.set_status(row.id, "in_progress")
    assert updated.status == "in_progress"


def test_set_status_invalid_raises(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.set_status(row.id, "not_a_status")
    assert exc_info.value.code == "engagement.status.invalid"


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_engagement(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    svc.delete_engagement(row.id)
    assert svc.get_engagement(row.id) is None


def test_delete_engagement_not_found_raises(svc):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.delete_engagement(99999)
    assert exc_info.value.code == "engagement.not_found"


def test_delete_engagement_records_audit(svc, client_id, conn):
    row = svc.create_engagement(_create_input(client_id))
    svc.delete_engagement(row.id)
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'engagement.delete'"
    ).fetchall()
    assert len(rows) == 1


# ── list / count ──────────────────────────────────────────────────────────────


def test_list_by_client_returns_active_only(svc, client_id):
    e1 = svc.create_engagement(_create_input(client_id, engagement_name="A"))
    e2 = svc.create_engagement(_create_input(client_id, engagement_name="B"))
    svc.delete_engagement(e1.id)
    rows = svc.list_by_client(client_id)
    ids = [r.id for r in rows]
    assert e2.id in ids
    assert e1.id not in ids


def test_count_by_client(svc, client_id):
    assert svc.count_by_client(client_id) == 0
    svc.create_engagement(_create_input(client_id))
    assert svc.count_by_client(client_id) == 1
    svc.create_engagement(_create_input(client_id, period_name="2024Q2"))
    assert svc.count_by_client(client_id) == 2


def test_all_valid_tax_types_accepted(svc, client_id):
    for tax_type in ("vat", "cit", "iit", "stamp", "inheritance", "other"):
        row = svc.create_engagement(_create_input(client_id, tax_type=tax_type))
        assert row.tax_type == tax_type


# ── FK validation ─────────────────────────────────────────────────────────────


def test_create_engagement_client_not_found(svc):
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.create_engagement(_create_input(client_id=99999))
    assert exc_info.value.code == "engagement.client_not_found"


# ── transition guard ──────────────────────────────────────────────────────────


def test_set_status_draft_to_closed_raises(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    assert row.status == "draft"
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.set_status(row.id, "closed")
    assert exc_info.value.code == "engagement.status.transition_invalid"


def test_set_status_pending_acceptance_to_filed_raises(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    row = svc.set_status(row.id, "pending_acceptance")
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.set_status(row.id, "filed")
    assert exc_info.value.code == "engagement.status.transition_invalid"


def test_set_status_valid_transition(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    updated = svc.set_status(row.id, "pending_acceptance")
    assert updated.status == "pending_acceptance"
    updated2 = svc.set_status(updated.id, "accepted")
    assert updated2.status == "accepted"


def test_update_engagement_transition_guard(svc, client_id):
    row = svc.create_engagement(_create_input(client_id))
    with pytest.raises(EngagementValidationError) as exc_info:
        svc.update_engagement(
            row.id,
            UpdateEngagementInput(
                engagement_name="X",
                tax_type="vat",
                period_name="2024Q1",
                status="filed",
            ),
        )
    assert exc_info.value.code == "engagement.status.transition_invalid"
