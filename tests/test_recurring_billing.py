"""Tests for Slice 18A: RecurringBillingService + RecurringBillingRepository."""

from __future__ import annotations

import datetime

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
        plan_id=plan.id, bill_to_name="台積電", amount_cents=50000
    ))
    assert line.id > 0
    assert line.amount_cents == 50000
    assert line.active is True


def test_list_lines_for_plan(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A公司", amount_cents=10000))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B公司", amount_cents=20000))
    lines = svc.list_lines(plan.id)
    assert len(lines) == 2


def test_deactivate_line_sets_inactive(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="C公司", amount_cents=5000))
    deactivated = svc.deactivate_line(line.id)
    assert deactivated.active is False


def test_update_line_amount(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="D公司", amount_cents=5000))
    updated = svc.update_line(line.id, UpdateLineInput(bill_to_name="D公司", amount_cents=9900))
    assert updated.amount_cents == 9900


def test_create_line_negative_amount_raises(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    with pytest.raises(RecurringBillingError) as exc:
        svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="E公司", amount_cents=-100))
    assert exc.value.code == "recurring_billing.amount_cents.non_positive"


def test_create_line_zero_amount_raises(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    with pytest.raises(RecurringBillingError) as exc:
        svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="F公司", amount_cents=0))
    assert exc.value.code == "recurring_billing.amount_cents.non_positive"


def test_list_active_lines_excludes_inactive(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid)
    line = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="G公司", amount_cents=1000))
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
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2026, 3, 31)
    occs = svc.generate_occurrences(plan.id, until_date=until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-01" in dates
    assert "2026-02-01" in dates
    assert "2026-03-01" in dates


def test_generate_quarterly_from_start_month(conn, svc):
    cid = _seed_client(conn)
    # start March -> billing months: Mar, Jun, Sep, Dec
    plan = _make_plan(svc, cid, start_date="2026-03-01", frequency="quarterly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2027, 3, 31)
    occs = svc.generate_occurrences(plan.id, until_date=until)
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
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2027, 12, 31)
    occs = svc.generate_occurrences(plan.id, until_date=until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-01" in dates
    assert "2026-07-01" in dates
    assert "2027-01-01" in dates
    assert len(dates) == 4  # Jan 26, Jul 26, Jan 27, Jul 27


def test_generate_annual(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-05-01", frequency="annual", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2028, 12, 31)
    occs = svc.generate_occurrences(plan.id, until_date=until)
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
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2026, 12, 31)
    occs = svc.generate_occurrences(plan.id, until_date=until)
    dates = [o.expected_issue_date for o in occs]
    assert "2026-01-15" in dates
    assert "2026-04-15" in dates
    assert "2026-07-15" in dates
    assert "2026-10-15" in dates
    assert len(dates) == 4


def test_generate_is_idempotent(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2026, 3, 31)
    first = svc.generate_occurrences(plan.id, until_date=until)
    second = svc.generate_occurrences(plan.id, until_date=until)
    assert len(first) == len(second)
    assert {o.id for o in first} == {o.id for o in second}


def test_generate_issue_day_31_feb_clamps(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-02-01", frequency="monthly", issue_day=31)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2026, 2, 28)
    occs = svc.generate_occurrences(plan.id, until_date=until)
    assert any(o.expected_issue_date == "2026-02-28" for o in occs)


def test_generate_issue_day_31_april_clamps(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-04-01", frequency="monthly", issue_day=31)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    until = datetime.date(2026, 4, 30)
    occs = svc.generate_occurrences(plan.id, until_date=until)
    assert any(o.expected_issue_date == "2026-04-30" for o in occs)


def test_generate_respects_end_date(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(
        svc, cid, start_date="2026-01-01", end_date="2026-03-01",
        frequency="monthly", issue_day=1,
    )
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2027, 12, 31))
    dates = [o.expected_issue_date for o in occs]
    assert "2026-04-01" not in dates
    assert "2026-03-01" in dates


def test_generate_with_until_date_param(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    dates = [o.expected_issue_date for o in occs]
    assert "2026-03-01" not in dates
    assert len(dates) == 2


def test_generate_plan_with_no_lines_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 6, 30))
    assert occs == []


def test_generate_for_multiple_lines(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount_cents=200))
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    assert len(occs) == 4  # 2 lines × 2 months


def test_generate_start_after_until_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2027-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 12, 31))
    assert occs == []


