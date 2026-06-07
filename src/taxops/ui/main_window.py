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

from ..i18n import NAV_LABELS
from ..services.container import ServiceContainer
from .action_registry import (
    NAV_ORDER,
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
from .pages.attachments_page import AttachmentsPage
from .pages.clients_page import ClientsPage
from .pages.engagements_page import EngagementsPage
from .pages.folder_bookmarks_page import FolderBookmarksPage
from .pages.late_fee_page import LateFeePage
from .pages.placeholder_page import PlaceholderPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
from .pages.work_records_page import WorkRecordsPage
from .pages.recurring_billing_page import RecurringBillingPage
from .pages.registry_page import RegistryPage
from .pages.templates_page import TemplatesPage

_SIDEBAR_EXPANDED_MIN = 200
_SIDEBAR_EXPANDED_MAX = 240
_SIDEBAR_COLLAPSED_WIDTH = 32
_WINDOW_MIN_SIZE = QSize(900, 540)
_WINDOW_MAX_INITIAL_SIZE = QSize(1280, 720)


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

        # Sidebar header: collapse toggle only.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(2)
        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setObjectName("SidebarToggle")
        self._collapse_btn.setFixedHeight(28)
        self._collapse_btn.setToolTip("收合側邊欄")
        header_row.addWidget(self._collapse_btn, stretch=1)
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

    def _build_pages(self) -> None:
        for page_id in NAV_ORDER:
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
                page = RegistryPage(self._container)
            elif page_id == PAGE_SETTINGS:
                settings_page = SettingsPage(self._container)
                self._settings_page = settings_page
                page = settings_page
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
        if self._nav.isVisible():
            self._apply_collapsed(save=True)
        else:
            self._apply_expanded(save=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        settings_page = getattr(self, "_settings_page", None)
        if settings_page is not None and settings_page.has_active_operation():
            QMessageBox.warning(
                self,
                "作業進行中",
                "資料匯入或下載仍在進行，完成後才能關閉應用程式。",
            )
            event.ignore()
            return
        super().closeEvent(event)

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
