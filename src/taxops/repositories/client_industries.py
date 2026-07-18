"""Persistence for the ordered client industry registry snapshot."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientIndustryRow:
    id: int
    client_id: int
    industry_code: str
    industry_name: str
    is_primary: bool
    sort_order: int
    source: str
    source_version: str | None
    applied_at: str

    @property
    def code(self) -> str:
        return self.industry_code

    @property
    def name(self) -> str:
        return self.industry_name


def _row(row: sqlite3.Row) -> ClientIndustryRow:
    return ClientIndustryRow(
        id=row["id"],
        client_id=row["client_id"],
        industry_code=row["industry_code"],
        industry_name=row["industry_name"],
        is_primary=bool(row["is_primary"]),
        sort_order=row["sort_order"],
        source=row["source"],
        source_version=row["source_version"],
        applied_at=row["applied_at"],
    )


class ClientIndustriesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def active_client_exists(self, client_id: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM clients WHERE id = ? AND deleted_at IS NULL", (client_id,)
        ).fetchone() is not None

    def list_for_client(self, client_id: int) -> list[ClientIndustryRow]:
        rows = self._conn.execute(
            "SELECT * FROM client_industries WHERE client_id = ?"
            " ORDER BY sort_order ASC, id ASC",
            (client_id,),
        ).fetchall()
        return [_row(row) for row in rows]

    def replace(
        self,
        client_id: int,
        industries: list[dict[str, object]],
        *,
        source: str,
        source_version: str | None,
        applied_at: str,
    ) -> list[ClientIndustryRow]:
        self.delete_for_client(client_id)
        return self.insert_many(
            client_id,
            industries,
            source=source,
            source_version=source_version,
            applied_at=applied_at,
        )

    def delete_for_client(self, client_id: int) -> None:
        self._conn.execute(
            "DELETE FROM client_industries WHERE client_id = ?", (client_id,)
        )

    def insert_many(
        self,
        client_id: int,
        industries: list[dict[str, object]],
        *,
        source: str,
        source_version: str | None,
        applied_at: str,
    ) -> list[ClientIndustryRow]:
        self._conn.executemany(
            """
            INSERT INTO client_industries(
                client_id, industry_code, industry_name, is_primary,
                sort_order, source, source_version, applied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    client_id,
                    item["industry_code"],
                    item["industry_name"],
                    int(bool(item["is_primary"])),
                    order,
                    source,
                    source_version,
                    applied_at,
                )
                for order, item in enumerate(industries)
            ],
        )
        return self.list_for_client(client_id)
