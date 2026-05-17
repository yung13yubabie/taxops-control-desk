"""Main application window: left navigation + stacked content."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    PAGE_DOC_REQUESTS,
    PAGE_ENGAGEMENTS,
    PAGE_LATE_FEE,
    PAGE_REGISTRY,
    PAGE_REVIEW_NOTES,
    PAGE_SETTINGS,
    PAGE_TASKS,
    PAGE_TEMPLATES,
)
from .pages.attachments_page import AttachmentsPage
from .pages.clients_page import ClientsPage
from .pages.dashboard_page import DashboardPage
from .pages.document_requests_page import DocumentRequestsPage
from .pages.engagements_page import EngagementsPage
from .pages.late_fee_page import LateFeePage
from .pages.placeholder_page import PlaceholderPage
from .pages.review_notes_page import ReviewNotesPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
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

        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setObjectName("SidebarToggle")
        self._collapse_btn.setFixedHeight(28)
        self._collapse_btn.setToolTip("收合側邊欄")
        sidebar_layout.addWidget(self._collapse_btn)

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

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
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
            if page_id == PAGE_DASHBOARD:
                dash_page = DashboardPage(self._container)
                dash_page.navigate_to_page.connect(self.navigate_to)
                page: QWidget = dash_page
            elif page_id == PAGE_CLIENTS:
                page = ClientsPage(self._container)
            elif page_id == PAGE_ENGAGEMENTS:
                eng_page = EngagementsPage(self._container)
                eng_page.open_doc_requests.connect(self._on_open_doc_requests)
                self._eng_page = eng_page
                page = eng_page
            elif page_id == PAGE_DOC_REQUESTS:
                doc_page = DocumentRequestsPage(self._container)
                doc_page.back_to_engagements.connect(
                    lambda: self.navigate_to(PAGE_ENGAGEMENTS)
                )
                self._doc_page = doc_page
                page = doc_page
            elif page_id == PAGE_TASKS:
                page = TasksPage(self._container)
            elif page_id == PAGE_TEMPLATES:
                page = TemplatesPage(self._container)
            elif page_id == PAGE_LATE_FEE:
                page = LateFeePage(self._container)
            elif page_id == PAGE_REVIEW_NOTES:
                page = ReviewNotesPage(self._container)
            elif page_id == PAGE_ATTACHMENTS:
                page = AttachmentsPage(self._container)
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
            self._stack.setCurrentIndex(idx)
            nav_idx = NAV_ORDER.index(page_id) if page_id in NAV_ORDER else -1
            if nav_idx >= 0:
                self._nav.setCurrentRow(nav_idx)
            if filter_key:
                page = self._stack.widget(idx)
                if hasattr(page, "set_filter"):
                    page.set_filter(filter_key)

    def _on_open_doc_requests(self, engagement_id: int) -> None:
        self._doc_page.load_engagement(engagement_id)
        self.navigate_to(PAGE_DOC_REQUESTS)

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
