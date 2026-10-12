"""Atomic-file-lock contracts; full IPC integration remains test_single_instance."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QLockFile

from taxops.ui import app as app_module
from taxops.ui import single_instance as instance


@pytest.fixture
def synthetic_ipc(monkeypatch):
    """Keep IPC out of these file-lock-only tests, including restricted Linux."""
    servers = []
    class Server:
        SocketOption = SimpleNamespace(UserAccessOption=1)
        @staticmethod
        def removeServer(name):
            pass
        def __init__(self, parent=None):
            self.newConnection = SimpleNamespace(connect=lambda callback: None)
            servers.append(self)
        def setSocketOptions(self, options):
            pass
        def listen(self, name):
            return True
        def close(self):
            pass
        def deleteLater(self):
            pass
    monkeypatch.setattr(instance, "QLocalServer", Server)
    class Socket:
        def connectToServer(self, name):
            pass
        def waitForConnected(self, ms):
            return False
    monkeypatch.setattr(instance, "QLocalSocket", Socket)
    return servers


def test_two_guards_share_real_atomic_file_and_release(tmp_path, qapp, synthetic_ipc):
    first = instance.SingleInstanceGuard("same synthetic name", lock_directory=tmp_path)
    second = instance.SingleInstanceGuard("same synthetic name", lock_directory=tmp_path)
    try:
        assert first.lock_path == second.lock_path
        assert first.acquire()
        assert first._file_lock.staleLockTime() == 0
        assert first.acquire()  # Safe idempotency, no second recursive QLockFile.
        original = first.lock_path.read_bytes()
        assert not second.acquire()
        second.release()
        assert first.lock_path.read_bytes() == original
        assert len(synthetic_ipc) == 1
        first.release()
        assert not first.lock_path.exists()
        assert second.acquire()
    finally:
        second.release()
        first.release()
    assert not first.lock_path.exists()


def test_default_lock_root_is_stable_data_not_temp_or_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "本機 資料"))
    monkeypatch.setenv("TEMP", str(tmp_path / "first-temp"))
    first = instance.SingleInstanceGuard("TaxOpsTest-only")
    monkeypatch.setenv("TEMP", str(tmp_path / "second-temp"))
    monkeypatch.setattr(instance, "__file__", str(tmp_path / "_MEI_fake" / "module.py"))
    second = instance.SingleInstanceGuard("TaxOpsTest-only")
    assert first.lock_path == second.lock_path
    assert first.lock_path.parent == tmp_path / "本機 資料" / "TaxOpsControlDesk" / ".instance-locks"
    assert first.lock_path.name == hashlib.sha256(b"TaxOpsTest-only").hexdigest() + ".lock"


def test_unwritable_lock_parent_fails_before_ipc(tmp_path, qapp, synthetic_ipc):
    blocked = tmp_path / "a-file"
    blocked.write_bytes(b"keep")
    guard = instance.SingleInstanceGuard("test", lock_directory=blocked)
    with pytest.raises(instance.InstanceLockError, match="資料夾"):
        guard.acquire()
    assert synthetic_ipc == []
    assert blocked.read_bytes() == b"keep"


@pytest.mark.parametrize("error", [QLockFile.LockError.PermissionError, QLockFile.LockError.UnknownError])
def test_lock_error_is_not_existing_instance(tmp_path, qapp, synthetic_ipc, monkeypatch, error):
    class BrokenLock:
        def __init__(self, filename):
            pass
        def setStaleLockTime(self, value):
            assert value == 0
        def tryLock(self, timeout):
            assert timeout >= 0
            return False
        def error(self):
            return error
        LockError = QLockFile.LockError
    monkeypatch.setattr(instance, "QLockFile", BrokenLock)
    guard = instance.SingleInstanceGuard("test", lock_directory=tmp_path)
    with pytest.raises(instance.InstanceLockError, match="確認程式"):
        guard.acquire()
    assert synthetic_ipc == []
    guard.release()


def test_same_pid_same_name_old_lock_is_not_removed(tmp_path, qapp, synthetic_ipc):
    first = instance.SingleInstanceGuard("test", lock_directory=tmp_path)
    assert first.acquire()
    try:
        original = first.lock_path.read_bytes()
        second = instance.SingleInstanceGuard("test", lock_directory=tmp_path)
        assert not second.acquire()
        assert first.lock_path.read_bytes() == original
    finally:
        first.release()


def test_startup_lock_permission_failure_is_visible_and_never_bootstraps(qapp, monkeypatch):
    monkeypatch.setattr(instance.SingleInstanceGuard, "acquire", lambda self: (_ for _ in ()).throw(instance.InstanceLockError("請確認資料夾可寫入")))
    monkeypatch.setattr(app_module, "bootstrap", lambda: pytest.fail("must not open database"))
    seen = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical", lambda *a: seen.append(a[2]))
    assert app_module.run() == 1
    assert seen == ["請確認資料夾可寫入"]


def test_no_notification_does_not_claim_window_activated(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(instance.SingleInstanceGuard, "acquire", lambda self: (calls.append("acquire"), False)[1])
    monkeypatch.setattr(instance.SingleInstanceGuard, "notify_existing", lambda self: False)
    monkeypatch.setattr(app_module, "bootstrap", lambda: pytest.fail("must not open database"))
    seen = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a: seen.append(a[2]))
    assert app_module.run() == 1
    assert calls == ["acquire", "acquire"]
    assert len(seen) == 1 and "暫時無法" in seen[0]
    assert "已將" not in seen[0]


def test_exited_owner_allows_one_bounded_startup_retry(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from taxops.db.migrate import UnsupportedSchemaError
    outcomes = iter([False, True])
    monkeypatch.setattr(instance.SingleInstanceGuard, "acquire", lambda self: next(outcomes))
    monkeypatch.setattr(instance.SingleInstanceGuard, "notify_existing", lambda self: False)
    # Reach the normal bootstrap after the retry; retain the schema failure UI.
    monkeypatch.setattr(app_module, "bootstrap", lambda: (_ for _ in ()).throw(UnsupportedSchemaError({"future"})))
    seen = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical", lambda *a: seen.append(a[1]))
    assert QApplication.instance() is qapp
    assert app_module.run() == 1
    assert seen == ["資料版本不相容"]


def test_crashed_child_lock_recovers_without_manual_deletion(tmp_path, qapp, synthetic_ipc):
    import os
    import subprocess
    import sys
    guard = instance.SingleInstanceGuard("crash-proof", lock_directory=tmp_path)
    code = """
