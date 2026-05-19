"""Dialog for adding a single document request item."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.document_requests import DocumentRequestValidationError, DocumentRequestsService

_log = logging.getLogger(__name__)


class AddDocumentItemDialog(QDialog):
    def __init__(
        self,
        svc: DocumentRequestsService,
        request_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._request_id = request_id
        self.setWindowTitle("新增文件項目")
        self.setMinimumWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例：進項憑證、租金收據")
        self._name_edit.setMaxLength(200)
        form.addRow(QLabel("文件名稱："), self._name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("新增")

    def _on_accept(self) -> None:
        self._ok_btn.setEnabled(False)
        try:
            self._svc.add_item(self._request_id, self._name_edit.text())
        except DocumentRequestValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
            self._ok_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("add_item unexpected error request_id=%s", self._request_id)
            QMessageBox.warning(self, "新增失敗", error_message("doc_request_item.add.failed"))
            self._ok_btn.setEnabled(True)
            return
        self.accept()
