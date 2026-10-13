"""Probe controls and transparent instrumentation, not native Windows evidence."""
import gc
import json
from types import SimpleNamespace
import weakref

import pytest
from build_tools import notification_transport_probe as probe


class Signal:
    def __init__(self):
        self.callbacks = []
    def connect(self, callback):
        self.callbacks.append(callback)
    def emit(self, value):
        for callback in self.callbacks:
            callback(value)


class Socket:
    LocalSocketState = SimpleNamespace(ConnectedState=SimpleNamespace(value=3))
    def __init__(self):
        self.bytesWritten, self.errorOccurred = Signal(), Signal()
        self.pending, self.connected, self.calls = 0, False, []
    def connectToServer(self, name):
        self.connected = True
        self.calls.append('connect')
    def write(self, data):
        self.calls.append('write')
        self.pending = len(data)
        return len(data)
    def flush(self):
        self.calls.append('flush')
        return False
    def waitForBytesWritten(self, timeout):
        self.calls.append(('wait', timeout))
        count, self.pending = self.pending, 0
        self.bytesWritten.emit(count)
        return True
    def disconnectFromServer(self):
        self.calls.append('disconnect')
        self.connected = False
    def bytesToWrite(self):
        return self.pending
    def state(self):
        return SimpleNamespace(value=3 if self.connected else 0)
    def isValid(self):
        return self.connected
    def error(self):
        return SimpleNamespace(value=-1)


@pytest.mark.parametrize('case', probe.CASES)
def test_trace_delegates_exact_methods_and_results_without_exporting_input(tmp_path, case):
    (tmp_path / 'allow-write').write_text('synthetic control')
    original = Socket.write
    socket = Socket()
    with probe.SocketTrace(Socket, tmp_path, case) as trace:
        assert socket.connectToServer('must-not-export-a-user-path') is None
        assert socket.write(b'activate\n') == 9
        assert socket.flush() is False
        assert socket.waitForBytesWritten(499) is True
        socket.disconnectFromServer()
    assert Socket.write is original
    assert (tmp_path / 'connected').exists() is (case in {'accepted_no_dispatch', 'peer_close'})
    assert (tmp_path / 'write-returned').exists() is (case in {'delayed_accept', 'accepted_no_dispatch'})
    assert socket.calls == ['connect', 'write', 'flush', ('wait', 499), 'disconnect']
    assert trace.terminal['pending_bytes'] == 0 and trace.terminal['valid'] is True
    assert trace.terminal['state'] == 3 and trace.terminal['bytes_written_signal_total'] == 9
    assert not trace.terminal['observed_error']
    assert 'must-not-export' not in json.dumps(trace.events)
    assert trace.events[-1]['valid'] is False
    assert len(trace.events) <= probe.TRACE_LIMIT
    reference = weakref.ref(socket)
    del socket
    gc.collect()
    assert reference() is None, 'Instrumentation must not prolong a pending socket lifetime'


def test_trace_records_error_and_keeps_pre_disconnect_snapshot_when_bounded(tmp_path):
    socket = Socket()
    with probe.SocketTrace(Socket, tmp_path, 'immediate') as trace:
        socket.connectToServer('synthetic')
        socket.write(b'activate\n')
        socket.errorOccurred.emit(SimpleNamespace(value=1))
        for _ in range(probe.TRACE_LIMIT):
            socket.flush()
        socket.disconnectFromServer()
    assert trace.truncated and len(trace.events) == probe.TRACE_LIMIT
    assert trace.terminal['pending_bytes'] == 9 and trace.terminal['observed_error']
    assert trace.terminal['valid'] is True


def test_trace_restores_real_methods_after_delegate_exception(tmp_path, monkeypatch):
    def fail(socket, data):
        raise RuntimeError('synthetic transport exception')
    monkeypatch.setattr(Socket, 'write', fail)
    with pytest.raises(RuntimeError, match='synthetic transport'):
        with probe.SocketTrace(Socket, tmp_path, 'immediate'):
            Socket().write(b'activate\n')
    assert Socket.write is fail


def test_non_windows_rejection_precedes_directory_or_actor_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'sys', SimpleNamespace(platform='linux'))
    output = tmp_path / 'not-created'
    with pytest.raises(RuntimeError, match='Windows'):
        probe.run(output)
    with pytest.raises(RuntimeError, match='Windows'):
        probe.actor('sender', output, 'immediate', 'synthetic')
    assert not output.exists()


