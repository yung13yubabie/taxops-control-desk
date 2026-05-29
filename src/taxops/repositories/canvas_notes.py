"""Repository for A4 canvas notes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class CanvasNoteRow:
    id: int
    title: str
    scene_json: str
    client_id: int | None
    engagement_id: int | None
    context_snapshot: str | None
    created_at: str
    updated_at: str


def _row(row: sqlite3.Row) -> CanvasNoteRow:
    return CanvasNoteRow(
        id=row["id"],
        title=row["title"],
        scene_json=row["scene_json"],
        client_id=row["client_id"],
        engagement_id=row["engagement_id"],
        context_snapshot=row["context_snapshot"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CanvasNotesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        title: str,
        scene_json: str,
        client_id: int | None = None,
        engagement_id: int | None = None,
        context_snapshot: str | None = None,
    ) -> CanvasNoteRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO canvas_notes("
            "title, scene_json, client_id, engagement_id, context_snapshot, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, scene_json, client_id, engagement_id, context_snapshot, ts, ts),
        )
        self._conn.commit()
        row = self.get(int(cur.lastrowid))
        if row is None:
            raise RuntimeError("inserted canvas note could not be reloaded")
        return row

    def get(self, note_id: int) -> CanvasNoteRow | None:
        row = self._conn.execute(
            "SELECT * FROM canvas_notes WHERE id = ? AND deleted_at IS NULL",
            (note_id,),
        ).fetchone()
        return _row(row) if row else None

    def list_all(self) -> list[CanvasNoteRow]:
        rows = self._conn.execute(
            "SELECT * FROM canvas_notes WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [_row(r) for r in rows]

    def update(self, note_id: int, *, title: str, scene_json: str) -> CanvasNoteRow | None:
        self._conn.execute(
            "UPDATE canvas_notes SET title = ?, scene_json = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (title, scene_json, now_iso(), note_id),
        )
        self._conn.commit()
        return self.get(note_id)

    def soft_delete(self, note_id: int) -> CanvasNoteRow | None:
        row = self.get(note_id)
        if row is None:
            return None
        self._conn.execute(
            "UPDATE canvas_notes SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now_iso(), now_iso(), note_id),
        )
        self._conn.commit()
        return row
