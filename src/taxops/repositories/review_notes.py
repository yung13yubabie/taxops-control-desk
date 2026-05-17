"""Repository for review_notes table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ReviewNoteRow:
    id: int
    engagement_id: int
    severity: str
    comment: str
    assigned_to: str | None
    related_task_id: int | None
    status: str
    response: str | None
    waive_reason: str | None
    created_at: str
    updated_at: str


def _row(r: sqlite3.Row) -> ReviewNoteRow:
    return ReviewNoteRow(
        id=r["id"],
        engagement_id=r["engagement_id"],
        severity=r["severity"],
        comment=r["comment"],
        assigned_to=r["assigned_to"],
        related_task_id=r["related_task_id"],
        status=r["status"],
        response=r["response"],
        waive_reason=r["waive_reason"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class ReviewNotesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        engagement_id: int,
        severity: str,
        comment: str,
        assigned_to: str | None = None,
        related_task_id: int | None = None,
    ) -> ReviewNoteRow:
        now = _now()
        cur = self._conn.execute(
            """
            INSERT INTO review_notes
                (engagement_id, severity, comment, assigned_to,
                 related_task_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (engagement_id, severity, comment, assigned_to, related_task_id, now, now),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, note_id: int) -> ReviewNoteRow | None:
        r = self._conn.execute(
            "SELECT * FROM review_notes WHERE id = ?", (note_id,)
        ).fetchone()
        return _row(r) if r else None

    def list_by_engagement(self, engagement_id: int) -> list[ReviewNoteRow]:
        rows = self._conn.execute(
            "SELECT * FROM review_notes WHERE engagement_id = ? ORDER BY id",
            (engagement_id,),
        ).fetchall()
        return [_row(r) for r in rows]

    def list_open_all(self) -> list[ReviewNoteRow]:
        rows = self._conn.execute(
            "SELECT * FROM review_notes"
            " WHERE status IN ('open', 'responded', 'reopened')"
            " ORDER BY id",
        ).fetchall()
        return [_row(r) for r in rows]

    def list_high_risk_all(self) -> list[ReviewNoteRow]:
        rows = self._conn.execute(
            "SELECT * FROM review_notes"
            " WHERE severity = 'critical' AND status = 'open'"
            " ORDER BY id",
        ).fetchall()
        return [_row(r) for r in rows]

    def update_status(
        self,
        note_id: int,
        status: str,
        response: str | None = None,
        waive_reason: str | None = None,
    ) -> ReviewNoteRow | None:
        now = _now()
        self._conn.execute(
            """
            UPDATE review_notes
               SET status = ?, response = ?, waive_reason = ?, updated_at = ?
             WHERE id = ?
            """,
            (status, response, waive_reason, now, note_id),
        )
        self._conn.commit()
        return self.get(note_id)
