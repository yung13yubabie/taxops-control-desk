"""Bounded local-registry search on an isolated read-only SQLite connection."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ...repositories.tax_registry import TaxRegistryRepository

_log = logging.getLogger(__name__)


class LocalRegistrySearchWorker(QThread):
    succeeded = Signal(object)
    errored = Signal(str)

    def __init__(
        self,
        db_path: str,
        query: str,
        *,
        limit: int = 50,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._query = query
        self._limit = limit

    def run(self) -> None:
        connection: sqlite3.Connection | None = None
        deadline = time.monotonic() + 10.0
        try:
            uri = f"{Path(self._db_path).resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=10.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline),
                10_000,
            )
            rows = TaxRegistryRepository(connection).search(
                self._query, limit=self._limit
            )
            self.succeeded.emit([dict(row) for row in rows])
        except sqlite3.OperationalError as exc:
            if time.monotonic() >= deadline or "interrupted" in str(exc).lower():
                _log.warning("local registry search exceeded the 10 second deadline")
                self.errored.emit("registry.search.timeout")
            else:
                _log.exception("local registry background search failed")
                self.errored.emit("registry.search.failed")
        except sqlite3.Error:
            _log.exception("local registry background search failed")
            self.errored.emit("registry.search.failed")
        except Exception:
            _log.exception("unexpected local registry background search failure")
            self.errored.emit("system.unexpected")
        finally:
            if connection is not None:
                connection.set_progress_handler(None, 0)
                connection.close()
