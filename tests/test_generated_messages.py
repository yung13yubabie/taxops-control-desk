"""Tests for GeneratedMessagesService + GeneratedMessagesRepository (Slice 7)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.document_requests import DocumentRequestsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.generated_messages import GeneratedMessagesRepository
from taxops.repositories.templates import TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.generated_messages import (
    GeneratedMessageValidationError,
    GenerateMessageInput,
    GeneratedMessagesService,
)
from taxops.services.templates import TemplatesService


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
def templates_svc(conn, audit):
    return TemplatesService(TemplatesRepository(conn), audit)


@pytest.fixture()
def gen_svc(conn, audit, templates_svc):
    return GeneratedMessagesService(
        repo=GeneratedMessagesRepository(conn),
        doc_requests_repo=DocumentRequestsRepository(conn),
        engagements_repo=EngagementsRepository(conn),
        clients_repo=ClientsRepository(conn),
        templates_svc=templates_svc,
        audit=audit,
    )


def _seed_request(conn) -> tuple[int, int]:
    """Insert client + engagement + document_request + items; return (client_id, req_id)."""
    ts = "2024-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, tax_id, contact_name, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("C001", "測試公司", "12345678", "王小明", ts, ts),
    )
    client_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO engagements(client_id, engagement_name, tax_type, period_name, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (client_id, "2024 VAT 申報", "vat", "2024Q1", "active", ts, ts),
    )
    eng_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO document_requests(engagement_id, tax_type, period_name, status, follow_up_count, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eng_id, "vat", "2024Q1", "requested", 0, ts, ts),
    )
    req_id = cur.lastrowid

    conn.execute(
        "INSERT INTO document_request_items(request_id, item_name, item_status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (req_id, "進項憑證", "missing", ts, ts),
    )
    conn.execute(
        "INSERT INTO document_request_items(request_id, item_name, item_status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (req_id, "折讓單", "invalid", ts, ts),
    )
    conn.commit()
    return client_id, req_id


# ── schema ────────────────────────────────────────────────────────────────────

def test_generated_messages_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='generated_messages'"
    ).fetchone()
    assert row is not None


def test_generated_messages_index_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_generated_messages_request'"
    ).fetchone()
    assert row is not None


def test_generated_messages_fk_columns(conn):
    fk_rows = conn.execute("PRAGMA foreign_key_list(generated_messages)").fetchall()
    tables = {row["table"] for row in fk_rows}
    assert "document_requests" in tables
    assert "message_templates" in tables


# ── build_variables ───────────────────────────────────────────────────────────

def test_build_variables_returns_all_keys(conn, gen_svc):
    _, req_id = _seed_request(conn)
    variables = gen_svc.build_variables(req_id)
    expected_keys = {
        "client_name", "tax_id", "contact_person", "period_name",
        "tax_type_name", "engagement_name", "missing_items", "invalid_items",
        "incomplete_items", "due_date", "notes",
    }
    assert set(variables.keys()) == expected_keys


def test_build_variables_client_fields(conn, gen_svc):
    _, req_id = _seed_request(conn)
    v = gen_svc.build_variables(req_id)
    assert v["client_name"] == "測試公司"
    assert v["tax_id"] == "12345678"
    assert v["contact_person"] == "王小明"


def test_build_variables_item_groups(conn, gen_svc):
    _, req_id = _seed_request(conn)
    v = gen_svc.build_variables(req_id)
    assert "進項憑證" in v["missing_items"]
    assert "折讓單" in v["invalid_items"]
    assert v["incomplete_items"] == ""


def test_build_variables_future_fields_absent(conn, gen_svc):
    _, req_id = _seed_request(conn)
    v = gen_svc.build_variables(req_id)
    for field in ("payment_due_date", "office_owner", "reviewer", "last_followed_up_at"):
        assert field not in v, f"future field '{field}' should not be in variables"


def test_build_variables_request_not_found(gen_svc):
    with pytest.raises(GeneratedMessageValidationError) as exc_info:
        gen_svc.build_variables(99999)
    assert exc_info.value.code == "gen_message.request_not_found"


# ── generate ──────────────────────────────────────────────────────────────────

def test_generate_with_builtin_template(conn, gen_svc):
    _, req_id = _seed_request(conn)
    # builtin template id=1 (vat) uses client_name, period_name, tax_type_name,
    # missing_items, due_date — all provided by build_variables
    payload = GenerateMessageInput(request_id=req_id, template_id=1)
    msg = gen_svc.generate(payload)
    assert msg.request_id == req_id
    assert msg.template_id == 1
    assert len(msg.body) > 0
    assert msg.id > 0


def test_generate_persists_to_db(conn, gen_svc):
    _, req_id = _seed_request(conn)
    payload = GenerateMessageInput(request_id=req_id, template_id=1)
    msg = gen_svc.generate(payload)
    fetched = gen_svc.get_message(msg.id)
    assert fetched is not None
    assert fetched.body == msg.body


def test_generate_records_audit(conn, gen_svc):
    _, req_id = _seed_request(conn)
    payload = GenerateMessageInput(request_id=req_id, template_id=1)
    msg = gen_svc.generate(payload)
    row = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'gen_message.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["action"] == "gen_message.create"


def test_generate_request_not_found_raises(gen_svc):
    with pytest.raises(GeneratedMessageValidationError) as exc_info:
        gen_svc.generate(GenerateMessageInput(request_id=99999, template_id=1))
    assert exc_info.value.code == "gen_message.request_not_found"


def test_generate_template_not_found_raises(conn, gen_svc):
    _, req_id = _seed_request(conn)
    with pytest.raises(GeneratedMessageValidationError):
        gen_svc.generate(GenerateMessageInput(request_id=req_id, template_id=99999))


# ── list_by_request ───────────────────────────────────────────────────────────

def test_list_by_request_empty(gen_svc):
    assert gen_svc.list_by_request(99999) == []


def test_list_by_request_returns_generated(conn, gen_svc):
    _, req_id = _seed_request(conn)
    payload = GenerateMessageInput(request_id=req_id, template_id=1)
    gen_svc.generate(payload)
    gen_svc.generate(payload)
    msgs = gen_svc.list_by_request(req_id)
    assert len(msgs) == 2
    assert all(m.request_id == req_id for m in msgs)


def test_generate_rejects_unsafe_db_template(conn, gen_svc):
    """generate() must fail and NOT persist if the DB template body is unsafe."""
    _, req_id = _seed_request(conn)
    ts = "2024-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO message_templates(name, template_type, body, is_builtin, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("Evil", "custom", "{{ client_name.__class__ }}", 0, ts, ts),
    )
    evil_tmpl_id = cur.lastrowid
    conn.commit()

    with pytest.raises(Exception):
        gen_svc.generate(GenerateMessageInput(request_id=req_id, template_id=evil_tmpl_id))

    count = conn.execute("SELECT COUNT(*) FROM generated_messages").fetchone()[0]
    assert count == 0, "unsafe template must not produce a persisted generated_message"
