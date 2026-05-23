"""Repository for recurring_billing_plans, lines, and occurrences."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class PlanRow:
    id: int
    client_id: int
    plan_name: str
    contract_ref: str | None
    frequency: str
    issue_day: int
    months_json: str
    start_date: str
    end_date: str | None
    advance_notice_days: int
    status: str
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class LineRow:
    id: int
    plan_id: int
    bill_to_name: str
    description: str | None
    amount: int
    tax_type: str | None
    sort_order: int
    active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OccurrenceRow:
    id: int
    plan_id: int
    line_id: int
    expected_issue_date: str
    status: str
    confirmed_invoice_no: str | None
    confirmed_issue_date: str | None
    confirmed_amount: int | None
    confirmed_at: str | None
    skipped_reason: str | None
    notes: str | None
    created_at: str
    updated_at: str


def _plan(r: sqlite3.Row) -> PlanRow:
    return PlanRow(
        id=r["id"],
        client_id=r["client_id"],
        plan_name=r["plan_name"],
        contract_ref=r["contract_ref"],
        frequency=r["frequency"],
        issue_day=r["issue_day"],
        months_json=r["months_json"],
        start_date=r["start_date"],
        end_date=r["end_date"],
        advance_notice_days=r["advance_notice_days"],
        status=r["status"],
        notes=r["notes"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        deleted_at=r["deleted_at"],
    )


def _line(r: sqlite3.Row) -> LineRow:
    return LineRow(
        id=r["id"],
        plan_id=r["plan_id"],
        bill_to_name=r["bill_to_name"],
        description=r["description"],
        amount=r["amount"],
        tax_type=r["tax_type"],
        sort_order=r["sort_order"],
        active=bool(r["active"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _occ(r: sqlite3.Row) -> OccurrenceRow:
    return OccurrenceRow(
        id=r["id"],
        plan_id=r["plan_id"],
        line_id=r["line_id"],
        expected_issue_date=r["expected_issue_date"],
        status=r["status"],
        confirmed_invoice_no=r["confirmed_invoice_no"],
        confirmed_issue_date=r["confirmed_issue_date"],
        confirmed_amount=r["confirmed_amount"],
        confirmed_at=r["confirmed_at"],
        skipped_reason=r["skipped_reason"],
        notes=r["notes"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class RecurringBillingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── plans ─────────────────────────────────────────────────────────────────

    def insert_plan(
        self,
        client_id: int,
        plan_name: str,
        contract_ref: str | None,
        frequency: str,
        issue_day: int,
        months_json: str,
        start_date: str,
        end_date: str | None,
        advance_notice_days: int,
        notes: str | None,
    ) -> PlanRow:
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO recurring_billing_plans
                (client_id, plan_name, contract_ref, frequency, issue_day,
                 months_json, start_date, end_date, advance_notice_days,
                 status, notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                client_id, plan_name, contract_ref, frequency, issue_day,
                months_json, start_date, end_date, advance_notice_days,
                "active", notes, now, now,
            ),
        )
        self._conn.commit()
        return self.get_plan(cur.lastrowid)  # type: ignore[arg-type]

    def get_plan(self, plan_id: int) -> PlanRow | None:
        r = self._conn.execute(
            "SELECT * FROM recurring_billing_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return _plan(r) if r else None

    def update_plan(
        self,
        plan_id: int,
        plan_name: str,
        contract_ref: str | None,
        frequency: str,
        issue_day: int,
        months_json: str,
        start_date: str,
        end_date: str | None,
        advance_notice_days: int,
        notes: str | None,
    ) -> PlanRow | None:
        now = now_iso()
        self._conn.execute(
            """
            UPDATE recurring_billing_plans
               SET plan_name=?, contract_ref=?, frequency=?, issue_day=?,
                   months_json=?, start_date=?, end_date=?,
                   advance_notice_days=?, notes=?, updated_at=?
             WHERE id=?
            """,
            (
                plan_name, contract_ref, frequency, issue_day,
                months_json, start_date, end_date, advance_notice_days,
                notes, now, plan_id,
            ),
        )
        self._conn.commit()
        return self.get_plan(plan_id)

    def set_plan_status(
        self, plan_id: int, status: str, deleted_at: str | None = None
    ) -> PlanRow | None:
        now = now_iso()
        self._conn.execute(
            "UPDATE recurring_billing_plans SET status=?, deleted_at=?, updated_at=? WHERE id=?",
            (status, deleted_at, now, plan_id),
        )
        self._conn.commit()
        return self.get_plan(plan_id)

    def list_plans(
        self, client_id: int | None = None, include_archived: bool = False
    ) -> list[PlanRow]:
        clauses: list[str] = []
        params: list[object] = []
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        if not include_archived:
            clauses.append("status != 'archived'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM recurring_billing_plans {where} ORDER BY id",
            params,
        ).fetchall()
        return [_plan(r) for r in rows]

    # ── lines ─────────────────────────────────────────────────────────────────

    def insert_line(
        self,
        plan_id: int,
        bill_to_name: str,
        description: str | None,
        amount: int,
        tax_type: str | None,
        sort_order: int,
    ) -> LineRow:
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO recurring_billing_lines
                (plan_id, bill_to_name, description, amount,
                 tax_type, sort_order, active, created_at, updated_at)
            VALUES (?,?,?,?,?,?,1,?,?)
            """,
            (plan_id, bill_to_name, description, amount, tax_type, sort_order, now, now),
        )
        self._conn.commit()
        return self.get_line(cur.lastrowid)  # type: ignore[arg-type]

    def get_line(self, line_id: int) -> LineRow | None:
        r = self._conn.execute(
            "SELECT * FROM recurring_billing_lines WHERE id = ?", (line_id,)
        ).fetchone()
        return _line(r) if r else None

    def update_line(
        self,
        line_id: int,
        bill_to_name: str,
        description: str | None,
        amount: int,
        tax_type: str | None,
        sort_order: int,
    ) -> LineRow | None:
        now = now_iso()
        self._conn.execute(
            """
            UPDATE recurring_billing_lines
               SET bill_to_name=?, description=?, amount=?,
                   tax_type=?, sort_order=?, updated_at=?
             WHERE id=?
            """,
            (bill_to_name, description, amount, tax_type, sort_order, now, line_id),
        )
        self._conn.commit()
        return self.get_line(line_id)

    def set_line_active(self, line_id: int, active: bool) -> LineRow | None:
        now = now_iso()
        self._conn.execute(
            "UPDATE recurring_billing_lines SET active=?, updated_at=? WHERE id=?",
            (int(active), now, line_id),
        )
        self._conn.commit()
        return self.get_line(line_id)

    def list_lines(self, plan_id: int, active_only: bool = False) -> list[LineRow]:
        if active_only:
            rows = self._conn.execute(
                "SELECT * FROM recurring_billing_lines WHERE plan_id=? AND active=1 ORDER BY sort_order, id",
                (plan_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM recurring_billing_lines WHERE plan_id=? ORDER BY sort_order, id",
                (plan_id,),
            ).fetchall()
        return [_line(r) for r in rows]

    # ── occurrences ───────────────────────────────────────────────────────────

    def insert_occurrence_if_missing(
        self,
        plan_id: int,
        line_id: int,
        expected_issue_date: str,
    ) -> None:
        now = now_iso()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO recurring_billing_occurrences
                (plan_id, line_id, expected_issue_date, status, created_at, updated_at)
            VALUES (?,?,?,'pending',?,?)
            """,
            (plan_id, line_id, expected_issue_date, now, now),
        )

    def commit(self) -> None:
        self._conn.commit()

    def get_occurrence(self, occurrence_id: int) -> OccurrenceRow | None:
        r = self._conn.execute(
            "SELECT * FROM recurring_billing_occurrences WHERE id = ?", (occurrence_id,)
        ).fetchone()
        return _occ(r) if r else None

    def update_occurrence_status(
        self,
        occurrence_id: int,
        status: str,
        confirmed_invoice_no: str | None = None,
        confirmed_issue_date: str | None = None,
        confirmed_amount: int | None = None,
        confirmed_at: str | None = None,
        skipped_reason: str | None = None,
        notes: str | None = None,
    ) -> OccurrenceRow | None:
        now = now_iso()
        self._conn.execute(
            """
            UPDATE recurring_billing_occurrences
               SET status=?, confirmed_invoice_no=?, confirmed_issue_date=?,
                   confirmed_amount=?, confirmed_at=?,
                   skipped_reason=?, notes=?, updated_at=?
             WHERE id=?
            """,
            (
                status, confirmed_invoice_no, confirmed_issue_date,
                confirmed_amount, confirmed_at,
                skipped_reason, notes, now, occurrence_id,
            ),
        )
        self._conn.commit()
        return self.get_occurrence(occurrence_id)

    def list_occurrences(
        self,
        plan_id: int | None = None,
        line_id: int | None = None,
        status: str | None = None,
        before_date: str | None = None,
    ) -> list[OccurrenceRow]:
        clauses: list[str] = []
        params: list[object] = []
        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if line_id is not None:
            clauses.append("line_id = ?")
            params.append(line_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if before_date is not None:
            clauses.append("expected_issue_date <= ?")
            params.append(before_date)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM recurring_billing_occurrences {where} ORDER BY expected_issue_date, id",
            params,
        ).fetchall()
        return [_occ(r) for r in rows]

    def count_occurrences_by_status(self, plan_id: int) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT status, COUNT(*) AS cnt
              FROM recurring_billing_occurrences
             WHERE plan_id = ?
             GROUP BY status
            """,
            (plan_id,),
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}
