"""Generated messages repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class GeneratedMessageRow:
    id: int
    request_id: int
    template_id: int
    body: str
    generated_at: str


def _row_to_message(row: sqlite3.Row) -> GeneratedMessageRow:
    return GeneratedMessageRow(
        id=row["id"],
        request_id=row["request_id"],
        template_id=row["template_id"],
        body=row["body"],
        generated_at=row["generated_at"],
    )


class GeneratedMessagesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self, *, request_id: int, template_id: int, body: str
    ) -> GeneratedMessageRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO generated_messages(request_id, template_id, body, generated_at)"
            " VALUES (?, ?, ?, ?)",
            (request_id, template_id, body, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("generated_messages.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("generated_messages.insert: row missing after insert")
        return got

    def get(self, message_id: int) -> GeneratedMessageRow | None:
        row = self._conn.execute(
            "SELECT * FROM generated_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def list_by_request(self, request_id: int) -> list[GeneratedMessageRow]:
        rows = self._conn.execute(
            "SELECT * FROM generated_messages WHERE request_id = ? ORDER BY id ASC",
            (request_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]
