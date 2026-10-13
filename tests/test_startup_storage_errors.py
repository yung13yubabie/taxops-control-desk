"""Real Qt/SQLite/file-lock storage recovery, with narrowly injected I/O faults.

Only local-socket activation is substituted in the integration fixture: restricted
Linux IPC is covered (and may fail) separately by test_single_instance.py.
"""

from __future__ import annotations

import errno
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from taxops.db import connection
from taxops.ui import app as app_module
from taxops.ui import single_instance as instance
from taxops.ui import startup_errors


def _sqlite_error(code: int) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("synthetic low-level storage detail")
    error.sqlite_errorcode = code
    return error


@pytest.fixture
def file_lock_without_ipc(monkeypatch, temp_paths):
    """Exercise production QLockFile acquisition/release, without socket claims."""
    class Server:
        SocketOption = SimpleNamespace(UserAccessOption=1)
        removeServer = staticmethod(lambda _name: None)

        def __init__(self, _parent=None):
            self.newConnection = SimpleNamespace(connect=lambda _callback: None)

        def setSocketOptions(self, _options):
            pass

        def listen(self, _name):
            return True

        def close(self):
            pass

        def deleteLater(self):
            pass

    class Socket:
        def connectToServer(self, _name):
            pass

        def waitForConnected(self, _timeout):
            return False

    monkeypatch.setattr(instance, "QLocalServer", Server)
    monkeypatch.setattr(instance, "QLocalSocket", Socket)
    monkeypatch.setattr(instance, "resolve_paths", lambda: temp_paths)
    monkeypatch.setattr(app_module, "resolve_paths", lambda **_kwargs: temp_paths)
    return instance.SingleInstanceGuard(app_module._SINGLE_INSTANCE_NAME).lock_path


