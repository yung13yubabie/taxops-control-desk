"""Persistence for one compliance profile and its retained rule rows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.compliance import WORK_TYPE_ORDER
from ..core.clock import now_iso


@dataclass(frozen=True)
class ComplianceProfileRow:
    id: int
    client_id: int
    fiscal_year_start_month: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ComplianceProfileItemRow:
    id: int
    profile_id: int
    work_type: str
    frequency: str
    enabled: bool
    notes: str | None
    created_at: str
    updated_at: str


def _profile_row(row: sqlite3.Row) -> ComplianceProfileRow:
    return ComplianceProfileRow(
        id=row["id"],
        client_id=row["client_id"],
        fiscal_year_start_month=row["fiscal_year_start_month"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _item_row(row: sqlite3.Row) -> ComplianceProfileItemRow:
    return ComplianceProfileItemRow(
        id=row["id"],
        profile_id=row["profile_id"],
        work_type=row["work_type"],
        frequency=row["frequency"],
        enabled=bool(row["enabled"]),
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ComplianceProfilesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def active_client_exists(self, client_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM clients WHERE id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone() is not None

    def get_for_client(self, client_id: int) -> ComplianceProfileRow | None:
        row = self._conn.execute(
            "SELECT cp.* FROM compliance_profiles cp "
            "JOIN clients c ON c.id = cp.client_id "
            "WHERE cp.client_id = ? AND c.deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return _profile_row(row) if row else None

    def upsert_profile(
        self, client_id: int, fiscal_year_start_month: int
    ) -> ComplianceProfileRow:
        timestamp = now_iso()
        self._conn.execute(
            """
            INSERT INTO compliance_profiles(
                client_id, fiscal_year_start_month, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                fiscal_year_start_month = excluded.fiscal_year_start_month,
                updated_at = excluded.updated_at
            """,
            (client_id, fiscal_year_start_month, timestamp, timestamp),
        )
        row = self.get_for_client(client_id)
        if row is None:
            raise RuntimeError("compliance_profiles.upsert_profile: row missing")
        return row

    def upsert_item(
        self,
        profile_id: int,
        work_type: str,
        frequency: str,
        enabled: bool,
        notes: str | None,
    ) -> ComplianceProfileItemRow:
        timestamp = now_iso()
        self._conn.execute(
            """
            INSERT INTO compliance_profile_items(
                profile_id, work_type, frequency, enabled, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, work_type) DO UPDATE SET
                frequency = excluded.frequency,
                enabled = excluded.enabled,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                profile_id,
                work_type,
                frequency,
                int(enabled),
                notes,
                timestamp,
                timestamp,
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM compliance_profile_items "
            "WHERE profile_id = ? AND work_type = ?",
            (profile_id, work_type),
        ).fetchone()
        if row is None:
            raise RuntimeError("compliance_profiles.upsert_item: row missing")
        return _item_row(row)

    def list_items(self, profile_id: int) -> list[ComplianceProfileItemRow]:
        order_cases = " ".join(
            f"WHEN '{work_type}' THEN {index}"
            for index, work_type in enumerate(WORK_TYPE_ORDER)
        )
        rows = self._conn.execute(
            "SELECT * FROM compliance_profile_items WHERE profile_id = ? "
            f"ORDER BY CASE work_type {order_cases} ELSE 999 END, work_type, id",
            (profile_id,),
        ).fetchall()
        return [_item_row(row) for row in rows]
