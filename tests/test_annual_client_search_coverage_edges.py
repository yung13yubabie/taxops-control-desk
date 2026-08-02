from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from PySide6.QtCore import QThread

from taxops.ui.workers import annual_client_search


def _capture_worker(
    worker: annual_client_search.AnnualClientSearchWorker,
) -> tuple[
    list[annual_client_search.AnnualClientSearchResult],
    list[tuple[int, str]],
]:
    results: list[annual_client_search.AnnualClientSearchResult] = []
    errors: list[tuple[int, str]] = []
    worker.succeeded.connect(results.append)
    worker.errored.connect(lambda token, code: errors.append((token, code)))
    worker.run()
    return results, errors


def test_real_worker_returns_all_same_name_matches_and_closes_readonly_connection(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = container.clients_repo.insert(
        client_code="SAME-002",
        client_name="同名記帳士事務所",
        contact_name="王小明",
    )
    second = container.clients_repo.insert(
        client_code="SAME-001",
        client_name="同名記帳士事務所",
        contact_name="王小華",
    )
    preselected = container.clients_repo.insert(
        client_code="OTHER-001",
        client_name="另一家有限公司",
    )
    container.conn.commit()
    real_connect = sqlite3.connect
    calls: list[tuple[str, bool, float]] = []
    opened: list[sqlite3.Connection] = []

    def tracking_connect(database, *args, **kwargs):
        calls.append(
            (str(database), bool(kwargs.get("uri")), float(kwargs["timeout"]))
        )
        connection = real_connect(database, *args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(annual_client_search.sqlite3, "connect", tracking_connect)
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path),
        "  同名記帳士事務所  ",
        41,
        preselected_client_id=preselected.id,
    )

    results, errors = _capture_worker(worker)

    assert errors == []
    assert len(results) == 1
    result = results[0]
    assert result.request_token == worker.request_token == 41
    assert result.normalized_query == "同名記帳士事務所"
    assert [(choice.id, choice.client_code, choice.client_name) for choice in result.choices] == [
        (second.id, "SAME-001", "同名記帳士事務所"),
        (first.id, "SAME-002", "同名記帳士事務所"),
    ]
    assert result.has_more is False
    assert result.preselected is not None
    assert result.preselected.id == preselected.id
    assert calls and calls[0][1:] == (True, 10.0)
    assert "mode=ro" in calls[0][0]
    assert opened[0] is not container.conn
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize("invalid_preselection", [None, True, 0])
def test_blank_query_is_bounded_and_rejects_non_positive_or_boolean_preselection(
    container,
    invalid_preselection: int | None,
) -> None:
    for index in range(3):
        container.clients_repo.insert(
            client_code=f"BOUND-EDGE-{index}",
            client_name=f"分頁客戶 {index}",
        )
    container.conn.commit()
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path),
        "   ",
        42,
        limit=2,
        preselected_client_id=invalid_preselection,
    )

    results, errors = _capture_worker(worker)

    assert errors == []
    assert len(results) == 1
    assert results[0].normalized_query == ""
    assert len(results[0].choices) == 2
    assert results[0].has_more is True
    assert results[0].preselected is None


def test_missing_and_deleted_preselection_never_leaks_into_result(container) -> None:
    deleted = container.clients_repo.insert(
        client_code="DELETED-PRESELECT",
        client_name="已刪除的預選客戶",
    )
    container.conn.execute(
        "UPDATE clients SET deleted_at = datetime('now') WHERE id = ?",
        (deleted.id,),
    )
    container.conn.commit()

    for selected_id in (deleted.id, deleted.id + 100_000):
        worker = annual_client_search.AnnualClientSearchWorker(
            str(container.paths.db_path),
            "找不到的關鍵字",
            selected_id,
            preselected_client_id=selected_id,
        )
        results, errors = _capture_worker(worker)
        assert errors == []
        assert results[0].choices == ()
        assert results[0].preselected is None


class _Cursor:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        row: dict[str, object] | None = None,
        on_fetchall: Callable[[], None] | None = None,
    ) -> None:
        self._rows = rows or []
        self._row = row
        self._on_fetchall = on_fetchall

    def fetchall(self) -> list[dict[str, object]]:
        if self._on_fetchall is not None:
            self._on_fetchall()
        return self._rows

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _TrackingConnection:
    row_factory = None

    def __init__(
        self,
        *,
        fail_when: str | None = None,
        failure: BaseException | None = None,
        on_fetchall: Callable[[], None] | None = None,
    ) -> None:
        self.fail_when = fail_when
        self.failure = failure
        self.on_fetchall = on_fetchall
        self.in_transaction = False
        self.progress_calls: list[tuple[object, int]] = []
        self.rollback_count = 0
        self.close_count = 0
        self.interrupt_count = 0

    def execute(self, sql: str, _params=()) -> _Cursor:
        if self.fail_when is not None and self.fail_when in sql:
            assert self.failure is not None
            raise self.failure
        if sql == "BEGIN":
            self.in_transaction = True
        if sql.startswith("SELECT id, client_code"):
            return _Cursor(on_fetchall=self.on_fetchall)
        return _Cursor()

    def set_progress_handler(self, callback, instructions: int) -> None:
        self.progress_calls.append((callback, instructions))

    def rollback(self) -> None:
        self.rollback_count += 1
        self.in_transaction = False

    def close(self) -> None:
        self.close_count += 1

    def interrupt(self) -> None:
        self.interrupt_count += 1


