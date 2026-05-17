"""Placeholder page used by every nav item that is not implemented yet.

Renders the page title plus a "此功能尚未開放" notice. Disabled action
buttons declared in the action registry are shown so the user can preview
what the page will offer once implemented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import DISABLED_TOOLTIP, NAV_LABELS
from ..action_registry import actions_for_page


class PlaceholderPage(QWidget):
    def __init__(self, page_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page_id = page_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(NAV_LABELS.get(page_id, page_id))
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        notice = QLabel(DISABLED_TOOLTIP + "，將於後續切片實作。")
        notice.setStyleSheet("color: #555; font-size: 14px;")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        actions = actions_for_page(page_id)
        if actions:
            row = QHBoxLayout()
            row.setSpacing(8)
            for action in actions:
                button = QPushButton(action.button_label)
                button.setEnabled(False)
                button.setToolTip(DISABLED_TOOLTIP)
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)

        layout.addStretch(1)
        self.setLayout(layout)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
