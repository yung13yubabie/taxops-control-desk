"""Registry match results repository.

Stores per-client match outcomes against a registry source (slice 2 emits
only ``mof``; ``gcis`` is reserved for slice 3).

``differences_json`` is a difference *summary* only — it must never be
applied back to ``clients`` automatically.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from ..core.clock import now_iso

REGISTRY_SOURCE_MOF = "mof"
REGISTRY_SOURCE_GCIS = "gcis"  # reserved for slice 3

VALID_MATCH_STATUSES = (
    "matched",
    "mismatch",
    "not_found",
    "needs_manual_review",
)


@dataclass(frozen=True)
class MatchInsert:
    client_id: int
    tax_id: str | None
    cache_version: str | None
    match_status: str
    matched_name: str | None = None
    matched_address: str | None = None
    matched_business_status: str | None = None
    differences: dict | None = None


@dataclass(frozen=True)
class MatchResultRow:
    id: int
    client_id: int
    tax_id: str | None
    registry_source: str
    cache_version: str | None
    match_status: str
    matched_name: str | None
    matched_address: str | None
    matched_business_status: str | None
    differences_json: str | None
    review_status: str
    generated_at: str


class RegistryMatchRepository:
    TABLE = "registry_match_results"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def replace_for_source(
        self,
        source: str,
        items: Iterable[MatchInsert],
    ) -> dict[str, int]:
        """Atomically delete all rows for ``source`` and insert the new set.

        Returns a status histogram (e.g. ``{"matched": 3, "mismatch": 1}``).
        """
        ts = now_iso()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"DELETE FROM {self.TABLE} WHERE registry_source = ?",
                (source,),
            )
            histogram: dict[str, int] = {s: 0 for s in VALID_MATCH_STATUSES}
            insert_sql = (
                f"INSERT INTO {self.TABLE}("
                f"client_id, tax_id, registry_source, cache_version, "
                f"match_status, matched_name, matched_address, "
                f"matched_business_status, differences_json, review_status, "
                f"generated_at"
                f") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)"
            )
            for item in items:
                if item.match_status not in VALID_MATCH_STATUSES:
                    raise ValueError(f"unknown match status: {item.match_status}")
                differences_json = (
                    json.dumps(item.differences, ensure_ascii=False)
                    if item.differences
                    else None
                )
                conn.execute(
                    insert_sql,
                    (
                        item.client_id,
                        item.tax_id,
                        source,
                        item.cache_version,
                        item.match_status,
                        item.matched_name,
                        item.matched_address,
                        item.matched_business_status,
                        differences_json,
                        ts,
                    ),
                )
                histogram[item.match_status] += 1
            conn.commit()
            return histogram
        except BaseException:
            conn.rollback()
            raise

    def list_for_client(self, client_id: int) -> list[MatchResultRow]:
        rows = self._conn.execute(
            f"SELECT * FROM {self.TABLE} WHERE client_id = ? ORDER BY id",
            (client_id,),
        ).fetchall()
        return [_row_to_match(r) for r in rows]

    def list_for_source(self, source: str) -> list[MatchResultRow]:
        rows = self._conn.execute(
            f"SELECT * FROM {self.TABLE} WHERE registry_source = ? ORDER BY id",
            (source,),
        ).fetchall()
        return [_row_to_match(r) for r in rows]

    def count_for_source(self, source: str) -> int:
        row = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM {self.TABLE} WHERE registry_source = ?",
            (source,),
        ).fetchone()
        return int(row["c"]) if row else 0


def _row_to_match(r: sqlite3.Row) -> MatchResultRow:
    return MatchResultRow(
        id=r["id"],
        client_id=r["client_id"],
        tax_id=r["tax_id"],
        registry_source=r["registry_source"],
        cache_version=r["cache_version"],
        match_status=r["match_status"],
        matched_name=r["matched_name"],
        matched_address=r["matched_address"],
        matched_business_status=r["matched_business_status"],
        differences_json=r["differences_json"],
        review_status=r["review_status"],
        generated_at=r["generated_at"],
    )
