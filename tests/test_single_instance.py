"""Single-instance guard via QLocalServer/QLocalSocket."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer

from taxops.ui.single_instance import InstanceLockError, SingleInstanceGuard


@pytest.fixture(autouse=True)
def isolated_lock_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-data"))


@pytest.fixture()
def server_name() -> str:
    return f"TaxOpsTest-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _qapp():
    app = QApplication.instance()
    created = False
    if app is None:
        app = QApplication([])
        created = True
    yield app
    if created:
        app.processEvents()


def test_first_acquire_returns_true(server_name: str) -> None:
    guard = SingleInstanceGuard(server_name)
    try:
        assert guard.acquire() is True
    finally:
        guard.release()


def test_second_acquire_returns_false(server_name: str) -> None:
    first = SingleInstanceGuard(server_name)
    second = SingleInstanceGuard(server_name)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
        second.release()


def test_release_allows_reacquisition(server_name: str) -> None:
    g1 = SingleInstanceGuard(server_name)
    assert g1.acquire() is True
    g1.release()
    g2 = SingleInstanceGuard(server_name)
    try:
        assert g2.acquire() is True
    finally:
        g2.release()


def test_notify_existing_returns_false_when_no_holder(server_name: str) -> None:
    orphan = SingleInstanceGuard(server_name)
    assert orphan.notify_existing() is False


def test_listen_failure_does_not_fail_open(
    server_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QLocalServer, "listen", lambda self, name: False)
    monkeypatch.setattr(
        QLocalServer, "errorString", lambda self: "simulated listen failure"
    )

    guard = SingleInstanceGuard(server_name)
    with pytest.raises(InstanceLockError):
        guard.acquire()
    assert not guard.lock_path.exists()


def test_notify_existing_fires_activation_signal_across_processes(
    tmp_path: Path, server_name: str
) -> None:
    ready = tmp_path / "ready.txt"
    activated = tmp_path / "activated.txt"
    holder_code = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QTimer
from taxops.ui.single_instance import SingleInstanceGuard

app = QCoreApplication([])
guard = SingleInstanceGuard(sys.argv[1])
if not guard.acquire():
    raise SystemExit(2)
Path(sys.argv[2]).write_text("ready", encoding="utf-8")
guard.activation_requested.connect(
    lambda: (Path(sys.argv[3]).write_text("activated", encoding="utf-8"), app.quit())
)
QTimer.singleShot(5000, app.quit)
exit_code = app.exec()
guard.release()
raise SystemExit(exit_code if Path(sys.argv[3]).exists() else 3)
"""
    notifier_code = """
import sys
from PySide6.QtCore import QCoreApplication
from taxops.ui.single_instance import SingleInstanceGuard

app = QCoreApplication([])
guard = SingleInstanceGuard(sys.argv[1])
if guard.acquire():
    guard.release()
    raise SystemExit(2)
raise SystemExit(0 if guard.notify_existing() else 3)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, server_name, str(ready), str(activated)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # A fresh Windows Python/PySide process can take more than ten seconds
        # to import while the full Qt suite and antivirus are both active.
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            if holder.poll() is not None:
                _stdout, stderr = holder.communicate()
                pytest.fail(
                    f"holder process exited with {holder.returncode}: {stderr}"
                )
            time.sleep(0.05)
        assert ready.exists(), "holder process did not acquire the local server"
        notifier = subprocess.run(
            [sys.executable, "-c", notifier_code, server_name],
            env=env,
            check=False,
            timeout=30,
        )
        assert notifier.returncode == 0
        assert holder.wait(timeout=5) == 0
        assert activated.read_text(encoding="utf-8") == "activated"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_payload_check_rejects_unrelated_bytes(server_name: str) -> None:
    """Sockets that disconnect without sending the activate payload must not
    trigger the activation signal (e.g. probe connections from acquire())."""
    holder = SingleInstanceGuard(server_name)
    fired: list[int] = []
    holder.activation_requested.connect(lambda: fired.append(1))
    try:
        assert holder.acquire() is True
        # Probe via second guard — its acquire() must not raise the window.
        second = SingleInstanceGuard(server_name)
        assert second.acquire() is False
        QApplication.processEvents()
        assert fired == []
    finally:
        holder.release()


def test_notification_waits_for_real_lock_holder_to_listen(tmp_path, server_name, monkeypatch):
    """The lock is really held while Qt's activation endpoint is unpublished.

    This exercises real Qt IPC on each OS; a host that cannot listen fails,
    just like the other IPC tests. It is not a frozen Windows acceptance.
    """
    import json
    locked = tmp_path / "locked"
    finished = tmp_path / "finished.json"
    release_endpoint = tmp_path / "release-endpoint"
    code = """
