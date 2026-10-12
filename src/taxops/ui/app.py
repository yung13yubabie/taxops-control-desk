"""Application bootstrap.

Wires the path resolver, SQLite connection, migrations, service container,
and the PySide6 main window. Keep this thin — it should not contain UI
logic itself.
"""

from __future__ import annotations

import os
import sys

from ..core.paths import AppPaths, ensure_paths, resolve_paths
from ..core.resources import asset_path
from ..db.connection import open_connection
from ..db.migrate import UnsupportedSchemaError, apply_migrations
from ..services.container import ServiceContainer, build_container

_WINDOWS_APP_ID = "TaxOps.ControlDesk.Desktop"


def _set_app_icon(app: object) -> None:
    """Set the QApplication window icon so the taskbar pin shows the custom icon."""
    from PySide6.QtGui import QIcon

    icon_path = asset_path("app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))  # type: ignore[attr-defined]


def _set_windows_app_user_model_id() -> None:
    """Keep the running app grouped with the packaged EXE/taskbar icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_ID)
    except Exception:
        # Icon grouping is cosmetic; startup must not fail if Windows rejects it.
        return


def bootstrap(paths: AppPaths | None = None) -> ServiceContainer:
    """Resolve paths, run migrations, and build the service container."""
    if paths is None:
        is_dev = os.environ.get("TAXOPS_DEV") == "1"
        paths = resolve_paths(is_dev=is_dev)
    ensure_paths(paths)
    conn = open_connection(paths.db_path)
    try:
        apply_migrations(conn)
        return build_container(paths, conn)
    except Exception:
        conn.close()
        raise


_SINGLE_INSTANCE_NAME = "TaxOpsControlDesk.SingleInstance"


def _activate_window(window) -> None:
    """Bring the existing main window to the foreground."""
    from PySide6.QtCore import Qt

    state = window.windowState() & ~Qt.WindowState.WindowMinimized
    window.setWindowState(state | Qt.WindowState.WindowActive)
    window.show()
    window.raise_()
    window.activateWindow()


def run() -> int:
    """Entry point used by ``python -m taxops``."""
    _set_windows_app_user_model_id()
    from PySide6.QtCore import QCoreApplication, Qt
    from ..i18n.qt import install_chinese
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    try:
        container = bootstrap()
    except UnsupportedSchemaError:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        install_chinese(app)
        _set_app_icon(app)
        QMessageBox.critical(None, "資料版本不相容", "這份資料由較新版本的程式建立，為保護資料已停止開啟。請改用最新版本；不要刪除或覆蓋原本資料。")
        return 1
    try:
        # Local import so the test/CI process can import bootstrap without
        # requiring Qt to be importable.
        from PySide6.QtWidgets import QApplication, QMessageBox

        from .main_window import MainWindow
        from .single_instance import SingleInstanceGuard

        app = QApplication.instance() or QApplication(sys.argv)
        install_chinese(app)
        _set_app_icon(app)
        from .style import apply as apply_style
        apply_style(app)

        guard = SingleInstanceGuard(_SINGLE_INSTANCE_NAME)
        if not guard.acquire():
            guard.notify_existing()
            QMessageBox.information(
                None,
                "TaxOps Control Desk",
                "TaxOps Control Desk 已在執行中，已將原視窗切回前景。",
            )
            return 0

        window = MainWindow(container)
        window.show()
        guard.activation_requested.connect(lambda w=window: _activate_window(w))
        try:
            return int(app.exec())
        finally:
            guard.release()
    finally:
        container.close()
