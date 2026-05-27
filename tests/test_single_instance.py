"""Single-instance guard via QLocalServer/QLocalSocket."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

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


@pytest.mark.skip(
    reason=(
        "QLocalSocket payload delivery requires two separate processes — "
        "in-process Qt drops server-side bytes when the client disconnects "
        "before the holder's event loop drains readyRead. Verified manually "
        "via dual EXE launch on Windows."
    )
)
def test_notify_existing_fires_activation_signal(qtbot, server_name: str) -> None:
    holder = SingleInstanceGuard(server_name)
    try:
        assert holder.acquire() is True

        with qtbot.waitSignal(holder.activation_requested, timeout=2000):
            notifier = SingleInstanceGuard(server_name)
            assert notifier.acquire() is False
            assert notifier.notify_existing() is True
    finally:
        holder.release()


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
