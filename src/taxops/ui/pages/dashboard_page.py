"""控制台 dock — sidebar modules as a compact live summary.

Slice 25 / v0.16.0: the dashboard is no longer a separate workflow with
its own hidden routing rules. It mirrors ``NAV_ORDER`` as a compact module
summary. Clicking a row emits the same page id as the sidebar and no
implicit filter, so dashboard navigation and sidebar navigation land in
the same place.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n import NAV_LABELS
from ...services.container import ServiceContainer
from ...services.dashboard import DashboardCounts
from ..action_registry import (
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
from ..style import toolbar_icon

_log = logging.getLogger(__name__)

_MODULE_ORDER: tuple[str, ...] = NAV_ORDER


def _summary_for(page_id: str, counts: DashboardCounts) -> str:
    if page_id == PAGE_CLIENTS:
        return f"租約到期 {counts.lease_expiring_soon}"
    if page_id == PAGE_ENGAGEMENTS:
        return f"即將 {counts.upcoming_engagements} / 逾期 {counts.overdue_engagements}"
    if page_id == PAGE_TASKS:
        return f"今日 {counts.tasks_due_today} / 逾期 {counts.tasks_overdue}"
    if page_id == PAGE_WORK_RECORDS:
        return "流程 / 筆記 / 錯誤回顧"
    if page_id == PAGE_TEMPLATES:
        return "模板"
    if page_id == PAGE_REGISTRY:
        return "本地查詢"
    if page_id == PAGE_LATE_FEE:
        return "試算"
    if page_id == PAGE_ATTACHMENTS:
        return "附件"
    if page_id == PAGE_FOLDER_BOOKMARKS:
        return "資料夾"
    if page_id == PAGE_RECURRING_BILLING:
        return "固定開立"
    if page_id == PAGE_SETTINGS:
        return "設定"
    return "開啟"


# Backward-compatible exported name for existing tests. Entries are page ids,
# exactly matching the sidebar order.
_CARD_DEFS: tuple[str, ...] = _MODULE_ORDER


_MODULE_TOOLTIPS: dict[str, str] = {
    page_id: f"開啟{NAV_LABELS.get(page_id, page_id)}" for page_id in _MODULE_ORDER
}


class _DashboardRow(QFrame):
    """One compact module row: ``module  …  summary  →`` button.

    Renders inside the dashboard dock list. Clicking ``nav_btn`` emits the
    parent ``navigate_to_page`` signal.
    """

    def __init__(self, title: str, nav_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardRow")
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        title_lbl.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(title_lbl, stretch=1)

        self._summary_lbl = QLabel("—")
        self._summary_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._summary_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._summary_lbl.setMinimumWidth(82)
        self._summary_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #2563EB;"
        )
        layout.addWidget(self._summary_lbl)

        self._nav_btn = QPushButton("→")
        self._nav_btn.setToolTip(nav_label)
        self._nav_btn.setFixedSize(28, 24)
        layout.addWidget(self._nav_btn)

    def set_summary(self, text: str) -> None:
        self._summary_lbl.setText(text)
        self._summary_lbl.setToolTip(text)

    def set_count(self, n: int) -> None:
        self.set_summary(str(n))

    def connect_nav(self, callback: object) -> None:
        self._nav_btn.clicked.connect(callback)

    @property
    def nav_btn(self) -> QPushButton:
        return self._nav_btn


# Backward-compat alias for code/tests that still reference _DashboardCard.
_DashboardCard = _DashboardRow


class DashboardPage(QWidget):
    """Compact dashboard widget intended to live inside a QDockWidget.

    Backward-compat: keeps the ``navigate_to_page(page_id, filter_key)``
    Signal so existing wiring in ``MainWindow.navigate_to`` and Slice 14 UI
    tests keep working.
    """

    navigate_to_page = Signal(str, str)  # (page_id, filter_key)

    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container

        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("控制台")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #1E293B;")
        header.addWidget(title)
        header.addStretch()
        self._refresh_btn = QPushButton("⟳")
        self._refresh_btn.setToolTip("重新整理")
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        self._refresh_btn.setFixedSize(28, 24)
        self._refresh_btn.clicked.connect(self._on_refresh)
        header.addWidget(self._refresh_btn)
        outer.addLayout(header)

        self._status_lbl = QLabel("")
        self._status_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._status_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        outer.addWidget(self._status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        rows_widget = QWidget()
        rows_layout = QVBoxLayout(rows_widget)
        rows_layout.setSpacing(2)
        rows_layout.setContentsMargins(0, 0, 0, 0)

        self._cards: dict[str, _DashboardRow] = {}
        for page_id in _MODULE_ORDER:
            title_text = NAV_LABELS.get(page_id, page_id)
            nav_label = _MODULE_TOOLTIPS[page_id]
            row = _DashboardRow(title_text, nav_label)
            row.connect_nav(
                lambda _checked=False, p=page_id: self.navigate_to_page.emit(p, "")
            )
            self._cards[page_id] = row
            rows_layout.addWidget(row)
        rows_layout.addStretch()

        scroll.setWidget(rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._on_refresh()

    def refresh_context(self) -> None:
        """Reload dashboard counts (called when dock becomes active)."""
        self._on_refresh()

    def _on_refresh(self) -> None:
        try:
            counts = self._container.dashboard.get_counts()
        except Exception:
            _log.error("dashboard refresh failed", exc_info=True)
            self._status_lbl.setText("載入失敗，請稍後再試。")
            return

        for page_id, row in self._cards.items():
            row.set_summary(_summary_for(page_id, counts))
        self._status_lbl.setText("")
