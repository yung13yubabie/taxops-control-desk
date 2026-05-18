"""Tasks page: all workflow tasks with engagement filter and CRUD actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
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
from ...i18n import error_message
from ...i18n.status_labels import PRIORITY_LABELS, STATUS_LABELS, status_to_label
from ...services.container import ServiceContainer
from ...services.tasks import VALID_TASK_STATUSES, TaskValidationError
from ..action_registry import FilterKey
from ..dialogs.new_task_dialog import NewTaskDialog

_COLUMN_ORDER = ("id", "title", "priority", "status", "assignee", "due_date", "updated_at")

_TABLE_HEADERS = {
    "id": "編號",
    "title": "標題",
    "priority": "優先級",
    "status": "狀態",
    "assignee": "負責人",
    "due_date": "到期日",
    "updated_at": "更新時間",
}

_ALL_ENGAGEMENTS = -1


class TasksPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title_label = QLabel("待辦事項")
        title_label.setObjectName("PageTitle")
        outer.addWidget(title_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("案件："))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(220)
        filter_row.addWidget(self._eng_combo)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_btn = QPushButton("新增待辦")
        self._complete_btn = QPushButton("完成待辦")
        self._complete_btn.setEnabled(False)
        self._status_btn = QPushButton("切換狀態")
        self._status_btn.setEnabled(False)
        self._delete_btn = QPushButton("刪除待辦")
        self._delete_btn.setEnabled(False)
        self._refresh_btn = QPushButton("重新整理")
        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._complete_btn)
        toolbar.addWidget(self._status_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._refresh_btn)
        outer.addLayout(toolbar)

        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        self._table.setHorizontalHeaderLabels([_TABLE_HEADERS[c] for c in _COLUMN_ORDER])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            _COLUMN_ORDER.index("title"), QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        outer.addWidget(self._table)

        self._empty_label = QLabel("目前沒有待辦事項")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.hide()
        outer.addWidget(self._empty_label)

        self._new_btn.clicked.connect(self._on_new_task)
        self._complete_btn.clicked.connect(self._on_complete_task)
        self._status_btn.clicked.connect(self._on_set_status)
        self._delete_btn.clicked.connect(self._on_delete_task)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._eng_combo.currentIndexChanged.connect(self._refresh)

        self._filter_key: str = ""
        self._load_engagements()
        self._refresh()

    # ------------------------------------------------------------------
    # Public filter API (called by MainWindow on dashboard navigation)

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._refresh()

    # ------------------------------------------------------------------
    # Private helpers

    def _load_engagements(self) -> None:
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("（全部案件）", userData=_ALL_ENGAGEMENTS)
        try:
            engs = self._container.engagements.list_all()
        except Exception as err:
            self._container.system_log.warn(
                "tasks_page: failed to load engagements for combo",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            engs = []
            self._eng_combo.addItem("（載入案件失敗）", userData=_ALL_ENGAGEMENTS)
        for eng in engs:
            label = f"{eng.engagement_name} [{STATUS_LABELS.get(eng.tax_type, eng.tax_type)}]"
            self._eng_combo.addItem(label, userData=eng.id)
        self._eng_combo.blockSignals(False)

    def _refresh(self) -> None:
        try:
            if self._filter_key == FilterKey.DUE_TODAY:
                tasks = self._container.tasks.list_due_today(today_iso())
            elif self._filter_key == FilterKey.OVERDUE:
                tasks = self._container.tasks.list_overdue(today_iso())
            else:
                eng_id: int = self._eng_combo.currentData() or _ALL_ENGAGEMENTS
                if eng_id == _ALL_ENGAGEMENTS:
                    tasks = self._container.tasks.list_all()
                else:
                    tasks = self._container.tasks.list_by_engagement(eng_id)
        except Exception:
            tasks = []

        self._table.setRowCount(len(tasks))
        for row_idx, task in enumerate(tasks):
            values = {
                "id": str(task.id),
                "title": task.title,
                "priority": PRIORITY_LABELS.get(task.priority, task.priority),
                "status": status_to_label(task.status),
                "assignee": task.assignee or "",
                "due_date": task.due_date or "",
                "updated_at": task.updated_at[:16] if task.updated_at else "",
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_idx, col_idx, item)

        has_rows = len(tasks) > 0
        self._table.setVisible(has_rows)
        self._empty_label.setVisible(not has_rows)
        self._on_selection_changed()

    def _selected_task_id(self) -> int | None:
        if not self._table.selectedItems():
            return None
        row = self._table.currentRow()
        id_item = self._table.item(row, 0)
        if id_item is None:
            return None
        try:
            return int(id_item.text())
        except ValueError:
            return None

    def _on_selection_changed(self) -> None:
        has_sel = self._selected_task_id() is not None
        self._complete_btn.setEnabled(has_sel)
        self._status_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)

    # ------------------------------------------------------------------
    # Action handlers

    def _on_new_task(self) -> None:
        eng_id: int = self._eng_combo.currentData() or _ALL_ENGAGEMENTS
        if eng_id == _ALL_ENGAGEMENTS:
            QMessageBox.information(self, "請選擇案件", "新增待辦前請先在上方選擇一個案件。")
            return
        dlg = NewTaskDialog(self._container.tasks, eng_id, parent=self)
        if dlg.exec() == NewTaskDialog.DialogCode.Accepted:
            self._refresh()

    def _on_complete_task(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        reply = QMessageBox.question(
            self,
            "完成待辦",
            "確定要將此待辦標記為已完成？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.tasks.complete_task(task_id)
        except TaskValidationError as err:
            QMessageBox.warning(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "操作失敗", error_message("task.complete.failed"))
            return
        self._refresh()

    def _on_set_status(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_TASK_STATUSES}
        choices = sorted(label_to_value)
        label, ok = QInputDialog.getItem(
            self, "切換狀態", "請選擇新狀態：", choices, editable=False
        )
        if not ok or not label:
            return
        target = label_to_value.get(label)
        if target is None:
            return
        try:
            self._container.tasks.set_status(task_id, target)
        except TaskValidationError as err:
            QMessageBox.warning(self, "切換失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "切換失敗", error_message("system.unexpected"))
            return
        self._refresh()

    def _on_delete_task(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        reply = QMessageBox.question(
            self,
            "刪除待辦",
            "確定要刪除此待辦？此操作無法復原，請聯絡系統維護人員。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.tasks.delete_task(task_id)
        except TaskValidationError as err:
            QMessageBox.warning(self, "刪除失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "刪除失敗", error_message("task.delete.failed"))
            return
        self._refresh()
