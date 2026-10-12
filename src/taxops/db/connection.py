"""SQLite connection helper.

All callers use parameterized SQL via ``sqlite3`` cursor methods.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_log = logging.getLogger(__name__)


def close_after_failed_setup(conn: sqlite3.Connection, error: Exception) -> None:
    """Attempt cleanup without replacing the original initialization failure."""
    try:
        conn.close()
    except Exception as close_error:
        # Retain both failures in diagnostics; do not claim cleanup succeeded.
        error.add_note(f"SQLite connection cleanup also failed: {close_error!r}")
        _log.exception("SQLite connection cleanup failed after initialization error")


def open_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enabled and Row factory."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except Exception as exc:
        close_after_failed_setup(conn, exc)
        raise


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context-managed transaction. Commits on success, rolls back on error."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
