"""Migration runner.

Applies pending migrations and records each in ``schema_migrations``.
Idempotent: running twice on the same DB is a no-op after the first.
"""

from __future__ import annotations

import sqlite3

from ..core.clock import now_iso
from .migrations import MIGRATIONS

_BOOTSTRAP_SQL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
)


class UnsupportedSchemaError(RuntimeError):
    """The database contains migrations this application cannot understand."""

    def __init__(self, versions: set[str]) -> None:
        self.versions = tuple(sorted(versions))
        super().__init__(
            "資料庫含有此版本無法識別的資料結構，可能由較新版本建立。\n\n"
            "為保護現有資料，已停止啟動，未執行資料遷移。"
            "請使用原先或更新版本的 TaxOps Control Desk。\n\n"
            "若要使用舊版，請先另外保留現有資料，再還原升級前的備份。"
        )


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    """Read the migration ledger without creating or changing database objects."""
    ledger = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("schema_migrations",),
    ).fetchone()
    if ledger is None:
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def _execute_statements(conn: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for char in sql:
        statement += char
        if char == ";" and sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Return list of versions applied."""
    applied = applied_versions(conn)
    unknown = applied - {version for version, _sql in MIGRATIONS}
    if unknown:
        # Refuse before any DDL/DML, including migration-ledger initialization.
        raise UnsupportedSchemaError(unknown)
    conn.execute(_BOOTSTRAP_SQL)
    newly_applied: list[str] = []
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        savepoint = "taxops_migration"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            _execute_statements(conn, sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, now_iso()),
            )
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        newly_applied.append(version)
    return newly_applied
