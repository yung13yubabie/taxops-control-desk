"""Reusable empty-state block with an optional primary action."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..style import SPACING_MD, SPACING_SM, TEXT_MUTED, toolbar_icon


class EmptyState(QWidget):
    """Small centered empty-state widget used by list pages."""

    def __init__(
        self,
        title: str,
        *,
        detail: str = "",
        action_text: str | None = None,
        action_icon: str = "new",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_MD, 24, SPACING_MD, 24)
        layout.setSpacing(SPACING_SM)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("EmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.title_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("EmptyStateBody")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.detail_label.setVisible(bool(detail))
        layout.addWidget(self.detail_label)

        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = QPushButton(action_text)
            self.action_button.setIcon(toolbar_icon(action_icon))
            layout.addWidget(
                self.action_button,
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )
