"""Dialog for bulk-adding document request items (one item per line)."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
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
        self.setWindowTitle("批量新增文件項目")
        self.setMinimumWidth(400)
        self.setMinimumHeight(240)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("文件項目名稱（每行一個）："))
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("例：\n進項憑證\n銷項發票明細\n銀行對帳單")
        layout.addWidget(self._text_edit, stretch=1)

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
            self._svc.add_items_bulk(self._request_id, self._text_edit.toPlainText())
        except DocumentRequestValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
            self._ok_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("add_items_bulk unexpected error request_id=%s", self._request_id)
            QMessageBox.warning(self, "新增失敗", error_message("doc_request_item.add.failed"))
            self._ok_btn.setEnabled(True)
            return
        self.accept()
