"""Tests for LateFeeService + LateFeeRepository + calculate_penalty_percent (Slice 8)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.document_requests import DocumentRequestsRepository
from taxops.repositories.late_fee import LateFeeRepository
from taxops.services.audit import AuditService
from taxops.services.late_fee import (
    CalculateLateFeeInput,
    LateFeeService,
    LateFeeValidationError,
    calculate_overdue_days,
    calculate_penalty_percent,
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
    return LateFeeService(
        repo=LateFeeRepository(conn),
        doc_requests_repo=DocumentRequestsRepository(conn),
        audit=audit,
    )


def _seed_request(conn, tax_type: str = "vat") -> int:
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) VALUES ('C001', '測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO engagements
           (client_id, engagement_name, tax_type, period_name, status, created_at, updated_at)
           VALUES (?, '案件', ?, '2024Q1', 'draft', '2026-01-01T00:00:00', '2026-01-01T00:00:00')""",
        (client_id, tax_type),
    )
    eng_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO document_requests
           (engagement_id, period_name, tax_type, status, created_at, updated_at)
           VALUES (?, '2024Q1', ?, 'not_requested', '2026-01-01T00:00:00', '2026-01-01T00:00:00')""",
        (eng_id, tax_type),
    )
    req_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return req_id


# ── schema ────────────────────────────────────────────────────────────────────

def test_late_fee_records_table_exists(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "late_fee_records" in tables


def test_late_fee_records_fk_columns(conn):
    fk_rows = conn.execute("PRAGMA foreign_key_list(late_fee_records)").fetchall()
    tables = {row["table"] for row in fk_rows}
    assert "document_requests" in tables


# ── calculate_penalty_percent pure function ────────────────────────────────────

@pytest.mark.parametrize("days,expected", [
    (0, 0.0),
    (1, 0.0),
    (2, 0.0),
    (3, 0.0),
    (4, 1.0),
    (6, 1.0),
    (7, 2.0),
    (10, 3.0),
    (30, 9.0),
    (31, 10.0),
    (100, 10.0),
])
def test_calculate_penalty_percent(days, expected):
    assert calculate_penalty_percent(days) == expected


@pytest.mark.parametrize("last_day,paid_day,expected", [
    ("2024-12-02", "2024-12-02", 0),
    ("2024-12-02", "2024-12-03", 1),
    ("2024-12-02", "2024-12-05", 3),
    ("2024-12-02", "2024-12-06", 4),
])
def test_calculate_overdue_days_from_payment_dates(last_day, paid_day, expected):
    assert calculate_overdue_days(last_day, paid_day) == expected


def test_calculate_overdue_days_rejects_bad_date():
    with pytest.raises(LateFeeValidationError) as exc:
        calculate_overdue_days("2024/12/02", "2024-12-06")
    assert exc.value.code == "late_fee.date.invalid"


# ── service: calculate_and_save ───────────────────────────────────────────────

def test_calculate_and_save_vat(conn, svc):
    req_id = _seed_request(conn, "vat")
    row = svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id, overdue_days=7, base_amount=10000.0
    ))
    assert row.penalty_percent == 2.0
    assert row.penalty_amount == 200.0
    assert row.tax_type == "vat"
    assert row.needs_manual_review is False


def test_calculate_and_save_uses_payment_dates(conn, svc):
    req_id = _seed_request(conn, "vat")
    row = svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id,
        overdue_days=0,
        base_amount=10000.0,
        last_payment_date="2024-12-02",
        actual_payment_date="2024-12-06",
    ))
    assert row.overdue_days == 4
    assert row.penalty_percent == 1.0
    assert row.penalty_amount == 100.0


def test_calculate_and_save_no_penalty_within_3_days(conn, svc):
    req_id = _seed_request(conn, "vat")
    row = svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id, overdue_days=3, base_amount=5000.0
    ))
    assert row.penalty_percent == 0.0
    assert row.penalty_amount == 0.0


def test_calculate_and_save_labor_health_manual_review(conn, svc):
    req_id = _seed_request(conn, "labor_health")
    row = svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id, overdue_days=30, base_amount=50000.0
    ))
    assert row.needs_manual_review is True
    assert row.penalty_percent == 0.0
    assert row.penalty_amount == 0.0


def test_calculate_and_save_cap_at_10_percent(conn, svc):
    req_id = _seed_request(conn, "cit")
    row = svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id, overdue_days=100, base_amount=1000.0
    ))
    assert row.penalty_percent == 10.0
    assert row.penalty_amount == 100.0


def test_calculate_and_save_records_audit(conn, svc):
    req_id = _seed_request(conn, "vat")
    svc.calculate_and_save(CalculateLateFeeInput(
        request_id=req_id, overdue_days=10, base_amount=1000.0
    ))
    row = conn.execute(
        "SELECT action FROM audit_logs WHERE action='late_fee.calculate' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


def test_calculate_negative_days_rejected(conn, svc):
    req_id = _seed_request(conn, "vat")
    with pytest.raises(LateFeeValidationError) as exc:
        svc.calculate_and_save(CalculateLateFeeInput(
            request_id=req_id, overdue_days=-1, base_amount=1000.0
        ))
    assert exc.value.code == "late_fee.negative_overdue_days"


def test_calculate_negative_base_rejected(conn, svc):
    req_id = _seed_request(conn, "vat")
    with pytest.raises(LateFeeValidationError) as exc:
        svc.calculate_and_save(CalculateLateFeeInput(
            request_id=req_id, overdue_days=5, base_amount=-100.0
        ))
    assert exc.value.code == "late_fee.negative_base_amount"


def test_calculate_request_not_found(conn, svc):
    with pytest.raises(LateFeeValidationError) as exc:
        svc.calculate_and_save(CalculateLateFeeInput(
            request_id=99999, overdue_days=5, base_amount=1000.0
        ))
    assert exc.value.code == "late_fee.request_not_found"


# ── list_by_request ───────────────────────────────────────────────────────────

def test_list_by_request_multiple(conn, svc):
    req_id = _seed_request(conn, "vat")
    svc.calculate_and_save(CalculateLateFeeInput(request_id=req_id, overdue_days=4, base_amount=1000.0))
    svc.calculate_and_save(CalculateLateFeeInput(request_id=req_id, overdue_days=7, base_amount=2000.0))
    records = svc.list_by_request(req_id)
    assert len(records) == 2


def test_list_by_request_empty(conn, svc):
    req_id = _seed_request(conn, "vat")
    assert svc.list_by_request(req_id) == []


# ── date pair validation ───────────────────────────────────────────────────────

def test_only_last_payment_date_raises(conn, svc):
    req_id = _seed_request(conn)
    with pytest.raises(LateFeeValidationError) as exc_info:
        svc.calculate_and_save(
            CalculateLateFeeInput(
                request_id=req_id,
                overdue_days=0,
                base_amount=1000.0,
                last_payment_date="2026-05-01",
                actual_payment_date=None,
            )
        )
    assert exc_info.value.code == "late_fee.date.required_pair"


def test_only_actual_payment_date_raises(conn, svc):
    req_id = _seed_request(conn)
    with pytest.raises(LateFeeValidationError) as exc_info:
        svc.calculate_and_save(
            CalculateLateFeeInput(
                request_id=req_id,
                overdue_days=0,
                base_amount=1000.0,
                last_payment_date=None,
                actual_payment_date="2026-05-10",
            )
        )
    assert exc_info.value.code == "late_fee.date.required_pair"


def test_actual_equals_last_payment_date_gives_zero_days(conn, svc):
    req_id = _seed_request(conn)
    row = svc.calculate_and_save(
        CalculateLateFeeInput(
            request_id=req_id,
            overdue_days=0,
            base_amount=5000.0,
            last_payment_date="2026-05-10",
            actual_payment_date="2026-05-10",
        )
    )
    assert row.overdue_days == 0
    assert row.penalty_amount == 0.0


def test_actual_one_day_after_last_payment_date_gives_one_day(conn, svc):
    req_id = _seed_request(conn)
    row = svc.calculate_and_save(
        CalculateLateFeeInput(
            request_id=req_id,
            overdue_days=0,
            base_amount=5000.0,
            last_payment_date="2026-05-10",
            actual_payment_date="2026-05-11",
        )
    )
    assert row.overdue_days == 1


def test_actual_before_last_payment_date_raises_range_invalid(conn, svc):
    """Reverse dates must raise, not silently store 0 days."""
    req_id = _seed_request(conn)
    with pytest.raises(LateFeeValidationError) as exc:
        svc.calculate_and_save(
            CalculateLateFeeInput(
                request_id=req_id,
                overdue_days=0,
                base_amount=5000.0,
                last_payment_date="2026-05-10",
                actual_payment_date="2026-05-01",
            )
        )
    assert exc.value.code == "late_fee.date.range_invalid"
    assert len(svc.list_by_request(req_id)) == 0
