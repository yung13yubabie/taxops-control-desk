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
    normalized_query: str
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

    @property
    def request_token(self) -> int:
        return self._request_token

    def cancel(self) -> None:
        self.requestInterruption()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.interrupt()
            except sqlite3.ProgrammingError:
                # The worker may have closed between native query return and
                # this native interrupt call.
                pass

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
                normalized_query=self._query,
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
                with self._connection_lock:
                    connection.set_progress_handler(None, 0)
                    if connection.in_transaction:
                        connection.rollback()
                    self._connection = None
                    connection.close()


_shutdown_survivors: set[QThread] = set()


class AnnualClientSearchCoordinator(QObject):
    """Own client-search workers and coordinate one aggregate app shutdown."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workers: set[QThread] = set()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def active_count(self) -> int:
        return sum(not worker.isFinished() for worker in self._workers)

    def register(self, worker: AnnualClientSearchWorker) -> None:
        worker.setParent(self)
        self._workers.add(worker)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, QThread):
            self._workers.discard(worker)
            _shutdown_survivors.discard(worker)

    def cancel_and_wait(self, timeout_ms: int = 11_000) -> bool:
        workers = tuple(self._workers)
        for worker in workers:
            if isinstance(worker, AnnualClientSearchWorker):
                worker.cancel()
            else:
                worker.requestInterruption()
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        all_finished = True
        for worker in workers:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if not worker.isFinished() and not worker.wait(remaining_ms):
                all_finished = False
        return all_finished

    def shutdown(self, timeout_ms: int = 11_000) -> bool:
        clean = self.cancel_and_wait(timeout_ms)
        if not clean:
            _log.critical(
                "annual client workers exceeded aggregate shutdown deadline"
            )
            for worker in tuple(self._workers):
                if not worker.isFinished():
                    worker.setParent(None)
                    _shutdown_survivors.add(worker)
        return clean


def annual_client_search_coordinator() -> AnnualClientSearchCoordinator:
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("annual client search requires a Qt application")
    coordinator = getattr(app, "_annual_client_search_coordinator", None)
    if not isinstance(coordinator, AnnualClientSearchCoordinator):
        coordinator = AnnualClientSearchCoordinator(app)
        setattr(app, "_annual_client_search_coordinator", coordinator)
    return coordinator
