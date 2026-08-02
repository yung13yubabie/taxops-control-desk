from __future__ import annotations

import sqlite3
import threading
import time

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QThread,
    Signal,
    qInstallMessageHandler,
)
from shiboken6 import isValid


def _wait_until(qapp, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate()


def _flush_controlled_worker_delete(qapp, worker: QObject) -> None:
    """Consume deleteLater while the worker's owning dialog is still alive."""
    QCoreApplication.sendPostedEvents(worker, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert not isValid(worker)
    if _ControlledWorker.instance is worker:
        _ControlledWorker.instance = None


def test_shared_local_worker_uses_fresh_readonly_connection_and_closes(
    container, qapp, monkeypatch
):
    from taxops.ui.workers.local_registry_search import LocalRegistrySearchWorker

    container.conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, cache_version, imported_at) "
        "VALUES ('87654321', '背景查詢公司', 'v1', datetime('now'))"
    )
    container.conn.commit()
    real_connect = sqlite3.connect
    calls: list[tuple[str, bool, float]] = []
    opened: list[sqlite3.Connection] = []

    def tracking_connect(database, *args, **kwargs):
        calls.append((str(database), bool(kwargs.get("uri")), float(kwargs["timeout"])))
        connection = real_connect(database, *args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(
        "taxops.ui.workers.local_registry_search.sqlite3.connect", tracking_connect
    )
    worker = LocalRegistrySearchWorker(
        str(container.paths.db_path), "背景查詢", limit=20
    )
    results: list[list[dict[str, object]]] = []
    errors: list[str] = []
    worker.succeeded.connect(results.append)
    worker.errored.connect(errors.append)
    worker.start()

    _wait_until(qapp, lambda: not worker.isRunning())
    assert worker.wait(1_000)
    assert errors == []
    assert [row["tax_id"] for row in results[0]] == ["87654321"]
    assert calls and calls[0][1:] == (True, 10.0)
    assert "mode=ro" in calls[0][0]
    assert opened[0] is not container.conn
    try:
        opened[0].execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("worker-owned SQLite connection was not closed")


def test_shared_local_worker_maps_interruption_to_timeout(container, qapp, monkeypatch):
    from taxops.ui.workers.local_registry_search import LocalRegistrySearchWorker

    monkeypatch.setattr(
        "taxops.ui.workers.local_registry_search.TaxRegistryRepository.search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("interrupted")
        ),
    )
    worker = LocalRegistrySearchWorker(str(container.paths.db_path), "逾時查詢")
    errors: list[str] = []
    worker.errored.connect(errors.append)
    worker.start()
    _wait_until(qapp, lambda: not worker.isRunning())
    assert worker.wait(1_000)
    assert errors == ["registry.search.timeout"]


class _ControlledWorker(QObject):
    succeeded = Signal(object)
    errored = Signal(str)
    finished = Signal()
    instance = None

    def __init__(self, _db_path, query, *, limit=20, parent=None):
        super().__init__(parent)
        self.query = query
        self.limit = limit
        self.running = False
        _ControlledWorker.instance = self

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def complete(self, rows):
        self.succeeded.emit(rows)
        self.running = False
        self.finished.emit()

    def fail(self, code):
        self.errored.emit(code)
        self.running = False
        self.finished.emit()


def test_new_client_name_search_is_async_busy_and_safe_to_close(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.LocalRegistrySearchWorker",
        _ControlledWorker,
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog.show()
    dialog._search_input.setText("設計業")
    dialog._search_btn.click()
    worker = _ControlledWorker.instance

    assert worker is not None and worker.running
    assert worker.query == "設計業"
    assert dialog._search_status.text() == "查詢中，請稍候…"
    assert not dialog._search_btn.isEnabled()
    assert not dialog._fill_btn.isEnabled()
    assert not dialog.save_button.isEnabled()

    dialog.reject()
    assert dialog.isVisible()
    assert dialog._search_status.text() == "查詢仍在進行，完成後才能關閉視窗。"

    worker.complete([])
    qapp.processEvents()
    assert dialog._local_worker is None
    assert dialog._search_btn.isEnabled()
    assert dialog.save_button.isEnabled()
    _flush_controlled_worker_delete(qapp, worker)
    dialog.reject()
    assert not dialog.isVisible()


def test_new_client_stale_async_result_is_ignored_and_error_recovers_controls(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.LocalRegistrySearchWorker",
        _ControlledWorker,
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("舊查詢")
    dialog._search_btn.click()
    worker = _ControlledWorker.instance
    assert worker is not None
    dialog._search_input.setText("新查詢")
    worker.complete(
        [{"tax_id": "11112222", "business_name": "舊結果", "business_address": ""}]
    )
    qapp.processEvents()
    assert dialog._result_combo.count() == 0
    _flush_controlled_worker_delete(qapp, worker)
    assert "已忽略" in dialog._search_status.text()

    dialog._search_btn.click()
    worker = _ControlledWorker.instance
    assert worker is not None
    worker.fail("registry.search.timeout")
    qapp.processEvents()
    assert dialog._local_worker is None
    assert dialog._search_btn.isEnabled()
    assert dialog.save_button.isEnabled()
    assert "逾時" in dialog._search_status.text()
    _flush_controlled_worker_delete(qapp, worker)


def test_new_client_exact_tax_id_remains_synchronous(container, qapp, monkeypatch):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", lambda *_args: None
    )

    class ForbiddenWorker:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("exact tax-id lookup must not create a worker")

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.LocalRegistrySearchWorker",
        ForbiddenWorker,
    )
    monkeypatch.setattr(
        container.tax_registry_repo,
        "search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("UI thread must use find_by_tax_id for an exact hit")
        ),
    )
    container.conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, cache_version, imported_at) "
        "VALUES ('11223344', '同步統編公司', 'v1', datetime('now'))"
    )
    container.conn.commit()
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("11223344")
    dialog._search_btn.click()
    assert dialog._result_combo.count() == 1
    assert dialog._local_worker is None


