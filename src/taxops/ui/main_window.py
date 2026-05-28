"""Main application window: left navigation + stacked content."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import NAV_LABELS
from ..services.container import ServiceContainer
from .action_registry import (
    NAV_ORDER,
    PAGE_ATTACHMENTS,
    PAGE_CLIENTS,
    PAGE_DASHBOARD,
    PAGE_ENGAGEMENTS,
    PAGE_FOLDER_BOOKMARKS,
    PAGE_LATE_FEE,
    PAGE_RECURRING_BILLING,
    PAGE_REGISTRY,
    PAGE_SETTINGS,
    PAGE_TASKS,
    PAGE_TEMPLATES,
)
from .pages.attachments_page import AttachmentsPage
from .pages.clients_page import ClientsPage
from .pages.dashboard_page import DashboardPage
from .pages.engagements_page import EngagementsPage
from .pages.folder_bookmarks_page import FolderBookmarksPage
from .pages.late_fee_page import LateFeePage
from .pages.placeholder_page import PlaceholderPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
from .pages.recurring_billing_page import RecurringBillingPage
from .pages.registry_page import RegistryPage
from .pages.templates_page import TemplatesPage

_SIDEBAR_EXPANDED_MIN = 200
_SIDEBAR_EXPANDED_MAX = 240
_SIDEBAR_COLLAPSED_WIDTH = 32


class MainWindow(QMainWindow):
    def __init__(self, container: ServiceContainer) -> None:
        super().__init__()
        self._container = container
        self.setWindowTitle("TaxOps Control Desk")
        self.setMinimumSize(1280, 720)

        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar wrapper: toggle button on top, nav list below
        self._sidebar = QWidget()
        self._sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Sidebar header — collapse toggle + dashboard dock toggle.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(2)
        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setObjectName("SidebarToggle")
        self._collapse_btn.setFixedHeight(28)
        self._collapse_btn.setToolTip("收合側邊欄")
        header_row.addWidget(self._collapse_btn, stretch=1)
        self._dock_toggle_btn = QPushButton("📊")
        self._dock_toggle_btn.setObjectName("DashboardDockToggle")
        self._dock_toggle_btn.setFixedSize(28, 28)
        self._dock_toggle_btn.setToolTip("顯示／隱藏控制台浮動視窗")
        self._dock_toggle_btn.clicked.connect(self._toggle_dashboard_dock)
        header_row.addWidget(self._dock_toggle_btn)
        sidebar_layout.addLayout(header_row)

        self._nav = QListWidget()
        self._nav.setObjectName("MainNav")
        self._nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        sidebar_layout.addWidget(self._nav)

        self._sidebar.setMinimumWidth(_SIDEBAR_EXPANDED_MIN)
        self._sidebar.setMaximumWidth(_SIDEBAR_EXPANDED_MAX)
        layout.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._page_indices: dict[str, int] = {}
        self._build_pages()

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._nav.setCurrentRow(self._page_indices.get(PAGE_CLIENTS, 0))

        # Restore sidebar collapse state from persisted setting
        collapsed_val = container.settings.get("ui.sidebar_collapsed") or "0"
        if collapsed_val == "1":
            self._apply_collapsed(save=False)

        self._collapse_btn.clicked.connect(self._on_toggle_sidebar)

        self.setCentralWidget(central)

        # Slice 23 / v0.15.0 — Dashboard lives in a dockable side panel.
        self._build_dashboard_dock()

    def _build_pages(self) -> None:
        for page_id in NAV_ORDER:
            # Slice 23: PAGE_DASHBOARD is no longer in NAV_ORDER, but defensive
            # guard kept in case other branches keep it.
            if page_id == PAGE_DASHBOARD:
                continue
            label = NAV_LABELS.get(page_id, page_id)
            self._nav.addItem(QListWidgetItem(label))
            page: QWidget
            if page_id == PAGE_CLIENTS:
                page = ClientsPage(self._container)
            elif page_id == PAGE_ENGAGEMENTS:
                eng_page = EngagementsPage(self._container)
                self._eng_page = eng_page
                page = eng_page
            elif page_id == PAGE_TASKS:
                page = TasksPage(self._container)
            elif page_id == PAGE_TEMPLATES:
                page = TemplatesPage(self._container)
            elif page_id == PAGE_LATE_FEE:
                page = LateFeePage(self._container)
            elif page_id == PAGE_FOLDER_BOOKMARKS:
                page = FolderBookmarksPage(self._container)
            elif page_id == PAGE_ATTACHMENTS:
                page = AttachmentsPage(self._container)
            elif page_id == PAGE_RECURRING_BILLING:
                page = RecurringBillingPage(self._container)
            elif page_id == PAGE_REGISTRY:
                page = RegistryPage(self._container)
            elif page_id == PAGE_SETTINGS:
                page = SettingsPage(self._container)
            else:
                page = PlaceholderPage(page_id)
            index = self._stack.addWidget(page)
            self._page_indices[page_id] = index

    def navigate_to(self, page_id: str, filter_key: str = "") -> None:
        idx = self._page_indices.get(page_id)
        if idx is not None:
            nav_idx = NAV_ORDER.index(page_id) if page_id in NAV_ORDER else -1
            if nav_idx >= 0 and self._nav.currentRow() != nav_idx:
                self._nav.setCurrentRow(nav_idx)
            else:
                self._activate_page(idx)
            if filter_key:
                page = self._stack.widget(idx)
                if hasattr(page, "set_filter"):
                    page.set_filter(filter_key)

    def _on_nav_changed(self, idx: int) -> None:
        if idx >= 0:
            page = self._stack.widget(idx)
            if hasattr(page, "clear_filter"):
                page.clear_filter()
            self._activate_page(idx)

    def _activate_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        page = self._stack.widget(idx)
        refresh = getattr(page, "refresh_context", None)
        if refresh is None:
            return
        try:
            refresh()
        except Exception as err:
            self._container.system_log.warn(
                "page activation refresh failed",
                detail={
                    "page": type(page).__name__,
                    "exc": type(err).__name__,
                    "msg": str(err),
                },
            )

    def _on_toggle_sidebar(self) -> None:
        if self._nav.isVisible():
            self._apply_collapsed(save=True)
        else:
            self._apply_expanded(save=True)

    def _apply_collapsed(self, *, save: bool) -> None:
        self._nav.setVisible(False)
        self._collapse_btn.setText("▶")
        self._collapse_btn.setToolTip("展開側邊欄")
        self._sidebar.setMinimumWidth(_SIDEBAR_COLLAPSED_WIDTH)
        self._sidebar.setMaximumWidth(_SIDEBAR_COLLAPSED_WIDTH)
        if save:
            try:
                self._container.settings.set_setting("ui.sidebar_collapsed", "1")
            except Exception as err:
                self._container.system_log.warn(
                    "sidebar collapse setting save failed",
                    detail={"exc": type(err).__name__, "msg": str(err)},
                )

    def _apply_expanded(self, *, save: bool) -> None:
        self._nav.setVisible(True)
        self._collapse_btn.setText("◀")
        self._collapse_btn.setToolTip("收合側邊欄")
        self._sidebar.setMinimumWidth(_SIDEBAR_EXPANDED_MIN)
        self._sidebar.setMaximumWidth(_SIDEBAR_EXPANDED_MAX)
        if save:
            try:
                self._container.settings.set_setting("ui.sidebar_collapsed", "0")
            except Exception as err:
                self._container.system_log.warn(
                    "sidebar expand setting save failed",
                    detail={"exc": type(err).__name__, "msg": str(err)},
                )

    # ------------------------------------------------------------------
    # Dashboard dock (Slice 23 / v0.15.0)
    # ------------------------------------------------------------------

    def _build_dashboard_dock(self) -> None:
        """Mount DashboardPage inside a dockable side panel.

        Default location: right edge. The user can drag it to any edge,
        float it out, or close it via the QDockWidget title bar; visibility
        persists via ``ui.dashboard_dock_visible``.
        """
        self._dashboard_page = DashboardPage(self._container)
        self._dashboard_page.navigate_to_page.connect(self.navigate_to)
        self._dashboard_dock = QDockWidget("控制台", self)
        self._dashboard_dock.setObjectName("DashboardDock")
        self._dashboard_dock.setWidget(self._dashboard_page)
        self._dashboard_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._dashboard_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._dashboard_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dashboard_dock)

        visible = self._container.settings.get("ui.dashboard_dock_visible")
        if visible == "0":
            self._dashboard_dock.hide()

        self._dashboard_dock.visibilityChanged.connect(self._on_dashboard_visibility_changed)

    def _toggle_dashboard_dock(self) -> None:
        if self._dashboard_dock is None:
            return
        new_visible = not self._dashboard_dock.isVisible()
        self._dashboard_dock.setVisible(new_visible)

    def _on_dashboard_visibility_changed(self, visible: bool) -> None:
        try:
            self._container.settings.set_setting(
                "ui.dashboard_dock_visible", "1" if visible else "0"
            )
        except Exception as err:
            self._container.system_log.warn(
                "dashboard dock visibility save failed",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
        if visible:
            try:
                self._dashboard_page.refresh_context()
            except Exception:
                pass
