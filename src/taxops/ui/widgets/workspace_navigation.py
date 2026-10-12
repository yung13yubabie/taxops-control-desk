"""Five everyday destinations and a categorized native data/tools menu."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QWidget,
)

from ...i18n import NAV_LABELS
from .. import icons, tokens
from ..action_registry import (
    NAV_ORDER, PAGE_ANNUAL_WORKBENCH, PAGE_ATTACHMENTS, PAGE_TASKS,
    PAGE_ENGAGEMENTS, PAGE_RECURRING_BILLING, PAGE_CLIENTS, PAGE_WORK_RECORDS,
    PAGE_TEMPLATES, PAGE_REGISTRY, PAGE_LATE_FEE, PAGE_FOLDER_BOOKMARKS,
    PAGE_SETTINGS,
)
from ..navigation import NAV_ICON_ROLES
from .buttons import make_button

PRIMARY_DESTINATIONS = (
    PAGE_ATTACHMENTS, PAGE_TASKS, PAGE_ANNUAL_WORKBENCH,
    PAGE_ENGAGEMENTS, PAGE_RECURRING_BILLING,
)
PRIMARY_LABELS = {
    PAGE_ATTACHMENTS: "收件核對",
    PAGE_TASKS: "待辦",
    PAGE_ANNUAL_WORKBENCH: "年度工作",
    PAGE_ENGAGEMENTS: "案件",
    PAGE_RECURRING_BILLING: "固定開立",
}
TOOL_GROUPS = (
    ("客戶資料", (PAGE_CLIENTS,)),
    ("工作資源", (PAGE_WORK_RECORDS, PAGE_TEMPLATES, PAGE_FOLDER_BOOKMARKS)),
    ("查詢與試算", (PAGE_REGISTRY, PAGE_LATE_FEE)),
    ("系統", (PAGE_SETTINGS,)),
)


class WorkspaceNavigation(QWidget):
    currentRowChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspaceNavigation")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._current_row = -1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.SPACING_MD, tokens.SPACING_SM,
            tokens.SPACING_MD, tokens.SPACING_SM,
        )
        self._layout.setSpacing(tokens.SPACING_XS)
        self._brand = QLabel("TaxOps")
        self._brand.setObjectName("WorkspaceBrand")
        self._layout.addWidget(self._brand)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        for page_id in PRIMARY_DESTINATIONS:
            button = make_button(
                PRIMARY_LABELS[page_id], role=tokens.ROLE_QUIET,
                icon_role=NAV_ICON_ROLES[page_id],
            )
            button.setObjectName("WorkspaceNavButton")
            button.setProperty("destination", page_id)
            button.setCheckable(True)
            button.setAccessibleName(PRIMARY_LABELS[page_id])
            button.setToolTip(NAV_LABELS[page_id])
            button.clicked.connect(
                lambda _checked=False, p=page_id: self.setCurrentRow(NAV_ORDER.index(p))
            )
            self._group.addButton(button)
            self._buttons[page_id] = button
            self._layout.addWidget(button)
        self._layout.addStretch(1)
        self._tools_button = make_button("資料與工具", role=tokens.ROLE_QUIET)
        self._tools_button.setObjectName("WorkspaceTools")
        self._tools_button.setAccessibleName(
            "資料與工具，包含客戶資料、工作資源、查詢與試算、系統"
        )
        self._menu = QMenu(self._tools_button)
        self._actions: dict[str, QAction] = {}
        self._action_group = QActionGroup(self)
        self._action_group.setExclusive(True)
        for group_name, destinations in TOOL_GROUPS:
            self._menu.addSection(group_name)
            for page_id in destinations:
                action = self._menu.addAction(
                    icons.icon(NAV_ICON_ROLES[page_id]), NAV_LABELS[page_id]
                )
                action.setCheckable(True)
                action.setData(page_id)
                self._action_group.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, p=page_id: self.setCurrentRow(NAV_ORDER.index(p))
                )
                self._actions[page_id] = action
        self._tools_button.setMenu(self._menu)
        self._layout.addWidget(self._tools_button)
        self._local_label = QLabel("本機資料")
        self._local_label.setObjectName("WorkspaceLocal")
        self._local_label.setToolTip(
            "資料保存在本機；核心工作不需要連線。工商線上補查與快取下載需要網路。"
        )
        self._layout.addWidget(self._local_label)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._local_label.hide()

    def currentRow(self) -> int:
        return self._current_row

    def setCurrentRow(self, row: int) -> None:
        if row < 0 or row >= len(NAV_ORDER):
            return
        changed = row != self._current_row
        self._current_row = row
        page_id = NAV_ORDER[row]
        self._group.setExclusive(False)
        for key, button in self._buttons.items():
            button.setChecked(key == page_id)
            button.setIcon(icons.icon(NAV_ICON_ROLES[key], tokens.TEXT if key == page_id else tokens.WORKSPACE_NAV_TEXT))
        self._group.setExclusive(True)
        for key, action in self._actions.items():
            action.setChecked(key == page_id)
        self._tools_button.setText(
            NAV_LABELS[page_id] if page_id in self._actions else "資料與工具"
        )
        self._tools_button.setProperty("active", page_id in self._actions)
        style = self._tools_button.style()
        style.unpolish(self._tools_button)
        style.polish(self._tools_button)
        if changed:
            self.currentRowChanged.emit(row)

    def resizeEvent(self, event: QResizeEvent) -> None:
        # Optional location hint yields space before any destination label does.
        self._local_label.setVisible(event.size().width() >= 1120)
        super().resizeEvent(event)

    def focus_current(self) -> None:
        page_id = NAV_ORDER[self._current_row] if self._current_row >= 0 else PAGE_ATTACHMENTS
        (self._buttons.get(page_id) or self._tools_button).setFocus(
            Qt.FocusReason.ShortcutFocusReason
        )
