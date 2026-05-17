"""Read-only aggregate count queries for the dashboard page.

All methods return integer counts from parameterized SQL.
No writes, no mutations.
"""

from __future__ import annotations

import sqlite3


class DashboardRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def count_tasks_due_today(self, today: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            "   AND due_date = ?"
            "   AND status NOT IN ('done', 'cancelled')",
            (today,),
        ).fetchone()
        return row[0] if row else 0

    def count_tasks_overdue(self, today: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            "   AND due_date IS NOT NULL"
            "   AND due_date < ?"
            "   AND status NOT IN ('done', 'cancelled')",
            (today,),
        ).fetchone()
        return row[0] if row else 0

    def count_waiting_client(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM workflow_tasks"
            " WHERE deleted_at IS NULL"
            "   AND status = 'waiting_client'",
        ).fetchone()
        return row[0] if row else 0

    def count_open_review_notes(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM review_notes"
            " WHERE status IN ('open', 'responded', 'reopened')",
        ).fetchone()
        return row[0] if row else 0

    def count_missing_item_requests(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT dr.id)"
            " FROM document_requests dr"
            " JOIN document_request_items dri ON dri.request_id = dr.id"
            " WHERE dr.deleted_at IS NULL"
            "   AND dri.item_status IN ('missing', 'incomplete', 'invalid')",
        ).fetchone()
        return row[0] if row else 0

    def count_upcoming_engagements(self, today: str, until: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM engagements"
            " WHERE deleted_at IS NULL"
            "   AND due_date IS NOT NULL"
            "   AND due_date >= ?"
            "   AND due_date <= ?"
            "   AND status != 'closed'",
            (today, until),
        ).fetchone()
        return row[0] if row else 0

    def count_overdue_engagements(self, today: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM engagements"
            " WHERE deleted_at IS NULL"
            "   AND due_date IS NOT NULL"
            "   AND due_date < ?"
            "   AND status != 'closed'",
            (today,),
        ).fetchone()
        return row[0] if row else 0

    def count_high_risk_engagements(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT engagement_id)"
            " FROM review_notes"
            " WHERE severity = 'critical'"
            "   AND status = 'open'",
        ).fetchone()
        return row[0] if row else 0
