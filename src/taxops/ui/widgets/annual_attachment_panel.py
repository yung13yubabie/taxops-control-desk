"""Annual-work attachment panel using the formal engagement attachment store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.attachments import AttachmentRow
from ...repositories.document_requests import DocumentRequestRow
from ...services.attachments import UploadAttachmentInput
from ...services.container import ServiceContainer

_PAGE_SIZE = 50
_FILE_FILTER = (
    "允許的檔案 (*.pdf *.jpg *.jpeg *.png *.xlsx *.xls *.docx *.doc *.txt *.csv)"
    ";;所有檔案 (*)"
)
_STATUS_LABELS = {
    "uploaded": "已上傳",
    "classified": "已分類",
    "needs_review": "待檢查",
    "accepted": "已驗收",
    "rejected": "已退回",
    "archived": "已封存",
    "on_hold": "法務保留",
}


@dataclass(frozen=True)
class AttachmentMutationEvidence:
    operation: str
    row: AttachmentRow
    count_before: int
    request_id: int | None
    archived: bool = False


class AnnualAttachmentPanel(QWidget):
    """Bounded, evidence-aware attachment management for one annual item."""

    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        *,
        commit_observer: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self.item_id = item_id
        self._commit_observer = commit_observer
        self._engagement_id: int | None = None
        self._page = 0
        self._total = 0
        self._rows: tuple[AttachmentRow, ...] = ()
        self._pending_mutation: AttachmentMutationEvidence | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.scope_label = QLabel(
            "案件共用附件｜附件屬於正式案件，年度工作台與附件管理會看到同一筆資料。"
        )
        self.scope_label.setWordWrap(True)
        self.scope_label.setStyleSheet("font-size: 14px; color: #334155;")
        layout.addWidget(self.scope_label)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("附件範圍："))
        self.request_combo = QComboBox()
        self.request_combo.setMinimumWidth(320)
        self.request_combo.addItem(
            "全部案件附件（上傳時存為案件層級）", None
        )
        filter_row.addWidget(self.request_combo)
        filter_row.addStretch(1)
        self.upload_button = QPushButton("上傳案件共用附件")
        self.accept_button = QPushButton("標記附件已驗收")
        self.reject_button = QPushButton("標記附件退回")
        self.archive_button = QPushButton("封存附件")
        self.retry_button = QPushButton("重新核對附件")
        self.retry_button.hide()
        filter_row.addWidget(self.upload_button)
        filter_row.addWidget(self.retry_button)
        layout.addLayout(filter_row)

        action_row = QHBoxLayout()
        action_row.addWidget(self.accept_button)
        action_row.addWidget(self.reject_button)
        action_row.addWidget(self.archive_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("編號", "檔名", "索件編號", "狀態", "大小", "上傳時間")
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.verticalHeader().setDefaultSectionSize(30)
        layout.addWidget(self.table, 1)

        page_row = QHBoxLayout()
        self.page_label = QLabel("第 1 / 1 頁，共 0 筆")
        self.previous_button = QPushButton("附件上一頁")
        self.next_button = QPushButton("附件下一頁")
        page_row.addWidget(self.page_label)
        page_row.addStretch(1)
        page_row.addWidget(self.previous_button)
        page_row.addWidget(self.next_button)
        layout.addLayout(page_row)

        self.request_combo.currentIndexChanged.connect(self._change_filter)
        self.table.itemSelectionChanged.connect(self._restore_buttons)
        self.upload_button.clicked.connect(self._upload)
        self.accept_button.clicked.connect(self._accept)
        self.reject_button.clicked.connect(self._reject)
        self.archive_button.clicked.connect(self._archive)
        self.retry_button.clicked.connect(self.retry_pending_verification)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self._render()

    @property
    def pending_mutation_evidence(self) -> AttachmentMutationEvidence | None:
        return self._pending_mutation

    def set_context(
        self,
        engagement_id: int | None,
        requests: tuple[DocumentRequestRow, ...],
    ) -> bool:
        selected_request_id = self.request_combo.currentData()
        self._engagement_id = engagement_id
        self.request_combo.blockSignals(True)
        self.request_combo.clear()
        self.request_combo.addItem(
            "全部案件附件（上傳時存為案件層級）", None
        )
        for request in requests:
            self.request_combo.addItem(
                f"索件 #{request.id}｜{request.request_name}", request.id
            )
        selected_index = self.request_combo.findData(selected_request_id)
        self.request_combo.setCurrentIndex(max(0, selected_index))
        self.request_combo.blockSignals(False)
        self._page = 0
        self.setEnabled(engagement_id is not None)
        if engagement_id is None:
            self._total = 0
            self._rows = ()
            self.feedback_label.setText("請先建立或連結正式案件，再管理共用附件。")
            self._render()
            return True
        return self.reload()

    def attachment_ids(self) -> tuple[int, ...]:
        return tuple(row.id for row in self._rows)

    def selected_attachment_id(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        item = self.table.item(indexes[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if type(value) is int else None

    def row_for_attachment_id(self, attachment_id: int) -> AttachmentRow | None:
        return next((row for row in self._rows if row.id == attachment_id), None)

    def _selected_row(self) -> AttachmentRow | None:
        selected_id = self.selected_attachment_id()
        return (
            self.row_for_attachment_id(selected_id)
            if selected_id is not None
            else None
        )

    def _request_id(self) -> int | None:
        value = self.request_combo.currentData()
        return value if type(value) is int else None

    def _read_count(self, request_id: int | None) -> int:
        if self._engagement_id is None:
            return 0
        if request_id is None:
            return self._container.attachments.count_by_engagement(
                self._engagement_id
            )
        return self._container.attachments.count_by_request(request_id)

    def _read_page(
        self, request_id: int | None, *, offset: int
    ) -> tuple[AttachmentRow, ...]:
        if self._engagement_id is None:
            return ()
        if request_id is None:
            rows = self._container.attachments.page_by_engagement(
                self._engagement_id, limit=_PAGE_SIZE, offset=offset
            )
        else:
            rows = self._container.attachments.page_by_request(
                request_id, limit=_PAGE_SIZE, offset=offset
            )
        return tuple(rows)

    def reload(self) -> bool:
        request_id = self._request_id()
        try:
            total = self._read_count(request_id)
            last_page = max(0, (total - 1) // _PAGE_SIZE)
            self._page = min(self._page, last_page)
            rows = self._read_page(
                request_id, offset=self._page * _PAGE_SIZE
            )
        except Exception as exc:
            self._read_failed(exc, committed=self._pending_mutation is not None)
            return False
        self._total = total
        self._rows = rows
        self._render()
        return True

    def _verify_pending(self, evidence: AttachmentMutationEvidence) -> None:
        current_count = self._read_count(evidence.request_id)
        expected_count = evidence.count_before + (-1 if evidence.archived else 1 if evidence.operation == "upload" else 0)
        if current_count != expected_count:
            raise RuntimeError("attachment readback count mismatch")
        stored = self._container.attachments.get(evidence.row.id)
        if evidence.archived:
            if stored != evidence.row or stored.status != "archived":
                raise RuntimeError("attachment archive readback mismatch")
        elif stored != evidence.row:
            raise RuntimeError("attachment row readback mismatch")

    def _finish_mutation(self, evidence: AttachmentMutationEvidence) -> bool:
        self._pending_mutation = evidence
        self._commit_observer()
        try:
            self._verify_pending(evidence)
            self._page = 0
            if not self.reload():
                raise RuntimeError("attachment page readback failed")
            if not evidence.archived:
                self._select_id(evidence.row.id)
        except Exception as exc:
            self._read_failed(exc, committed=True)
            return False
        self._pending_mutation = None
        self.retry_button.hide()
        self._restore_buttons()
        messages = {
            "upload": "附件已上傳並完成資料核對。",
            "accept": "附件已標記驗收並完成資料核對。",
            "reject": "附件已標記退回並完成資料核對。",
            "archive": "附件已封存並完成資料核對。",
        }
        self.feedback_label.setText(messages[evidence.operation])
        return True

    def retry_pending_verification(self) -> bool:
        evidence = self._pending_mutation
        if evidence is None:
            succeeded = self.reload()
            if succeeded:
                self.retry_button.hide()
                self._restore_buttons()
                self.feedback_label.setText("附件已重新讀取。")
            return succeeded
        try:
            self._verify_pending(evidence)
            self._page = 0
            if not self.reload():
                raise RuntimeError("attachment page readback failed")
            if not evidence.archived:
                self._select_id(evidence.row.id)
        except Exception as exc:
            self._read_failed(exc, committed=True)
            return False
        self._pending_mutation = None
        self.retry_button.hide()
        self._restore_buttons()
        self.feedback_label.setText("附件異動已重新核對，未重複送出。")
        return True

    def _upload(self) -> None:
        if self._pending_mutation is not None or self._engagement_id is None:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "選擇案件共用附件", "", _FILE_FILTER
        )
        if not path:
            return
        request_id = self._request_id()
        try:
            count_before = self._read_count(request_id)
            row = self._container.attachments.upload_attachment(
                UploadAttachmentInput(
                    engagement_id=self._engagement_id,
                    request_id=request_id,
                    source_path=Path(path),
                )
            )
        except Exception as exc:
            self._mutation_failed(exc, "附件上傳失敗，資料未變更。")
            return
        self._finish_mutation(
            AttachmentMutationEvidence(
                "upload", row, count_before, request_id
            )
        )

    def _accept(self) -> None:
        self._set_status("accept")

    def _reject(self) -> None:
        self._set_status("reject")

    def _set_status(self, operation: str) -> None:
        if self._pending_mutation is not None:
            return
        selected = self._selected_row()
        if selected is None:
            return
        request_id = self._request_id()
        try:
            count_before = self._read_count(request_id)
            row = (
                self._container.attachments.accept_attachment(selected.id)
                if operation == "accept"
                else self._container.attachments.reject_attachment(selected.id)
            )
        except Exception as exc:
            self._mutation_failed(exc, "附件狀態更新失敗，資料未變更。")
            return
        self._finish_mutation(
            AttachmentMutationEvidence(
                operation, row, count_before, request_id
            )
        )

    def _archive(self) -> None:
        if self._pending_mutation is not None:
            return
        selected = self._selected_row()
        if selected is None:
            return
        request_id = self._request_id()
        try:
            count_before = self._read_count(request_id)
            row = self._container.attachments.delete_attachment(selected.id)
        except Exception as exc:
            self._mutation_failed(exc, "附件封存失敗，資料未變更。")
            return
        self._finish_mutation(
            AttachmentMutationEvidence(
                "archive", row, count_before, request_id, archived=True
            )
        )

    def _change_filter(self) -> None:
        if self._pending_mutation is not None:
            return
        self._page = 0
        self.reload()

    def _previous_page(self) -> None:
        if self._page > 0 and self._pending_mutation is None:
            self._page -= 1
            self.reload()

    def _next_page(self) -> None:
        if (
            (self._page + 1) * _PAGE_SIZE < self._total
            and self._pending_mutation is None
        ):
            self._page += 1
            self.reload()

    def _render(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row_data in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                str(row_data.id),
                row_data.original_filename,
                str(row_data.request_id) if row_data.request_id is not None else "案件層級",
                _STATUS_LABELS.get(row_data.status, row_data.status),
                f"{row_data.file_size / 1024:.1f} KB",
                row_data.uploaded_at,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row_data.id)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        pages = max(1, (self._total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page_label.setText(
            f"第 {self._page + 1} / {pages} 頁，共 {self._total} 筆"
        )
        self.previous_button.setEnabled(
            self._page > 0 and self._pending_mutation is None
        )
        self.next_button.setEnabled(
            (self._page + 1) * _PAGE_SIZE < self._total
            and self._pending_mutation is None
        )
        self._restore_buttons()

    def _select_id(self, attachment_id: int) -> bool:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole) == attachment_id
            ):
                self.table.selectRow(row)
                return True
        return False

    def _restore_buttons(self) -> None:
        locked = self._pending_mutation is not None
        has_context = self._engagement_id is not None
        has_selection = self._selected_row() is not None
        self.request_combo.setEnabled(has_context and not locked)
        self.upload_button.setEnabled(has_context and not locked)
        self.accept_button.setEnabled(has_selection and not locked)
        self.reject_button.setEnabled(has_selection and not locked)
        self.archive_button.setEnabled(has_selection and not locked)

    def _read_failed(self, exc: BaseException, *, committed: bool) -> None:
        self.feedback_label.setText(
            (
                "資料可能已寫入，請勿重送。附件核對失敗，請按「重新核對附件」。"
                if committed
                else f"附件讀取失敗：{self._message(exc)}"
            )
        )
        self.retry_button.show()
        self._restore_buttons()

    def _mutation_failed(self, exc: BaseException, prefix: str) -> None:
        self.feedback_label.setText(f"{prefix} {self._message(exc)}")

    @staticmethod
    def _message(exc: BaseException) -> str:
        code = getattr(exc, "code", "system.unexpected")
        return error_message(code if isinstance(code, str) else "system.unexpected")