@pytest.mark.parametrize("scenario", [
    "corrupt", "permission_prepare", "permission_connect", "full_pragma",
    "io_migration", "io_container", "sqlite_connect",
])
def test_storage_failure_real_dialog_preserves_data_and_same_profile_retry(
    qapp, temp_paths, monkeypatch, file_lock_without_ipc, scenario, request, tmp_path,
):
    # QApplication.quit() is process-global: a completed real app.exec() can
    # immediately dismiss later modal loops. Give each complete startup/retry
    # flow a fresh process; do not replace QApplication.exec with a mock. When
    # the matrix collects coverage, collect these children into that same pool.
    if os.environ.get("TAXOPS_STARTUP_STORAGE_TEST_CHILD") != scenario:
        env = os.environ.copy()
        env["TAXOPS_STARTUP_STORAGE_TEST_CHILD"] = scenario
        command = [sys.executable]
        if env.get("COVERAGE_FILE"):
            command += ["-m", "coverage", "run", "--parallel-mode", "--branch", "--source=taxops"]
        command += ["-m", "pytest", request.node.nodeid, "-q", "--tb=short",
                    "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "child")]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return

    from taxops.ui.main_window import MainWindow

    seed = app_module.bootstrap(temp_paths)
    seed.conn.execute(
        "INSERT INTO clients(client_code,client_name,created_at,updated_at) "
        "VALUES ('RECOVERY-001','合成保留客戶','2026-01-01','2026-01-01')"
    )
    seed.conn.commit()
    seed.close()
    attachment = temp_paths.attachments_dir / "合成附件.txt"
    attachment.write_bytes(b"synthetic attachment bytes must survive")
    if scenario == "corrupt":
        temp_paths.db_path.write_bytes(b"synthetic corrupt database; preserve exactly")
    before = (temp_paths.db_path.read_bytes(), attachment.read_bytes())
    enabled = True
    events = []
    opened = []
    lock_path = file_lock_without_ipc
    real_connect = sqlite3.connect
    real_mkdir = Path.mkdir
    real_release = instance.SingleInstanceGuard.release

    class Cursor(sqlite3.Cursor):
        def execute(self, sql, *args, **kwargs):
            if enabled and scenario == "io_container" and sql.startswith("INSERT OR IGNORE INTO app_settings"):
                raise _sqlite_error(sqlite3.SQLITE_IOERR)
            return super().execute(sql, *args, **kwargs)

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if enabled:
                if scenario == "full_pragma" and sql == "PRAGMA journal_mode = WAL":
                    raise _sqlite_error(sqlite3.SQLITE_FULL)
                if scenario == "io_migration" and sql.startswith("SELECT 1 FROM sqlite_master"):
                    raise _sqlite_error(sqlite3.SQLITE_IOERR)
            return super().execute(sql, *args, **kwargs)

        def cursor(self, *args, **kwargs):
            return super().cursor(factory=Cursor)

        def close(self):
            super().close()
            events.append("closed")

    def connect(*args, **kwargs):
        if enabled and scenario == "permission_connect":
            raise PermissionError(errno.EACCES, "synthetic denied")
        if enabled and scenario == "sqlite_connect":
            raise _sqlite_error(sqlite3.SQLITE_CANTOPEN)
        conn = real_connect(*args, **kwargs, factory=Connection)
        opened.append(conn)
        events.append("opened")
        return conn

    def mkdir(path, *args, **kwargs):
        if enabled and scenario == "permission_prepare" and path == temp_paths.attachments_dir:
            raise PermissionError(errno.EACCES, "synthetic denied")
        return real_mkdir(path, *args, **kwargs)

    def release(guard):
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                _ = conn.total_changes
        events.append("release")
        return real_release(guard)

    monkeypatch.setattr(connection.sqlite3, "connect", connect)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(instance.SingleInstanceGuard, "release", release)
    seen = []
    timer = QTimer()
    timer.setInterval(10)

    def close_error_with_keyboard():
        dialog = qapp.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            seen.append({
                "title": dialog.windowTitle(), "text": dialog.text(),
                "buttons": [button.text() for button in dialog.buttons()],
                "lock_held": lock_path.exists(),
                "main_visible": any(isinstance(w, MainWindow) and w.isVisible() for w in qapp.topLevelWidgets()),
            })
            events.append("dialog")
            QTest.keyClick(dialog, Qt.Key.Key_Escape if scenario == "corrupt" else Qt.Key.Key_Return)

    timer.timeout.connect(close_error_with_keyboard)
    timer.start()
    try:
        assert app_module.run() == 1
        if scenario == "corrupt":
            # Retry without replacing the corrupt file must fail again safely.
            assert app_module.run() == 1
    finally:
        timer.stop()
    assert len(seen) == (2 if scenario == "corrupt" else 1)
    for dialog in seen:
        assert dialog["title"] == "無法開啟資料"
        assert dialog["buttons"] == ["確定"]
        assert dialog["lock_held"] and not dialog["main_visible"]
        assert "沒有自動重建資料" in dialog["text"]
        assert "請勿刪除或覆蓋" in dialog["text"]
        assert "Traceback" not in dialog["text"]
        assert "synthetic" not in dialog["text"]
        assert "OperationalError" not in dialog["text"]
        log_path = Path(dialog["text"].split("本機診斷紀錄：", 1)[1].split("\n", 1)[0])
        assert log_path.is_relative_to(temp_paths.data_root.parent)
        diagnostic = log_path.read_text(encoding="utf-8")
        assert "Traceback" in diagnostic and "Error type:" in diagnostic
        assert "synthetic attachment bytes" not in diagnostic
        assert "合成保留客戶" not in diagnostic
        log_path.unlink()  # Only test-created diagnostics, never user data.
    assert not lock_path.exists()
    assert before == (temp_paths.db_path.read_bytes(), attachment.read_bytes())
    assert events[-1] == "release"
    if opened:
        assert events.index("closed") < events.index("dialog") < events.index("release")
    else:
        assert "closed" not in events
    assert sorted(p.name for p in temp_paths.data_root.iterdir()) == [".instance-locks", "attachments", "taxops.sqlite"]

    if scenario == "corrupt":
        return  # No repair, replacement, or claim that corrupt data can reopen.
    enabled = False  # Remove only the injected ordinary I/O cause.
    reopened = []

    def close_recovered_window():
        for window in qapp.topLevelWidgets():
            if isinstance(window, MainWindow) and window.isVisible():
                reopened.append(window._container.conn.execute(
                    "SELECT client_name FROM clients WHERE client_code='RECOVERY-001'"
                ).fetchone()[0])
                window.close()
                qapp.exit(0)

    timer.timeout.disconnect(close_error_with_keyboard)
    timer.timeout.connect(close_recovered_window)
    timer.start()
    try:
        assert app_module.run() == 0
    finally:
        timer.stop()
    assert reopened == ["合成保留客戶"]
    assert attachment.read_bytes() == before[1]
    assert events[-2:] == ["closed", "release"]
    assert not lock_path.exists()


@pytest.mark.parametrize("stage", ["foreign_keys", "row_factory", "migrations", "container"])
def test_setup_failure_keeps_original_error_when_close_also_fails(
    temp_paths, monkeypatch, caplog, stage,
):
    error = _sqlite_error(sqlite3.SQLITE_IOERR)
    close_error = OSError(errno.EIO, "synthetic cleanup failure")
    conn = None
    real_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def __setattr__(self, name, value):
            if stage == "row_factory" and name == "row_factory":
                raise error
            super().__setattr__(name, value)

        def execute(self, sql, *args, **kwargs):
            if stage == "foreign_keys" and sql == "PRAGMA foreign_keys = ON":
                raise error
            return super().execute(sql, *args, **kwargs)

        def close(self):
            raise close_error

    def connect(*args, **kwargs):
        nonlocal conn
        conn = real_connect(*args, **kwargs, factory=Connection)
        return conn

    def fail(*_args):
        raise error

    monkeypatch.setattr(connection.sqlite3, "connect", connect)
    if stage in {"migrations", "container"}:
        monkeypatch.setattr(app_module, "apply_migrations" if stage == "migrations" else "build_container", fail)
    try:
        with pytest.raises(sqlite3.Error) as raised:
            app_module.bootstrap(temp_paths)
        assert raised.value is error
        assert any("cleanup also failed" in note for note in error.__notes__)
        assert "SQLite connection cleanup failed" in caplog.text
        assert conn.total_changes >= 0  # Explicit negative control: not closed.
    finally:
        if conn is not None:
            sqlite3.Connection.close(conn)


def test_failed_pending_migration_rolls_back_its_write_and_closes_connection(
    temp_paths, monkeypatch,
):
    from taxops.db import migrate

    seed = app_module.bootstrap(temp_paths)
    seed.conn.execute(
        "INSERT INTO clients(client_code,client_name,created_at,updated_at) "
        "VALUES ('KEEP-001','合成原有客戶','2026-01-01','2026-01-01')"
    )
    seed.conn.commit()
    before_logical = tuple(seed.conn.iterdump())
    seed.close()
    attachment = temp_paths.attachments_dir / "migration.txt"
    attachment.write_bytes(b"synthetic original attachment")
    before_attachment = attachment.read_bytes()
    real_connect = sqlite3.connect
    opened = []
    pending_wrote = []
    failure = _sqlite_error(sqlite3.SQLITE_IOERR)
    inject_failure = True

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "synthetic_io_failure" in sql:
                if not inject_failure:
                    return super().execute("SELECT 1")
                # The pending transaction really changed a row before failing.
                pending_wrote.append(super().execute(
                    "SELECT client_name FROM clients WHERE client_code='KEEP-001'"
                ).fetchone()[0])
                raise failure
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs, factory=Connection)
        opened.append(conn)
        return conn

    monkeypatch.setattr(connection.sqlite3, "connect", connect)
    monkeypatch.setattr(migrate, "MIGRATIONS", [*migrate.MIGRATIONS, (
        "9998_synthetic_rollback", "UPDATE clients SET client_name='不應保留的變更' "
        "WHERE client_code='KEEP-001'; SELECT synthetic_io_failure; "
        "UPDATE clients SET client_name='合成原有客戶' WHERE client_code='KEEP-001';",
    )])
    with pytest.raises(sqlite3.Error) as raised:
        app_module.bootstrap(temp_paths)
    assert raised.value is failure
    assert pending_wrote == ["不應保留的變更"]
    # Rollback protects data, but SQLite may still update file metadata/pages.
    # Do not promise byte-identical storage after an attempted write.
    assert attachment.read_bytes() == before_attachment
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        _ = opened[0].total_changes
    with real_connect(temp_paths.db_path) as check:
        assert tuple(check.iterdump()) == before_logical
        assert check.execute(
            "SELECT client_name FROM clients WHERE client_code='KEEP-001'"
        ).fetchone()[0] == "合成原有客戶"
        assert check.execute(
            "SELECT version FROM schema_migrations WHERE version='9998_synthetic_rollback'"
        ).fetchall() == []
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()
    # Remove only the failing I/O operation; never copy a saved database back.
    inject_failure = False
    recovered = app_module.bootstrap(temp_paths)
    try:
        assert recovered.conn.execute(
            "SELECT client_name FROM clients WHERE client_code='KEEP-001'"
        ).fetchone()[0] == "合成原有客戶"
        assert recovered.conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version='9998_synthetic_rollback'"
        ).fetchone()[0] == 1
        assert recovered.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert attachment.read_bytes() == before_attachment
    finally:
        recovered.close()


