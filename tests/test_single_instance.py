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

from taxops.ui.single_instance import SingleInstanceGuard


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
    assert guard.acquire() is False


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
