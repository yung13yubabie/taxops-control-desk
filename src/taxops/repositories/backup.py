"""Backup record repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class BackupRow:
    id: int
    filename: str
    backup_path: str
    file_size: int
    notes: str | None
    created_at: str


class BackupRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        filename: str,
        backup_path: str,
        file_size: int,
        notes: str | None = None,
    ) -> BackupRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO backup_records(filename, backup_path, file_size, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (filename, backup_path, file_size, notes, ts),
        )
        self._conn.commit()
        return BackupRow(
            id=int(cur.lastrowid or 0),
            filename=filename,
            backup_path=backup_path,
            file_size=file_size,
            notes=notes,
            created_at=ts,
        )

    def list_all(self) -> list[BackupRow]:
        rows = self._conn.execute(
            "SELECT id, filename, backup_path, file_size, notes, created_at"
            " FROM backup_records ORDER BY id DESC"
        ).fetchall()
        return [
            BackupRow(
                id=row["id"],
                filename=row["filename"],
                backup_path=row["backup_path"],
                file_size=row["file_size"],
                notes=row["notes"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get(self, backup_id: int) -> BackupRow | None:
        row = self._conn.execute(
            "SELECT id, filename, backup_path, file_size, notes, created_at"
            " FROM backup_records WHERE id = ?",
            (backup_id,),
        ).fetchone()
        if row is None:
            return None
        return BackupRow(
            id=row["id"],
            filename=row["filename"],
            backup_path=row["backup_path"],
            file_size=row["file_size"],
            notes=row["notes"],
            created_at=row["created_at"],
        )
