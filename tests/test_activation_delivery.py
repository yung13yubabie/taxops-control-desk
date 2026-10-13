"""Activation retention and local-socket delivery contracts; no lock bypass."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from taxops.ui import app as app_module
from taxops.ui import single_instance as instance


@pytest.mark.parametrize("phase", ["acquire", "bootstrap", "constructor", "show", "running"])
def test_activation_is_retained_until_window_is_fully_shown(qapp, monkeypatch, phase):
    events = []
    holder = []
    class Guard(QObject):
        activation_requested = Signal()
        def __init__(self, name):
            super().__init__()
            holder.append(self)
        def acquire(self):
            events.append("acquire")
            if phase == "acquire":
                self.activation_requested.emit()
            return True
        def release(self):
            events.append("release")
    def signal_at(stage):
        if phase == stage:
            holder[0].activation_requested.emit()
            holder[0].activation_requested.emit()  # Startup requests coalesce.
    def close():
        events.append("db-close")
        holder[0].activation_requested.emit()  # Never reactivate while closing DB.
    def bootstrap():
        events.append("bootstrap")
        signal_at("bootstrap")
        return SimpleNamespace(close=close)
    class Window:
        def __init__(self, container):
            events.append("constructor-start")
            signal_at("constructor")
            events.append("constructor-end")
        def show(self):
            events.append("show-start")
            signal_at("show")
            events.append("show-end")
    def execute(self):
        events.append("exec")
        signal_at("running")
        return 0
    monkeypatch.setattr(instance, "SingleInstanceGuard", Guard)
    monkeypatch.setattr(app_module, "bootstrap", bootstrap)
    monkeypatch.setattr("taxops.ui.main_window.MainWindow", Window)
    monkeypatch.setattr(app_module, "_activate_window", lambda window: events.append("activate"))
    monkeypatch.setattr(QApplication, "exec", execute)
    assert app_module.run() == 0
    assert events.count("activate") == (2 if phase == "running" else 1)
    assert events.index("show-end") < events.index("activate") < events.index("db-close")
    assert events[-2:] == ["db-close", "release"]
    assert events.index("acquire") < events.index("bootstrap")


def test_real_mainwindow_constructor_processes_an_early_activation(qapp, temp_paths, monkeypatch):
    """A real page's constructor dispatches the queued Qt signal before show."""
    from taxops.ui.main_window import MainWindow
    events, guards, windows = [], [], []
    class Guard(QObject):
        activation_requested = Signal()
        def __init__(self, name):
            super().__init__()
            guards.append(self)
        def acquire(self):
            QTimer.singleShot(0, lambda: (events.append("early_signal"), self.activation_requested.emit()))
            return True
        def release(self):
            events.append("release")
    original_show = MainWindow.show
    def show(window):
        if window not in windows:
            windows.append(window)
        events.append("show")
        original_show(window)
    monkeypatch.setattr(instance, "SingleInstanceGuard", Guard)
    monkeypatch.setattr(app_module, "resolve_paths", lambda **kwargs: temp_paths)
    monkeypatch.setattr(MainWindow, "show", show)
    monkeypatch.setattr(app_module, "_activate_window", lambda window: events.append("activated"))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    try:
        assert app_module.run() == 0
        assert events.index("early_signal") < events.index("show") < events.index("activated")
        assert events.count("activated") == 1
    finally:
        for window in windows:
            window.close()
            window.deleteLater()


@pytest.mark.parametrize("accepted,pending,waits,expected", [
    (-1, [], [], False), (0, [], [], False), (3, [], [], False),
    (9, [0], [], True), (9, [9, 9], [False], False),
    (9, [9, 0], [False], True),
    (9, [9, 4, 0], [True, True], True),
])
def test_notify_requires_complete_write_and_bounded_drain(qapp, tmp_path, monkeypatch, accepted, pending, waits, expected):
    events, counts, outcomes = [], iter(pending), iter(waits)
    class Socket:
        LocalSocketState = instance.QLocalSocket.LocalSocketState
        errorOccurred = SimpleNamespace(connect=lambda callback: None)
        def state(self): return self.LocalSocketState.ConnectedState
        def isValid(self): return True
        def connectToServer(self, name):
            events.append("connect")
        def waitForConnected(self, timeout):
            return True
        def write(self, payload):
            assert payload == b"activate\n"
            return accepted
        def flush(self):
            events.append("flush")
            return False  # Nothing newly flushed may still mean queue already drained.
        def bytesToWrite(self):
            return next(counts)
        def waitForBytesWritten(self, timeout):
            assert 0 < timeout <= 500
            events.append("wait")
            return next(outcomes)
        def disconnectFromServer(self):
            events.append("disconnect")
    monkeypatch.setattr(instance, "QLocalSocket", Socket)
    guard = instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path)
    assert guard.notify_existing() is expected
    assert events[-1] == "disconnect" and events.count("wait") == len(waits)


