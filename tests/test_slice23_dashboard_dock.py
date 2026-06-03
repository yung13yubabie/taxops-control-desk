"""v0.21.0: dashboard dock is removed from the main window."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDockWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_has_no_dashboard_dock(container):
    from taxops.ui.main_window import MainWindow

    _app()
    win = MainWindow(container)

    assert not hasattr(win, "_dashboard_dock")
    assert win.findChildren(QDockWidget) == []
    assert not hasattr(win, "_dock_toggle_btn")


def test_nav_order_has_no_dashboard():
    from taxops.ui.action_registry import NAV_ORDER

    assert "dashboard" not in NAV_ORDER


def test_dashboard_dock_setting_default_is_removed():
    from taxops.repositories.app_settings import DEFAULT_SETTINGS

    defaults = dict(DEFAULT_SETTINGS)
    assert "ui.dashboard_dock_visible" not in defaults
