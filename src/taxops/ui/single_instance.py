"""Atomic per-user instance lock, with a local socket only for activation.

Pattern:
    guard = SingleInstanceGuard("TaxOpsControlDesk.SingleInstance")
    guard.activation_requested.connect(startup_aware_activator)
    if not guard.acquire():
        return 0 if guard.notify_existing() else 1

The guard owns a ``QLocalServer`` on first instance; subsequent processes
connect to the named pipe, send an ``activate`` message, and exit.  The
first instance receives the message via ``activation_requested`` and the
caller is expected to raise its main window.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ..core.paths import resolve_paths

_log = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 500
_NOTIFY_TIMEOUT_MS = 3000
_CONNECT_RETRY_SECONDS = 0.025
_WRITE_TIMEOUT_MS = 500
_ACTIVATE_PAYLOAD = b"activate\n"


class InstanceLockError(RuntimeError):
    """An instance cannot start safely; the caller must not open the database."""


class SingleInstanceGuard(QObject):
    """Hold a QLockFile for the complete database lifetime.

    QLocalServer alone is not a Windows mutex: multiple servers may listen on
    the same pipe. All new instances must share this stable per-user file,
    outside the onefile extraction directory. Older versions must be closed
    before using the candidate; their socket probe is compatibility assistance,
    not a lock protocol they understand.
    """

    activation_requested = Signal()

    def __init__(self, server_name: str, *, lock_directory: Path | None = None) -> None:
        super().__init__()
        self._server_name = server_name
        self._server: QLocalServer | None = None
        self._activation_buffers: dict[QLocalSocket, bytes] = {}
        directory = lock_directory if lock_directory is not None else resolve_paths().data_root / ".instance-locks"
        self._lock_path = directory.absolute() / (hashlib.sha256(server_name.encode("utf-8")).hexdigest() + ".lock")
        self._file_lock: QLockFile | None = None
        # Anonymous transport diagnostics consumed only by the isolated probe.
        self._notification_diagnostics: dict = {}

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def server_name(self) -> str:
        return self._server_name

    def acquire(self) -> bool:
        """Return True when this process becomes the lock holder.

        Returns False when another process already holds the lock; the caller
        should then call :meth:`notify_existing` and exit cleanly.
        """
        if self._server is not None:
            return True
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InstanceLockError("無法準備啟動所需的資料夾。請確認資料夾可寫入且空間足夠，再重新開啟。") from exc
        lock = QLockFile(str(self._lock_path))
        # A long-running application is never stale merely because time passed.
        # Qt checks the PID/process name and the OS-held file handle. Never call
        # removeStaleLockFile() or delete a lock ourselves.
        lock.setStaleLockTime(0)
        if not lock.tryLock(250):
            if lock.error() == QLockFile.LockError.LockFailedError:
                return False
            raise InstanceLockError("無法確認程式是否已開啟。請確認資料夾可寫入且空間足夠，再重新開啟。")
        self._file_lock = lock
        probe = QLocalSocket()
        probe.connectToServer(self._server_name)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            probe.disconnectFromServer()
            self.release()
            return False
        QLocalServer.removeServer(self._server_name)
        server = QLocalServer(self)
        # Restrict the named pipe to the current user. Windows defaults to
        # per-user namespaces but on Linux/macOS the socket otherwise lives in
        # a world-writable temp directory.  Explicit option = cross-platform
        # safe and prevents another user DoS'ing the lock.
        server.setSocketOptions(
            QLocalServer.SocketOption.UserAccessOption
        )
        if not server.listen(self._server_name):
            _log.warning(
                "single_instance: listen failed name=%s err=%s",
                self._server_name,
                server.errorString(),
            )
            server.deleteLater()
            self.release()
            raise InstanceLockError("程式無法完成啟動。請稍候再試；若舊版程式仍在執行，請先關閉舊版。")
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def notify_existing(self) -> bool:
        """Wait briefly for an endpoint, then submit the activation frame once.

        Only failed connections before any write may be retried. All waits
        share one budget; Qt's synchronous native connect can itself overrun
        that budget, so check it again before sending anything.
        """
        started = time.monotonic()
        deadline = started + _NOTIFY_TIMEOUT_MS / 1000
        diagnostic = self._notification_diagnostics = {
            "phase": "connect", "attempts": 0, "last_error_code": None,
            "accepted_bytes": None,
        }
        sock = None
        write_error = False

        def record_error(error) -> None:
            nonlocal write_error
            write_error = True
            diagnostic["last_error_code"] = error.value

        def connected_without_error() -> bool:
            return (
                not write_error
                and sock.state() == QLocalSocket.LocalSocketState.ConnectedState
                and sock.isValid()
            )

        try:
            while time.monotonic() < deadline:
                diagnostic["attempts"] += 1
                write_error = False
                sock = QLocalSocket()
                sock.errorOccurred.connect(record_error)
                sock.connectToServer(self._server_name)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    sock.abort()
                    return False
                if sock.waitForConnected(min(_CONNECT_TIMEOUT_MS, max(1, int(remaining * 1000)))):
                    break
                error = sock.error()
                diagnostic["last_error_code"] = error.value
                # No bytes have been submitted. Abandon this connection before
                # a fresh attempt, including any still-pending native connect.
                sock.abort()
                sock.disconnectFromServer()
                sock = None
                if error not in (
                    QLocalSocket.LocalSocketError.ServerNotFoundError,
                    QLocalSocket.LocalSocketError.ConnectionRefusedError,
                ):
                    return False
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(_CONNECT_RETRY_SECONDS, remaining))
            else:
                return False
            if time.monotonic() >= deadline:
                return False
            diagnostic["phase"] = "write"
            diagnostic["accepted_bytes"] = sock.write(_ACTIVATE_PAYLOAD)
            if diagnostic["accepted_bytes"] != len(_ACTIVATE_PAYLOAD):
                return False
            sock.flush()
            diagnostic["phase"] = "drain"
            deadline = min(deadline, time.monotonic() + _WRITE_TIMEOUT_MS / 1000)
            # flush() may already have drained everything. A successful wait
            # reports progress, not necessarily completion of the full frame.
            while sock.bytesToWrite() > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                if not sock.waitForBytesWritten(max(1, int(remaining * 1000))):
                    # Completion may have preceded the wait, so its signal
                    # is no longer observable. Pending bytes still mean failure.
                    if sock.bytesToWrite() > 0:
                        return False
                    break
            # Windows may clear its write queue by deleting a failed pipe
            # writer. An empty queue alone cannot establish successful submission.
            if time.monotonic() >= deadline or not connected_without_error():
                return False
            diagnostic["phase"] = "submitted"
            return True
        finally:
            diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            if sock is not None:
                sock.disconnectFromServer()

    def release(self) -> None:
        server = self._server
        self._server = None
        self._activation_buffers.clear()
        try:
            if server is not None:
                server.close()
                QLocalServer.removeServer(self._server_name)
                server.deleteLater()
        finally:
            if self._file_lock is not None:
                self._file_lock.unlock()
                self._file_lock = None

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                continue
            self._activation_buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._drain_socket(s))
            sock.disconnected.connect(lambda s=sock: self._forget_socket(s))
            if sock.bytesAvailable() > 0:
                self._drain_socket(sock)

    def _forget_socket(self, sock) -> None:
        # A peer may close immediately after sending its final bytes.
        self._drain_socket(sock)
        self._activation_buffers.pop(sock, None)
        sock.deleteLater()

    def _drain_socket(self, sock) -> None:
        if sock not in self._activation_buffers:
            return  # This connection already delivered or rejected its frame.
        try:
            data = bytes(sock.read(len(_ACTIVATE_PAYLOAD) + 1))
        except RuntimeError:
            self._activation_buffers.pop(sock, None)
            return
        if not data:
            return
        frame = self._activation_buffers[sock] + data
        if not _ACTIVATE_PAYLOAD.startswith(frame):
            self._activation_buffers.pop(sock, None)
            sock.disconnectFromServer()
        elif frame == _ACTIVATE_PAYLOAD:
            self._activation_buffers.pop(sock, None)
            self.activation_requested.emit()
        else:
            self._activation_buffers[sock] = frame
