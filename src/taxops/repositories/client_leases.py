"""Persistence for the v0.30 client lease collection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class ClientLeaseRow:
    id: int
    client_id: int
    lease_name: str
    premises_address: str | None
    landlord_name: str | None
    start_date: str | None
    end_date: str | None
    monthly_rent: int | None
    deposit_amount: int | None
    reminder_days: int
    status: str
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


def _row(row: sqlite3.Row) -> ClientLeaseRow:
    return ClientLeaseRow(**{field: row[field] for field in ClientLeaseRow.__dataclass_fields__})


class ClientLeasesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def active_client_exists(self, client_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM clients WHERE id = ? AND deleted_at IS NULL", (client_id,)
        ).fetchone() is not None

    def insert(self, client_id: int, **values: object) -> ClientLeaseRow:
        timestamp = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO client_leases(
                client_id, lease_name, premises_address, landlord_name,
                start_date, end_date, monthly_rent, deposit_amount,
                reminder_days, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                values["lease_name"],
                values["premises_address"],
                values["landlord_name"],
                values["start_date"],
                values["end_date"],
                values["monthly_rent"],
                values["deposit_amount"],
                values["reminder_days"],
                values["status"],
                values["notes"],
                timestamp,
                timestamp,
            ),
        )
        row = self.get(int(cur.lastrowid or 0))
        if row is None:
            raise RuntimeError("client_leases.insert: row missing after insert")
        return row

    def get(self, lease_id: int, *, include_deleted: bool = False) -> ClientLeaseRow | None:
        deleted_sql = "" if include_deleted else " AND deleted_at IS NULL"
        row = self._conn.execute(
            f"SELECT * FROM client_leases WHERE id = ?{deleted_sql}", (lease_id,)
        ).fetchone()
        return _row(row) if row else None

    def list_for_client(
        self, client_id: int, *, include_deleted: bool = False
    ) -> list[ClientLeaseRow]:
        deleted_sql = "" if include_deleted else " AND deleted_at IS NULL"
        rows = self._conn.execute(
            "SELECT * FROM client_leases WHERE client_id = ?"
            f"{deleted_sql} ORDER BY start_date ASC, id ASC",
            (client_id,),
        ).fetchall()
        return [_row(row) for row in rows]

    def update(self, lease_id: int, **values: object) -> ClientLeaseRow | None:
        self._conn.execute(
            """
            UPDATE client_leases
               SET lease_name = ?, premises_address = ?, landlord_name = ?,
                   start_date = ?, end_date = ?, monthly_rent = ?,
                   deposit_amount = ?, reminder_days = ?, status = ?, notes = ?,
                   updated_at = ?
             WHERE id = ? AND deleted_at IS NULL
            """,
            (
                values["lease_name"],
                values["premises_address"],
                values["landlord_name"],
                values["start_date"],
                values["end_date"],
                values["monthly_rent"],
                values["deposit_amount"],
                values["reminder_days"],
                values["status"],
                values["notes"],
                now_iso(),
                lease_id,
            ),
        )
        return self.get(lease_id)

    def archive(self, lease_id: int) -> ClientLeaseRow | None:
        timestamp = now_iso()
        self._conn.execute(
            "UPDATE client_leases SET deleted_at = ?, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (timestamp, timestamp, lease_id),
        )
        return self.get(lease_id, include_deleted=True)
