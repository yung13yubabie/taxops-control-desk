"""Engagements repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class EngagementRow:
    id: int
    client_id: int
    engagement_name: str
    tax_type: str
    period_name: str
    status: str
    owner: str | None
    due_date: str | None
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


def _row_to_engagement(row: sqlite3.Row) -> EngagementRow:
    keys = row.keys()
    return EngagementRow(
        id=row["id"],
        client_id=row["client_id"],
        engagement_name=row["engagement_name"],
        tax_type=row["tax_type"],
        period_name=row["period_name"],
        status=row["status"],
        owner=row["owner"],
        due_date=row["due_date"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"] if "deleted_at" in keys else None,
    )


class EngagementsRepository:
    _SORT_COLUMNS = frozenset({
        "id", "engagement_name", "tax_type", "period_name",
        "status", "due_date", "updated_at",
    })

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        client_id: int,
        engagement_name: str,
        tax_type: str,
        period_name: str,
        status: str = "draft",
        owner: str | None = None,
        due_date: str | None = None,
        notes: str | None = None,
    ) -> EngagementRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO engagements("
            "client_id, engagement_name, tax_type, period_name, status,"
            " owner, due_date, notes, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (client_id, engagement_name, tax_type, period_name, status,
             owner, due_date, notes, ts, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("engagements.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("engagements.insert: row missing after insert")
        return got

    def get(self, engagement_id: int) -> EngagementRow | None:
        row = self._conn.execute(
            "SELECT * FROM engagements WHERE id = ? AND deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return _row_to_engagement(row) if row else None

    def list_by_ids(self, ids: list[int]) -> list[EngagementRow]:
        """Return active engagements for the given ID list, preserving FTS rank order."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT * FROM engagements WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            ids,
        ).fetchall()
        by_id = {_row_to_engagement(r).id: _row_to_engagement(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def list_by_client(
        self,
        client_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[EngagementRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "updated_at"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM engagements WHERE client_id = ? AND deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (client_id, limit, offset),
        ).fetchall()
        return [_row_to_engagement(r) for r in rows]

    def count_by_client(self, client_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM engagements WHERE client_id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return int(row["c"]) if row else 0

    def update(
        self,
        engagement_id: int,
        *,
        engagement_name: str,
        tax_type: str,
        period_name: str,
        status: str,
        owner: str | None = None,
        due_date: str | None = None,
        notes: str | None = None,
    ) -> EngagementRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE engagements SET engagement_name = ?, tax_type = ?, period_name = ?,"
            " status = ?, owner = ?, due_date = ?, notes = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (engagement_name, tax_type, period_name, status, owner, due_date, notes, ts,
             engagement_id),
        )
        self._conn.commit()
        return self.get(engagement_id)

    def update_status(self, engagement_id: int, status: str) -> EngagementRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE engagements SET status = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (status, ts, engagement_id),
        )
        self._conn.commit()
        return self.get(engagement_id)

    def delete(self, engagement_id: int) -> bool:
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE engagements SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (ts, engagement_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_all(
        self,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[EngagementRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "updated_at"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM engagements WHERE deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_engagement(r) for r in rows]

    def list_upcoming(self, today: str, until: str) -> list[EngagementRow]:
        rows = self._conn.execute(
            "SELECT * FROM engagements"
            " WHERE deleted_at IS NULL"
            "   AND due_date >= ? AND due_date <= ?"
            "   AND status NOT IN ('filed', 'cancelled')"
            " ORDER BY due_date ASC",
            (today, until),
        ).fetchall()
        return [_row_to_engagement(r) for r in rows]

    def list_overdue(self, today: str) -> list[EngagementRow]:
        rows = self._conn.execute(
            "SELECT * FROM engagements"
            " WHERE deleted_at IS NULL"
            "   AND due_date < ?"
            "   AND status NOT IN ('filed', 'cancelled')"
            " ORDER BY due_date ASC",
            (today,),
        ).fetchall()
        return [_row_to_engagement(r) for r in rows]

    def client_exists(self, client_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM clients WHERE id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return row is not None