def test_new_client_exact_miss_runs_fallback_only_in_worker_and_restores_result(
    container, qapp, monkeypatch
):
    from taxops.repositories.tax_registry import TaxRegistryRepository
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", lambda *_args: None
    )

    container.conn.execute(
        "INSERT INTO tax_registry_cache("
        "tax_id, business_name, industry_code_1, industry_name_1, cache_version, imported_at"
        ") VALUES ('99112233', '含 22334455 的公司', '22334455', '八位行業', 'v1', datetime('now'))"
    )
    container.conn.commit()
    gui_thread = QThread.currentThread()
    started = threading.Event()
    release = threading.Event()
    original_search = TaxRegistryRepository.search

    def guarded_search(repo, query, *, limit=20):
        assert QThread.currentThread() is not gui_thread
        started.set()
        assert release.wait(3.0)
        return original_search(repo, query, limit=limit)

    monkeypatch.setattr(TaxRegistryRepository, "search", guarded_search)
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("22334455")
    dialog._search_btn.click()
    assert started.wait(2.0)
    assert dialog._local_worker is not None
    assert not dialog._search_btn.isEnabled()
    assert not dialog.save_button.isEnabled()

    release.set()
    _wait_until(qapp, lambda: dialog._local_worker is None)
    assert dialog._result_combo.count() == 1
    assert "99112233" in dialog._result_combo.itemText(0)
    assert dialog._search_btn.isEnabled()
    assert dialog.save_button.isEnabled()


def test_registry_page_exact_hit_is_sync_but_exact_miss_fallback_is_worker_only(
    container, qapp, monkeypatch
):
    from taxops.repositories.tax_registry import TaxRegistryRepository
    from taxops.ui.pages.registry_page import RegistryPage

    container.conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, cache_version, imported_at) "
        "VALUES ('33445566', '統編直接命中', 'v1', datetime('now'))"
    )
    container.conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, cache_version, imported_at) "
        "VALUES ('66778899', '名稱包含 44556677', 'v1', datetime('now'))"
    )
    container.conn.commit()
    page = RegistryPage(container)
    gui_thread = QThread.currentThread()
    original_search = TaxRegistryRepository.search
    started = threading.Event()
    release = threading.Event()

    def guarded_search(repo, query, *, limit=20):
        assert QThread.currentThread() is not gui_thread
        started.set()
        assert release.wait(3.0)
        return original_search(repo, query, limit=limit)

    monkeypatch.setattr(TaxRegistryRepository, "search", guarded_search)
    page._query_edit.setText("33445566")
    page._search_btn.click()
    assert page._local_worker is None
    assert page._result is not None
    assert page._result["business_name"] == "統編直接命中"

    page._query_edit.setText("44556677")
    page._search_btn.click()
    assert started.wait(2.0)
    assert page._local_worker is not None
    assert not page._search_btn.isEnabled()
    assert not page._gcis_btn.isEnabled()

    release.set()
    _wait_until(qapp, lambda: page._local_worker is None)
    assert page._result is not None
    assert page._result["tax_id"] == "66778899"
    assert page._search_btn.isEnabled()
    assert page._gcis_btn.isEnabled()


def test_exact_miss_worker_error_restores_both_ui_entry_points(
    container, qapp, monkeypatch
):
    from taxops.repositories.tax_registry import TaxRegistryRepository
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog
    from taxops.ui.pages.registry_page import RegistryPage

    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", lambda *_args: None
    )

    gui_thread = QThread.currentThread()

    def background_failure(_repo, _query, *, limit=20):
        assert QThread.currentThread() is not gui_thread
        raise sqlite3.DatabaseError("simulated worker failure")

    monkeypatch.setattr(TaxRegistryRepository, "search", background_failure)

    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("55667788")
    dialog._search_btn.click()
    _wait_until(qapp, lambda: dialog._local_worker is None)
    assert dialog._search_btn.isEnabled()
    assert dialog.save_button.isEnabled()
    assert "失敗" in dialog._search_status.text()

    page = RegistryPage(container)
    page._query_edit.setText("77889900")
    page._search_btn.click()
    _wait_until(qapp, lambda: page._local_worker is None)
    assert page._search_btn.isEnabled()
    assert page._gcis_btn.isEnabled()
    assert "失敗" in page._status_label.text()


def test_real_dialog_close_waits_for_native_worker_without_qthread_destroyed_warning(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog
    from taxops.ui.workers.local_registry_search import TaxRegistryRepository

    started = threading.Event()
    release = threading.Event()
    original_search = TaxRegistryRepository.search

    def delayed_search(repo, query, *, limit=20):
        started.set()
        assert release.wait(3.0)
        return original_search(repo, query, limit=limit)

    monkeypatch.setattr(TaxRegistryRepository, "search", delayed_search)
    qt_messages: list[str] = []
    previous_handler = qInstallMessageHandler(
        lambda _mode, _context, message: qt_messages.append(message)
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    try:
        dialog.show()
        dialog._search_input.setText("原生背景查詢")
        dialog._search_btn.click()
        assert started.wait(2.0)
        dialog.close()
        qapp.processEvents()
        assert dialog.isVisible()
        assert dialog._search_status.text() == "查詢仍在進行，完成後才能關閉視窗。"

        release.set()
        _wait_until(qapp, lambda: dialog._local_worker is None)
        dialog.close()
        qapp.processEvents()
        assert not dialog.isVisible()
        assert not any("QThread: Destroyed" in message for message in qt_messages)
    finally:
        release.set()
        qInstallMessageHandler(previous_handler)
