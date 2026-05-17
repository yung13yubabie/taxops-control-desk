"""Audit log repository (business operations only)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..core.clock import now_iso


@dataclass(frozen=True)
class AuditLogRow:
    id: int
    actor: str
    action: str
    target_type: str
    target_id: str | None
    detail_json: str | None
    created_at: str


class AuditLogRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditLogRow:
        detail_json: str | None = (
            json.dumps(detail, ensure_ascii=False) if detail else None
        )
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO audit_logs(actor, action, target_type, target_id, "
            "detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (actor, action, target_type, target_id, detail_json, ts),
        )
        self._conn.commit()
        return AuditLogRow(
            id=int(cur.lastrowid or 0),
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail_json=detail_json,
            created_at=ts,
        )

    def list_recent(self, *, limit: int = 100) -> list[AuditLogRow]:
        rows = self._conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            AuditLogRow(
                id=row["id"],
                actor=row["actor"],
                action=row["action"],
                target_type=row["target_type"],
                target_id=row["target_id"],
                detail_json=row["detail_json"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM audit_logs"
        ).fetchone()
        return int(row["c"]) if row else 0
