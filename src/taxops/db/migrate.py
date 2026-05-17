"""Migration runner.

Applies pending migrations and records each in ``schema_migrations``.
Idempotent: running twice on the same DB is a no-op after the first.
"""

from __future__ import annotations

import sqlite3

from ..core.clock import now_iso
from .connection import transaction
from .migrations import MIGRATIONS

_BOOTSTRAP_SQL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
)


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    conn.execute(_BOOTSTRAP_SQL)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Return list of versions applied."""
    applied = applied_versions(conn)
    newly_applied: list[str] = []
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        with transaction(conn):
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, now_iso()),
            )
        newly_applied.append(version)
    return newly_applied
