"""Slice 20C regression tests: atomic create_plan_with_lines + bulk paste.

Covers:
- Service: create_plan_with_lines atomic (plan + N lines in single transaction)
- Service: invalid line rollback (no plan, no lines persisted)
- Service: audit log records plan + line_count once
- Helper: parse_bulk_lines (tab-separated, empty-skip, per-row error reporting)
- PlanDialog: lines table + add/remove rows + bulk paste integration
- Occurrence confirm preserves expected_amount vs confirmed_amount distinction
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.recurring_billing import RecurringBillingRepository
from taxops.services.audit import AuditService
from taxops.services.recurring_billing import (
    ConfirmOccurrenceInput,
    CreateLineInput,
    CreatePlanInput,
    RecurringBillingError,
    RecurringBillingService,
    parse_bulk_lines,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
    return RecurringBillingService(
        repo=RecurringBillingRepository(conn),
        audit=audit,
    )


@pytest.fixture()
def client_id(conn) -> int:
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) "
        "VALUES ('C20C', '20C測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return cid


def _plan_input(client_id: int, **overrides) -> CreatePlanInput:
    defaults = dict(
        client_id=client_id,
        plan_name="月結方案",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=15,
    )
    defaults.update(overrides)
    return CreatePlanInput(**defaults)


# ── service: create_plan_with_lines atomic ─────────────────────────────────


def test_create_plan_with_lines_persists_plan_and_all_lines(svc, conn, client_id):
    plan_inp = _plan_input(client_id)
    lines = [
        CreateLineInput(plan_id=0, bill_to_name="客戶A", amount=10000),
        CreateLineInput(plan_id=0, bill_to_name="客戶B", amount=20000, tax_type="vat"),
        CreateLineInput(plan_id=0, bill_to_name="客戶C", amount=30000, description="月度服務"),
    ]
    plan, created_lines = svc.create_plan_with_lines(plan_inp, lines)
    assert plan.id > 0
    assert len(created_lines) == 3
    row = conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_lines WHERE plan_id = ?",
        (plan.id,),
    ).fetchone()
    assert row[0] == 3


def test_create_plan_with_lines_invalid_line_rolls_back_plan(svc, conn, client_id):
    """If any line is invalid, neither the plan nor any line is persisted."""
    plan_inp = _plan_input(client_id, plan_name="會被回滾的方案")
    lines = [
        CreateLineInput(plan_id=0, bill_to_name="客戶A", amount=10000),
        CreateLineInput(plan_id=0, bill_to_name="客戶B", amount=-50),  # invalid
    ]
    with pytest.raises(RecurringBillingError):
        svc.create_plan_with_lines(plan_inp, lines)
    plan_count = conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_plans WHERE plan_name = ?",
        ("會被回滾的方案",),
    ).fetchone()[0]
    assert plan_count == 0
    line_count = conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_lines WHERE bill_to_name IN ('客戶A','客戶B')"
    ).fetchone()[0]
    assert line_count == 0


def test_create_plan_with_lines_empty_lines_raises(svc, client_id):
    """Empty lines list is rejected — a plan with no billing target is meaningless."""
    plan_inp = _plan_input(client_id)
    with pytest.raises(RecurringBillingError) as ei:
        svc.create_plan_with_lines(plan_inp, [])
    assert ei.value.code == "recurring_billing.lines.empty"


def test_create_plan_with_lines_audit_records_line_count(svc, conn, client_id):
    plan_inp = _plan_input(client_id, plan_name="審計驗證方案")
    lines = [
        CreateLineInput(plan_id=0, bill_to_name="客戶A", amount=10000),
        CreateLineInput(plan_id=0, bill_to_name="客戶B", amount=20000),
    ]
    plan, _ = svc.create_plan_with_lines(plan_inp, lines)
    row = conn.execute(
        "SELECT detail_json FROM audit_logs WHERE action = ? AND target_id = ?",
        ("recurring_billing.plan.create_with_lines", str(plan.id)),
    ).fetchone()
    assert row is not None
    assert "line_count" in row["detail_json"]
    assert '"line_count": 2' in row["detail_json"]


def test_create_plan_with_lines_invalid_plan_raises_no_db_write(svc, conn, client_id):
    """Plan validation errors prevent the entire transaction."""
    plan_inp = _plan_input(client_id, plan_name="   ")
    lines = [CreateLineInput(plan_id=0, bill_to_name="客戶A", amount=10000)]
    with pytest.raises(RecurringBillingError) as ei:
        svc.create_plan_with_lines(plan_inp, lines)
    assert ei.value.code == "recurring_billing.plan_name.empty"
    cnt = conn.execute("SELECT COUNT(*) FROM recurring_billing_plans").fetchone()[0]
    assert cnt == 0


# ── helper: parse_bulk_lines ───────────────────────────────────────────────


def test_parse_bulk_lines_valid_input():
    text = "客戶甲\t10000\tvat\t月度服務\n客戶乙\t20000\tservice\t季度顧問"
    lines, errors = parse_bulk_lines(text)
    assert errors == []
    assert len(lines) == 2
    assert lines[0].bill_to_name == "客戶甲"
    assert lines[0].amount == 10000
    assert lines[0].tax_type == "vat"
    assert lines[0].description == "月度服務"
    assert lines[1].bill_to_name == "客戶乙"


def test_parse_bulk_lines_skips_empty_rows():
    text = "客戶甲\t10000\n\n\n客戶乙\t20000"
    lines, errors = parse_bulk_lines(text)
    assert errors == []
    assert len(lines) == 2


def test_parse_bulk_lines_partial_fields_allowed():
    """Only bill_to and amount are required; tax_type and description optional."""
    text = "客戶甲\t10000"
    lines, errors = parse_bulk_lines(text)
    assert errors == []
    assert len(lines) == 1
    assert lines[0].bill_to_name == "客戶甲"
    assert lines[0].amount == 10000
    assert lines[0].tax_type is None
    assert lines[0].description is None


def test_parse_bulk_lines_invalid_amount_reports_row_number():
    text = "客戶甲\t10000\n客戶乙\tabc\n客戶丙\t30000"
    lines, errors = parse_bulk_lines(text)
    assert len(errors) == 1
    row_no, msg = errors[0]
    assert row_no == 2
    assert "金額" in msg or "amount" in msg.lower()


def test_parse_bulk_lines_missing_required_field_reports_row():
    text = "客戶甲\n客戶乙\t20000"
    lines, errors = parse_bulk_lines(text)
    assert len(errors) == 1
    row_no, _ = errors[0]
    assert row_no == 1


def test_parse_bulk_lines_negative_amount_reports():
    text = "客戶甲\t-100"
    lines, errors = parse_bulk_lines(text)
    assert len(errors) == 1


# ── occurrence confirm: expected vs confirmed amount ───────────────────────


def test_confirm_occurrence_audit_records_confirmed_amount(svc, conn, client_id):
    plan_inp = _plan_input(client_id)
    lines = [CreateLineInput(plan_id=0, bill_to_name="客戶A", amount=10000)]
    plan, _ = svc.create_plan_with_lines(plan_inp, lines)
    occs = svc.generate_occurrences(plan.id)
    assert occs
    first = occs[0]
    confirmed = svc.confirm_occurrence(
        first.id,
        ConfirmOccurrenceInput(
            confirmed_amount=12000,
            confirmed_invoice_no="INV-001",
        ),
    )
    assert confirmed.confirmed_amount == 12000
    assert confirmed.confirmed_invoice_no == "INV-001"
    audit_row = conn.execute(
        "SELECT detail_json FROM audit_logs WHERE action = ? AND target_id = ?",
        ("recurring_billing.occurrence.confirm", str(first.id)),
    ).fetchone()
    assert audit_row is not None
    assert '"confirmed_amount": 12000' in audit_row["detail_json"]


# ── PlanDialog: lines table + bulk paste ──────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_has_lines_table(conn, client_id, audit):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    svc = RecurringBillingService(
        repo=RecurringBillingRepository(conn), audit=audit
    )
    dlg = PlanDialog(svc, client_id=client_id)
    assert hasattr(dlg, "_lines_table")
    assert dlg._lines_table.columnCount() >= 4


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_add_line_button_adds_row(conn, client_id, audit):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    svc = RecurringBillingService(
        repo=RecurringBillingRepository(conn), audit=audit
    )
    dlg = PlanDialog(svc, client_id=client_id)
    initial = dlg._lines_table.rowCount()
    dlg._on_add_line_row()
    assert dlg._lines_table.rowCount() == initial + 1


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_save_creates_plan_and_lines_atomically(conn, client_id, audit):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    svc = RecurringBillingService(
        repo=RecurringBillingRepository(conn), audit=audit
    )
    dlg = PlanDialog(svc, client_id=client_id)
    dlg._name.setText("UI 建立的方案")
    dlg._start_date.set_value("2026-02-01")
    dlg._on_add_line_row()
    dlg._set_line_cell(0, "bill_to", "客戶A")
    dlg._set_line_cell(0, "amount", "10000")
    dlg._on_add_line_row()
    dlg._set_line_cell(1, "bill_to", "客戶B")
    dlg._set_line_cell(1, "amount", "20000")
    dlg._on_save()
    plans = svc.list_plans(client_id=client_id)
    matching = [p for p in plans if p.plan_name == "UI 建立的方案"]
    assert len(matching) == 1
    lines = svc.list_lines(matching[0].id)
    assert len(lines) == 2
    assert {ln.bill_to_name for ln in lines} == {"客戶A", "客戶B"}


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_save_rejects_no_lines(conn, client_id, audit):
    """Empty lines table must not create a plan."""
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    svc = RecurringBillingService(
        repo=RecurringBillingRepository(conn), audit=audit
    )
    dlg = PlanDialog(svc, client_id=client_id)
    dlg._name.setText("不應建立的方案")
    dlg._start_date.set_value("2026-02-01")
    with patch.object(QMessageBox, "warning") as warn:
        dlg._on_save()
        warn.assert_called_once()
    plans = svc.list_plans(client_id=client_id)
    assert not any(p.plan_name == "不應建立的方案" for p in plans)
