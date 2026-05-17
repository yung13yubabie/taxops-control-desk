"""Attachments page: upload and manage evidence files per engagement."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.attachments import AttachmentValidationError, UploadAttachmentInput
from ...services.container import ServiceContainer

def _plain_label(text: str) -> QLabel:
    lbl = QLabel(str(text))
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    return lbl


_COLUMNS = ("id", "original_filename", "extension", "file_size", "status", "uploaded_at")
_HEADERS = {
    "id": "編號",
    "original_filename": "原始檔名",
    "extension": "副檔名",
    "file_size": "大小",
    "status": "狀態",
    "uploaded_at": "上傳時間",
}
_STATUS_LABELS = {
    "uploaded": "已上傳",
    "classified": "已分類",
    "needs_review": "待檢查",
    "accepted": "已驗收",
    "rejected": "已退回",
    "archived": "已封存",
    "on_hold": "法務保留",
}
_FILE_FILTER = (
    "允許的檔案 (*.pdf *.jpg *.jpeg *.png *.xlsx *.xls *.docx *.doc *.txt *.csv)"
    ";;所有檔案 (*)"
)
_ALL = -1


class _AttachmentInfoDialog(QDialog):
    def __init__(self, att, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("附件資訊")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        form.setSpacing(10)
        form.addRow("編號：", _plain_label(str(att.id)))
        form.addRow("原始檔名：", _plain_label(att.original_filename))
        form.addRow("副檔名：", _plain_label(att.extension))
        size_kb = f"{att.file_size / 1024:.1f} KB ({att.file_size:,} bytes)"
        form.addRow("大小：", _plain_label(size_kb))
        form.addRow("SHA-256：", _plain_label(att.file_hash_sha256))
        form.addRow("MIME 類型：", _plain_label(att.mime_type))
        form.addRow("狀態：", _plain_label(_STATUS_LABELS.get(att.status, att.status)))
        form.addRow("上傳者：", _plain_label(att.uploaded_by))
        form.addRow("上傳時間：", _plain_label(att.uploaded_at))
        if att.accepted_by:
            form.addRow("驗收者：", _plain_label(att.accepted_by))
        if att.accepted_at:
            form.addRow("驗收時間：", _plain_label(att.accepted_at))
        if att.notes:
            form.addRow("備註：", _plain_label(att.notes))
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(self.accept)
        form.addRow("", close_btn)


class AttachmentsPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._attachments: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("附件管理")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("案件："))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(250)
        filter_row.addWidget(self._eng_combo)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._upload_btn = QPushButton("新增附件")
        self._upload_btn.clicked.connect(self._on_upload)
        btn_row.addWidget(self._upload_btn)

        self._accept_btn = QPushButton("標記已驗收")
        self._accept_btn.setEnabled(False)
        self._accept_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self._accept_btn)

        self._reject_btn = QPushButton("標記退回")
        self._reject_btn.setEnabled(False)
        self._reject_btn.clicked.connect(self._on_reject)
        btn_row.addWidget(self._reject_btn)

        self._info_btn = QPushButton("檔案資訊")
        self._info_btn.setEnabled(False)
        self._info_btn.clicked.connect(self._on_show_info)
        btn_row.addWidget(self._info_btn)

        self._open_btn = QPushButton("用系統程式開啟")
        self._open_btn.setEnabled(False)
        self._open_btn.setToolTip("此功能尚未開放")
        btn_row.addWidget(self._open_btn)

        btn_row.addStretch()
        outer.addLayout(btn_row)

        # Attachment table
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([_HEADERS[c] for c in _COLUMNS])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        outer.addWidget(self._table)

        self._eng_combo.currentIndexChanged.connect(self._load_attachments)
        self._load_engagements()

    def _load_engagements(self) -> None:
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("（請選擇案件）", _ALL)
        try:
            for eng in self._container.engagements.list_all():
                self._eng_combo.addItem(eng.engagement_name, eng.id)
        except Exception as exc:
            self._container.system_log.warn(
                "attachments: failed to load engagements",
                detail={"exc": type(exc).__name__, "msg": str(exc)},
            )
        self._eng_combo.blockSignals(False)
        self._load_attachments()

    def _load_attachments(self) -> None:
        eng_id = self._eng_combo.currentData()
        self._attachments = []
        if eng_id and eng_id != _ALL:
            try:
                self._attachments = self._container.attachments.list_by_engagement(eng_id)
            except Exception as exc:
                self._container.system_log.warn(
                    "attachments: failed to load attachments",
                    detail={"exc": type(exc).__name__, "msg": str(exc)},
                )
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(0)
        for att in self._attachments:
            row = self._table.rowCount()
            self._table.insertRow(row)
            vals = {
                "id": str(att.id),
                "original_filename": att.original_filename,
                "extension": att.extension,
                "file_size": f"{att.file_size / 1024:.1f} KB",
                "status": _STATUS_LABELS.get(att.status, att.status),
                "uploaded_at": att.uploaded_at,
            }
            for col, key in enumerate(_COLUMNS):
                self._table.setItem(row, col, QTableWidgetItem(vals[key]))

    def _selected_index(self) -> int | None:
        items = self._table.selectedItems()
        if not items:
            return None
        return self._table.row(items[0])

    def _selected_attachment(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._attachments):
            return None
        return self._attachments[idx]

    def _on_selection_changed(self) -> None:
        has = self._selected_index() is not None
        self._accept_btn.setEnabled(has)
        self._reject_btn.setEnabled(has)
        self._info_btn.setEnabled(has)

    def _on_upload(self) -> None:
        eng_id = self._eng_combo.currentData()
        if not eng_id or eng_id == _ALL:
            QMessageBox.warning(self, "提示", "請先選擇案件")
            return

        path, _ = QFileDialog.getOpenFileName(self, "選擇附件", "", _FILE_FILTER)
        if not path:
            return

        try:
            self._container.attachments.upload_attachment(
                UploadAttachmentInput(
                    engagement_id=eng_id,
                    request_id=None,
                    source_path=Path(path),
                )
            )
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "上傳失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "上傳失敗", error_message("attachment.upload.failed"))
            return

        self._load_attachments()

    def _on_accept(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        try:
            self._container.attachments.accept_attachment(att.id)
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "操作失敗", error_message("attachment.accept.failed"))
            return
        self._load_attachments()

    def _on_reject(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        try:
            self._container.attachments.reject_attachment(att.id)
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "操作失敗", error_message("attachment.reject.failed"))
            return
        self._load_attachments()

    def _on_show_info(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        dlg = _AttachmentInfoDialog(att, self)
        dlg.exec()
