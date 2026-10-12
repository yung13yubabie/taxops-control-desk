"""A temporary-file cleanup failure must not undo or misreport a committed operation."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from taxops.core.paths import resolve_paths
from taxops.services.backup import BackupError, BackupService
from taxops.services.clients import CreateClientInput
from taxops.ui.app import bootstrap
from taxops.ui.pages.settings_page import SettingsPage


@pytest.fixture
def pair(tmp_path):
    source = bootstrap(resolve_paths(override_root=tmp_path / "source"))
    target = bootstrap(resolve_paths(override_root=tmp_path / "target"))
    source.clients.create_client(CreateClientInput("RESTORED", "合成備份客戶"))
    target.clients.create_client(CreateClientInput("ORIGINAL", "合成現有客戶"))
    yield source, target
    source.close()
    target.close()


def fail_cleanup(monkeypatch, prefix):
    cleanup = tempfile.TemporaryDirectory.cleanup

    def fail(temporary):
        if Path(temporary.name).name.startswith(prefix):
            raise PermissionError("synthetic temporary file still in use")
        cleanup(temporary)

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", fail)


def clients(container):
    with closing(sqlite3.connect(container.paths.db_path)) as fresh:
        return [r[0] for r in fresh.execute("SELECT client_code FROM clients")]


def test_committed_backup_survives_cleanup_error_and_shows_success_warning(
    pair, qapp, monkeypatch
):
    source, _ = pair
    fail_cleanup(monkeypatch, ".backup_stage_")
    infos, errors = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[1:3]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a[1:3]))
    page = SettingsPage(source)
    try:
        page.on_backup()
        with closing(sqlite3.connect(source.paths.db_path)) as fresh:
            records = fresh.execute("SELECT backup_path FROM backup_records").fetchall()
            count = fresh.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action='backup.create'"
            ).fetchone()[0]
        assert len(records) == count == 1
        assert Path(records[0][0]).is_file()
        assert len(source.backup.cleanup_warnings) == 1
        assert errors == []
        assert infos[0][0] == "備份完成"
        assert "操作已完成" in infos[0][1]
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("legacy", [False, True])
def test_committed_restore_cleanup_error_still_quits_with_success_warning(
    pair, qapp, monkeypatch, legacy
):
    source, target = pair
    create = (
        source.backup.create_database_snapshot
        if legacy
        else source.backup.create_backup
    )
    archive = Path(create(source.paths).backup_path)
    if legacy:
        remove = BackupService._remove_sqlite_files

        def fail(path):
            if path.name.startswith(".restore_stage_"):
                raise PermissionError("synthetic temporary file still in use")
            remove(path)

        monkeypatch.setattr(BackupService, "_remove_sqlite_files", staticmethod(fail))
    else:
        fail_cleanup(monkeypatch, ".restore_bundle_")
    infos, errors, quits = [], [], []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(archive), ""))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[1:3]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a[1:3]))
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    page = SettingsPage(target)
    try:
        page.on_restore()
        assert clients(target) == ["RESTORED"]
        assert len(target.backup.cleanup_warnings) == 1
        assert quits == [True]
        assert errors == []
        assert infos[0][0] == "還原完成"
        assert "操作已完成" in infos[0][1]
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_precommit_backup_failure_keeps_original_error_when_cleanup_also_fails(
    pair, monkeypatch
):
    source, _ = pair
    fail_cleanup(monkeypatch, ".backup_stage_")

    def audit_error(**kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(source.backup._audit, "record", audit_error)
    with pytest.raises(BackupError, match="backup.create.failed") as raised:
        source.backup.create_backup(source.paths)
    assert str(raised.value.__cause__) == "synthetic audit failure"
    assert source.conn.execute("SELECT COUNT(*) FROM backup_records").fetchone()[0] == 0
    assert list(source.paths.backups_dir.glob("*.taxops.zip")) == []
    assert clients(source) == ["RESTORED"]


def test_precommit_restore_failure_keeps_original_db_when_cleanup_also_fails(
    pair, monkeypatch
):
    source, target = pair
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    fail_cleanup(monkeypatch, ".restore_bundle_")

    def validation_error(*a, **kw):
        raise BackupError("backup.invalid_file")

    monkeypatch.setattr(target.backup, "_assert_integrity", validation_error)
    with pytest.raises(BackupError, match="backup.invalid_file"):
        target.backup.restore_backup(archive, target.paths)
    assert clients(target) == ["ORIGINAL"]
    assert len(target.backup.cleanup_warnings) == 1


def test_cleanup_warnings_reset_for_next_successful_operation(pair, monkeypatch):
    source, _ = pair
    with monkeypatch.context() as patch:
        fail_cleanup(patch, ".backup_stage_")
        source.backup.create_backup(source.paths)
        assert len(source.backup.cleanup_warnings) == 1
    source.backup.create_backup(source.paths)
    assert source.backup.cleanup_warnings == ()
