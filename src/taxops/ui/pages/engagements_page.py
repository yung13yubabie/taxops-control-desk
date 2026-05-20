"""Engagements page: per-client list + CRUD + navigate to doc requests."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.clock import today_iso
from ...i18n import NAV_LABELS, error_message
from ...i18n.status_labels import STATUS_LABELS, status_to_label
from ...services.container import ServiceContainer
from ...services.engagements import EngagementValidationError
from ..action_registry import FilterKey
from ..dialogs.edit_engagement_dialog import EditEngagementDialog
from ..dialogs.new_engagement_dialog import NewEngagementDialog
from ..style import toolbar_icon

_COLUMN_ORDER = (
    "id",
    "engagement_name",
    "tax_type",
    "period_name",
    "status",
    "owner",
    "due_date",
    "updated_at",
)

_TABLE_HEADERS = {
    "id": "編號",
    "engagement_name": "案件名稱",
    "tax_type": "稅種",
    "period_name": "期間",
    "status": "狀態",
    "owner": "負責人",
    "due_date": "截止日",
    "updated_at": "更新時間",
}


class EngagementsPage(QWidget):
    open_doc_requests = Signal(int)  # engagement_id

    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._current_client_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel(NAV_LABELS["engagements"])
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        outer.addWidget(title)

        # Client filter
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("客戶："))
        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(260)
        filter_row.addWidget(self._client_combo)
        filter_row.addStretch(1)
        outer.addLayout(filter_row)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_btn = QPushButton("新增案件")
        self._edit_btn = QPushButton("編輯案件")
        self._status_btn = QPushButton("切換狀態")
        self._delete_btn = QPushButton("刪除案件")
        self._doc_btn = QPushButton("管理索件批次")
        self._refresh_btn = QPushButton("重新整理")

        self._new_btn.setIcon(toolbar_icon("new"))
        self._edit_btn.setIcon(toolbar_icon("edit"))
        self._status_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._doc_btn.setIcon(toolbar_icon("bulk"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))

        self._new_btn.setEnabled(False)
        self._edit_btn.setEnabled(False)
        self._status_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._doc_btn.setEnabled(False)

        for btn in (
            self._new_btn,
            self._edit_btn,
            self._status_btn,
            self._delete_btn,
            self._doc_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        self._empty_label = QLabel("請先選擇客戶，或此客戶尚無案件。")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #777; padding: 24px;")
        outer.addWidget(self._empty_label)

        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        self._table.setHorizontalHeaderLabels(
            [_TABLE_HEADERS[c] for c in _COLUMN_ORDER]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(
            _COLUMN_ORDER.index("engagement_name"), QHeaderView.ResizeMode.Stretch
        )
        outer.addWidget(self._table, stretch=1)

        self._client_combo.currentIndexChanged.connect(self._on_client_changed)
        self._new_btn.clicked.connect(self._on_new_engagement)
        self._edit_btn.clicked.connect(self._on_edit_engagement)
        self._status_btn.clicked.connect(self._on_set_status)
        self._delete_btn.clicked.connect(self._on_delete)
        self._doc_btn.clicked.connect(self._on_open_doc_requests)
        self._refresh_btn.clicked.connect(self._on_load_and_refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._filter_key: str = ""
        self._on_load_and_refresh()

    # ------------------------------------------------------------------
    # Public filter API (called by MainWindow on dashboard navigation)

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._refresh_engagements()

    def refresh_context(self) -> None:
        """Reload client choices when the page becomes active."""
        self._on_load_and_refresh()

    # ------------------------------------------------------------------
    # Client loading
    # ------------------------------------------------------------------

    def _on_load_and_refresh(self) -> None:
        saved_id = self._current_client_id
        self._client_combo.blockSignals(True)
        self._client_combo.clear()
        try:
            clients = self._container.clients.search_clients("", limit=500)
        except Exception as err:
            self._container.system_log.error("clients.list in engagements failed", exc=err)
            clients = []
        for client in clients:
            label = f"{client.client_code}  {client.client_name}"
            self._client_combo.addItem(label, userData=client.id)
        self._client_combo.blockSignals(False)

        if not clients:
            self._current_client_id = None
            self._new_btn.setEnabled(False)
            self._table.setRowCount(0)
            self._empty_label.setVisible(True)
            self._table.setVisible(False)
            return

        restore_idx = 0
        if saved_id is not None:
            for i in range(self._client_combo.count()):
                if self._client_combo.itemData(i) == saved_id:
                    restore_idx = i
                    break
        self._client_combo.setCurrentIndex(restore_idx)
        self._current_client_id = self._client_combo.currentData()
        self._new_btn.setEnabled(True)
        self._refresh_engagements()

    def _on_client_changed(self, idx: int) -> None:
        if idx < 0:
            self._current_client_id = None
            self._new_btn.setEnabled(False)
            self._table.setRowCount(0)
            self._empty_label.setVisible(True)
            self._table.setVisible(False)
            return
        self._current_client_id = self._client_combo.itemData(idx)
        self._new_btn.setEnabled(True)
        self._refresh_engagements()

    # ------------------------------------------------------------------
    # Table refresh
    # ------------------------------------------------------------------

    def _refresh_engagements(self) -> None:
        try:
            if self._filter_key == FilterKey.UPCOMING:
                today = today_iso()
                until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=7)).isoformat()
                rows = self._container.engagements.list_upcoming(today, until)
            elif self._filter_key == FilterKey.OVERDUE:
                rows = self._container.engagements.list_overdue(today_iso())
            else:
                if self._current_client_id is None:
                    return
                rows = self._container.engagements.list_by_client(self._current_client_id)
        except Exception as err:
            self._container.system_log.error("engagements.list failed", exc=err)
            QMessageBox.warning(self, "載入失敗", error_message("system.unexpected"))
            return

        self._table.setRowCount(len(rows))
        for row_idx, eng in enumerate(rows):
            values = {
                "id": str(eng.id),
                "engagement_name": eng.engagement_name,
                "tax_type": status_to_label(eng.tax_type),
                "period_name": eng.period_name,
                "status": status_to_label(eng.status),
                "owner": eng.owner or "",
                "due_date": eng.due_date or "",
                "updated_at": eng.updated_at,
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setToolTip(values[col])
                self._table.setItem(row_idx, col_idx, item)

        has_rows = len(rows) > 0
        self._empty_label.setVisible(not has_rows)
        self._table.setVisible(has_rows)
        self._on_selection_changed()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._edit_btn.setEnabled(has_sel)
        self._status_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._doc_btn.setEnabled(has_sel)

    def _selected_engagement_id(self) -> int | None:
        items = self._table.selectedItems()
        if not items:
            return None
        row = self._table.row(items[0])
        id_item = self._table.item(row, 0)
        return int(id_item.text()) if id_item else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new_engagement(self) -> None:
        if self._current_client_id is None:
            return
        dialog = NewEngagementDialog(
            self._container.engagements,
            self._current_client_id,
            parent=self,
        )
        if dialog.exec() == NewEngagementDialog.DialogCode.Accepted:
            self._refresh_engagements()

    def _on_edit_engagement(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        dialog = EditEngagementDialog(
            self._container.engagements,
            eng,
            parent=self,
        )
        if dialog.exec() == EditEngagementDialog.DialogCode.Accepted:
            self._refresh_engagements()

    def _on_set_status(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        allowed = self._container.engagements.valid_next_statuses(eng_id)
        choices = sorted(
            STATUS_LABELS.get(s, s) for s in allowed if s != eng.status
        )
        if not choices:
            QMessageBox.information(self, "無可用狀態", "此案件目前無法切換到其他狀態。")
            return
        choice_label, ok = QInputDialog.getItem(
            self,
            "切換案件狀態",
            f"目前狀態：{status_to_label(eng.status)}\n請選擇目標狀態：",
            choices,
            editable=False,
        )
        if not ok or not choice_label:
            return
        label_to_value = {v: k for k, v in STATUS_LABELS.items()}
        target = label_to_value.get(choice_label)
        if target is None:
            return
        try:
            self._container.engagements.set_status(eng_id, target)
        except EngagementValidationError as exc:
            QMessageBox.warning(self, "切換失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "切換失敗", error_message("engagement.update.failed"))
            return
        self._refresh_engagements()

    def _on_delete(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除案件「{eng.engagement_name}」（{eng.period_name}）？\n"
            "資料將標記為已刪除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.engagements.delete_engagement(eng_id)
        except EngagementValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "刪除失敗", error_message("engagement.delete.failed"))
            return
        self._refresh_engagements()

    def _on_open_doc_requests(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is not None:
            self.open_doc_requests.emit(eng_id)
