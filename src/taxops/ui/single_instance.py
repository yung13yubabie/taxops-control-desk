"""Single-instance guard using QLocalServer/QLocalSocket.

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

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 500
_READ_TIMEOUT_MS = 500
_WRITE_TIMEOUT_MS = 500
_ACTIVATE_PAYLOAD = b"activate\n"


class SingleInstanceGuard(QObject):
    """Detects an existing instance via a named QLocalServer."""

    activation_requested = Signal()

    def __init__(self, server_name: str) -> None:
        super().__init__()
        self._server_name = server_name
        self._server: QLocalServer | None = None

    @property
    def server_name(self) -> str:
        return self._server_name

    def acquire(self) -> bool:
        """Return True when this process becomes the lock holder.

        Returns False when another process already holds the lock; the caller
        should then call :meth:`notify_existing` and exit cleanly.
        """
        probe = QLocalSocket()
        probe.connectToServer(self._server_name)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._server_name)
        server = QLocalServer()
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
            return True
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
        if self._server is None:
            return
        self._server.close()
        QLocalServer.removeServer(self._server_name)
        self._server = None

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
