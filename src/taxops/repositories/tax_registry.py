"""Repository for tax registry cache + cache metadata.

Designed for streaming bulk inserts. Uses a TEMP staging table so the
formal ``tax_registry_cache`` is never partially overwritten on failure
(slice 2 hard rule: ZIP imports must stage before promoting).
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Iterator

from ..core.clock import now_iso
from ..services.registry.parser import TaxRegistryEntry

INSERT_SQL = (
    "INSERT INTO {table}("
    "tax_id, business_name, business_address, parent_tax_id, "
    "capital, registered_date_roc, organization_type, uses_uniform_invoice, "
    "industry_code_primary, industry_name_primary, "
    "industry_code_1, industry_name_1, "
    "industry_code_2, industry_name_2, "
    "industry_code_3, industry_name_3, "
    "cache_version, imported_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _entry_tuple(
    entry: TaxRegistryEntry,
    cache_version: str,
    imported_at: str,
) -> tuple:
    return (
        entry.tax_id,
        entry.business_name,
        entry.business_address,
        entry.parent_tax_id,
        entry.capital,
        entry.registered_date_roc,
        entry.organization_type,
        entry.uses_uniform_invoice,
        entry.industry_code_primary,
        entry.industry_name_primary,
        entry.industry_code_1,
        entry.industry_name_1,
        entry.industry_code_2,
        entry.industry_name_2,
        entry.industry_code_3,
        entry.industry_name_3,
        cache_version,
        imported_at,
    )


class TaxRegistryRepository:
    STAGING_TABLE = "staging_tax_registry_cache"
    FORMAL_TABLE = "tax_registry_cache"
    BATCH_SIZE = 1000

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def count(self) -> int:
        row = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM {self.FORMAL_TABLE}"
        ).fetchone()
        return int(row["c"]) if row else 0

    def find_by_tax_id(self, tax_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            f"SELECT * FROM {self.FORMAL_TABLE} WHERE tax_id = ? LIMIT 1",
            (tax_id,),
        ).fetchone()

    def search(self, query: str, *, limit: int = 20) -> list[sqlite3.Row]:
        """Search by exact tax_id (if 8 digits) or partial business_name LIKE."""
        q = query.strip()
        if not q:
            return []
        if len(q) == 8 and q.isdigit():
            rows = self._conn.execute(
                f"SELECT * FROM {self.FORMAL_TABLE} WHERE tax_id = ? LIMIT ?",
                (q, limit),
            ).fetchall()
            if rows:
                return rows
        return self._conn.execute(
            f"SELECT * FROM {self.FORMAL_TABLE} WHERE business_name LIKE ? LIMIT ?",
            (f"%{q}%", limit),
        ).fetchall()

    def iter_all(self) -> Iterator[sqlite3.Row]:
        cur = self._conn.execute(f"SELECT * FROM {self.FORMAL_TABLE}")
        for row in cur:
            yield row

    # ------------------------------------------------------------------
    # Write — staging-first replace
    # ------------------------------------------------------------------
    def replace_all_from_entries(
        self,
        entries: Iterable[TaxRegistryEntry],
        *,
        cache_version: str,
        on_progress=None,
    ) -> int:
        """Atomically replace the formal cache from a stream of entries.

        Sequence:
          BEGIN IMMEDIATE
          create + populate staging table
          (validate count > 0)
          DELETE formal; INSERT formal SELECT staging
          DROP staging
          COMMIT

        On any exception the transaction rolls back, leaving the existing
        formal cache untouched. Returns the imported row count.
        """
        imported_at = now_iso()
        conn = self._conn
        conn.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"CREATE TEMP TABLE {self.STAGING_TABLE} AS "
                f"SELECT * FROM {self.FORMAL_TABLE} WHERE 0"
            )
            insert_sql = INSERT_SQL.format(table=self.STAGING_TABLE)
            count = 0
            batch: list[tuple] = []
            for entry in entries:
                batch.append(_entry_tuple(entry, cache_version, imported_at))
                if len(batch) >= self.BATCH_SIZE:
                    conn.executemany(insert_sql, batch)
                    count += len(batch)
                    batch.clear()
                    if on_progress is not None:
                        on_progress(count)
            if batch:
                conn.executemany(insert_sql, batch)
                count += len(batch)
                if on_progress is not None:
                    on_progress(count)

            if count == 0:
                raise ValueError("registry.import.no_rows")

            conn.execute(f"DELETE FROM {self.FORMAL_TABLE}")
            conn.execute(
                f"INSERT INTO {self.FORMAL_TABLE} SELECT * FROM {self.STAGING_TABLE}"
            )
            conn.execute(f"DROP TABLE {self.STAGING_TABLE}")
            conn.commit()
            return count
        except BaseException:
            conn.rollback()
            try:
                conn.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
                conn.commit()
            except Exception:
                pass
            raise


class TaxCacheMetadataRepository:
    """Key/value metadata for the tax registry cache.

    Stored in its own table (not ``app_settings``) so cache bundles can
    safely include cache metadata without exposing user/local-path data.
    """

    TABLE = "tax_cache_metadata"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> str | None:
        row = self._conn.execute(
            f"SELECT value FROM {self.TABLE} WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_all(self) -> dict[str, str]:
        rows = self._conn.execute(f"SELECT key, value FROM {self.TABLE}").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def upsert(self, key: str, value: str) -> None:
        self._conn.execute(
            f"INSERT INTO {self.TABLE}(key, value, updated_at) VALUES (?, ?, ?) "
            f"ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            f"updated_at = excluded.updated_at",
            (key, value, now_iso()),
        )
        self._conn.commit()

    def upsert_many(self, items: dict[str, str]) -> None:
        ts = now_iso()
        rows = [(k, v, ts) for k, v in items.items()]
        self._conn.executemany(
            f"INSERT INTO {self.TABLE}(key, value, updated_at) VALUES (?, ?, ?) "
            f"ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            f"updated_at = excluded.updated_at",
            rows,
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute(f"DELETE FROM {self.TABLE}")
        self._conn.commit()
