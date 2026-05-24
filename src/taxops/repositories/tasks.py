"""Workflow tasks repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class TaskRow:
    id: int
    engagement_id: int | None
    client_id: int | None
    title: str
    assignee: str | None
    due_date: str | None
    priority: str
    status: str
    next_step: str | None
    notes: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


def _row_to_task(row: sqlite3.Row) -> TaskRow:
    keys = row.keys()
    return TaskRow(
        id=row["id"],
        engagement_id=row["engagement_id"],
        client_id=row["client_id"] if "client_id" in keys else None,
        title=row["title"],
        assignee=row["assignee"],
        due_date=row["due_date"],
        priority=row["priority"],
        status=row["status"],
        next_step=row["next_step"],
        notes=row["notes"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"] if "deleted_at" in keys else None,
    )


class TasksRepository:
    _SORT_COLUMNS = frozenset({"id", "title", "priority", "status", "due_date", "updated_at"})

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        engagement_id: int | None,
        title: str,
        client_id: int | None = None,
        assignee: str | None = None,
        due_date: str | None = None,
        priority: str = "normal",
        status: str = "todo",
        next_step: str | None = None,
        notes: str | None = None,
    ) -> TaskRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO workflow_tasks("
            "engagement_id, client_id, title, assignee, due_date, priority, status,"
            " next_step, notes, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (engagement_id, client_id, title, assignee, due_date, priority, status,
             next_step, notes, ts, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("tasks.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("tasks.insert: row missing after insert")
        return got

    def get(self, task_id: int) -> TaskRow | None:
        row = self._conn.execute(
            "SELECT * FROM workflow_tasks WHERE id = ? AND deleted_at IS NULL",
            (task_id,),
        ).fetchone()
        return _row_to_task(row) if row else None

    def list_by_engagement(
        self,
        engagement_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[TaskRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "updated_at"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM workflow_tasks"
            f" WHERE engagement_id = ? AND deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (engagement_id, limit, offset),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_all(
        self,
        *,
        order_by: str = "due_date",
        order_dir: str = "ASC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[TaskRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "due_date"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM workflow_tasks WHERE deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_overdue(self, today: str) -> list[TaskRow]:
        """Return tasks where due_date < today AND status NOT IN done/cancelled."""
        rows = self._conn.execute(
            "SELECT * FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            "   AND due_date IS NOT NULL"
            "   AND due_date < ?"
            "   AND status NOT IN ('done', 'cancelled')"
            " ORDER BY due_date ASC",
            (today,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_due_today(self, today: str) -> list[TaskRow]:
        rows = self._conn.execute(
            "SELECT * FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            "   AND due_date = ?"
            "   AND status NOT IN ('done', 'cancelled')"
            " ORDER BY id ASC",
            (today,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def update(
        self,
        task_id: int,
        *,
        title: str,
        assignee: str | None,
        due_date: str | None,
        priority: str,
        next_step: str | None,
        notes: str | None,
    ) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks"
            " SET title = ?, assignee = ?, due_date = ?, priority = ?,"
            "     next_step = ?, notes = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (title, assignee, due_date, priority, next_step, notes, ts, task_id),
        )
        self._conn.commit()
        return self.get(task_id)

    def update_status(self, task_id: int, status: str) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks SET status = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (status, ts, task_id),
        )
        self._conn.commit()
        return self.get(task_id)

    def complete(self, task_id: int) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks"
            " SET status = 'done', completed_at = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (ts, ts, task_id),
        )
        self._conn.commit()
        return self.get(task_id)

    def delete(self, task_id: int) -> bool:
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE workflow_tasks SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (ts, task_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def engagement_exists(self, engagement_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM engagements WHERE id = ? AND deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return row is not None

    def get_engagement_client_id(self, engagement_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT client_id FROM engagements WHERE id = ? AND deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return row["client_id"] if row else None

    def client_exists(self, client_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM clients WHERE id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return row is not None

    def list_by_client(
        self,
        client_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[TaskRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "updated_at"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM workflow_tasks"
            f" WHERE client_id = ? AND deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (client_id, limit, offset),
        ).fetchall()
        return [_row_to_task(r) for r in rows]
