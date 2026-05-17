"""Clients repository.

Parameterized SQL only. No business validation here — that belongs in the
service layer.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class ClientRow:
    id: int
    client_code: str
    tax_id: str | None
    client_name: str
    short_name: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    note: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


def _row_to_client(row: sqlite3.Row) -> ClientRow:
    keys = row.keys()
    return ClientRow(
        id=row["id"],
        client_code=row["client_code"],
        tax_id=row["tax_id"],
        client_name=row["client_name"],
        short_name=row["short_name"],
        contact_name=row["contact_name"],
        contact_phone=row["contact_phone"],
        contact_email=row["contact_email"],
        address=row["address"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"] if "deleted_at" in keys else None,
    )


class ClientsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        client_code: str,
        client_name: str,
        tax_id: str | None = None,
        short_name: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
        contact_email: str | None = None,
        address: str | None = None,
        note: str | None = None,
    ) -> ClientRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO clients("
            "client_code, tax_id, client_name, short_name, contact_name, "
            "contact_phone, contact_email, address, note, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                client_code,
                tax_id,
                client_name,
                short_name,
                contact_name,
                contact_phone,
                contact_email,
                address,
                note,
                ts,
                ts,
            ),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("clients.insert: lastrowid missing")
        got = self.get(new_id)
        if got is None:
            raise RuntimeError("clients.insert: row missing after insert")
        return got

    def get(self, client_id: int) -> ClientRow | None:
        """Return the client only if active (deleted_at IS NULL)."""
        row = self._conn.execute(
            "SELECT * FROM clients WHERE id = ? AND deleted_at IS NULL",
            (client_id,),
        ).fetchone()
        return _row_to_client(row) if row else None

    def find_by_code(self, client_code: str) -> ClientRow | None:
        """Return active client by code; soft-deleted rows are invisible."""
        row = self._conn.execute(
            "SELECT * FROM clients WHERE client_code = ? AND deleted_at IS NULL",
            (client_code,),
        ).fetchone()
        return _row_to_client(row) if row else None

    def list_clients(self, *, limit: int = 500, offset: int = 0) -> list[ClientRow]:
        rows = self._conn.execute(
            "SELECT * FROM clients WHERE deleted_at IS NULL"
            " ORDER BY client_code LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_client(row) for row in rows]

    def update(
        self,
        client_id: int,
        *,
        client_code: str,
        client_name: str,
        tax_id: str | None = None,
        short_name: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
        contact_email: str | None = None,
        address: str | None = None,
        note: str | None = None,
    ) -> ClientRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE clients SET client_code = ?, tax_id = ?, client_name = ?, "
            "short_name = ?, contact_name = ?, contact_phone = ?, "
            "contact_email = ?, address = ?, note = ?, updated_at = ? "
            "WHERE id = ?",
            (
                client_code,
                tax_id,
                client_name,
                short_name,
                contact_name,
                contact_phone,
                contact_email,
                address,
                note,
                ts,
                client_id,
            ),
        )
        self._conn.commit()
        return self.get(client_id)

    def delete(self, client_id: int) -> bool:
        """Soft-delete: set deleted_at on an active row.

        Returns True if the row was active and is now soft-deleted.
        Returns False if the row does not exist or is already deleted.
        """
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE clients SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (ts, client_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def restore(self, client_id: int) -> bool:
        """Undo a soft-delete: clear deleted_at.

        Returns True if the row was deleted and is now restored.
        """
        cur = self._conn.execute(
            "UPDATE clients SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
            (client_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    _SORT_COLUMNS = frozenset({
        "id", "client_code", "tax_id", "client_name", "short_name",
        "contact_name", "contact_phone", "contact_email", "updated_at",
    })

    def search_clients(
        self,
        query: str = "",
        *,
        order_by: str = "client_code",
        order_dir: str = "ASC",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClientRow]:
        """Return paginated, optionally filtered + sorted active clients."""
        col = order_by if order_by in self._SORT_COLUMNS else "client_code"
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        base = "SELECT * FROM clients WHERE deleted_at IS NULL"
        if query.strip():
            q = f"%{query.strip()}%"
            rows = self._conn.execute(
                f"{base} AND (client_code LIKE ? OR client_name LIKE ? OR tax_id LIKE ?)"
                f" ORDER BY {col} {direction} LIMIT ? OFFSET ?",
                (q, q, q, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"{base} ORDER BY {col} {direction} LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_client(row) for row in rows]

    def count_clients(self, query: str = "") -> int:
        """Return total count of active clients matching optional query."""
        base = "SELECT COUNT(*) AS c FROM clients WHERE deleted_at IS NULL"
        if query.strip():
            q = f"%{query.strip()}%"
            row = self._conn.execute(
                f"{base} AND (client_code LIKE ? OR client_name LIKE ? OR tax_id LIKE ?)",
                (q, q, q),
            ).fetchone()
        else:
            row = self._conn.execute(base).fetchone()
        return int(row["c"]) if row else 0

    def find_by_tax_id(self, tax_id: str) -> list["ClientRow"]:
        rows = self._conn.execute(
            "SELECT * FROM clients WHERE tax_id = ? AND deleted_at IS NULL",
            (tax_id,),
        ).fetchall()
        return [_row_to_client(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM clients WHERE deleted_at IS NULL"
        ).fetchone()
        return int(row["c"]) if row else 0
