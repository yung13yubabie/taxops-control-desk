"""Message templates repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class TemplateRow:
    id: int
    name: str
    template_type: str
    body: str
    is_builtin: bool
    created_at: str
    updated_at: str
    deleted_at: str | None = None


def _row_to_template(row: sqlite3.Row) -> TemplateRow:
    return TemplateRow(
        id=row["id"],
        name=row["name"],
        template_type=row["template_type"],
        body=row["body"],
        is_builtin=bool(row["is_builtin"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


class TemplatesRepository:
    _SORT_COLUMNS = frozenset({"id", "name", "template_type", "updated_at"})

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, *, name: str, template_type: str, body: str) -> TemplateRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO message_templates(name, template_type, body, is_builtin, created_at, updated_at)"
            " VALUES (?, ?, ?, 0, ?, ?)",
            (name, template_type, body, ts, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("templates.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("templates.insert: row missing after insert")
        return got

    def get(self, template_id: int) -> TemplateRow | None:
        row = self._conn.execute(
            "SELECT * FROM message_templates WHERE id = ? AND deleted_at IS NULL",
            (template_id,),
        ).fetchone()
        return _row_to_template(row) if row else None

    def list_all(
        self,
        *,
        order_by: str = "name",
        order_dir: str = "ASC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[TemplateRow]:
        col = order_by if order_by in self._SORT_COLUMNS else "name"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        rows = self._conn.execute(
            f"SELECT * FROM message_templates WHERE deleted_at IS NULL"
            f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_template(r) for r in rows]

    def update(
        self, template_id: int, *, name: str, template_type: str, body: str
    ) -> TemplateRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE message_templates SET name = ?, template_type = ?, body = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL AND is_builtin = 0",
            (name, template_type, body, ts, template_id),
        )
        self._conn.commit()
        return self.get(template_id)

    def delete(self, template_id: int) -> bool:
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE message_templates SET deleted_at = ?"
            " WHERE id = ? AND deleted_at IS NULL AND is_builtin = 0",
            (ts, template_id),
        )
        self._conn.commit()
        return cur.rowcount > 0
