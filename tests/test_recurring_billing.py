"""Tests for Slice 18A: RecurringBillingService + RecurringBillingRepository."""

from __future__ import annotations

import datetime
import json
from unittest.mock import patch

import pytest

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
    UpdateLineInput,
    UpdatePlanInput,
    _billing_dates,
    _clamp_day,
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
    return RecurringBillingService(
        repo=RecurringBillingRepository(conn),
        audit=audit,
    )


def _seed_client(conn) -> int:
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) "
        "VALUES ('C001', '測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return cid


def _make_plan(svc, client_id: int, **kwargs) -> object:
    defaults = dict(
        client_id=client_id,
        plan_name="月結發票",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=15,
    )
    defaults.update(kwargs)
    return svc.create_plan(CreatePlanInput(**defaults))


def _generate_and_list(svc, plan_id: int, until_date: datetime.date):
    svc.generate_occurrences(plan_id, until_date=until_date)
    return svc.list_occurrences(plan_id=plan_id)


# ── schema ────────────────────────────────────────────────────────────────────

def test_recurring_billing_tables_exist(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "recurring_billing_plans" in tables
    assert "recurring_billing_lines" in tables
    assert "recurring_billing_occurrences" in tables


# ── plan CRUD ─────────────────────────────────────────────────────────────────

def test_create_plan_returns_row(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    assert plan.id > 0
    assert plan.plan_name == "月結發票"
    assert plan.status == "active"
    assert plan.frequency == "monthly"
    assert plan.issue_day == 15


def test_create_plan_rejects_soft_deleted_client(conn, svc):
    cid = _seed_client(conn)
    conn.execute(
        "UPDATE clients SET deleted_at = '2026-07-11T00:00:00Z' WHERE id = ?",
        (cid,),
    )
    conn.commit()

    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid)

    assert exc.value.code == "recurring_billing.client_not_found"
    assert conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_plans WHERE client_id = ?",
        (cid,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE action = 'recurring_billing.plan.create'"
    ).fetchone()[0] == 0


def test_get_plan_returns_created(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    fetched = svc.get_plan(plan.id)
    assert fetched is not None
    assert fetched.id == plan.id


def test_update_plan_changes_name(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    updated = svc.update_plan(plan.id, UpdatePlanInput(
        plan_name="季結發票", start_date="2026-01-01",
        frequency="quarterly", issue_day=10,
    ))
    assert updated.plan_name == "季結發票"
    assert updated.frequency == "quarterly"


def test_archive_plan_sets_status_and_deleted_at(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    archived = svc.archive_plan(plan.id)
    assert archived.status == "archived"
    assert archived.deleted_at is not None


def test_delete_plan_physically_removes_plan_lines_and_pending_occurrences(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="刪除測試", amount=5000))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))

    svc.delete_plan(plan.id)

    assert conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_plans WHERE id = ?", (plan.id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_lines WHERE plan_id = ?", (plan.id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM recurring_billing_occurrences WHERE plan_id = ?", (plan.id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'recurring_billing.plan.delete'"
    ).fetchone()[0] == 1


def test_delete_plan_with_confirmed_history_is_blocked(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="歷史測試", amount=5000))
    occurrence = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 1, 31)
    )[0]
    svc.confirm_occurrence(
        occurrence.id,
        ConfirmOccurrenceInput(confirmed_amount=5000),
    )

    with pytest.raises(RecurringBillingError) as exc:
        svc.delete_plan(plan.id)

    assert exc.value.code == "recurring_billing.plan.has_confirmed_history"
    assert svc.get_plan(plan.id) is not None


def test_reopen_confirmed_occurrence_clears_confirmation_fields_and_audits(conn, svc):
    plan, occurrence = _seed_occurrence(svc, conn)
    svc.confirm_occurrence(
        occurrence.id,
        ConfirmOccurrenceInput(
            confirmed_amount=50000,
            confirmed_invoice_no="AB12345678",
            confirmed_issue_date="2026-01-02",
        ),
    )

    reopened = svc.reopen_occurrence(occurrence.id)

    assert reopened.status == "pending"
    assert reopened.confirmed_amount is None
    assert reopened.confirmed_invoice_no is None
    assert reopened.confirmed_issue_date is None
    assert reopened.confirmed_at is None
    audit = conn.execute(
        "SELECT action, detail_json FROM audit_logs"
        " WHERE action = 'recurring_billing.occurrence.reopen'"
    ).fetchone()
    assert audit is not None
    detail = json.loads(audit["detail_json"])
    assert detail["previous_confirmed_invoice_no"] == "AB12345678"
    assert detail["previous_confirmed_issue_date"] == "2026-01-02"
    assert detail["previous_confirmed_amount"] == 50000
    assert detail["previous_confirmed_at"]