@pytest.mark.parametrize(("error", "expected"), [
    (_sqlite_error(sqlite3.SQLITE_CORRUPT | (2 << 8)), "可能已損壞"),
    (_sqlite_error(sqlite3.SQLITE_NOTADB), "可能已損壞"),
    (_sqlite_error(sqlite3.SQLITE_FULL), "儲存空間不足"),
    (OSError(errno.ENOSPC, "synthetic full"), "儲存空間不足"),
    (PermissionError("synthetic denied"), "目前無法寫入"),
    (OSError(errno.EROFS, "synthetic read-only"), "目前無法寫入"),
    (_sqlite_error(sqlite3.SQLITE_READONLY), "目前無法寫入"),
    (_sqlite_error(sqlite3.SQLITE_BUSY), "資料檔目前忙碌"),
    (_sqlite_error(sqlite3.SQLITE_LOCKED), "資料檔目前忙碌"),
    (_sqlite_error(sqlite3.SQLITE_IOERR), "讀取或寫入程式資料時失敗"),
    (sqlite3.DatabaseError("synthetic unknown"), "讀取或寫入程式資料時失敗"),
    (OSError(errno.EIO, "synthetic I/O"), "讀取或寫入程式資料時失敗"),
])
def test_guidance_uses_codes_without_raw_exception_text(error, expected):
    text = startup_errors._storage_guidance(error)
    assert expected in text
    assert "synthetic" not in text


