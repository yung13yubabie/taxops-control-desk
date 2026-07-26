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
from ...services.document_requests import (
    MAX_ITEM_NAMES_TOTAL_LENGTH,
    MAX_ITEMS_PER_REQUEST,
    DocumentItemsMutationResult,
    DocumentRequestValidationError,
    DocumentRequestsService,
    validate_bulk_item_text,
)

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
        self.created_items = ()
        self.mutation_result = None
        self.setWindowTitle("批量新增文件項目")
        self.setMinimumWidth(400)
        self.setMinimumHeight(240)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("文件項目名稱（每行一個）："))
        layout.addWidget(
            QLabel(
                f"限制：單一索件批次最多 {MAX_ITEMS_PER_REQUEST:,} 項；"
                f"本次貼上總字數最多 {MAX_ITEM_NAMES_TOTAL_LENGTH:,} 字。"
            )
        )
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
        self._ok_btn.setDefault(True)

        self.setTabOrder(self._text_edit, self._ok_btn)

    def _on_accept(self) -> None:
        self._ok_btn.setEnabled(False)
        raw_text = self._text_edit.toPlainText()
        try:
            validate_bulk_item_text(raw_text)
            self.mutation_result = (
                self._svc.add_items_bulk(
                    self._request_id,
                    raw_text,
                    with_request=True,
                )
            )
            if not isinstance(
                self.mutation_result, DocumentItemsMutationResult
            ):
                raise RuntimeError("doc_request_item.result.invalid")
            self.created_items = self.mutation_result.affected_items
        except DocumentRequestValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
            self._ok_btn.setEnabled(True)
            self._text_edit.setFocus()
            return
        except Exception:
            _log.exception("add_items_bulk unexpected error request_id=%s", self._request_id)
            QMessageBox.warning(self, "新增失敗", error_message("doc_request_item.add.failed"))
            self._ok_btn.setEnabled(True)
            return
        self.accept()
