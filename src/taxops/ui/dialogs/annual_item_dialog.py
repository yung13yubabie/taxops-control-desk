"""Modal editor for one annual-work item."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from ...services.container import ServiceContainer
from ..widgets.annual_item_detail import AnnualItemDetail


class AnnualItemDialog(QDialog):
    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualItemDialog")
        self.setWindowTitle("年度工作明細")
        self.setMinimumSize(900, 540)
        self.resize(980, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.detail = AnnualItemDetail(container, item_id, self)
        layout.addWidget(self.detail)
        self.detail.saved.connect(self.accept)

    def reject(self) -> None:
        if self.detail.is_busy:
            self.detail.feedback_label.setText("處理中，請等待操作完成。")
            return
        super().reject()