def test_notification_drain_deadline_cannot_spin_forever(qapp, tmp_path, monkeypatch):
    class Socket:
        errorOccurred = SimpleNamespace(connect=lambda callback: None)
        def connectToServer(self, name): pass
        def waitForConnected(self, timeout): return True
        def write(self, payload): return len(payload)
        def flush(self): pass
        def bytesToWrite(self): return 9
        def waitForBytesWritten(self, timeout): pytest.fail("Deadline has expired")
        def disconnectFromServer(self): pass
    # The operation budget begins before connect; expire the smaller drain
    # budget only after the first queued-bytes check.
    ticks = iter([10.0, 10.0, 10.0, 10.0, 10.0, 11.0, 11.0])
    monkeypatch.setattr(instance, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(instance, "QLocalSocket", Socket)
    assert not instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path).notify_existing()


@pytest.mark.parametrize("chunks,expected", [
    ([b"activate\n"], 1), ([b"act", b"iv", b"ate\n"], 1),
    ([b"activate"], 0), ([b"deactivate\n"], 0),
    ([b"activate\nextra"], 0), ([b"activate\n", b"activate\n"], 1),
    ([b"", b"activate\n"], 1),
])
def test_receiver_retains_partial_frame_and_emits_once_for_exact_payload(qapp, tmp_path, chunks, expected):
    guard = instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path)
    fired = []
    guard.activation_requested.connect(lambda: fired.append(1))
    class Socket:
        chunk = b""
        closed = False
        def read(self, limit):
            assert limit == 10
            return self.chunk[:limit]
        def disconnectFromServer(self):
            self.closed = True
        def deleteLater(self):
            pass
    sock = Socket()
    guard._activation_buffers[sock] = b""
    for chunk in chunks:
        sock.chunk = chunk
        guard._drain_socket(sock)
    assert len(fired) == expected
    guard._forget_socket(sock)
    assert sock not in guard._activation_buffers


def test_disconnect_drains_final_complete_frame_before_forgetting(qapp, tmp_path):
    guard = instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path)
    fired = []
    guard.activation_requested.connect(lambda: fired.append(1))
    class Socket:
        deleted = False
        def read(self, size):
            return b"ate\n"
        def deleteLater(self):
            self.deleted = True
    sock = Socket()
    guard._activation_buffers[sock] = b"activ"
    guard._forget_socket(sock)
    assert fired == [1] and sock.deleted and not guard._activation_buffers


@pytest.mark.parametrize("split", range(1, 9))
def test_each_payload_split_retains_exact_remaining_prefix(qapp, tmp_path, split):
    guard = instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path)
    fired = []
    guard.activation_requested.connect(lambda: fired.append(1))
    class Socket:
        chunk = b""
        def read(self, size):
            return self.chunk
    sock = Socket()
    guard._activation_buffers[sock] = b""
    sock.chunk = b"activate\n"[:split]
    guard._drain_socket(sock)
    assert not fired and guard._activation_buffers[sock] == sock.chunk
    sock.chunk = b"activate\n"[split:]
    guard._drain_socket(sock)
    assert fired == [1] and sock not in guard._activation_buffers


@pytest.mark.parametrize("phase", ["flush", "wait"])
@pytest.mark.parametrize("failure", ["error", "disconnected", "invalid"])
def test_empty_queue_after_pipe_failure_is_not_notification_success(qapp, tmp_path, monkeypatch, phase, failure):
    """Qt Windows can delete a failed pipe writer, making bytesToWrite zero."""
    class Socket:
        LocalSocketState = instance.QLocalSocket.LocalSocketState
        failed = False
        disconnected = False
        def __init__(self):
            self.errorOccurred = SimpleNamespace(connect=lambda callback: setattr(self, "on_error", callback))
        def state(self):
            if self.failed and failure == "disconnected":
                return self.LocalSocketState.UnconnectedState
            return self.LocalSocketState.ConnectedState
        def isValid(self): return not (self.failed and failure == "invalid")
        def connectToServer(self, name): pass
        def waitForConnected(self, timeout): return True
        def write(self, payload): return len(payload)
        def fail_pipe(self):
            self.failed = True
            if failure == "error":
                self.on_error(instance.QLocalSocket.LocalSocketError.PeerClosedError)
        def flush(self):
            if phase == "flush":
                self.fail_pipe()
            return False
        def bytesToWrite(self): return 0 if self.failed else 9
        def waitForBytesWritten(self, timeout):
            self.fail_pipe()
            return False
        def disconnectFromServer(self): self.disconnected = True
    socket = Socket()
    # A callable preserves the enum used by the production status check.
    class Factory:
        LocalSocketState = Socket.LocalSocketState
        LocalSocketError = instance.QLocalSocket.LocalSocketError
        def __new__(cls): return socket
    monkeypatch.setattr(instance, "QLocalSocket", Factory)
    assert not instance.SingleInstanceGuard("synthetic", lock_directory=tmp_path).notify_existing()
    assert socket.failed and socket.disconnected