import os, sys
from PySide6.QtCore import QCoreApplication, QLockFile
app = QCoreApplication([])
lock = QLockFile(sys.argv[1]); lock.setStaleLockTime(0)
assert lock.tryLock(0)
os._exit(77)
"""
    result = subprocess.run([sys.executable, "-c", code, str(guard.lock_path)],
                            env=os.environ.copy(), timeout=30, capture_output=True)
    assert result.returncode == 77, result.stderr
    assert guard.lock_path.exists()
    try:
        assert guard.acquire()
        assert guard._file_lock.isLocked()
    finally:
        guard.release()
    assert not guard.lock_path.exists()


def test_same_pid_name_reused_metadata_is_conservatively_retained(tmp_path, qapp, synthetic_ipc):
    import os
    guard = instance.SingleInstanceGuard("pid-reuse-proof", lock_directory=tmp_path)
    holder = QLockFile(str(guard.lock_path))
    holder.setStaleLockTime(0)
    assert holder.tryLock(0)
    contents = guard.lock_path.read_bytes()
    holder.unlock()
    # Model a previous lifetime's file with a now-live, same-name reused PID.
    # There is no held OS handle, so protection must not depend on age alone.
    guard.lock_path.write_bytes(contents)
    os.utime(guard.lock_path, (1, 1))
    assert not guard.acquire()
    assert guard.lock_path.read_bytes() == contents
    guard.release()
    assert guard.lock_path.read_bytes() == contents


def test_foreign_host_metadata_is_not_force_removed(tmp_path, qapp, synthetic_ipc):
    import os
    import subprocess
    import sys
    guard = instance.SingleInstanceGuard("host-proof", lock_directory=tmp_path)
    code = """
import os, sys
from PySide6.QtCore import QCoreApplication, QLockFile
app = QCoreApplication([])
lock = QLockFile(sys.argv[1]); lock.setStaleLockTime(0)
assert lock.tryLock(0)
os._exit(77)
"""
    result = subprocess.run([sys.executable, "-c", code, str(guard.lock_path)],
                            env=os.environ.copy(), timeout=30, capture_output=True)
    assert result.returncode == 77, result.stderr
    contents = guard.lock_path.read_bytes().splitlines()
    assert len(contents) >= 3
    # Use an actually dead PID, and remove optional machine/boot IDs so a
    # same-machine ID cannot supersede the hostname under test.
    contents = contents[:3] + [b"", b""]
    local_hostname = contents[2]
    contents[2] = b"synthetic-other-machine.invalid"
    value = b"\n".join(contents) + b"\n"
    guard.lock_path.write_bytes(value)
    assert not guard.acquire()
    assert guard.lock_path.read_bytes() == value
    # Positive control: the same dead PID and file now identifies this host.
    contents[2] = local_hostname
    guard.lock_path.write_bytes(b"\n".join(contents) + b"\n")
    try:
        assert guard.acquire()
    finally:
        guard.release()


def test_ipc_close_failure_still_releases_only_owned_file_lock(tmp_path, qapp, synthetic_ipc, monkeypatch):
    guard = instance.SingleInstanceGuard("close-failure", lock_directory=tmp_path)
    assert guard.acquire()
    monkeypatch.setattr(guard._server, "close", lambda: (_ for _ in ()).throw(RuntimeError("synthetic close")))
    with pytest.raises(RuntimeError, match="synthetic close"):
        guard.release()
    assert guard._server is None and guard._file_lock is None
    assert not guard.lock_path.exists()
    guard.release()


def test_database_close_precedes_lock_release(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication
    events = []
    monkeypatch.setattr(instance.SingleInstanceGuard, "acquire", lambda self: True)
    monkeypatch.setattr(instance.SingleInstanceGuard, "release", lambda self: events.append("release"))
    monkeypatch.setattr(app_module, "bootstrap", lambda: SimpleNamespace(close=lambda: events.append("close_database")))
    monkeypatch.setattr("taxops.ui.main_window.MainWindow", lambda container: SimpleNamespace(show=lambda: None))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert app_module.run() == 0
    assert events == ["close_database", "release"]
