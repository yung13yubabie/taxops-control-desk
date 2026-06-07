from __future__ import annotations

import sqlite3
import time

import pytest
from PySide6.QtWidgets import QApplication

from taxops.core.paths import ensure_paths
from taxops.services.registry_download import DownloadError
from taxops.ui.pages.settings_page import _RegistryWorker


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


def test_registry_worker_unknown_error_is_sanitized(qapp, temp_paths) -> None:
    ensure_paths(temp_paths)

    def task(_container):
        raise RuntimeError("sensitive internal detail")

    worker = _RegistryWorker(temp_paths, task)
    errored = []
    native_finished = []
    worker.errored.connect(errored.append)
    worker.finished.connect(lambda: native_finished.append(True))

    worker.start()

    _wait_for_worker(qapp, worker)
    assert native_finished == [True]
    assert errored == ["system.unexpected"]
