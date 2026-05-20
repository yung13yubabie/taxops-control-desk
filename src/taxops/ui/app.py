"""Application bootstrap.

Wires the path resolver, SQLite connection, migrations, service container,
and the PySide6 main window. Keep this thin — it should not contain UI
logic itself.
"""

from __future__ import annotations

import os
import sys

from ..core.paths import AppPaths, ensure_paths, resolve_paths
from ..db.connection import open_connection
from ..db.migrate import apply_migrations
from ..services.container import ServiceContainer, build_container

_WINDOWS_APP_ID = "TaxOps.ControlDesk.Desktop"


def _set_app_icon(app: object) -> None:
    """Set the QApplication window icon so the taskbar pin shows the custom icon."""
    import pathlib

    from PySide6.QtGui import QIcon

    if getattr(sys, "frozen", False):
        # PyInstaller one-dir: exe lives in dist/TaxOpsControlDesk/
        icon_path = pathlib.Path(sys.executable).parent / "assets" / "app_icon.ico"
    else:
        icon_path = pathlib.Path(__file__).parent.parent.parent.parent / "assets" / "app_icon.ico"
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
    apply_migrations(conn)
    return build_container(paths, conn)


def run() -> int:
    """Entry point used by ``python -m taxops``."""
    _set_windows_app_user_model_id()
    container = bootstrap()
    try:
        # Local import so the test/CI process can import bootstrap without
        # requiring Qt to be importable.
        from PySide6.QtWidgets import QApplication

        from .main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        _set_app_icon(app)
        from .style import apply as apply_style
        apply_style(app)
        window = MainWindow(container)
        window.show()
        return int(app.exec())
    finally:
        container.close()
