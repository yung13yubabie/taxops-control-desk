"""Workflow tasks repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso

_ACTIVE_OWNER_SQL = (
    "(workflow_tasks.client_id IS NULL OR EXISTS ("
    " SELECT 1 FROM clients c"
    " WHERE c.id = workflow_tasks.client_id AND c.deleted_at IS NULL"
    "))"
    " AND (workflow_tasks.engagement_id IS NULL OR EXISTS ("
    " SELECT 1 FROM engagements e"
    " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
    " WHERE e.id = workflow_tasks.engagement_id AND e.deleted_at IS NULL"
    "))"
    " AND (workflow_tasks.annual_work_item_id IS NULL OR EXISTS ("
    " SELECT 1 FROM annual_work_items awi"
    " JOIN annual_workspaces aw ON aw.id = awi.workspace_id AND aw.deleted_at IS NULL"
    " JOIN clients c ON c.id = aw.client_id AND c.deleted_at IS NULL"
    " WHERE awi.id = workflow_tasks.annual_work_item_id AND awi.deleted_at IS NULL"
    "))"
)


@dataclass(frozen=True)
class TaskRow:
    id: int
    engagement_id: int | None
    client_id: int | None
    parent_task_id: int | None
    annual_work_item_id: int | None
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
        parent_task_id=row["parent_task_id"] if "parent_task_id" in keys else None,
        annual_work_item_id=(
            row["annual_work_item_id"] if "annual_work_item_id" in keys else None
        ),
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
        parent_task_id: int | None = None,
        annual_work_item_id: int | None = None,
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
            "engagement_id, client_id, parent_task_id, annual_work_item_id, title, assignee, due_date, priority, status,"
            " next_step, notes, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (engagement_id, client_id, parent_task_id, annual_work_item_id, title, assignee, due_date, priority, status,
             next_step, notes, ts, ts),
        )
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("tasks.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("tasks.insert: row missing after insert")
        return got

    def get(self, task_id: int) -> TaskRow | None:
        row = self._conn.execute(
            "SELECT * FROM workflow_tasks WHERE id = ? AND deleted_at IS NULL"
            f" AND {_ACTIVE_OWNER_SQL}",
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
            f" AND {_ACTIVE_OWNER_SQL}"
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
            f" AND {_ACTIVE_OWNER_SQL}"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_overdue(self, today: str) -> list[TaskRow]:
        """Return tasks where due_date < today AND status NOT IN done/cancelled."""
        rows = self._conn.execute(
            "SELECT * FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            f"   AND {_ACTIVE_OWNER_SQL}"
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
            f"   AND {_ACTIVE_OWNER_SQL}"
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
        return self.get(task_id)

    def update_status(self, task_id: int, status: str) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks"
            " SET status = ?,"
            "     completed_at = CASE WHEN ? = 'done' THEN ? ELSE completed_at END,"
            "     updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (status, status, ts, ts, task_id),
        )
        return self.get(task_id)

    def complete(self, task_id: int) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks"
            " SET status = 'done', completed_at = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (ts, ts, task_id),
        )
        return self.get(task_id)

    def delete(self, task_id: int) -> bool:
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE workflow_tasks SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (ts, task_id),
        )
        return cur.rowcount > 0

    def engagement_exists(self, engagement_id: int) -> bool:
        row = self._conn.execute(
            "SELECT e.id FROM engagements e"
            " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
            " WHERE e.id = ? AND e.deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return row is not None

    def get_engagement_client_id(self, engagement_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT e.client_id FROM engagements e"
            " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
            " WHERE e.id = ? AND e.deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return row["client_id"] if row else None

    def client_exists(self, client_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM clients WHERE id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return row is not None

    def get_annual_work_context(
        self, item_id: int
    ) -> tuple[int, int | None] | None:
        row = self._conn.execute(
            "SELECT aw.client_id, awi.engagement_id FROM annual_work_items awi"
            " JOIN annual_workspaces aw ON aw.id = awi.workspace_id"
            " JOIN clients c ON c.id = aw.client_id"
            " WHERE awi.id = ? AND awi.deleted_at IS NULL"
            " AND aw.deleted_at IS NULL AND c.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return int(row["client_id"]), (
            int(row["engagement_id"])
            if row["engagement_id"] is not None
            else None
        )

    def list_by_annual_work_item(
        self,
        item_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[TaskRow]:
        if order_by not in self._SORT_COLUMNS or order_dir not in {"ASC", "DESC"}:
            raise ValueError("task.list.invalid_sort")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 500
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= 1_000_000
        ):
            raise ValueError("task.list.invalid_pagination")
        rows = self._conn.execute(
            f"SELECT * FROM workflow_tasks WHERE annual_work_item_id = ?"
            f" AND deleted_at IS NULL AND {_ACTIVE_OWNER_SQL}"
            f" ORDER BY {order_by} {order_dir}, id ASC LIMIT ? OFFSET ?",
            (item_id, limit, offset),
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def update_parent(self, task_id: int, parent_task_id: int | None) -> TaskRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_tasks SET parent_task_id = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (parent_task_id, ts, task_id),
        )
        return self.get(task_id)

    def count_children(self, task_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM workflow_tasks"
            " WHERE parent_task_id = ? AND deleted_at IS NULL"
            f" AND {_ACTIVE_OWNER_SQL}",
            (task_id,),
        ).fetchone()
        return int(row["c"]) if row else 0

    def get_parent_id(self, task_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT parent_task_id FROM workflow_tasks"
            " WHERE id = ? AND deleted_at IS NULL"
            f" AND {_ACTIVE_OWNER_SQL}",
            (task_id,),
        ).fetchone()
        return row["parent_task_id"] if row else None

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
            f" AND {_ACTIVE_OWNER_SQL}"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (client_id, limit, offset),
        ).fetchall()
        return [_row_to_task(r) for r in rows]
