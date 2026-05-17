"""System log repository (technical/system errors).

Distinct from audit_logs: system_logs records technical failures and
diagnostic events that are not business operations.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..core.clock import now_iso

VALID_LEVELS = ("INFO", "WARN", "ERROR")


@dataclass(frozen=True)
class SystemLogRow:
    id: int
    level: str
    message: str
    detail_json: str | None
    created_at: str


class SystemLogRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        *,
        level: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> SystemLogRow:
        if level not in VALID_LEVELS:
            level = "ERROR"
        detail_json: str | None = (
            json.dumps(detail, ensure_ascii=False) if detail else None
        )
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO system_logs(level, message, detail_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (level, message, detail_json, ts),
        )
        self._conn.commit()
        return SystemLogRow(
            id=int(cur.lastrowid or 0),
            level=level,
            message=message,
            detail_json=detail_json,
            created_at=ts,
        )

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM system_logs"
        ).fetchone()
        return int(row["c"]) if row else 0
