"""Slice 23 / v0.15.0: Dashboard as a floating QDockWidget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDockWidget


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.usefixtures("qapp")
def test_main_window_creates_dashboard_dock(container):
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    assert isinstance(win._dashboard_dock, QDockWidget)
    assert win._dashboard_dock.windowTitle() == "控制台"


@pytest.mark.usefixtures("qapp")
def test_dashboard_dock_hosts_dashboard_page(container):
    from taxops.ui.main_window import MainWindow
    from taxops.ui.pages.dashboard_page import DashboardPage
    win = MainWindow(container)
    inner = win._dashboard_dock.widget()
    assert isinstance(inner, DashboardPage)


@pytest.mark.usefixtures("qapp")
def test_dashboard_dock_is_floatable_movable_closable(container):
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    features = win._dashboard_dock.features()
    assert features & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable


def test_dashboard_removed_from_nav_order():
    from taxops.ui.action_registry import NAV_ORDER, PAGE_DASHBOARD
    assert PAGE_DASHBOARD not in NAV_ORDER


@pytest.mark.usefixtures("qapp")
def test_main_window_page_indices_skip_dashboard(container):
    from taxops.ui.action_registry import PAGE_DASHBOARD
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    assert PAGE_DASHBOARD not in win._page_indices


@pytest.mark.usefixtures("qapp")
def test_dock_visibility_persists_via_settings(container):
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    win._on_dashboard_visibility_changed(False)
    assert container.settings.get("ui.dashboard_dock_visible") == "0"
    win._on_dashboard_visibility_changed(True)
    assert container.settings.get("ui.dashboard_dock_visible") == "1"


@pytest.mark.usefixtures("qapp")
def test_dashboard_page_uses_compact_rows(container):
    from taxops.ui.pages.dashboard_page import DashboardPage, _DashboardRow
    page = DashboardPage(container)
    assert len(page._cards) == 9
    for card in page._cards.values():
        assert isinstance(card, _DashboardRow)


@pytest.mark.usefixtures("qapp")
def test_dashboard_page_navigate_to_page_signal_still_emits(container):
    from taxops.ui.pages.dashboard_page import DashboardPage
    page = DashboardPage(container)
    emitted: list[tuple[str, str]] = []
    page.navigate_to_page.connect(lambda p, f: emitted.append((p, f)))
    page._cards["tasks_due_today"].nav_btn.click()
    assert len(emitted) == 1
    assert emitted[0][0] == "tasks"


@pytest.mark.usefixtures("qapp")
def test_dock_toggle_button_exists_in_sidebar(container):
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    assert win._dock_toggle_btn is not None
    assert win._dock_toggle_btn.toolTip().startswith("顯示")


def test_dashboard_dock_visible_setting_default_is_shown():
    from taxops.repositories.app_settings import DEFAULT_SETTINGS
    defaults = dict(DEFAULT_SETTINGS)
    assert defaults["ui.dashboard_dock_visible"] == "1"