import json, sys, time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtNetwork import QLocalServer
from taxops.ui.single_instance import SingleInstanceGuard
app = QApplication([])
guard = SingleInstanceGuard(sys.argv[1])
window = QWidget()
received = []
visible_at_activation = []
def activate():
    visible = window.isVisible()
    visible_at_activation.append(visible)
    received.append("activate")
    assert visible
    QTimer.singleShot(100, app.quit)
guard.activation_requested.connect(activate)
original = QLocalServer.listen
def delayed_listen(server, name):
    assert guard._file_lock is not None and guard._file_lock.isLocked()
    Path(sys.argv[2]).write_text("lock held; endpoint not yet listening", encoding="utf-8")
    deadline = time.monotonic() + 15
    while not Path(sys.argv[4]).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Notifier did not release endpoint barrier")
        time.sleep(0.01)
    return original(server, name)
QLocalServer.listen = delayed_listen
try:
    assert guard.acquire()
    window.show()
    QTimer.singleShot(10000, app.quit)
    app.exec()
    Path(sys.argv[3]).write_text(json.dumps({"received": received,
        "visible_at_activation": visible_at_activation,
        "window_visible_after_exec": window.isVisible()}), encoding="utf-8")
    raise SystemExit(0 if received == ["activate"] and visible_at_activation == [True] else 3)
finally:
    window.close()
    guard.release()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    child = subprocess.Popen([sys.executable, "-c", code, server_name, str(locked), str(finished), str(release_endpoint)],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30
        while not locked.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert locked.exists(), "Child did not hold the real lock before listen"
        guard = SingleInstanceGuard(server_name)
        assert not guard.acquire()
        from PySide6.QtNetwork import QLocalSocket
        original_connect = QLocalSocket.connectToServer
        def connect_and_release(socket, name):
            original_connect(socket, name)
            # Release the real holder only after the first actual absent-pipe
            # result, making this regression independent of scheduler timing.
            if name == server_name and socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                assert socket.error() in (QLocalSocket.LocalSocketError.ServerNotFoundError,
                                          QLocalSocket.LocalSocketError.ConnectionRefusedError)
                release_endpoint.write_text("First real connect failed", encoding="utf-8")
        monkeypatch.setattr(QLocalSocket, "connectToServer", connect_and_release)
        notified = guard.notify_existing()
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, (stdout, stderr)
        assert notified
        assert guard._notification_diagnostics["attempts"] > 1
        result = json.loads(finished.read_text(encoding="utf-8"))
        assert result["received"] == ["activate"]
        assert result["visible_at_activation"] == [True]
        # QApplication handles Quit by closing its windows before exec returns.
        # The after-exec observation is diagnostic, not activation readiness.
        assert isinstance(result["window_visible_after_exec"], bool)
    finally:
        if child.poll() is None:
            if sys.platform == "win32":
                from build_tools.owned_process_cleanup import terminate_owned_tree
                terminate_owned_tree(child, tmp_path / "owned-child-failure-cleanup.json")
            else:
                child.kill()  # Only this synthetic child owned by this test.
                child.wait(timeout=5)


@pytest.mark.parametrize("visibility", [[True], [False], [False, True], [True, True]])
def test_activation_observation_uses_actual_callback_visibility(visibility):
    """Exercise the embedded callback, including Qt swallowing a slot assertion."""
    import ast
    import inspect
    from types import SimpleNamespace
    test_body = ast.parse(inspect.getsource(test_notification_waits_for_real_lock_holder_to_listen)).body[0]
    child_source = next(node.value.value for node in test_body.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "code")
    child = ast.parse(child_source)
    callback = next(node for node in child.body if isinstance(node, ast.FunctionDef) and node.name == "activate")
    exit_call = next(node.exc for node in ast.walk(child) if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "SystemExit")
    window = SimpleNamespace(visible=True)
    window.isVisible = lambda: window.visible
    context = {"window": window, "received": [], "visible_at_activation": [],
        "app": SimpleNamespace(quit=lambda: None),
        "QTimer": SimpleNamespace(singleShot=lambda ms, fn: None)}
    exec(compile(ast.Module(body=[callback], type_ignores=[]), "<actual-child-callback>", "exec"), context)
    for visible in visibility:
        window.visible = visible
        if visible:
            context["activate"]()
        else:
            with pytest.raises(AssertionError):
                context["activate"]()
    # A later visible state must not conceal an invisible or repeated callback.
    window.visible = True
    assert context["received"] == ["activate"] * len(visibility)
    assert context["visible_at_activation"] == visibility
    actual_exit = eval(compile(ast.Expression(exit_call.args[0]), "<actual-child-exit>", "eval"), context)
    assert actual_exit == (0 if visibility == [True] else 3)
