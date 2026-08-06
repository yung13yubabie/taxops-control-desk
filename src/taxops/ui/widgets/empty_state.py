"""Reusable empty-state block with at most one call to action.

Styling lives in the global stylesheet under `#EmptyStateTitle` and
`#EmptyStateBody` rather than in inline stylesheets, so the type scale and colours
stay in one place.

The action stays secondary. When a page shows an empty state its header primary is
usually the same action, and two primaries on one page is exactly what the rebuild
removes. A page that hides its header action while empty may promote this one.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .. import tokens
from ..style import toolbar_icon
from .buttons import set_button_role


class EmptyState(QWidget):
    """Centered explanation of why a list is empty, plus one next step."""

    def __init__(
        self,
        title: str,
        *,
        detail: str = "",
        action_text: str | None = None,
        action_icon: str = "add",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACING_MD, tokens.SPACING_2XL, tokens.SPACING_MD, tokens.SPACING_2XL
        )
        layout.setSpacing(tokens.SPACING_SM)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # The title carries the weight; the detail explains. Giving both the same
        # muted tone left the block with no reading order.
        self.title_label = QLabel(title)
        self.title_label.setObjectName("EmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("EmptyStateBody")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(bool(detail))
        layout.addWidget(self.detail_label)

        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = QPushButton(action_text)
            self.action_button.setIcon(toolbar_icon(action_icon))
            self.action_button.setIconSize(
                QSize(tokens.ICON_SIZE_MD, tokens.ICON_SIZE_MD)
            )
            set_button_role(self.action_button, tokens.ROLE_SECONDARY)
            layout.addWidget(
                self.action_button,
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )
