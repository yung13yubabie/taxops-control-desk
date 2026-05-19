"""控制台頁 — 顯示 8 張即時統計卡片，資料來自 SQLite 真實查詢。

所有卡片數字均不可 hardcode：空資料庫下所有數字應為 0。
卡片按鈕導向對應頁面並套用篩選；filter_key="" 表示不套用篩選。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...services.container import ServiceContainer
from ..action_registry import (
    PAGE_ENGAGEMENTS,
    PAGE_REVIEW_NOTES,
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
    ("open_review_notes", "未關閉覆核意見", PAGE_REVIEW_NOTES, "前往覆核意見", FilterKey.OPEN),
    ("missing_item_requests", "缺件案件", PAGE_ENGAGEMENTS, "前往案件管理", ""),
    ("upcoming_engagements", "即將申報案件（7天內）", PAGE_ENGAGEMENTS, "前往案件管理", FilterKey.UPCOMING),
    ("overdue_engagements", "逾期繳款風險", PAGE_ENGAGEMENTS, "前往案件管理", FilterKey.OVERDUE),
    ("high_risk_engagements", "高風險案件", PAGE_REVIEW_NOTES, "前往覆核意見", FilterKey.HIGH_RISK),
)


class _DashboardCard(QFrame):
    def __init__(self, title: str, nav_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("DashboardCard")
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(16, 14, 16, 14)

        title_lbl = QLabel(title)
        title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        title_lbl.setStyleSheet("font-size: 13px; color: #64748B;")
        layout.addWidget(title_lbl)

        self._count_lbl = QLabel("—")
        self._count_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._count_lbl.setStyleSheet("font-size: 32px; font-weight: 700; color: #1E293B;")
        layout.addWidget(self._count_lbl)

        layout.addStretch()

        self._nav_btn = QPushButton(nav_label)
        layout.addWidget(self._nav_btn)

    def set_count(self, n: int) -> None:
        self._count_lbl.setText(str(n))

    def connect_nav(self, callback: object) -> None:
        self._nav_btn.clicked.connect(callback)

    @property
    def nav_btn(self) -> QPushButton:
        return self._nav_btn


class DashboardPage(QWidget):
    """Controls desk dashboard showing live counts across all modules."""

    navigate_to_page = Signal(str, str)  # (page_id, filter_key)

    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container

        outer = QVBoxLayout(self)
        outer.setSpacing(16)
        outer.setContentsMargins(24, 24, 24, 24)

        header = QHBoxLayout()
        title = QLabel("控制台")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        self._refresh_btn = QPushButton("重新整理")
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        header.addWidget(self._refresh_btn)
        outer.addLayout(header)

        self._status_lbl = QLabel("")
        self._status_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._status_lbl.setStyleSheet("color: #64748B; font-size: 13px;")
        outer.addWidget(self._status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        grid_widget = QWidget()
        self._grid = QGridLayout(grid_widget)
        self._grid.setSpacing(12)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(grid_widget)
        outer.addWidget(scroll, stretch=1)

        self._cards: dict[str, _DashboardCard] = {}
        for i, (field, title_text, target_page, nav_label, fkey) in enumerate(_CARD_DEFS):
            card = _DashboardCard(title_text, nav_label)
            card.connect_nav(
                lambda _checked=False, p=target_page, f=fkey: self.navigate_to_page.emit(p, f)
            )
            self._cards[field] = card
            row, col = divmod(i, 2)
            self._grid.addWidget(card, row, col)

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
        self._cards["open_review_notes"].set_count(counts.open_review_notes)
        self._cards["missing_item_requests"].set_count(counts.missing_item_requests)
        self._cards["upcoming_engagements"].set_count(counts.upcoming_engagements)
        self._cards["overdue_engagements"].set_count(counts.overdue_engagements)
        self._cards["high_risk_engagements"].set_count(counts.high_risk_engagements)
        self._status_lbl.setText("")
