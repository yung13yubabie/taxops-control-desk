"""控制台 dock — 9 個即時統計，資料來自 SQLite。

Slice 23 / v0.15.0 redesign: the page is no longer one of the sidebar
QStackedWidget pages. ``MainWindow`` hosts it inside a ``QDockWidget`` on
the right side; the user can drag the dock to any window edge, float it
out, or close it. The 8 large cards from Slice 14 collapse into compact
``title: count →`` rows so the dock keeps a narrow footprint.

Backend data (DashboardService / DashboardRepository) is unchanged —
this file only restyles the presentation.
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

from ...services.container import ServiceContainer
from ..action_registry import (
    PAGE_CLIENTS,
    PAGE_ENGAGEMENTS,
    PAGE_TASKS,
    FilterKey,
)
from ..style import toolbar_icon

_log = logging.getLogger(__name__)

# (field_name, display_title, target_page_id, nav_btn_label, filter_key)
_CARD_DEFS: tuple[tuple[str, str, str, str, str], ...] = (
    ("tasks_due_today", "我的今日待辦", PAGE_TASKS, "前往待辦事項", FilterKey.DUE_TODAY),
    ("tasks_overdue", "我的逾期待辦", PAGE_TASKS, "前往待辦事項", FilterKey.OVERDUE),
    ("waiting_client", "等客戶回覆", PAGE_ENGAGEMENTS, "前往案件管理", ""),
    ("missing_item_requests", "缺件案件", PAGE_ENGAGEMENTS, "前往案件管理", ""),
    ("upcoming_engagements", "即將申報案件（7天內）", PAGE_ENGAGEMENTS, "前往案件管理", FilterKey.UPCOMING),
    ("overdue_engagements", "逾期繳款風險", PAGE_ENGAGEMENTS, "前往案件管理", FilterKey.OVERDUE),
    ("lease_expiring_soon", "租約即將到期（30天內）", PAGE_CLIENTS, "前往客戶清單", FilterKey.LEASE_EXPIRING),
)


class _DashboardRow(QFrame):
    """One compact row: ``title  …  count  →`` button.

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

        self._count_lbl = QLabel("—")
        self._count_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._count_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._count_lbl.setMinimumWidth(36)
        self._count_lbl.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #2563EB;"
        )
        layout.addWidget(self._count_lbl)

        self._nav_btn = QPushButton("→")
        self._nav_btn.setToolTip(nav_label)
        self._nav_btn.setFixedSize(28, 24)
        layout.addWidget(self._nav_btn)

    def set_count(self, n: int) -> None:
        self._count_lbl.setText(str(n))

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
        for field, title_text, target_page, nav_label, fkey in _CARD_DEFS:
            row = _DashboardRow(title_text, nav_label)
            row.connect_nav(
                lambda _checked=False, p=target_page, f=fkey: self.navigate_to_page.emit(p, f)
            )
            self._cards[field] = row
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

        self._cards["tasks_due_today"].set_count(counts.tasks_due_today)
        self._cards["tasks_overdue"].set_count(counts.tasks_overdue)
        self._cards["waiting_client"].set_count(counts.waiting_client)
        self._cards["missing_item_requests"].set_count(counts.missing_item_requests)
        self._cards["upcoming_engagements"].set_count(counts.upcoming_engagements)
        self._cards["overdue_engagements"].set_count(counts.overdue_engagements)
        self._cards["lease_expiring_soon"].set_count(counts.lease_expiring_soon)
        self._status_lbl.setText("")
