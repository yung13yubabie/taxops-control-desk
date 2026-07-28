"""Modal editor for one annual-work item."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...services.container import ServiceContainer
from ...i18n.labels import BUTTON_LABELS
from .annual_workflow_dialog import AnnualWorkflowDialog
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
        self._container = container
        self.setObjectName("AnnualItemDialog")
        self.setWindowTitle("年度工作明細")
        self.setMinimumSize(900, 540)
        self.resize(980, 680)
        font = self.font()
        font.setPointSize(11)
        self.setFont(font)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.has_committed_change = False
        self._workflow_open = False
        workflow_row = QHBoxLayout()
        workflow_row.addStretch(1)
        self.request_management_button = QPushButton(
            BUTTON_LABELS["annual.request_management"]
        )
        self.request_management_button.setStyleSheet(
            "font-size: 14px; font-weight: 600;"
        )
        workflow_row.addWidget(self.request_management_button)
        layout.addLayout(workflow_row)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.detail = AnnualItemDetail(container, item_id, self)
        self.ledger = AnnualTransactionPanel(
            container,
            item_id,
            commit_observer=self._mark_committed_change,
            parent=self,
        )
        self.splitter.addWidget(self.detail)
        self.splitter.addWidget(self.ledger)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes((330, 540))
        layout.addWidget(self.splitter)
        self.detail.mutation_committed.connect(
            self._mark_committed_change
        )
        self.detail.saved.connect(self.accept)
        self.request_management_button.clicked.connect(
            self._open_request_management
        )

    def _mark_committed_change(self) -> None:
        self.has_committed_change = True

    def _open_request_management(self) -> None:
        if self._workflow_open:
            return
        self._workflow_open = True
        self.request_management_button.setEnabled(False)
        try:
            # The workflow may reload this detail after a request mutation.
            # Persist current form values first so that reload cannot silently
            # discard edits the user made before opening request management.
            if not self.detail.save_in_place():
                return
            dialog = AnnualWorkflowDialog(
                self._container, self.detail.item_id, parent=self
            )
            dialog.exec()
            if dialog.has_committed_change:
                self._mark_committed_change()
                self.detail.reload()
        finally:
            self._workflow_open = False
            self.request_management_button.setEnabled(True)

    def reject(self) -> None:
        if self.detail.is_busy:
            self.detail.feedback_label.setText("處理中，請等待操作完成。")
            return
        super().reject()