@pytest.mark.parametrize(("stage", "cleanup_fails"), [
    ("create", False), ("write", False), ("close", False),
    ("write", True), ("close", True),
])
def test_diagnostic_failure_retains_original_storage_guidance(
    monkeypatch, tmp_path, caplog, stage, cleanup_fails,
):
    error = _sqlite_error(sqlite3.SQLITE_FULL)
    real_temporary = startup_errors.tempfile.NamedTemporaryFile
    real_unlink = Path.unlink
    existing = Path(startup_errors.tempfile.gettempdir()) / "TaxOps-startup-existing.log"
    existing.write_bytes(b"existing complete diagnostic must survive")
    created = []
    cleanup_attempts = []

    class FailingOutput:
        def __init__(self, output):
            self.output = output
            self.name = output.name
            self.writes = 0

        def __enter__(self):
            return self

        def write(self, text):
            self.writes += 1
            if stage == "write" and self.writes == 3:
                self.output.write(text[:4])
                self.output.flush()
                raise OSError(errno.ENOSPC, "synthetic partial write")
            return self.output.write(text)

        def __exit__(self, *_args):
            self.output.close()
            if stage == "close":
                raise OSError(errno.EIO, "synthetic flush/close failure")

    def fail(*args, **kwargs):
        if stage == "create":
            raise PermissionError(errno.EACCES, "synthetic temp denied")
        output = real_temporary(*args, **kwargs)
        created.append(Path(output.name))
        return FailingOutput(output)

    def unlink(path, *args, **kwargs):
        cleanup_attempts.append(path)
        assert path in created  # No existing log or other file may be removed.
        if cleanup_fails:
            raise PermissionError(errno.EACCES, "synthetic cleanup denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(startup_errors.tempfile, "NamedTemporaryFile", fail)
    monkeypatch.setattr(Path, "unlink", unlink)
    try:
        text = startup_errors.startup_error_message(error)
        assert "儲存空間不足" in text
        assert "診斷紀錄無法儲存" in text
        assert "本機診斷紀錄：" not in text
        assert "synthetic" not in text and "Traceback" not in text
        assert "Could not save startup diagnostic file" in caplog.text
        assert cleanup_attempts == created
        assert existing.read_bytes() == b"existing complete diagnostic must survive"
        assert all(path.is_relative_to(tmp_path) for path in created)
        assert all(path.exists() == cleanup_fails for path in created)
        if cleanup_fails:
            assert len(created) == 1 and created[0].stat().st_size > 0
            assert str(created[0]) in text
            assert "未完成的診斷檔無法清理" in text
            assert "這不是完整的診斷紀錄" in text
            assert "Could not remove incomplete startup diagnostic file" in caplog.text
        else:
            assert "未完成的診斷檔無法清理" not in text
    finally:
        for path in created:
            real_unlink(path, missing_ok=True)
        real_unlink(existing)


def test_successful_diagnostic_keeps_complete_and_existing_logs(tmp_path):
    existing = Path(startup_errors.tempfile.gettempdir()) / "TaxOps-startup-existing.log"
    existing.write_bytes(b"existing diagnostic")
    created = None
    try:
        text = startup_errors.startup_error_message(_sqlite_error(sqlite3.SQLITE_FULL))
        created = Path(text.split("本機診斷紀錄：", 1)[1].split("\n", 1)[0])
        assert created != existing and created.is_relative_to(tmp_path)
        assert "Error type: OperationalError" in created.read_text(encoding="utf-8")
        assert "SQLite code: 13" in created.read_text(encoding="utf-8")
        assert existing.read_bytes() == b"existing diagnostic"
        assert "診斷紀錄無法儲存" not in text
    finally:
        if created is not None:
            created.unlink()
        existing.unlink()
