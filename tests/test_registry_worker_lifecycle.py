from __future__ import annotations

import sqlite3
import time
import logging

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from taxops.core.paths import ensure_paths
from taxops.services.registry_download import DownloadError
from taxops.ui.pages.settings_page import SettingsPage, _RegistryWorker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait_for_worker(qapp: QApplication, worker: _RegistryWorker) -> None:
    deadline = time.monotonic() + 30
    while worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert not worker.isRunning()
    assert worker.wait(1_000)


def test_registry_worker_success_closes_owned_connection(qapp, temp_paths) -> None:
    ensure_paths(temp_paths)
    captured = []

    def task(container):
        captured.append(container.conn)
        return "done"

    worker = _RegistryWorker(temp_paths, task)
    succeeded = []
    native_finished = []
    worker.succeeded.connect(succeeded.append)
    worker.finished.connect(lambda: native_finished.append(True))

    worker.start()

    _wait_for_worker(qapp, worker)
    assert native_finished == [True]
    assert succeeded == ["done"]
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")


def test_registry_worker_known_error_emits_code_and_closes_connection(
    qapp, temp_paths
) -> None:
    ensure_paths(temp_paths)
    captured = []

    def task(container):
        captured.append(container.conn)
        raise DownloadError("registry.download.network_error")

    worker = _RegistryWorker(temp_paths, task)
    errored = []
    native_finished = []
    worker.errored.connect(errored.append)
    worker.finished.connect(lambda: native_finished.append(True))

    worker.start()

    _wait_for_worker(qapp, worker)
    assert native_finished == [True]
    assert errored == ["registry.download.network_error"]
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")


def test_registry_worker_unknown_error_is_sanitized(
    qapp, temp_paths, caplog
) -> None:
    ensure_paths(temp_paths)

    def task(_container):
        raise RuntimeError("sensitive internal detail")

    worker = _RegistryWorker(temp_paths, task)
    errored = []
    native_finished = []
    worker.errored.connect(errored.append)
    worker.finished.connect(lambda: native_finished.append(True))

    with caplog.at_level(
        logging.ERROR, logger="taxops.ui.pages.settings_page"
    ):
        worker.start()
        _wait_for_worker(qapp, worker)
    assert native_finished == [True]
    assert errored == ["system.unexpected"]
    assert "Registry worker failed unexpectedly" in caplog.text
    assert "RuntimeError" in caplog.text


def test_settings_page_keeps_operation_active_until_worker_cleanup_finishes(
    qapp,
    container,
    monkeypatch,
) -> None:
    class ControlledWorker(QObject):
        succeeded = Signal(object)
        errored = Signal(str)
        finished = Signal()
        instance = None

        def __init__(self, *_args, parent=None, **_kwargs) -> None:
            super().__init__(parent)
            self.running = False
            ControlledWorker.instance = self

        def start(self) -> None:
            self.running = True

        def isRunning(self) -> bool:
            return self.running

    monkeypatch.setattr(
        "taxops.ui.pages.settings_page._RegistryWorker",
        ControlledWorker,
    )
    page = SettingsPage(container)
    active_during_success = []
    page._run_async(
        lambda _worker_container: "done",
        "Testing cleanup lifecycle",
        lambda _result: active_during_success.append(page.has_active_operation()),
    )
    worker = page._active_worker
    assert worker is not None
    assert worker is ControlledWorker.instance
    for control in (
        page._save_display_name_btn,
        page._save_query_mode_btn,
        page._backup_btn,
        page._restore_btn,
    ):
        assert not control.isEnabled()

    backup_calls = []
    monkeypatch.setattr(
        container.backup,
        "create_backup",
        lambda _paths: backup_calls.append(True),
    )
    page._backup_btn.click()
    assert backup_calls == []

    worker.succeeded.emit("done")
    qapp.processEvents()
    assert active_during_success == []
    assert page._active_worker is worker
    assert worker.isRunning()

    worker.running = False
    worker.finished.emit()
    qapp.processEvents()
    assert active_during_success == [False]
    assert page._active_worker is None
    for control in (
        page._save_display_name_btn,
        page._save_query_mode_btn,
        page._backup_btn,
        page._restore_btn,
    ):
        assert control.isEnabled()
    QCoreApplication.sendPostedEvents(worker, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert not isValid(worker)
