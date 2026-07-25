"""Modal editor for one annual-work item."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QSplitter, QVBoxLayout, QWidget

from ...services.container import ServiceContainer
from ..widgets.annual_item_detail import AnnualItemDetail
from ..widgets.annual_transaction_panel import AnnualTransactionPanel


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
        self.has_committed_change = False
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.detail = AnnualItemDetail(container, item_id, self)
        self.ledger = AnnualTransactionPanel(container, item_id, self)
        self.splitter.addWidget(self.detail)
        self.splitter.addWidget(self.ledger)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes((330, 540))
        layout.addWidget(self.splitter)
        self.detail.mutation_committed.connect(
            self._mark_committed_change
        )
        self.ledger.mutation_committed.connect(
            self._mark_committed_change
        )
        self.detail.saved.connect(self.accept)

    def _mark_committed_change(self) -> None:
        self.has_committed_change = True

    def reject(self) -> None:
        if self.detail.is_busy:
            self.detail.feedback_label.setText("處理中，請等待操作完成。")
            return
        super().reject()