def test_cancellation_after_fetch_suppresses_stale_success_and_cleans_transaction(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CancellationWorker(annual_client_search.AnnualClientSearchWorker):
        cancellation_requested = False

        def isInterruptionRequested(self) -> bool:
            return self.cancellation_requested

    worker = CancellationWorker(
        str(container.paths.db_path), "即將取消", 51
    )
    connection = _TrackingConnection(
        on_fetchall=lambda: setattr(worker, "cancellation_requested", True)
    )
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: connection,
    )

    results, errors = _capture_worker(worker)

    assert results == []
    assert errors == []
    assert connection.rollback_count == 1
    assert connection.close_count == 1
    assert connection.progress_calls[-1] == (None, 0)
    assert worker._connection is None


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (sqlite3.OperationalError("database is locked"), "annual_client_search.failed"),
        (sqlite3.OperationalError("interrupted"), "annual_client_search.timeout"),
        (sqlite3.DatabaseError("malformed database"), "annual_client_search.failed"),
        (RuntimeError("unexpected private detail"), "system.unexpected"),
    ],
)
def test_connection_failures_map_to_stable_public_codes_without_raw_details(
    container,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    expected_code: str,
) -> None:
    def failing_connect(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(annual_client_search.sqlite3, "connect", failing_connect)
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path), "錯誤查詢", 52
    )

    results, errors = _capture_worker(worker)

    assert results == []
    assert errors == [(52, expected_code)]
    assert all("private" not in code and "locked" not in code for _, code in errors)


def test_elapsed_deadline_maps_operational_error_to_timeout(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monotonic_values = iter((100.0, 111.0))
    monkeypatch.setattr(
        annual_client_search.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("busy")
        ),
    )
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path), "逾時查詢", 53
    )

    results, errors = _capture_worker(worker)

    assert results == []
    assert errors == [(53, "annual_client_search.timeout")]


def test_operational_error_after_cancellation_is_silent(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CancelledWorker(annual_client_search.AnnualClientSearchWorker):
        def isInterruptionRequested(self) -> bool:
            return True

    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("interrupted")
        ),
    )
    worker = CancelledWorker(str(container.paths.db_path), "取消查詢", 54)

    results, errors = _capture_worker(worker)

    assert results == []
    assert errors == []


@pytest.mark.parametrize(
    ("fail_when", "expected_rollbacks"),
    [("PRAGMA query_only", 0), ("SELECT id, client_code", 1)],
)
def test_database_failure_always_removes_progress_handler_and_closes_connection(
    container,
    monkeypatch: pytest.MonkeyPatch,
    fail_when: str,
    expected_rollbacks: int,
) -> None:
    connection = _TrackingConnection(
        fail_when=fail_when,
        failure=sqlite3.DatabaseError("simulated corruption"),
    )
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: connection,
    )
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path), "清理查詢", 55
    )

    results, errors = _capture_worker(worker)

    assert results == []
    assert errors == [(55, "annual_client_search.failed")]
    assert connection.progress_calls[-1] == (None, 0)
    assert connection.rollback_count == expected_rollbacks
    assert connection.close_count == 1
    assert worker._connection is None


def test_cancel_without_live_connection_and_with_live_connection_is_idempotent(
    container,
) -> None:
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path), "取消", 56
    )
    worker.cancel()
    connection = _TrackingConnection()
    worker._connection = connection

    worker.cancel()

    assert connection.interrupt_count == 1


def test_coordinator_handles_plain_qthread_and_aggregate_timeout(qapp) -> None:
    events: list[str] = []

    class FinishedThread(QThread):
        def isFinished(self) -> bool:
            return True

        def requestInterruption(self) -> None:
            events.append("plain-cancel")

    class StuckWorker(annual_client_search.AnnualClientSearchWorker):
        def __init__(self) -> None:
            super().__init__("unused.sqlite", "", 61)
            self.detached = False

        def cancel(self) -> None:
            events.append("annual-cancel")

        def isFinished(self) -> bool:
            return False

        def wait(self, _timeout=0) -> bool:
            events.append("annual-wait")
            return False

        def setParent(self, parent) -> None:
            super().setParent(parent)
            if parent is None:
                self.detached = True

    coordinator = annual_client_search.AnnualClientSearchCoordinator()
    plain = FinishedThread()
    stuck = StuckWorker()
    coordinator.register(plain)
    coordinator.register(stuck)
    annual_client_search._shutdown_survivors.discard(stuck)

    assert coordinator.active_count == 1
    assert coordinator.shutdown(-1) is False
    assert set(events[:-1]) == {"plain-cancel", "annual-cancel"}
    assert events[-1] == "annual-wait"
    assert stuck.detached is True
    assert stuck in annual_client_search._shutdown_survivors

    annual_client_search._shutdown_survivors.discard(stuck)
    coordinator._workers.clear()
    plain.setParent(None)


def test_coordinator_ignores_non_thread_sender_and_requires_qt_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = annual_client_search.AnnualClientSearchCoordinator()
    coordinator._on_worker_finished()
    monkeypatch.setattr(
        annual_client_search.QCoreApplication,
        "instance",
        staticmethod(lambda: None),
    )

    with pytest.raises(
        RuntimeError, match="annual client search requires a Qt application"
    ):
        annual_client_search.annual_client_search_coordinator()
