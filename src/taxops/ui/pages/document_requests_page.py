"""Document requests page: request list + items split view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import NAV_LABELS, error_message
from ...i18n.status_labels import STATUS_LABELS, status_to_label
from ...services.container import ServiceContainer
from ...services.document_requests import (
    CreateDocumentRequestInput,
    DocumentRequestValidationError,
    VALID_ITEM_STATUSES,
)
from ...services.export import ExportValidationError
from ...services.generated_messages import GeneratedMessageValidationError
from ..dialogs.add_document_item_dialog import AddDocumentItemDialog
from ..dialogs.generate_message_dialog import GenerateMessageDialog

_REQ_COLUMNS = (
    "id",
    "tax_type",
    "period_name",
    "status",
    "follow_up_count",
    "requested_at",
    "due_date",
)

_REQ_HEADERS = {
    "id": "編號",
    "tax_type": "稅種",
    "period_name": "期間",
    "status": "狀態",
    "follow_up_count": "催件次數",
    "requested_at": "發出時間",
    "due_date": "截止日",
}

_ITEM_COLUMNS = ("id", "item_name", "item_status", "notes")
_ITEM_HEADERS = {
    "id": "編號",
    "item_name": "文件名稱",
    "item_status": "狀態",
    "notes": "備註",
}


class DocumentRequestsPage(QWidget):
    back_to_engagements = Signal()

    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._engagement_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        # Header row: back button + page title
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(8)
        self._back_btn = QPushButton("← 返回案件")
        self._context_label = QLabel(NAV_LABELS["doc_requests"])
        self._context_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        hdr_row.addWidget(self._back_btn)
        hdr_row.addWidget(self._context_label)
        hdr_row.addStretch(1)
        outer.addLayout(hdr_row)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_req_btn = QPushButton("新增索件批次")
        self._mark_requested_btn = QPushButton("標記已發出")
        self._follow_up_btn = QPushButton("催件 +1")
        self._delete_req_btn = QPushButton("刪除批次")
        self._add_item_btn = QPushButton("新增文件項目")
        self._item_status_btn = QPushButton("切換項目狀態")
        self._generate_btn = QPushButton("產生訊息")
        self._export_btn = QPushButton("匯出缺件清單")

        self._new_req_btn.setEnabled(False)
        self._mark_requested_btn.setEnabled(False)
        self._follow_up_btn.setEnabled(False)
        self._delete_req_btn.setEnabled(False)
        self._add_item_btn.setEnabled(False)
        self._item_status_btn.setEnabled(False)
        self._generate_btn.setEnabled(False)
        self._export_btn.setEnabled(False)

        for btn in (
            self._new_req_btn,
            self._mark_requested_btn,
            self._follow_up_btn,
            self._delete_req_btn,
            self._add_item_btn,
            self._item_status_btn,
            self._generate_btn,
            self._export_btn,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        # Empty state shown before an engagement is loaded
        self._no_engagement_label = QLabel(
            "請從案件管理頁選擇一個案件，再查看索件批次。"
        )
        self._no_engagement_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_engagement_label.setStyleSheet("color: #777; padding: 48px;")
        outer.addWidget(self._no_engagement_label)

        # Splitter: request list (top) + item list (bottom)
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        req_widget = QWidget()
        req_layout = QVBoxLayout(req_widget)
        req_layout.setContentsMargins(0, 0, 0, 4)
        req_layout.addWidget(QLabel("索件批次"))
        self._req_table = QTableWidget(0, len(_REQ_COLUMNS))
        self._req_table.setHorizontalHeaderLabels(
            [_REQ_HEADERS[c] for c in _REQ_COLUMNS]
        )
        self._req_table.verticalHeader().setVisible(False)
        self._req_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._req_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rh = self._req_table.horizontalHeader()
        rh.setSectionResizeMode(
            _REQ_COLUMNS.index("period_name"), QHeaderView.ResizeMode.Stretch
        )
        req_layout.addWidget(self._req_table)
        self._splitter.addWidget(req_widget)

        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 4, 0, 0)
        item_layout.addWidget(QLabel("文件項目"))
        self._item_table = QTableWidget(0, len(_ITEM_COLUMNS))
        self._item_table.setHorizontalHeaderLabels(
            [_ITEM_HEADERS[c] for c in _ITEM_COLUMNS]
        )
        self._item_table.verticalHeader().setVisible(False)
        self._item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._item_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        ih = self._item_table.horizontalHeader()
        ih.setSectionResizeMode(
            _ITEM_COLUMNS.index("item_name"), QHeaderView.ResizeMode.Stretch
        )
        item_layout.addWidget(self._item_table)
        self._splitter.addWidget(item_widget)

        self._splitter.setVisible(False)
        outer.addWidget(self._splitter, stretch=1)

        self._back_btn.clicked.connect(self.back_to_engagements)
        self._new_req_btn.clicked.connect(self._on_new_request)
        self._mark_requested_btn.clicked.connect(self._on_mark_requested)
        self._follow_up_btn.clicked.connect(self._on_follow_up)
        self._delete_req_btn.clicked.connect(self._on_delete_request)
        self._add_item_btn.clicked.connect(self._on_add_item)
        self._item_status_btn.clicked.connect(self._on_set_item_status)
        self._generate_btn.clicked.connect(self._on_generate_message)
        self._export_btn.clicked.connect(self._on_export)
        self._req_table.itemSelectionChanged.connect(self._on_req_selection_changed)
        self._item_table.itemSelectionChanged.connect(self._on_item_selection_changed)

    # ------------------------------------------------------------------
    # Public API called by MainWindow
    # ------------------------------------------------------------------

    def load_engagement(self, engagement_id: int) -> None:
        eng = self._container.engagements.get_engagement(engagement_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            return
        self._engagement_id = engagement_id
        client = self._container.clients.get_client(eng.client_id)
        client_part = f"【{client.client_name}】" if client else ""
        label = (
            f"{NAV_LABELS['doc_requests']} — "
            f"{client_part}{eng.engagement_name}（{status_to_label(eng.status)}）"
        )
        self._context_label.setText(label)
        self._new_req_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._no_engagement_label.setVisible(False)
        self._splitter.setVisible(True)
        self._refresh_requests()

    # ------------------------------------------------------------------
    # Table refresh
    # ------------------------------------------------------------------

    def _refresh_requests(self) -> None:
        if self._engagement_id is None:
            return
        try:
            reqs = self._container.doc_requests.list_by_engagement(self._engagement_id)
        except Exception as err:
            self._container.system_log.error("doc_requests.list failed", exc=err)
            QMessageBox.warning(self, "載入失敗", error_message("system.unexpected"))
            return

        self._req_table.setRowCount(len(reqs))
        for row_idx, req in enumerate(reqs):
            values = {
                "id": str(req.id),
                "tax_type": status_to_label(req.tax_type),
                "period_name": req.period_name,
                "status": status_to_label(req.status),
                "follow_up_count": str(req.follow_up_count),
                "requested_at": req.requested_at or "",
                "due_date": req.due_date or "",
            }
            for col_idx, col in enumerate(_REQ_COLUMNS):
                self._req_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(values[col])
                )

        self._item_table.setRowCount(0)
        self._on_req_selection_changed()

    def _load_items_for_selected(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            self._item_table.setRowCount(0)
            return
        try:
            items = self._container.doc_requests.list_items(req_id)
        except Exception as err:
            self._container.system_log.error("doc_request_items.list failed", exc=err)
            return

        self._item_table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            values = {
                "id": str(item.id),
                "item_name": item.item_name,
                "item_status": status_to_label(item.item_status),
                "notes": item.notes or "",
            }
            for col_idx, col in enumerate(_ITEM_COLUMNS):
                self._item_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(values[col])
                )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_req_selection_changed(self) -> None:
        has_sel = bool(self._req_table.selectedItems())
        self._mark_requested_btn.setEnabled(has_sel)
        self._follow_up_btn.setEnabled(has_sel)
        self._delete_req_btn.setEnabled(has_sel)
        self._add_item_btn.setEnabled(has_sel)
        self._generate_btn.setEnabled(has_sel)
        if has_sel:
            self._load_items_for_selected()
        else:
            self._item_table.setRowCount(0)
            self._item_status_btn.setEnabled(False)

    def _on_item_selection_changed(self) -> None:
        self._item_status_btn.setEnabled(bool(self._item_table.selectedItems()))

    def _selected_request_id(self) -> int | None:
        items = self._req_table.selectedItems()
        if not items:
            return None
        row = self._req_table.row(items[0])
        id_item = self._req_table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _selected_item_id(self) -> int | None:
        items = self._item_table.selectedItems()
        if not items:
            return None
        row = self._item_table.row(items[0])
        id_cell = self._item_table.item(row, 0)
        return int(id_cell.text()) if id_cell else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new_request(self) -> None:
        if self._engagement_id is None:
            return
        eng = self._container.engagements.get_engagement(self._engagement_id)
        if eng is None:
            return
        payload = CreateDocumentRequestInput(
            engagement_id=self._engagement_id,
            tax_type=eng.tax_type,
            period_name=eng.period_name,
            use_vat_template=(eng.tax_type == "vat"),
        )
        try:
            self._container.doc_requests.create_request(payload)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "新增失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(
                self, "新增失敗", error_message("doc_request.create.failed")
            )
            return
        self._refresh_requests()

    def _on_mark_requested(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        try:
            self._container.doc_requests.mark_requested(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "操作失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "操作失敗", error_message("system.unexpected"))
            return
        self._refresh_requests()

    def _on_follow_up(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        try:
            self._container.doc_requests.add_follow_up(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "操作失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "操作失敗", error_message("system.unexpected"))
            return
        self._refresh_requests()

    def _on_delete_request(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            "確定要刪除這個索件批次？刪除後將無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.doc_requests.delete_request(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(
                self, "刪除失敗", error_message("doc_request.delete.failed")
            )
            return
        self._refresh_requests()

    def _on_add_item(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        dlg = AddDocumentItemDialog(self._container.doc_requests, req_id, parent=self)
        if dlg.exec() == AddDocumentItemDialog.DialogCode.Accepted:
            self._refresh_requests()

    def _on_set_item_status(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_ITEM_STATUSES}
        choices = sorted(label_to_value)
        item_row = self._item_table.currentRow()
        cur_item_label = (self._item_table.item(item_row, _ITEM_COLUMNS.index("item_status")) or QTableWidgetItem()).text()
        current_idx = choices.index(cur_item_label) if cur_item_label in choices else 0
        label, ok = QInputDialog.getItem(
            self,
            "切換項目狀態",
            "請選擇新狀態：",
            choices,
            current=current_idx,
            editable=False,
        )
        if not ok or not label:
            return
        target = label_to_value.get(label)
        if target is None:
            return
        try:
            self._container.doc_requests.set_item_status(item_id, item_status=target)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "切換失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "切換失敗", error_message("system.unexpected"))
            return
        self._load_items_for_selected()

    def _on_generate_message(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        dlg = GenerateMessageDialog(
            gen_svc=self._container.gen_messages,
            templates_svc=self._container.templates,
            request_id=req_id,
            parent=self,
        )
        dlg.exec()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "匯出缺件清單",
            "缺件清單.xlsx",
            "Excel 檔案 (*.xlsx)",
        )
        if not path:
            return
        try:
            count = self._container.export.export_missing_items_xlsx(
                output_path=Path(path),
                engagement_id=self._engagement_id,
            )
        except ExportValidationError as err:
            QMessageBox.critical(self, "匯出失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(
                self, "匯出失敗", error_message("export.save_failed")
            )
            return
        if count == 0:
            QMessageBox.information(self, "匯出完成", error_message("export.no_rows"))
        else:
            QMessageBox.information(
                self, "匯出完成", f"已匯出 {count} 筆缺件項目至：\n{path}"
            )
