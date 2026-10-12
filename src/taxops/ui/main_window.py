"""Document-first shell with grouped navigation and stable deep links."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.container import ServiceContainer
from .navigation import NAV_ICON_ROLES, NavigationTarget
from .widgets.workspace_navigation import WorkspaceNavigation
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

# Compatibility for the established per-page glyph contract.
_NAV_ICON_ROLES = NAV_ICON_ROLES

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
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._nav = WorkspaceNavigation()
        layout.addWidget(self._nav)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)
        self._page_indices: dict[str, int] = {}
        self._build_pages()
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._nav.setCurrentRow(NAV_ORDER.index(PAGE_ATTACHMENTS))
        self.statusBar().showMessage("本機資料 · 核心工作可離線使用")
        self._nav_shortcut = QShortcut(QKeySequence("F6"), self)
        self._nav_shortcut.activated.connect(self._focus_navigation)
        self.setCentralWidget(central)

    def _build_pages(self) -> None:
        for page_id in NAV_ORDER:
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

            signal = getattr(page, "navigate_requested", None)
            if signal is not None:
                signal.connect(self.open_target)

    def navigate_to(self, page_id: str, filter_key: str = "") -> None:
        if not self._can_navigate():
            return
        idx = self._page_indices.get(page_id)
        if idx is not None:
            nav_idx = NAV_ORDER.index(page_id) if page_id in NAV_ORDER else -1
            if nav_idx >= 0 and self._nav.currentRow() != nav_idx:
                self._nav.setCurrentRow(nav_idx)
            else:
                if not filter_key and page_id != PAGE_ATTACHMENTS:
                    page = self._stack.widget(idx)
                    if hasattr(page, "clear_filter"):
                        page.clear_filter()
                self._activate_page(idx)
            if filter_key:
                page = self._stack.widget(idx)
                if hasattr(page, "set_filter"):
                    page.set_filter(filter_key)

    def _on_nav_changed(self, idx: int) -> None:
        if idx < 0:
            return
        if not self._can_navigate():
            self._nav.blockSignals(True)
            self._nav.setCurrentRow(self._stack.currentIndex())
            self._nav.blockSignals(False)
            return
        page = self._stack.widget(idx)
        # Global destinations deliberately reset their list filters. The receipt
        # workbench retains its queue/search/selection when returning from a case.
        if NAV_ORDER[idx] != PAGE_ATTACHMENTS:
            if hasattr(page, "clear_filter"):
                page.clear_filter()
        self._activate_page(idx)

    def _can_navigate(self) -> bool:
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self:
            self.statusBar().showMessage("請先完成或取消目前的對話框，再切換工作。")
            return False
        page = self._stack.currentWidget()
        can_leave = getattr(page, "can_leave_page", None)
        return bool(can_leave()) if can_leave is not None else True

    def _focus_navigation(self) -> None:
        if self._can_navigate():
            self._nav.focus_current()

    def open_target(self, target: NavigationTarget) -> bool:
        """Resolve exact IDs before replacing a visible page or editor context."""
        if not isinstance(target, NavigationTarget) or not self._can_navigate():
            return False
        if target.page_id not in self._page_indices:
            return False
        try:
            ids = (target.engagement_id, target.request_id,
                   target.task_id, target.attachment_id)
            if any(value is not None and (type(value) is not int or value <= 0)
                   for value in ids):
                raise ValueError("工作連結無效，請重新選取。")
            if target.task_id is not None:
                if target.page_id != PAGE_TASKS:
                    raise ValueError("待辦連結的目的地不正確。")
                task = self._container.tasks.get_task(target.task_id)
                if task is None or (
                    target.engagement_id is not None
                    and task.engagement_id != target.engagement_id
                ):
                    raise ValueError("待辦已刪除、所屬資料已停用，或案件範圍已變更。")
            if target.engagement_id is not None:
                if target.page_id not in {PAGE_ENGAGEMENTS, PAGE_TASKS, PAGE_ATTACHMENTS}:
                    raise ValueError("案件連結的目的地不正確。")
                if self._container.engagements.get_engagement(target.engagement_id) is None:
                    raise ValueError("案件已刪除或所屬客戶已停用。")
            if target.request_id is not None:
                request = self._container.doc_requests.get_request(target.request_id)
                if (target.page_id != PAGE_ENGAGEMENTS or request is None
                        or request.engagement_id != target.engagement_id):
                    raise ValueError("索件批次已刪除或不屬於這個案件。")
            if target.attachment_id is not None:
                attachment = self._container.attachments.get(target.attachment_id)
                if (target.page_id != PAGE_ATTACHMENTS or attachment is None
                        or attachment.status == "archived"
                        or target.engagement_id is None
                        or attachment.engagement_id != target.engagement_id):
                    raise ValueError("附件已封存、所屬資料已停用，或不屬於這個案件。")
            page = self._stack.widget(self._page_indices[target.page_id])
            opened = None
            if target.page_id == PAGE_ENGAGEMENTS and target.engagement_id is not None:
                opened = page.open_context(target.engagement_id, target.request_id)
            elif target.page_id == PAGE_TASKS and target.task_id is not None:
                opened = page.open_task(target.task_id)
            elif target.page_id == PAGE_ATTACHMENTS and target.engagement_id is not None:
                opened = page.open_context(target.engagement_id, target.attachment_id)
            elif any(value is not None for value in ids):
                raise ValueError("工作連結缺少指定資料，請重新選取。")
            else:
                self.navigate_to(target.page_id)
                return self._stack.currentWidget() is page
            if opened is False:
                raise ValueError("讀取指定工作失敗，請重新整理後再試。")
            # open_context has already loaded and selected the exact target.
            # A generic activation refresh here would overwrite drill-down scope
            # from a hidden master-table selection or a bounded combo list.
            with QSignalBlocker(self._nav):
                self._nav.setCurrentRow(NAV_ORDER.index(target.page_id))
            self._stack.setCurrentWidget(page)
            self.statusBar().showMessage("已開啟指定工作。", 5000)
            return True
        except ValueError as exc:
            QMessageBox.warning(self, "無法開啟工作", str(exc))
        except Exception as exc:
            self._container.system_log.warn(
                "navigation target failed", detail={"exc": type(exc).__name__}
            )
            QMessageBox.warning(self, "無法開啟工作", "讀取工作資料失敗，請重新整理後再試。")
        return False

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