def test_delete_plan_rolls_back_everything_when_audit_fails(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="Rollback", amount=5000)
    )
    occurrence = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 1, 31)
    )[0]

    with patch.object(svc._audit, "record", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            svc.delete_plan(plan.id)

    assert svc.get_plan(plan.id) is not None
    assert svc._repo.get_line(line.id) is not None
    assert svc._repo.get_occurrence(occurrence.id) is not None


def test_update_plan_reconciles_pending_dates_but_preserves_confirmed_history(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", issue_day=1)
    first_line = svc.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="已確認歷史", amount=5000)
    )
    second_line = svc.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="待重算排程", amount=6000)
    )
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 3, 31)
    )
    svc.confirm_occurrence(
        next(row.id for row in occurrences if row.line_id == first_line.id),
        ConfirmOccurrenceInput(confirmed_amount=5000),
    )

    svc.update_plan(
        plan.id,
        UpdatePlanInput(
            plan_name=plan.plan_name,
            start_date="2026-02-01",
            frequency="monthly",
            issue_day=1,
        ),
    )

    rows = svc.list_occurrences(plan_id=plan.id)
    assert any(
        row.line_id == first_line.id
        and row.expected_issue_date == "2026-01-01"
        and row.status == "confirmed"
        for row in rows
    )
    assert not any(
        row.line_id == second_line.id
        and row.expected_issue_date == "2026-01-01"
        and row.status == "pending"
        for row in rows
    )
    assert any(
        row.line_id == second_line.id
        and row.expected_issue_date == "2026-02-01"
        and row.status == "pending"
        for row in rows
    )


def test_bulk_confirm_is_atomic_and_uses_expected_amounts(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount=200))
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 1, 31)
    )

    confirmed = svc.confirm_occurrences_bulk([row.id for row in occurrences])

    assert [row.confirmed_amount for row in confirmed] == [100, 200]
    assert all(row.status == "confirmed" for row in confirmed)
    audit = conn.execute(
        "SELECT detail_json FROM audit_logs"
        " WHERE action = 'recurring_billing.occurrence.bulk_confirm'"
    ).fetchone()
    assert audit is not None and '"confirmed_count": 2' in audit["detail_json"]


def test_bulk_confirm_rolls_back_every_row_when_audit_fails(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount=200))
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 1, 31)
    )

    with patch.object(svc._audit, "record", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            svc.confirm_occurrences_bulk([row.id for row in occurrences])

    stored = [svc._repo.get_occurrence(row.id) for row in occurrences]
    assert all(row is not None and row.status == "pending" for row in stored)
    assert all(row is not None and row.confirmed_amount is None for row in stored)


def test_list_plans_for_client(conn, svc):
    cid = _seed_client(conn)
    _make_plan(svc, cid, plan_name="方案A")
    _make_plan(svc, cid, plan_name="方案B")
    plans = svc.list_plans(client_id=cid)
    assert len(plans) == 2


def test_list_plans_excludes_archived_by_default(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.archive_plan(plan.id)
    assert svc.list_plans(client_id=cid) == []


def test_list_plans_includes_archived_when_requested(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.archive_plan(plan.id)
    assert len(svc.list_plans(client_id=cid, include_archived=True)) == 1


def test_create_plan_invalid_frequency_raises(conn, svc):
    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid, frequency="weekly")
    assert exc.value.code == "recurring_billing.frequency.invalid"


def test_create_plan_invalid_issue_day_raises(conn, svc):
    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid, issue_day=0)
    assert exc.value.code == "recurring_billing.issue_day.invalid"


def test_create_plan_invalid_advance_notice_days_raises(conn, svc):
    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid, advance_notice_days=400)
    assert exc.value.code == "recurring_billing.advance_notice_days.invalid"


def test_create_plan_end_before_start_raises(conn, svc):
    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid, start_date="2026-06-01", end_date="2026-01-01")
    assert exc.value.code == "recurring_billing.date_range.invalid"


# ── line CRUD ─────────────────────────────────────────────────────────────────

