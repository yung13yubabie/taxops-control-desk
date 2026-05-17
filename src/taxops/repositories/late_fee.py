"""Repository for late_fee_records table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class LateFeeRow:
    id: int
    request_id: int
    overdue_days: int
    penalty_percent: float
    base_amount: float
    penalty_amount: float
    tax_type: str
    needs_manual_review: bool
    calc_at: str


def _row(r: sqlite3.Row) -> LateFeeRow:
    return LateFeeRow(
        id=r["id"],
        request_id=r["request_id"],
        overdue_days=r["overdue_days"],
        penalty_percent=r["penalty_percent"],
        base_amount=r["base_amount"],
        penalty_amount=r["penalty_amount"],
        tax_type=r["tax_type"],
        needs_manual_review=bool(r["needs_manual_review"]),
        calc_at=r["calc_at"],
    )


class LateFeeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        request_id: int,
        overdue_days: int,
        penalty_percent: float,
        base_amount: float,
        penalty_amount: float,
        tax_type: str,
        needs_manual_review: bool,
    ) -> LateFeeRow:
        now = _now()
        cur = self._conn.execute(
            """
            INSERT INTO late_fee_records
                (request_id, overdue_days, penalty_percent, base_amount,
                 penalty_amount, tax_type, needs_manual_review, calc_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                overdue_days,
                penalty_percent,
                base_amount,
                penalty_amount,
                tax_type,
                int(needs_manual_review),
                now,
            ),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, record_id: int) -> LateFeeRow | None:
        r = self._conn.execute(
            "SELECT * FROM late_fee_records WHERE id = ?", (record_id,)
        ).fetchone()
        return _row(r) if r else None

    def list_by_request(self, request_id: int) -> list[LateFeeRow]:
        rows = self._conn.execute(
            "SELECT * FROM late_fee_records WHERE request_id = ? ORDER BY id",
            (request_id,),
        ).fetchall()
        return [_row(r) for r in rows]
