"""Bounded endpoint-readiness contracts; real IPC remains in test_single_instance."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalSocket

from taxops.ui import single_instance as instance


class Clock:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 0.025
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def endpoint(monkeypatch, tmp_path, qapp):
    clock = Clock()
    state = SimpleNamespace(ready_at=10.1, connect_cost=0.0, wait_connected_cost=0.0, write_cost=0.0,
        error=QLocalSocket.LocalSocketError.ServerNotFoundError, accepted=9,
        pending=0, drain_cost=0.0, events=[], sockets=[])

    class Socket:
        LocalSocketState = QLocalSocket.LocalSocketState
        LocalSocketError = QLocalSocket.LocalSocketError

        def __init__(self):
            self.connected = False
            self.on_error = lambda error: None
            self.errorOccurred = SimpleNamespace(connect=lambda fn: setattr(self, 'on_error', fn))
            state.sockets.append(self)

        def connectToServer(self, name):
            state.events.append('connect')
            clock.now += state.connect_cost
            self.connected = clock.now >= state.ready_at
            if not self.connected:
                self.on_error(state.error)

        def waitForConnected(self, timeout):
            assert 0 < timeout <= 500
            clock.now += state.wait_connected_cost
            return self.connected

        def error(self):
            return state.error

        def abort(self):
            state.events.append('abort')
            self.connected = False

        def write(self, payload):
            assert self.connected and payload == b'activate\n'
            state.events.append('write')
            clock.now += state.write_cost
            return state.accepted

        def flush(self):
            state.events.append('flush')

        def bytesToWrite(self):
            return state.pending

        def waitForBytesWritten(self, timeout):
            assert 0 < timeout <= 500
            state.events.append(('wait', timeout))
            clock.now += state.drain_cost
            state.pending = 0
            return True

        def state(self):
            return self.LocalSocketState.ConnectedState

        def isValid(self):
            return True

        def disconnectFromServer(self):
            state.events.append('disconnect')

    monkeypatch.setattr(instance, 'time', clock)
    monkeypatch.setattr(instance, 'QLocalSocket', Socket)
    return clock, state, instance.SingleInstanceGuard('synthetic-readiness', lock_directory=tmp_path)


def test_lock_holder_can_publish_endpoint_after_first_connection_fails(endpoint):
    clock, state, guard = endpoint
    lock = QLockFile(str(guard.lock_path))
    assert lock.tryLock(0)
    original = guard.lock_path.read_bytes()
    try:
        assert not guard.acquire()
        assert guard.notify_existing()
        assert state.events.count('connect') > 1
        assert state.events.count('write') == 1
        assert state.events.count('abort') == state.events.count('connect') - 1
        assert guard.lock_path.read_bytes() == original
        assert guard._file_lock is None
    finally:
        lock.unlock()


@pytest.mark.parametrize('error', [QLocalSocket.LocalSocketError.ServerNotFoundError,
                                   QLocalSocket.LocalSocketError.ConnectionRefusedError])
def test_unready_endpoint_stops_at_single_budget_without_writing(endpoint, error):
    clock, state, guard = endpoint
    state.ready_at = float('inf')
    state.error = error
    assert not guard.notify_existing()
    assert 0 < clock.now - 10.0 <= instance._NOTIFY_TIMEOUT_MS / 1000 + 0.001
    assert 'write' not in state.events
    assert len(clock.sleeps) > 1
    assert state.events.count('connect') == state.events.count('abort')


@pytest.mark.parametrize('error', [QLocalSocket.LocalSocketError.SocketAccessError,
    QLocalSocket.LocalSocketError.SocketResourceError, QLocalSocket.LocalSocketError.ConnectionError,
    QLocalSocket.LocalSocketError.UnknownSocketError])
def test_non_readiness_error_fails_without_retry(endpoint, error):
    clock, state, guard = endpoint
    state.error = error
    assert not guard.notify_existing()
    assert state.events.count('connect') == 1
    assert not clock.sleeps and 'write' not in state.events


@pytest.mark.parametrize('accepted', [-1, 0, 3, 8])
def test_any_write_attempt_is_never_replayed(endpoint, accepted):
    clock, state, guard = endpoint
    state.ready_at = 10.0
    state.accepted = accepted
    assert not guard.notify_existing()
    assert state.events.count('write') == 1
    assert state.events[-1] == 'disconnect'


def test_connect_that_returns_after_deadline_never_writes_or_retries(endpoint):
    clock, state, guard = endpoint
    state.connect_cost = 10.0  # Qt Windows connectToServer may block internally.
    assert not guard.notify_existing()
    assert state.events.count('connect') == 1
    assert 'write' not in state.events


def test_deadline_is_shared_with_write_drain_not_reset_after_readiness(endpoint):
    clock, state, guard = endpoint
    state.ready_at = 10.0 + instance._NOTIFY_TIMEOUT_MS / 1000 - 0.05
    state.pending = 9
    state.drain_cost = 0.1
    assert not guard.notify_existing()
    assert state.events.count('write') == 1
    waits = [event[1] for event in state.events if isinstance(event, tuple)]
    assert len(waits) == 1 and 0 < waits[0] <= 50


def test_expired_budget_after_write_does_not_claim_success(endpoint):
    clock, state, guard = endpoint
    state.ready_at = 10.0
    state.write_cost = 10.0
    assert not guard.notify_existing()
    assert state.events.count('write') == 1


def test_ready_legacy_endpoint_uses_original_frame_once_without_new_protocol(endpoint):
    clock, state, guard = endpoint
    state.ready_at = 10.0
    assert guard.notify_existing()
    assert state.events.count('connect') == state.events.count('write') == 1
    assert not clock.sleeps


def test_wait_for_connected_overrun_never_writes_or_retries(endpoint):
    clock, state, guard = endpoint
    state.ready_at = 10.0
    state.wait_connected_cost = 10.0
    assert not guard.notify_existing()
    assert state.events.count('connect') == 1 and 'write' not in state.events


def test_active_legacy_endpoint_probe_releases_file_lock_before_notification(endpoint, monkeypatch):
    clock, state, guard = endpoint
    state.ready_at = 10.0
    assert not guard.acquire()
    assert guard._file_lock is None and not guard.lock_path.exists()
    assert 'write' not in state.events  # Empty compatibility probe never activates.
    assert guard.notify_existing()
    assert state.events.count('connect') == 2 and state.events.count('write') == 1


def test_owner_exiting_without_endpoint_is_not_notification_success(endpoint, monkeypatch):
    clock, state, guard = endpoint
    state.ready_at = float('inf')
    owner = QLockFile(str(guard.lock_path))
    assert owner.tryLock(0)
    sleep = clock.sleep
    def owner_exits(seconds):
        owner.unlock()
        sleep(seconds)
    monkeypatch.setattr(clock, 'sleep', owner_exits)
    try:
        assert not guard.acquire()
        assert not guard.notify_existing()
        assert 'write' not in state.events
        assert not guard.lock_path.exists()
        # The app's existing single reacquire is safe only after atomic ownership.
        assert owner.tryLock(0)
    finally:
        owner.unlock()


def test_app_reacquires_real_lock_once_after_owner_cancels_before_listen(endpoint, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from taxops.ui import app as app_module
    clock, state, guard = endpoint
    state.ready_at = float('inf')
    owner = QLockFile(str(guard.lock_path))
    assert owner.tryLock(0)
    events = []
    sleep = clock.sleep
    def owner_exits(seconds):
        owner.unlock()
        sleep(seconds)
    monkeypatch.setattr(clock, 'sleep', owner_exits)
    class Server:
        SocketOption = SimpleNamespace(UserAccessOption=1)
        removeServer = staticmethod(lambda name: None)
        def __init__(self, parent):
            self.newConnection = SimpleNamespace(connect=lambda fn: None)
        def setSocketOptions(self, options):
            pass
        def listen(self, name):
            events.append('listen')
            return True
        def close(self):
            events.append('close-endpoint')
        def deleteLater(self):
            pass
    monkeypatch.setattr(instance, 'QLocalServer', Server)
    original = guard.acquire
    def acquire():
        events.append('acquire')
        return original()
    monkeypatch.setattr(guard, 'acquire', acquire)
    monkeypatch.setattr(instance, 'SingleInstanceGuard', lambda name: guard)
    def bootstrap():
        assert guard._file_lock is not None and guard._file_lock.isLocked()
        events.append('bootstrap')
        return SimpleNamespace(close=lambda: events.append('close-database'))
    monkeypatch.setattr(app_module, 'bootstrap', bootstrap)
    monkeypatch.setattr('taxops.ui.main_window.MainWindow',
        lambda container: SimpleNamespace(show=lambda: events.append('show')))
    monkeypatch.setattr(QApplication, 'exec', lambda self: 0)
    try:
        assert app_module.run() == 0
        assert events == ['acquire', 'acquire', 'listen', 'bootstrap', 'show',
                          'close-database', 'close-endpoint']
        assert 'write' not in state.events and not guard.lock_path.exists()
    finally:
        owner.unlock()
        guard.release()
