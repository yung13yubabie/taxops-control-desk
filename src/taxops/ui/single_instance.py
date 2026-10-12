"""Atomic per-user instance lock, with a local socket only for activation.

Pattern:
    guard = SingleInstanceGuard("TaxOpsControlDesk.SingleInstance")
    if not guard.acquire():
        guard.notify_existing()
        return 0
    guard.activation_requested.connect(window_activator)

The guard owns a ``QLocalServer`` on first instance; subsequent processes
connect to the named pipe, send an ``activate`` message, and exit.  The
first instance receives the message via ``activation_requested`` and the
caller is expected to raise its main window.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ..core.paths import resolve_paths

_log = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 500
_READ_TIMEOUT_MS = 500
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
        directory = lock_directory if lock_directory is not None else resolve_paths().data_root / ".instance-locks"
        self._lock_path = directory.absolute() / (hashlib.sha256(server_name.encode("utf-8")).hexdigest() + ".lock")
        self._file_lock: QLockFile | None = None

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
        """Send the activate payload to the running instance."""
        sock = QLocalSocket()
        sock.connectToServer(self._server_name)
        if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        sock.write(_ACTIVATE_PAYLOAD)
        sock.flush()
        sock.waitForBytesWritten(_WRITE_TIMEOUT_MS)
        sock.disconnectFromServer()
        return True

    def release(self) -> None:
        server = self._server
        self._server = None
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
            if sock.bytesAvailable() > 0:
                self._drain_socket(sock)
            else:
                sock.readyRead.connect(lambda s=sock: self._drain_socket(s))
            sock.disconnected.connect(sock.deleteLater)

    def _drain_socket(self, sock) -> None:
        try:
            data = bytes(sock.readAll())
        except RuntimeError:
            return
        if not data:
            return
        # readyRead can fire multiple times if the client sends in chunks; the
        # activate payload is small (~10B) so the first fire usually carries
        # everything, but disconnect the slot after we have read it once to
        # avoid emitting activation_requested twice for the same socket.
        try:
            sock.readyRead.disconnect()
        except (RuntimeError, TypeError):
            pass
        if _ACTIVATE_PAYLOAD.strip() in data:
            self.activation_requested.emit()
