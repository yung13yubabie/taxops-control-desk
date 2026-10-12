"""Synthetic progress-dialog lifecycle checks on the current schema."""

from __future__ import annotations


import errno
import sqlite3
import time

import zipfile


import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QThread

from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from shiboken6 import isValid


from taxops.services.registry.parser import EXPECTED_HEADERS

from taxops.ui.pages.settings_page import SettingsPage


def _flush_owned(app, page):
    app.processEvents()
    # Only drain the objects owned by this page; other test modules may still
    # own queued Qt objects and their teardown responsibility remains theirs.
    for child in page.findChildren(QProgressDialog) + page.findChildren(QThread):
        if isValid(child):
            if isinstance(child, QThread):
                if child.isRunning():
                    continue
                # finished can precede native thread-local cleanup. Synchronize
                # before explicitly forcing deletion in the test event loop.
                assert child.wait(5000)
            QCoreApplication.sendPostedEvents(child, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("outcome", ["success", "read_error"])
def test_finished_imports_dispose_progress_and_threads(
    container, qapp, tmp_path, monkeypatch, outcome
):
    # Independent review contract: inspect closure in the owning worker thread,
    # not a main-thread affinity error that could hide a still-open connection.
    import taxops.ui.pages.settings_page as settings_module
    from taxops.services.container import ServiceContainer

    opened, closed = [], {}
    original_open = settings_module.open_connection
    original_close = ServiceContainer.close

    def capture_open(path):
        connection = original_open(path)
        opened.append(connection)
        return connection

    def capture_close(value):
        original_close(value)
        if value.conn in opened:
            try:
                value.conn.execute("SELECT 1")
            except sqlite3.ProgrammingError as exc:
                closed[value.conn] = str(exc)
            else:
                closed[value.conn] = "still open"

    monkeypatch.setattr(settings_module, "open_connection", capture_open)
    monkeypatch.setattr(ServiceContainer, "close", capture_close)
    source = tmp_path / "synthetic.zip"
    text = (
        ",".join(EXPECTED_HEADERS)
        + "\n"
        + ",".join(
            [
                "合成地址",
                "11111111",
                "",
                "合成商號",
                "1000",
                "1150101",
                "獨資",
                "N",
                "000000",
                "合成",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        + "\n"
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("BGMOPEN1.csv", text)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), "")
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[1:3]))
    if outcome == "read_error":

        def read_error(*args, **kwargs):
            raise OSError(errno.EIO, "synthetic read failure")

        monkeypatch.setattr(
            "taxops.services.registry.importer.TaxRegistryImporter.import_zip",
            read_error,
        )
    page = SettingsPage(container)
    try:
        for _ in range(5):
            page._slice2_buttons[0].click()
            deadline = time.monotonic() + 5
            while page._active_worker is not None and time.monotonic() < deadline:
                _flush_owned(qapp, page)
                time.sleep(0.002)
            _flush_owned(qapp, page)
            assert page._active_worker is None
            assert page.findChildren(QProgressDialog) == []
            assert page.findChildren(QThread) == []
            assert page._slice2_buttons[0].isEnabled()
            assert "closed database" in closed[opened[-1]]
        assert container.tax_registry_repo.count() == (1 if outcome == "success" else 0)
        assert len(warnings) == (0 if outcome == "success" else 5)
        assert len(opened) == len(closed) == 5
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_import_file_picker_cancel_creates_no_worker_or_progress(
    container, qapp, monkeypatch
):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    opened = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.open_connection",
        lambda *args: opened.append(args),
    )
    page = SettingsPage(container)
    for _ in range(5):
        page._slice2_buttons[0].click()
    assert page._active_worker is None
    assert opened == []
    assert page.findChildren(QProgressDialog) == []
    page.deleteLater()
    QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)
