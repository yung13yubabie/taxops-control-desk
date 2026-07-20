"""Read-only navigation skeleton for the annual workbench."""

from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ...i18n import DISABLED_TOOLTIP, NAV_LABELS
from ...services.container import ServiceContainer
from ..widgets.empty_state import EmptyState


class AnnualWorkbenchPage(QWidget):
    """Safe Task 1 surface while annual data views are not connected yet."""

    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._filter_key = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        self.title_label = QLabel(NAV_LABELS["annual_workbench"])
        self.title_label.setObjectName("PageTitle")
        outer.addWidget(self.title_label)

        self._filter_notice = QLabel()
        self._filter_notice.setObjectName("AnnualFilterNotice")
        self._filter_notice.setWordWrap(True)
        self._filter_notice.setStyleSheet("color: #64748B; font-size: 14px;")
        outer.addWidget(self._filter_notice)

        self._empty_state = EmptyState(
            "年度工作資料尚未顯示",
            detail=(
                "年度總覽服務仍在建置中；目前僅提供安全的導覽入口，"
                "不會顯示推測資料。"
            ),
            action_text="年度工作項目尚未開放",
        )
        self.future_action_button = cast(
            QPushButton, self._empty_state.action_button
        )
        self.future_action_button.setEnabled(False)
        self.future_action_button.setToolTip(DISABLED_TOOLTIP)
        outer.addWidget(self._empty_state, stretch=1)

        self._apply_filter_state()

    def refresh_context(self) -> None:
        """Refresh the visible Task 1 state without inventing annual data."""
        self._apply_filter_state()

    def clear_filter(self) -> None:
        self._filter_key = ""
        self._apply_filter_state()

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key.strip()
        self._apply_filter_state()

    def _apply_filter_state(self) -> None:
        has_filter = bool(self._filter_key)
        self._filter_notice.setText(
            "已套用導覽篩選；年度資料檢視功能尚未開放。"
            if has_filter
            else ""
        )
        self._filter_notice.setVisible(has_filter)