def test_control_handshake_failure_is_bounded(tmp_path, monkeypatch):
    ticks = iter([0.0, probe.CONTROL_TIMEOUT + 1])
    monkeypatch.setattr(probe, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(RuntimeError, match='handshake'):
        probe.wait_marker(tmp_path / 'missing')


def test_process_output_artifact_contains_only_digest_and_count():
    import hashlib
    import io
    raw = b'Traceback at C:/Users/synthetic/private/path; full environment must not leak'
    summary = probe.summarize_process_output(io.BytesIO(raw))
    assert summary == {'output_bytes': len(raw), 'output_sha256': hashlib.sha256(raw).hexdigest(),
                       'raw_text_omitted': True}
    assert 'Users' not in json.dumps(summary) and 'environment' not in json.dumps(summary)


def test_cleanup_preserves_both_live_actor_receipts_without_raw_fields(tmp_path, monkeypatch):
    actors = [SimpleNamespace(pid=1234, poll=lambda: None),
              SimpleNamespace(pid=5678, poll=lambda: None)]
    called = []
    def cleanup(process, evidence):
        assert evidence == tmp_path / 'profile/raw-cleanup.json'
        called.append(process.pid)
        return {'pid': process.pid, 'normal_cleanup': False,
            'status': 'owned_tree_termination_requested', 'descendant_cleanup_verified': False,
            'taskkill_exit_code': 0, 'parent_exit_code': 1,
            'stdout': 'C:/Users/synthetic/private/path', 'stderr': 'must-not-export',
            'error': {'type': 'SyntheticError', 'message': 'must-not-export'}}
    monkeypatch.setattr(probe, 'terminate_owned_tree', cleanup)
    probe.cleanup_owned_processes(actors, tmp_path)
    report = json.loads((tmp_path / 'owned-process-cleanup.json').read_text(encoding='utf-8'))
    assert called == [1234, 5678]
    assert [(record['role'], record['pid']) for record in report['processes']] == [
        ('receiver', 1234), ('sender', 5678)]
    assert all(record['error_type'] == 'SyntheticError' for record in report['processes'])
    assert all(record['descendant_cleanup_verified'] is False for record in report['processes'])
    assert 'must-not-export' not in json.dumps(report) and 'Users' not in json.dumps(report)


def test_cleanup_does_not_target_exited_actor(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'terminate_owned_tree', lambda *args: pytest.fail('Exited actor must not be targeted'))
    probe.cleanup_owned_processes([SimpleNamespace(poll=lambda: 0)], tmp_path)
    assert not (tmp_path / 'owned-process-cleanup.json').exists()


@pytest.mark.parametrize('valid,connected', [(False, True), (True, False), (False, False)])
def test_connect_marker_never_certifies_failed_or_invalid_connection(tmp_path, monkeypatch, valid, connected):
    monkeypatch.setattr(Socket, 'isValid', lambda self: valid)
    monkeypatch.setattr(Socket, 'state', lambda self: SimpleNamespace(value=3 if connected else 0))
    socket = Socket()
    with probe.SocketTrace(Socket, tmp_path, 'peer_close'):
        socket.connectToServer('synthetic')
    assert not (tmp_path / 'connected').exists()
    assert socket.calls == ['connect']  # No handshake/replay manufactured a connection.


@pytest.mark.parametrize('fault', [None, 'role', 'case', 'qt_version', 'pyside_version',
    'application_type', 'python_version', 'single_instance_source_sha256', 'probe_source_sha256'])
def test_actor_identity_is_bound_to_parent_source_and_requested_control(fault):
    expected = {'single_instance_source_sha256': 'source-hash', 'probe_source_sha256': 'probe-hash',
        'qt_version': '6.10.2', 'pyside_version': '6.10.2', 'python_version': [3, 11, 9]}
    receipt = {**expected, 'role': 'sender', 'case': 'immediate', 'qt_version': '6.10.2',
        'pyside_version': '6.10.2', 'application_type': 'QCoreApplication',
        'status': 'diagnostic_complete', 'notify_result': False}
    if fault:
        receipt[fault] = 'wrong'
        with pytest.raises(ValueError, match='identity'):
            probe.validate_actor_receipt(receipt, 'sender', 'immediate', expected)
    else:
        probe.validate_actor_receipt(receipt, 'sender', 'immediate', expected)


@pytest.mark.parametrize('accepted', [-1, 0, 3, 9])
def test_delayed_hold_requires_real_complete_write_return(tmp_path, accepted):
    probe.write_json(tmp_path / 'write-returned', {'accepted_bytes': accepted})
    if accepted == 9:
        probe.wait_full_write_marker(tmp_path)
    else:
        with pytest.raises(RuntimeError, match='full frame'):
            probe.wait_full_write_marker(tmp_path)


def test_first_cleanup_exception_does_not_skip_other_owned_actor(tmp_path, monkeypatch):
    actors = [SimpleNamespace(pid=1234, poll=lambda: None),
              SimpleNamespace(pid=5678, poll=lambda: None)]
    called = []
    def cleanup(process, evidence):
        called.append(process.pid)
        if process.pid == 1234:
            raise OSError('synthetic receipt write failure')
        return {'pid': process.pid, 'status': 'owned_tree_termination_requested',
                'normal_cleanup': False, 'descendant_cleanup_verified': False}
    monkeypatch.setattr(probe, 'terminate_owned_tree', cleanup)
    probe.cleanup_owned_processes(actors, tmp_path)
    report = json.loads((tmp_path / 'owned-process-cleanup.json').read_text(encoding='utf-8'))
    assert called == [1234, 5678]
    assert report['processes'][0] == {'pid': 1234, 'role': 'receiver', 'normal_cleanup': False,
        'status': 'cleanup_call_failed', 'descendant_cleanup_verified': False, 'error_type': 'OSError'}
    assert report['processes'][1]['pid'] == 5678 and report['processes'][1]['role'] == 'sender'


def test_public_receipt_failure_happens_after_every_owned_cleanup_attempt(tmp_path, monkeypatch):
    actors = [SimpleNamespace(pid=1234, poll=lambda: None),
              SimpleNamespace(pid=5678, poll=lambda: None)]
    events = []
    def cleanup(process, evidence):
        events.append(process.pid)
        return {'pid': process.pid, 'descendant_cleanup_verified': False}
    def fail_write(path, report):
        events.append('write')
        assert [record['pid'] for record in report['processes']] == [1234, 5678]
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(probe, 'terminate_owned_tree', cleanup)
    monkeypatch.setattr(probe, 'write_json', fail_write)
    with pytest.raises(OSError, match='synthetic disk'):
        probe.cleanup_owned_processes(actors, tmp_path)
    assert events == [1234, 5678, 'write']