def test_generate_archived_plan_returns_empty(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.archive_plan(plan.id)
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 6, 30))
    assert occs == []


# ── occurrence status ─────────────────────────────────────────────────────────

def _seed_occurrence(svc, conn):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=50000))
    occs = svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 1, 31))
    return plan, occs[0]


def test_confirm_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    confirmed = svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(
        confirmed_amount_cents=50000,
        confirmed_invoice_no="INV-001",
    ))
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_amount_cents == 50000
    assert confirmed.confirmed_invoice_no == "INV-001"


def test_confirm_occurrence_sets_confirmed_at(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    confirmed = svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount_cents=100))
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


def test_confirm_rejects_non_positive_amount_cents(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount_cents=0))
    assert exc.value.code == "recurring_billing.confirmed_amount_cents.non_positive"


def test_confirm_rejects_long_invoice_no(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(
            confirmed_amount_cents=100,
            confirmed_invoice_no="X" * 51,
        ))
    assert exc.value.code == "recurring_billing.confirmed_invoice_no.too_long"


def test_cannot_confirm_skipped_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.skip_occurrence(occ.id)
    with pytest.raises(RecurringBillingError) as exc:
        svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount_cents=100))
    assert exc.value.code == "recurring_billing.occurrence.not_pending"


def test_cannot_skip_confirmed_occurrence(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount_cents=100))
    with pytest.raises(RecurringBillingError) as exc:
        svc.skip_occurrence(occ.id)
    assert exc.value.code == "recurring_billing.occurrence.not_pending"


# ── list / query occurrences ──────────────────────────────────────────────────

def test_list_occurrences_for_plan(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="quarterly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 12, 31))
    occs = svc.list_occurrences(plan_id=plan.id)
    assert len(occs) == 4  # Jan, Apr, Jul, Oct


def test_list_pending_occurrences(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    pending = svc.list_occurrences(plan_id=plan.id, status="pending")
    assert all(o.status == "pending" for o in pending)


def test_list_occurrences_by_status_after_confirm(conn, svc):
    plan, occ = _seed_occurrence(svc, conn)
    svc.confirm_occurrence(occ.id, ConfirmOccurrenceInput(confirmed_amount_cents=100))
    confirmed = svc.list_occurrences(plan_id=plan.id, status="confirmed")
    assert len(confirmed) == 1


def test_list_occurrences_for_line(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    line_a = svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="B", amount_cents=200))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 3, 31))
    occs_a = svc.list_occurrences(line_id=line_a.id)
    assert all(o.line_id == line_a.id for o in occs_a)
    assert len(occs_a) == 3


def test_upcoming_notices_within_advance_notice_days(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly",
                      issue_day=10, advance_notice_days=14)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
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
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 2, 28))
    # ref = 2026-01-31, window = 0 days => only up to 2026-01-31; issue date 2026-02-01 excluded
    ref = datetime.date(2026, 1, 31)
    notices = svc.upcoming_notices(today=ref)
    assert notices == []


def test_occurrence_summary_counts_by_status(conn, svc):
    cid = _seed_client(conn)
    plan = _make_plan(svc, cid, start_date="2026-01-01", frequency="monthly", issue_day=1)
    svc.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="A", amount_cents=100))
    svc.generate_occurrences(plan.id, until_date=datetime.date(2026, 3, 31))
    occs = svc.list_occurrences(plan_id=plan.id)
    svc.confirm_occurrence(occs[0].id, ConfirmOccurrenceInput(confirmed_amount_cents=100))
    svc.skip_occurrence(occs[1].id)
    summary = svc.get_occurrence_summary(plan.id)
    assert summary["confirmed"] == 1
    assert summary["skipped"] == 1
    assert summary["pending"] == 1
