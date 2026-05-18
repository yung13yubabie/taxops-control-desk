"""Tests for TemplatesService + TemplatesRepository + audit log (Slice 6)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.templates import TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.templates import (
    ALLOWED_VARIABLES,
    CreateTemplateInput,
    TemplateValidationError,
    TemplatesService,
    UpdateTemplateInput,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def audit_repo(conn):
    return AuditLogRepository(conn)


@pytest.fixture()
def svc(conn, audit_repo):
    audit = AuditService(audit_repo, actor="test_user")
    repo = TemplatesRepository(conn)
    return TemplatesService(repo, audit)


# ── schema ────────────────────────────────────────────────────────────────────

def test_message_templates_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='message_templates'"
    ).fetchone()
    assert row is not None


def test_message_templates_columns_present(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(message_templates)").fetchall()}
    required = {"id", "name", "template_type", "body", "is_builtin", "created_at", "updated_at", "deleted_at"}
    assert required.issubset(cols)


def test_builtin_templates_seeded(conn):
    rows = conn.execute(
        "SELECT id, name, is_builtin FROM message_templates WHERE is_builtin = 1"
    ).fetchall()
    assert len(rows) >= 2
    ids = {r["id"] for r in rows}
    assert 1 in ids
    assert 2 in ids


# ── create ────────────────────────────────────────────────────────────────────

def test_create_template_ok(svc):
    tmpl = svc.create_template(
        CreateTemplateInput(name="催件模板", template_type="follow_up", body="您好 {{ client_name }}")
    )
    assert tmpl.id > 0
    assert tmpl.name == "催件模板"
    assert tmpl.template_type == "follow_up"
    assert tmpl.is_builtin is False


def test_create_template_name_required(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="", body="hello"))
    assert exc.value.code == "template.name.required"


def test_create_template_body_required(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Test", body=""))
    assert exc.value.code == "template.body.required"


def test_create_template_body_whitespace_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Test", body="   "))
    assert exc.value.code == "template.body.required"


def test_create_template_syntax_error(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Bad", body="{{ unclosed"))
    assert exc.value.code == "template.body.syntax_error"


def test_create_template_unknown_variable(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Bad", body="{{ secret_field }}"))
    assert exc.value.code == "template.unknown_variable"


def test_create_template_invalid_type(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Bad", template_type="invalid", body="hello"))
    assert exc.value.code == "template.type.invalid"


def test_create_template_all_allowed_variables(svc):
    body = " ".join(f"{{{{ {v} }}}}" for v in sorted(ALLOWED_VARIABLES))
    tmpl = svc.create_template(CreateTemplateInput(name="AllVars", body=body))
    assert tmpl.id > 0


# ── get + list ────────────────────────────────────────────────────────────────

def test_get_template_returns_row(svc):
    created = svc.create_template(CreateTemplateInput(name="T1", body="body"))
    fetched = svc.get_template(created.id)
    assert fetched is not None
    assert fetched.id == created.id


def test_get_template_missing_returns_none(svc):
    assert svc.get_template(99999) is None


def test_list_all_includes_builtins(svc):
    rows = svc.list_all()
    builtin_ids = {r.id for r in rows if r.is_builtin}
    assert {1, 2}.issubset(builtin_ids)


def test_list_all_includes_custom(svc):
    svc.create_template(CreateTemplateInput(name="Custom1", body="hi"))
    rows = svc.list_all()
    names = [r.name for r in rows]
    assert "Custom1" in names


# ── update ────────────────────────────────────────────────────────────────────

def test_update_template_ok(svc):
    created = svc.create_template(CreateTemplateInput(name="Old", body="old body"))
    updated = svc.update_template(
        created.id,
        UpdateTemplateInput(name="New", template_type="follow_up", body="new {{ client_name }}"),
    )
    assert updated.name == "New"
    assert updated.body == "new {{ client_name }}"


def test_update_template_not_found(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.update_template(99999, UpdateTemplateInput(name="X", template_type="custom", body="x"))
    assert exc.value.code == "template.not_found"


def test_update_builtin_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.update_template(
            1,
            UpdateTemplateInput(name="Hacked", template_type="custom", body="hacked"),
        )
    assert exc.value.code == "template.builtin.readonly"


def test_update_template_name_required(svc):
    created = svc.create_template(CreateTemplateInput(name="T", body="body"))
    with pytest.raises(TemplateValidationError) as exc:
        svc.update_template(created.id, UpdateTemplateInput(name="", template_type="custom", body="x"))
    assert exc.value.code == "template.name.required"


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_template_ok(svc):
    created = svc.create_template(CreateTemplateInput(name="Delete Me", body="bye"))
    svc.delete_template(created.id)
    assert svc.get_template(created.id) is None


def test_delete_template_not_found(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.delete_template(99999)
    assert exc.value.code == "template.not_found"


def test_delete_builtin_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.delete_template(1)
    assert exc.value.code == "template.builtin.readonly"


def test_deleted_template_not_in_list(svc):
    created = svc.create_template(CreateTemplateInput(name="Gone", body="bye"))
    svc.delete_template(created.id)
    names = [r.name for r in svc.list_all()]
    assert "Gone" not in names


# ── render ────────────────────────────────────────────────────────────────────

def test_render_template_substitutes_variables(svc):
    created = svc.create_template(
        CreateTemplateInput(name="Render Test", body="Dear {{ client_name }}, period {{ period_name }}")
    )
    result = svc.render_template(
        created.id, {"client_name": "ABC Corp", "period_name": "2024Q1", "ignored_key": "x"}
    )
    assert "ABC Corp" in result
    assert "2024Q1" in result
    assert "ignored_key" not in result


def test_render_template_unknown_variables_filtered(svc):
    created = svc.create_template(
        CreateTemplateInput(name="Safe", body="Hi {{ client_name }}")
    )
    result = svc.render_template(created.id, {"client_name": "X", "evil": "drop tables"})
    assert "drop tables" not in result
    assert "X" in result


def test_render_template_not_found(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(99999, {})
    assert exc.value.code == "template.not_found"


_BUILTIN_FULL_VARS = {
    "client_name": "TestCo",
    "period_name": "2024Q1",
    "tax_type_name": "營業稅",
    "missing_items": "- 進項憑證\n- 銷項憑證",
    "due_date": "2024-03-31",
}


def test_render_builtin_template_all_vars_succeeds(svc):
    result = svc.render_template(1, _BUILTIN_FULL_VARS)
    assert "TestCo" in result
    assert "2024Q1" in result
    assert "營業稅" in result


def test_render_builtin_template_missing_tax_type_fails(svc):
    partial = {k: v for k, v in _BUILTIN_FULL_VARS.items() if k != "tax_type_name"}
    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(1, partial)
    assert exc.value.code == "template.variable.missing"


def test_render_builtin_template_missing_missing_items_fails(svc):
    partial = {k: v for k, v in _BUILTIN_FULL_VARS.items() if k != "missing_items"}
    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(1, partial)
    assert exc.value.code == "template.variable.missing"


def test_render_builtin_template_missing_due_date_fails(svc):
    partial = {k: v for k, v in _BUILTIN_FULL_VARS.items() if k != "due_date"}
    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(1, partial)
    assert exc.value.code == "template.variable.missing"


def test_render_template_missing_variable_fails(svc):
    created = svc.create_template(
        CreateTemplateInput(name="NeedsVar", body="Type: {{ tax_type_name }}")
    )
    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(created.id, {})
    assert exc.value.code == "template.variable.missing"


def test_create_template_extended_allowed_variables(svc):
    body = "{{ tax_id }} {{ contact_person }} {{ engagement_name }} {{ notes }}"
    tmpl = svc.create_template(CreateTemplateInput(name="Extended", body=body))
    assert tmpl.id > 0


def test_create_template_future_fields_rejected(svc):
    for field in ("payment_due_date", "office_owner", "reviewer", "last_followed_up_at"):
        with pytest.raises(TemplateValidationError) as exc:
            svc.create_template(CreateTemplateInput(name=f"Bad-{field}", body=f"{{{{ {field} }}}}"))
        assert exc.value.code == "template.unknown_variable", f"expected rejection for {field}"


def test_create_template_getattr_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Evil", body="{{ client_name.__class__ }}"))
    assert exc.value.code in ("template.body.syntax_error", "template.body.unsafe_expression")


def test_create_template_binary_expr_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Evil", body="{{ client_name ~ 'x' }}"))
    assert exc.value.code == "template.body.unsafe_expression"


def test_create_template_for_loop_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(
            CreateTemplateInput(name="Evil", body="{% for x in missing_items %}{{ x }}{% endfor %}")
        )
    assert exc.value.code == "template.body.unsafe_expression"


def test_create_template_filter_rejected(svc):
    with pytest.raises(TemplateValidationError) as exc:
        svc.create_template(CreateTemplateInput(name="Evil", body="{{ client_name | upper }}"))
    assert exc.value.code == "template.body.unsafe_expression"


# ── audit ─────────────────────────────────────────────────────────────────────

def test_create_template_records_audit(conn, svc):
    svc.create_template(CreateTemplateInput(name="AuditCheck", body="hi"))
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'template.create' ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert len(rows) == 1


def test_update_template_records_audit(conn, svc):
    created = svc.create_template(CreateTemplateInput(name="AU", body="x"))
    svc.update_template(created.id, UpdateTemplateInput(name="AU2", template_type="custom", body="y"))
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'template.update' ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert len(rows) == 1


def test_delete_template_records_audit(conn, svc):
    created = svc.create_template(CreateTemplateInput(name="Del", body="z"))
    svc.delete_template(created.id)
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'template.delete' ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert len(rows) == 1


def test_render_template_rejects_unsafe_db_body(conn, svc):
    """render_template() must re-validate body from DB, rejecting templates inserted via direct SQL."""
    ts = "2024-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO message_templates(name, template_type, body, is_builtin, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("Evil", "custom", "{{ client_name.__class__ }}", 0, ts, ts),
    )
    evil_id = cur.lastrowid
    conn.commit()

    with pytest.raises(TemplateValidationError) as exc:
        svc.render_template(evil_id, {"client_name": "TestCo"})
    assert exc.value.code in ("template.body.syntax_error", "template.body.unsafe_expression")