def test_create_line_returns_row(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(
        plan_id=plan.id, bill_to_name="台積電", amount=50000
    ))
    assert line.id > 0
    assert line.amount == 50000
    assert line.active is True


def test_list_lines_for_plan(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A公司", amount=10000))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B公司", amount=20000))
    lines = svc.list_lines(plan.id)
    assert len(lines) == 2


def test_deactivate_line_sets_inactive(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="C公司", amount=5000))
    deactivated = svc.deactivate_line(line.id)
    assert deactivated.active is False


def test_deactivate_line_cancels_pending_occurrences_but_keeps_confirmed(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(
        svc,
        cid,
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=1,
    )
    line = svc.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="停用測試", amount=5000)
    )
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 2, 1)
    )
    svc.confirm_occurrence(
        occurrences[0].id,
        ConfirmOccurrenceInput(confirmed_amount=5000),
    )

    svc.deactivate_line(line.id)

    rows = svc.list_occurrences(line_id=line.id)
    assert [row.status for row in rows] == ["confirmed", "cancelled"]
    audit = conn.execute(
        """
        SELECT detail_json
        FROM audit_logs
        WHERE action = 'recurring_billing.line.deactivate'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert '"cancelled_pending_count": 1' in audit["detail_json"]


def test_update_line_amount(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="D公司", amount=5000))
    updated = svc.update_line(line.id, UpdateLineInput(bill_to_name="D公司", amount=9900))
    assert updated.amount == 9900


def test_update_line_rejects_archived_plan(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(
        plan_id=plan.id,
        bill_to_name="Archived contract",
        amount=5000,
    ))
    svc.archive_plan(plan.id)

    with pytest.raises(RecurringBillingError) as exc:
        svc.update_line(line.id, UpdateLineInput(
            bill_to_name="Rewritten history",
            amount=9900,
        ))

    assert exc.value.code == "recurring_billing.line.not_found"
    stored = conn.execute(
        "SELECT bill_to_name, amount FROM recurring_billing_lines WHERE id = ?",
        (line.id,),
    ).fetchone()
    assert (stored["bill_to_name"], stored["amount"]) == (
        "Archived contract",
        5000,
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE action = 'recurring_billing.line.update' AND target_id = ?",
        (str(line.id),),
    ).fetchone()[0] == 0


def test_create_line_negative_amount_raises(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    with pytest.raises(RecurringBillingError) as exc:
        svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="E公司", amount=-100))
    assert exc.value.code == "recurring_billing.amount.non_positive"


def test_create_line_zero_amount_raises(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    with pytest.raises(RecurringBillingError) as exc:
        svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="F公司", amount=0))
    assert exc.value.code == "recurring_billing.amount.non_positive"


def test_list_active_lines_excludes_inactive(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="G公司", amount=1000))
    svc.deactivate_line(line.id)
    assert svc.list_lines(plan.id, active_only=True) == []


# ── clamp_day pure function ───────────────────────────────────────────────────

def test_clamp_day_normal():
    assert _clamp_day(2026, 3, 15) == datetime.date(2026, 3, 15)


def test_clamp_day_31_in_april_clamps_to_30():
    assert _clamp_day(2026, 4, 31) == datetime.date(2026, 4, 30)


def test_clamp_day_31_in_february_regular_year_clamps_to_28():
    assert _clamp_day(2026, 2, 31) == datetime.date(2026, 2, 28)


def test_clamp_day_31_in_february_leap_year_clamps_to_29():
    assert _clamp_day(2024, 2, 31) == datetime.date(2024, 2, 29)


# ── occurrence generation ─────────────────────────────────────────────────────

def test_generate_monthly_creates_occurrences(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2026, 3, 31)
    occs = _generate_and_list(svc, plan.id, until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-01" in dates
    assert "2026-02-01" in dates
    assert "2026-03-01" in dates


def test_generate_occurrences_preserves_list_contract_and_audits(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))

    first = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 3, 31)
    )
    second = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 3, 31)
    )

    assert len(first) == 3
    assert {row.id for row in first} == {row.id for row in second}
    logs = conn.execute(
        """
        SELECT detail_json
          FROM audit_logs
         WHERE action = 'recurring_billing.occurrence.generate'
         ORDER BY id
        """
    ).fetchall()
    assert len(logs) == 2
    assert '"added_count": 3' in logs[0]["detail_json"]
    assert '"added_count": 0' in logs[1]["detail_json"]


def test_generate_occurrences_rolls_back_when_audit_fails(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))

    with patch.object(svc._audit, "record", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            svc.generate_occurrences(
                plan.id, until_date=datetime.date(2026, 3, 31)
            )

    assert svc.list_occurrences(plan_id=plan.id) == []


@pytest.mark.parametrize(
    ("column", "value", "expected_code"),
    [
        ("frequency", "weekly", "recurring_billing.frequency.invalid"),
        ("months_json", "{broken", "recurring_billing.months_json.invalid"),
        ("start_date", "not-a-date", "recurring_billing.start_date.invalid"),
        ("end_date", "not-a-date", "recurring_billing.end_date.invalid"),
    ],
)
def test_generate_rejects_invalid_persisted_plan_data(
    conn, svc, column, value, expected_code
):
    cid = _seed_client(conn)
    plan = _make_plan(
        svc,
        cid,
        start_date="2026-01-01",
        frequency="custom_months",
        months_json="[1, 4, 7, 10]",
        issue_day=1,
    )
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    conn.execute(
        f"UPDATE recurring_billing_plans SET {column} = ? WHERE id = ?",
        (value, plan.id),
    )
    conn.commit()

    with pytest.raises(RecurringBillingError) as exc:
        svc.generate_occurrences(
            plan.id, until_date=datetime.date(2026, 12, 31)
        )

    assert exc.value.code == expected_code
    assert svc.list_occurrences(plan_id=plan.id) == []


def test_generate_quarterly_from_start_month(conn, svc):
    cid = _seed_client(conn)
    # start March -> billing months: Mar, Jun, Sep, Dec
    plan = _make_plan(svc, cid, start_date="2026-03-01", frequency="quarterly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2027, 3, 31)
    occs = _generate_and_list(svc, plan.id, until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-03-01" in dates
    assert "2026-06-01" in dates
    assert "2026-09-01" in dates
    assert "2026-12-01" in dates
    assert "2027-03-01" in dates
    assert "2026-04-01" not in dates
    assert "2026-05-01" not in dates


def test_generate_semiannual(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="semiannual", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2027, 12, 31)
    occs = _generate_and_list(svc, plan.id, until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-01" in dates
    assert "2026-07-01" in dates
    assert "2027-01-01" in dates
    assert len(dates) == 4  # Jan 26, Jul 26, Jan 27, Jul 27


def test_generate_annual(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-05-01", frequency="annual", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2028, 12, 31)
    occs = _generate_and_list(svc, plan.id, until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-05-01" in dates
    assert "2027-05-01" in dates
    assert "2028-05-01" in dates
    assert len(dates) == 3


def test_generate_custom_months(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(
        svc, cid,
        start_date="2026-01-01",
        frequency="custom_months",
        months_json="[1, 4, 7, 10]",
        issue_day=15,
    )
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2026, 12, 31)
    occs = _generate_and_list(svc, plan.id, until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-15" in dates
    assert "2026-04-15" in dates
    assert "2026-07-15" in dates
    assert "2026-10-15" in dates
    assert len(dates) == 4


def test_generate_is_idempotent(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2026, 3, 31)
    first = svc.generate_occurrences(plan.id, until_date=until)
    second = svc.generate_occurrences(plan.id, until_date=until)
    assert len(first) == 3
    assert {row.id for row in first} == {row.id for row in second}


def test_generate_issue_day_31_feb_clamps(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-02-01", frequency="monthly", issue_day=31)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2026, 2, 28)
    occs = _generate_and_list(svc, plan.id, until)
    assert any(o.expected_issue_date == "2026-02-28" for o in occs)


def test_generate_issue_day_31_april_clamps(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-04-01", frequency="monthly", issue_day=31)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    until = datetime.date(2026, 4, 30)
    occs = _generate_and_list(svc, plan.id, until)
    assert any(o.expected_issue_date == "2026-04-30" for o in occs)


def test_generate_respects_end_date(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(
        svc, cid, start_date="2026-01-01", end_date="2026-03-01",
        frequency="monthly", issue_day=1,
    )
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    occs = _generate_and_list(svc, plan.id, datetime.date(2027, 12, 31))
    dates = [o.expected_issue_date for o in occs]
    assert "2026-04-01" not in dates
    assert "2026-03-01" in dates


def test_generate_with_until_date_param(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    occs = _generate_and_list(svc, plan.id, datetime.date(2026, 2, 28))
    dates = [o.expected_issue_date for o in occs]
    assert "2026-03-01" not in dates
    assert len(dates) == 2


def test_generate_plan_with_no_lines_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 6, 30)
    )
    assert occurrences == []


def test_generate_for_multiple_lines(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount=200))
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 2, 28)
    )
    assert len(occurrences) == 4  # 2 lines × 2 months


def test_generate_start_after_until_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2027-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 12, 31)
    )
    assert occurrences == []


def test_generate_archived_plan_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.archive_plan(plan.id)
    occurrences = svc.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 6, 30)
    )
    assert occurrences == []


# ── occurrence status ─────────────────────────────────────────────────────────

def _seed_occurrence(svc, conn):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=50000))
    occs = _generate_and_list(svc, plan.id, datetime.date(2026, 1, 31))
    return plan, occs[0]


def test_confirm_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    confirmed = svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(
        confirmed_amount=50000,
        confirmed_invoice_no="INV-001",
    ))
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_amount == 50000
    assert confirmed.confirmed_invoice_no == "INV-001"


def test_confirm_occurrence_sets_confirmed_at(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    confirmed = svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount=100))
    assert confirmed.confirmed_at is not None


def test_skip_occurrence_with_reason(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    skipped = svc.skip_occurrence(occ.id, reason="客戶取消")
    assert skipped.status == "skipped"
    assert skipped.skipped_reason == "客戶取消"


def test_cancel_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    cancelled = svc.cancel_occurrence(occ.id)
    assert cancelled.status == "cancelled"


def test_cancel_occurrence_writes_audit(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.cancel_occurrence(occ.id)
    logs = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'recurring_billing.occurrence.cancel'"
    ).fetchall()
    assert len(logs) == 1


def test_update_line_writes_audit(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.update_line(line.id, UpdateLineInput(bill_to_name="B", amount=200))
    logs = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'recurring_billing.line.update'"
    ).fetchall()
    assert len(logs) == 1


def test_deactivate_line_writes_audit(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.deactivate_line(line.id)
    logs = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'recurring_billing.line.deactivate'"
    ).fetchall()
    assert len(logs) == 1


def test_confirm_rejects_non_positive_confirmed_amount(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount=0))
    assert exc.value.code == "recurring_billing.confirmed_amount.non_positive"


def test_confirm_rejects_long_invoice_no(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(
            confirmed_amount=100,
            confirmed_invoice_no="X" * 51,
        ))
    assert exc.value.code == "recurring_billing.confirmed_invoice_no.too_long"


def test_cannot_confirm_skipped_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.skip_occurrence(occ.id, "test skip")
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount=100))
    assert exc.value.code == "recurring_billing.occurrence.not_pending"


def test_cannot_skip_confirmed_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount=100))
    with pytest.raises(RecurringBillingError) as exc:
        svc.skip_occurrence(occ.id, "test skip")
    assert exc.value.code == "recurring_billing.occurrence.not_pending"


# ── list / query occurrences ──────────────────────────────────────────────────

def test_list_occurrences_for_plan(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="quarterly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 12, 31))
    occs = svc.list_occurrences(plan_id=plan.id)
    assert len(occs) == 4  # Jan, Apr, Jul, Oct


def test_list_pending_occurrences(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    pending = svc.list_occurrences(plan_id=plan.id, status="pending")
    assert all(o.status == "pending" for o in pending)


def test_list_occurrences_by_status_after_confirm(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount=100))
    confirmed = svc.list_occurrences(plan_id=plan.id, status="confirmed")
    assert len(confirmed) == 1


def test_list_occurrences_for_line(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    line_a = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount=200))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 3, 31))
    occs_a = svc.list_occurrences(line_id=line_a.id)
    assert all(o.line_id == line_a.id for o in occs_a)
    assert len(occs_a) == 3


def test_upcoming_notices_within_advance_notice_days(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly",
                      issue_day=10, advance_notice_days=14)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 3, 31))
    # ref = 2026-01-01, window = 14 days => up to 2026-01-15
    ref = datetime.date(2026, 1, 1)
    notices = svc.upcoming_notices(today=ref)
    dates = [o.expected_issue_date for o in notices]
    assert "2026-01-10" in dates
    assert "2026-02-10" not in dates


def test_upcoming_notices_respects_zero_advance_notice_days(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-02-01", frequency="monthly",
                      issue_day=1, advance_notice_days=0)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    # ref = 2026-01-31, window = 0 days => only up to 2026-01-31; issue date 2026-02-01 excluded
    ref = datetime.date(2026, 1, 31)
    notices = svc.upcoming_notices(today=ref)
    assert notices == []


def test_occurrence_summary_counts_by_status(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 3, 31))
    occs = svc.list_occurrences(plan_id=plan.id)
    svc.confirm_occurrence(occs[0].id, ConfirmOccurrenceInput(confirmed_amount=100))
    svc.skip_occurrence(occs[1].id, "test skip")
    summary = svc.get_occurrence_summary(plan.id)
    assert summary["confirmed"] == 1
    assert summary["skipped"] == 1
    assert summary["pending"] == 1


@pytest.mark.parametrize("months_json", ['{}', '[0]', '[13]', '["1"]'])
def test_custom_months_rejects_non_month_values(conn, svc, months_json):
    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as exc:
        _make_plan(svc, cid, frequency="custom_months", months_json=months_json)
    assert exc.value.code == "recurring_billing.months_json.invalid"


def test_bulk_parser_rejects_blank_bill_to():
    from taxops.services.recurring_billing import parse_bulk_lines

    rows, errors = parse_bulk_lines("\t100")

    assert rows == []
    assert errors and errors[0][0] == 1


def test_create_plan_with_lines_rejects_missing_client_and_blank_bill_to(conn, svc):
    plan_input = CreatePlanInput(
        client_id=999999,
        plan_name="Missing client",
        start_date="2026-01-01",
    )
    with pytest.raises(RecurringBillingError) as missing_client:
        svc.create_plan_with_lines(
            plan_input,
            [CreateLineInput(plan_id=0, bill_to_name="A", amount=100)],
        )
    assert missing_client.value.code == "recurring_billing.client_not_found"

    cid = _seed_client(conn)
    with pytest.raises(RecurringBillingError) as blank_name:
        svc.create_plan_with_lines(
            CreatePlanInput(client_id=cid, plan_name="Plan", start_date="2026-01-01"),
            [CreateLineInput(plan_id=0, bill_to_name=" ", amount=100)],
        )
    assert blank_name.value.code == "recurring_billing.bill_to_name.empty"


def test_plan_mutations_report_missing_rows_even_after_race(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    update = UpdatePlanInput(
        plan_name="Plan",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=15,
    )

    with pytest.raises(RecurringBillingError) as missing_update:
        svc.update_plan(999999, update)
    assert missing_update.value.code == "recurring_billing.plan.not_found"

    with patch.object(svc._repo, "update_plan", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_update:
            svc.update_plan(plan.id, update)
    assert raced_update.value.code == "recurring_billing.plan.not_found"

    with pytest.raises(RecurringBillingError) as missing_archive:
        svc.archive_plan(999999)
    assert missing_archive.value.code == "recurring_billing.plan.not_found"

    with patch.object(svc._repo, "set_plan_status", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_archive:
            svc.archive_plan(plan.id)
    assert raced_archive.value.code == "recurring_billing.plan.not_found"

    with pytest.raises(RecurringBillingError) as missing_delete:
        svc.delete_plan(999999)
    assert missing_delete.value.code == "recurring_billing.plan.not_found"


def test_line_mutations_reject_missing_invalid_and_raced_rows(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount=100))

    for bad_input, code in (
        (CreateLineInput(plan_id=999999, bill_to_name="A", amount=100), "recurring_billing.plan.not_found"),
        (CreateLineInput(plan_id=plan.id, bill_to_name=" ", amount=100), "recurring_billing.bill_to_name.empty"),
    ):
        with pytest.raises(RecurringBillingError) as exc:
            svc.create_line(bad_input)
        assert exc.value.code == code

    for line_id, bad_input, code in (
        (999999, UpdateLineInput(bill_to_name="A", amount=100), "recurring_billing.line.not_found"),
        (line.id, UpdateLineInput(bill_to_name=" ", amount=100), "recurring_billing.bill_to_name.empty"),
        (line.id, UpdateLineInput(bill_to_name="A", amount=0), "recurring_billing.amount.non_positive"),
    ):
        with pytest.raises(RecurringBillingError) as exc:
            svc.update_line(line_id, bad_input)
        assert exc.value.code == code

    with patch.object(svc._repo, "update_line", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_update:
            svc.update_line(line.id, UpdateLineInput(bill_to_name="A", amount=100))
    assert raced_update.value.code == "recurring_billing.line.not_found"

    with pytest.raises(RecurringBillingError) as missing_deactivate:
        svc.deactivate_line(999999)
    assert missing_deactivate.value.code == "recurring_billing.line.not_found"

    with patch.object(svc._repo, "set_line_active", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_deactivate:
            svc.deactivate_line(line.id)
    assert raced_deactivate.value.code == "recurring_billing.line.not_found"


def test_occurrence_mutations_cover_missing_invalid_and_raced_rows(conn, svc):
    plan, occurrence = _seed_occurrence(svc, conn)

    with pytest.raises(RecurringBillingError) as missing_confirm:
        svc.confirm_occurrence(999999, ConfirmOccurrenceInput(confirmed_amount=100))
    assert missing_confirm.value.code == "recurring_billing.occurrence.not_found"

    with pytest.raises(RecurringBillingError) as invalid_date:
        svc.confirm_occurrence(
            occurrence.id,
            ConfirmOccurrenceInput(confirmed_amount=100, confirmed_issue_date="not-a-date"),
        )
    assert invalid_date.value.code == "recurring_billing.confirmed_issue_date.invalid"

    with patch.object(svc._repo, "update_occurrence_status", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_confirm:
            svc.confirm_occurrence(occurrence.id, ConfirmOccurrenceInput(confirmed_amount=100))
    assert raced_confirm.value.code == "recurring_billing.occurrence.not_found"

    with pytest.raises(RecurringBillingError) as missing_skip:
        svc.skip_occurrence(999999, "reason")
    assert missing_skip.value.code == "recurring_billing.occurrence.not_found"

    with patch.object(svc._repo, "update_occurrence_status", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_skip:
            svc.skip_occurrence(occurrence.id, "reason")
    assert raced_skip.value.code == "recurring_billing.occurrence.not_found"

    with pytest.raises(RecurringBillingError) as missing_cancel:
        svc.cancel_occurrence(999999)
    assert missing_cancel.value.code == "recurring_billing.occurrence.not_found"

    confirmed = svc.confirm_occurrence(
        occurrence.id, ConfirmOccurrenceInput(confirmed_amount=100)
    )
    with pytest.raises(RecurringBillingError) as confirmed_cancel:
        svc.cancel_occurrence(confirmed.id)
    assert confirmed_cancel.value.code == "recurring_billing.occurrence.cannot_cancel_confirmed"

    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    occurrence2 = svc.list_occurrences(plan_id=plan.id, status="pending")[0]
    with patch.object(svc._repo, "update_occurrence_status", return_value=None):
        with pytest.raises(RecurringBillingError) as raced_cancel:
            svc.cancel_occurrence(occurrence2.id)
    assert raced_cancel.value.code == "recurring_billing.occurrence.not_found"


def test_bulk_confirm_rejects_every_invalid_precondition(conn, svc):
    with pytest.raises(RecurringBillingError) as empty:
        svc.confirm_occurrences_bulk([])
    assert empty.value.code == "recurring_billing.bulk_selection.empty"

    with pytest.raises(RecurringBillingError) as missing:
        svc.confirm_occurrences_bulk([999999])
    assert missing.value.code == "recurring_billing.occurrence.not_found"

    plan, occurrence = _seed_occurrence(svc, conn)
    svc.skip_occurrence(occurrence.id, "skip")
    with pytest.raises(RecurringBillingError) as non_pending:
        svc.confirm_occurrences_bulk([occurrence.id])
    assert non_pending.value.code == "recurring_billing.occurrence.not_pending"

    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    occurrence2 = svc.list_occurrences(plan_id=plan.id, status="pending")[0]
    with patch.object(svc._repo, "get_plan", return_value=None):
        with pytest.raises(RecurringBillingError) as missing_plan:
            svc.confirm_occurrences_bulk([occurrence2.id])
    assert missing_plan.value.code == "recurring_billing.plan.not_found"

    with patch.object(svc._repo, "get_line", return_value=None):
        with pytest.raises(RecurringBillingError) as missing_line:
            svc.confirm_occurrences_bulk([occurrence2.id])
    assert missing_line.value.code == "recurring_billing.line.not_found"

    with patch.object(svc._repo, "update_occurrence_status", return_value=None):
        with pytest.raises(RecurringBillingError) as raced:
            svc.confirm_occurrences_bulk([occurrence2.id])
    assert raced.value.code == "recurring_billing.occurrence.not_found"
