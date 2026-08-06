"""Main application window: left navigation + stacked content."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons, tokens
from ..i18n import NAV_LABELS
from ..services.container import ServiceContainer
from .widgets.buttons import make_icon_button
from .action_registry import (
    NAV_ORDER,
    PAGE_ANNUAL_WORKBENCH,
    PAGE_ATTACHMENTS,
    PAGE_CLIENTS,
    PAGE_ENGAGEMENTS,
    PAGE_FOLDER_BOOKMARKS,
    PAGE_LATE_FEE,
    PAGE_RECURRING_BILLING,
    PAGE_REGISTRY,
    PAGE_SETTINGS,
    PAGE_TASKS,
    PAGE_TEMPLATES,
    PAGE_WORK_RECORDS,
)
from .pages.annual_workbench_page import AnnualWorkbenchPage
from .pages.attachments_page import AttachmentsPage
from .pages.clients_page import ClientsPage
from .pages.engagements_page import EngagementsPage
from .pages.folder_bookmarks_page import FolderBookmarksPage
from .pages.late_fee_page import LateFeePage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
from .pages.work_records_page import WorkRecordsPage
from .pages.recurring_billing_page import RecurringBillingPage
from .pages.registry_page import RegistryPage
from .pages.templates_page import TemplatesPage

_SIDEBAR_EXPANDED_MIN = tokens.SIDEBAR_EXPANDED_WIDTH
_SIDEBAR_EXPANDED_MAX = tokens.SIDEBAR_EXPANDED_MAX_WIDTH
# Wide enough for a centred icon plus its hit target. The former 32px left a bare
# strip that erased every module's identity once collapsed.
_SIDEBAR_COLLAPSED_WIDTH = tokens.SIDEBAR_COLLAPSED_WIDTH
_WINDOW_MIN_SIZE = QSize(900, 540)
_WINDOW_MAX_INITIAL_SIZE = QSize(1280, 720)

# One glyph per module, so a collapsed sidebar still says which page is which.
_NAV_ICON_ROLES: dict[str, str] = {
    PAGE_CLIENTS: "nav-clients",
    PAGE_ANNUAL_WORKBENCH: "nav-calendar",
    PAGE_ENGAGEMENTS: "nav-engagements",
    PAGE_TASKS: "nav-tasks",
    PAGE_WORK_RECORDS: "nav-work-records",
    PAGE_TEMPLATES: "nav-templates",
    PAGE_REGISTRY: "nav-registry",
    PAGE_LATE_FEE: "trial",
    PAGE_ATTACHMENTS: "nav-attachments",
    PAGE_FOLDER_BOOKMARKS: "nav-folders",
    PAGE_RECURRING_BILLING: "nav-billing",
    PAGE_SETTINGS: "nav-settings",
}


def _initial_window_size(available: QSize) -> QSize:
    width = min(_WINDOW_MAX_INITIAL_SIZE.width(), round(available.width() * 0.9))
    height = min(_WINDOW_MAX_INITIAL_SIZE.height(), round(available.height() * 0.9))
    width = min(available.width(), max(_WINDOW_MIN_SIZE.width(), width))
    height = min(available.height(), max(_WINDOW_MIN_SIZE.height(), height))
    return QSize(width, height)


def _minimum_window_size(available: QSize) -> QSize:
    return QSize(
        min(_WINDOW_MIN_SIZE.width(), available.width()),
        min(_WINDOW_MIN_SIZE.height(), available.height()),
    )


class MainWindow(QMainWindow):
    def __init__(self, container: ServiceContainer) -> None:
        super().__init__()
        self._container = container
        self.setWindowTitle("TaxOps Control Desk")
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry().size()
            self.setMinimumSize(_minimum_window_size(available))
            self.resize(_initial_window_size(available))
        else:
            self.setMinimumSize(_WINDOW_MIN_SIZE)

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

        # Sidebar header: a 32x32 quiet icon button, not a full-width blue bar.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(
            tokens.SPACING_SM, tokens.SPACING_SM, tokens.SPACING_SM, tokens.SPACING_XS
        )
        header_row.setSpacing(0)
        self._collapse_btn = make_icon_button(
            "chevron-left",
            tooltip="收合側邊欄",
            accessible_name="收合側邊欄",
            icon_color=tokens.SIDEBAR_TEXT,
        )
        self._collapse_btn.setObjectName("SidebarToggle")
        header_row.addStretch(1)
        header_row.addWidget(self._collapse_btn)
        sidebar_layout.addLayout(header_row)

        self._collapsed = False
        self._nav = QListWidget()
        self._nav.setObjectName("MainNav")
        self._nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._nav.setIconSize(QSize(tokens.ICON_SIZE_LG, tokens.ICON_SIZE_LG))
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

    def _build_pages(self) -> None:
        for page_id in NAV_ORDER:
            label = NAV_LABELS.get(page_id, page_id)
            item = QListWidgetItem(label)
            # KeyError here is intentional: a new page must declare its glyph rather
            # than fall back to a generic one.
            item.setIcon(icons.icon(_NAV_ICON_ROLES[page_id], tokens.SIDEBAR_TEXT))
            self._nav.addItem(item)
            page: QWidget
            if page_id == PAGE_CLIENTS:
                page = ClientsPage(self._container)
            elif page_id == PAGE_ANNUAL_WORKBENCH:
                page = AnnualWorkbenchPage(self._container)
            elif page_id == PAGE_ENGAGEMENTS:
                eng_page = EngagementsPage(self._container)
                self._eng_page = eng_page
                page = eng_page
            elif page_id == PAGE_TASKS:
                page = TasksPage(self._container)
            elif page_id == PAGE_WORK_RECORDS:
                page = WorkRecordsPage(self._container)
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
                registry_page = RegistryPage(self._container)
                self._registry_page = registry_page
                page = registry_page
            elif page_id == PAGE_SETTINGS:
                settings_page = SettingsPage(self._container)
                self._settings_page = settings_page
                page = settings_page
            else:
                raise RuntimeError(f"unmapped navigation page: {page_id}")
            index = self._stack.addWidget(page)
            self._page_indices[page_id] = index

    def navigate_to(self, page_id: str, filter_key: str = "") -> None:
        idx = self._page_indices.get(page_id)
        if idx is not None:
            nav_idx = NAV_ORDER.index(page_id) if page_id in NAV_ORDER else -1
            if nav_idx >= 0 and self._nav.currentRow() != nav_idx:
                self._nav.setCurrentRow(nav_idx)
            else:
                if not filter_key:
                    page = self._stack.widget(idx)
                    if hasattr(page, "clear_filter"):
                        page.clear_filter()
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
        if self._collapsed:
            self._apply_expanded(save=True)
        else:
            self._apply_collapsed(save=True)

    def _set_nav_collapsed(self, collapsed: bool) -> None:
        """Hide or restore navigation labels while keeping icons and tooltips.

        The list itself stays visible in both states. Hiding it — the previous
        behaviour — left a blank strip with no way to tell the modules apart.
        """
        for row, page_id in enumerate(NAV_ORDER):
            item = self._nav.item(row)
            if item is None:
                continue
            label = NAV_LABELS.get(page_id, page_id)
            item.setText("" if collapsed else label)
            item.setToolTip(label if collapsed else "")
        self._nav.setProperty("collapsed", "true" if collapsed else "false")
        style = self._nav.style()
        if style is not None:
            style.unpolish(self._nav)
            style.polish(self._nav)

    def closeEvent(self, event: QCloseEvent) -> None:
        settings_page = getattr(self, "_settings_page", None)
        registry_page = getattr(self, "_registry_page", None)
        operation_active = (
            settings_page is not None and settings_page.has_active_operation()
        ) or (
            registry_page is not None and registry_page.has_active_operation()
        )
        if operation_active:
            QMessageBox.warning(
                self,
                "作業進行中",
                "資料匯入或下載仍在進行，完成後才能關閉應用程式。",
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _apply_collapsed(self, *, save: bool) -> None:
        self._collapsed = True
        self._set_nav_collapsed(True)
        self._collapse_btn.setIcon(icons.icon("chevron-right", tokens.SIDEBAR_TEXT))
        self._collapse_btn.setToolTip("展開側邊欄")
        self._collapse_btn.setAccessibleName("展開側邊欄")
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
        self._collapsed = False
        self._set_nav_collapsed(False)
        self._collapse_btn.setIcon(icons.icon("chevron-left", tokens.SIDEBAR_TEXT))
        self._collapse_btn.setToolTip("收合側邊欄")
        self._collapse_btn.setAccessibleName("收合側邊欄")
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
