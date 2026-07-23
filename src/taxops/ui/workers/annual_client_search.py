"""Bounded annual-workspace client search on an isolated SQLite reader."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnualClientChoice:
    id: int
    client_code: str
    client_name: str


@dataclass(frozen=True)
class AnnualClientSearchResult:
    request_token: int
    choices: tuple[AnnualClientChoice, ...]
    has_more: bool
    preselected: AnnualClientChoice | None


class AnnualClientSearchWorker(QThread):
    """Read active clients without sharing the GUI connection across threads."""

    succeeded = Signal(object)
    errored = Signal(int, str)

    def __init__(
        self,
        db_path: str,
        query: str,
        request_token: int,
        *,
        limit: int = 100,
        preselected_client_id: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._query = query.strip()
        self._request_token = request_token
        self._limit = limit
        self._preselected_client_id = preselected_client_id
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.Lock()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def request_token(self) -> int:
        return self._request_token

    def cancel(self) -> None:
        self.requestInterruption()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            connection.interrupt()

    def shutdown(self) -> None:
        """Bound app shutdown so a native worker cannot outlive Qt."""
        self.cancel()
        self.wait(11_000)

    @staticmethod
    def _choice(row: sqlite3.Row) -> AnnualClientChoice:
        return AnnualClientChoice(
            id=int(row["id"]),
            client_code=str(row["client_code"]),
            client_name=str(row["client_name"]),
        )

    def run(self) -> None:
        connection: sqlite3.Connection | None = None
        deadline = time.monotonic() + 10.0
        try:
            uri = f"{Path(self._db_path).resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=10.0)
            with self._connection_lock:
                self._connection = connection
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.set_progress_handler(
                lambda: int(
                    self.isInterruptionRequested()
                    or time.monotonic() >= deadline
                ),
                1_000,
            )
            connection.execute("BEGIN")
            params: list[object] = []
            where = " WHERE deleted_at IS NULL"
            if self._query:
                wildcard = f"%{self._query}%"
                where += (
                    " AND (client_code LIKE ? OR client_name LIKE ?"
                    " OR tax_id LIKE ? OR short_name LIKE ?"
                    " OR contact_name LIKE ?)"
                )
                params.extend([wildcard] * 5)
            params.append(self._limit + 1)
            rows = connection.execute(
                "SELECT id, client_code, client_name FROM clients"
                f"{where} ORDER BY client_code ASC LIMIT ?",
                tuple(params),
            ).fetchall()
            preselected = None
            if (
                type(self._preselected_client_id) is int
                and self._preselected_client_id > 0
            ):
                selected_row = connection.execute(
                    "SELECT id, client_code, client_name FROM clients"
                    " WHERE id = ? AND deleted_at IS NULL",
                    (self._preselected_client_id,),
                ).fetchone()
                if selected_row is not None:
                    preselected = self._choice(selected_row)
            if self.isInterruptionRequested():
                return
            result = AnnualClientSearchResult(
                request_token=self._request_token,
                choices=tuple(self._choice(row) for row in rows[: self._limit]),
                has_more=len(rows) > self._limit,
                preselected=preselected,
            )
            self.succeeded.emit(result)
        except sqlite3.OperationalError as exc:
            if self.isInterruptionRequested():
                return
            if time.monotonic() >= deadline or "interrupted" in str(exc).lower():
                _log.warning("annual client search exceeded its deadline")
                self.errored.emit(
                    self._request_token, "annual_client_search.timeout"
                )
            else:
                _log.exception("annual client search failed")
                self.errored.emit(
                    self._request_token, "annual_client_search.failed"
                )
        except sqlite3.Error:
            _log.exception("annual client search failed")
            self.errored.emit(self._request_token, "annual_client_search.failed")
        except Exception:
            _log.exception("unexpected annual client search failure")
            self.errored.emit(self._request_token, "system.unexpected")
        finally:
            if connection is not None:
                connection.set_progress_handler(None, 0)
                if connection.in_transaction:
                    connection.rollback()
                with self._connection_lock:
                    self._connection = None
                connection.close()
