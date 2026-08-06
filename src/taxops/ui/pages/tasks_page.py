"""Tasks page: all workflow tasks with client + engagement cascade filter."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
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
from ...services.tasks import TaskValidationError, allowed_task_status_transitions
from ..action_registry import FilterKey
from ..dialogs.new_task_dialog import NewTaskDialog
from ..dialogs.task_bulk_dialogs import (
    BulkCreateTasksDialog,
    BulkEditTasksDialog,
    ParentTaskDialog,
)
from ..style import DANGER_COLOR, toolbar_icon
from ..widgets.buttons import set_button_role
from ..widgets.column_settings import ColumnSettings
from ..widgets.empty_state import EmptyState
from ..widgets.flow_layout import FlowLayout
from ..widgets.table_builder import build_standard_table

_COLUMN_ORDER = (
    "id",
    "client_label",
    "title",
    "priority",
    "status",
    "assignee",
    "due_date",
    "updated_at",
)

_TABLE_HEADERS = {
    "id": "編號",
    "client_label": "客戶",
    "title": "標題",
    "priority": "優先級",
    "status": "狀態",
    "assignee": "負責人",
    "due_date": "到期日",
    "updated_at": "更新時間",
}

# Slice 21C: cols user cannot hide via header context menu.
_CORE_COLS = frozenset({"client_label", "title", "status"})

# Fixed status-column width so the title can never crush the status cell.
_STATUS_COL_WIDTH = 110

_ALL_CLIENTS = -1
_ALL_ENGAGEMENTS = -1


class TasksPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._tasks: list = []
        self._task_by_id: dict[int, object] = {}
        self._status_change_in_progress = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title_label = QLabel("待辦事項")
        title_label.setObjectName("PageTitle")
        outer.addWidget(title_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("客戶："))
        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(180)
        filter_row.addWidget(self._client_combo)
        filter_row.addWidget(QLabel("案件："))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(220)
        filter_row.addWidget(self._eng_combo)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self._new_btn = QPushButton("新增待辦")
        # 新增下一步 acts on a selected task and stays secondary.
        set_button_role(self._new_btn, "primary")
        self._complete_btn = QPushButton("完成待辦")
        self._complete_btn.setEnabled(False)
        self._status_btn = QPushButton("切換狀態")
        self._status_btn.setEnabled(False)
        self._delete_btn = QPushButton("刪除待辦")
        self._delete_btn.setEnabled(False)
        self._bulk_new_btn = QPushButton("批量新增")
        self._bulk_edit_btn = QPushButton("批量編輯")
        self._bulk_edit_btn.setEnabled(False)
        self._bulk_delete_btn = QPushButton("批量刪除")
        self._bulk_delete_btn.setEnabled(False)
        self._next_step_btn = QPushButton("新增下一步")
        self._next_step_btn.setEnabled(False)
        self._make_child_btn = QPushButton("設為子待辦")
        self._make_child_btn.setEnabled(False)
        self._refresh_btn = QPushButton("重新整理")
        self._new_btn.setIcon(toolbar_icon("new"))
        self._complete_btn.setIcon(toolbar_icon("complete"))
        self._status_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._bulk_new_btn.setIcon(toolbar_icon("new"))
        self._bulk_edit_btn.setIcon(toolbar_icon("edit"))
        self._bulk_delete_btn.setIcon(toolbar_icon("delete"))
        self._next_step_btn.setIcon(toolbar_icon("new"))
        self._make_child_btn.setIcon(toolbar_icon("edit"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        for btn in (
            self._new_btn,
            self._bulk_new_btn,
            self._complete_btn,
            self._status_btn,
            self._delete_btn,
            self._bulk_edit_btn,
            self._bulk_delete_btn,
            self._next_step_btn,
            self._make_child_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        outer.addWidget(toolbar_widget)

        self._table = build_standard_table(
            _COLUMN_ORDER,
            _TABLE_HEADERS,
            stretch_col="title",
            fixed_cols={"status": _STATUS_COL_WIDTH},
            selection_mode=QTableWidget.SelectionMode.ExtendedSelection,
        )
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSortIndicatorShown(True)
        self._table.horizontalHeader().setSectionsClickable(True)
        outer.addWidget(self._table, stretch=1)

        self._empty_state = EmptyState(
            "目前沒有待辦事項",
            detail="可直接新增，或先選擇客戶 / 案件後建立關聯待辦。",
            action_text="新增待辦",
        )
        self._empty_label = self._empty_state.title_label
        self._empty_state.hide()
        outer.addWidget(self._empty_state, stretch=1)

        self._error_label = QLabel("載入待辦事項失敗，請重新整理或重新啟動程式")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setObjectName("ErrorState")
        self._error_label.setStyleSheet(f"color: {DANGER_COLOR};")
        self._error_label.hide()
        outer.addWidget(self._error_label, stretch=1)

        self._new_btn.clicked.connect(self._on_new_task)
        if self._empty_state.action_button is not None:
            self._empty_state.action_button.clicked.connect(self._on_new_task)
        self._bulk_new_btn.clicked.connect(self._on_bulk_new_tasks)
        self._complete_btn.clicked.connect(self._on_complete_task)
        self._status_btn.clicked.connect(self._on_set_status)
        self._delete_btn.clicked.connect(self._on_delete_task)
        self._bulk_edit_btn.clicked.connect(self._on_bulk_edit_tasks)
        self._bulk_delete_btn.clicked.connect(self._on_bulk_delete_tasks)
        self._next_step_btn.clicked.connect(self._on_create_next_step_task)
        self._make_child_btn.clicked.connect(self._on_make_child_task)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._client_combo.currentIndexChanged.connect(self._on_client_changed)
        self._eng_combo.currentIndexChanged.connect(self._refresh)

        self._col_settings = ColumnSettings(
            table=self._table,
            table_id="tasks",
            all_cols=_COLUMN_ORDER,
            core_cols=_CORE_COLS,
            headers=_TABLE_HEADERS,
            settings=container.settings,
        )
        self._col_settings.install()
        for col in ("id", "priority", "assignee", "updated_at"):
            self._table.setColumnHidden(_COLUMN_ORDER.index(col), True)

        self._filter_key: str = ""
        self._load_clients()
        self._reload_engagement_combo()
        self._refresh()

    # ------------------------------------------------------------------
    # Public filter API (called by MainWindow deep links)

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._refresh()

    def clear_filter(self) -> None:
        self._filter_key = ""
        self._client_combo.setCurrentIndex(0)  # 重置為「全部客戶」；會觸發 _on_client_changed 連帶更新 _eng_combo

    def refresh_context(self) -> None:
        """Reload client + engagement choices when data changed elsewhere."""
        self._load_clients()
        self._reload_engagement_combo()
        self._refresh()

    # ------------------------------------------------------------------
    # Combo population

    def _load_clients(self) -> None:
        selected = self._client_combo.currentData()
        self._client_combo.blockSignals(True)
        try:
            self._client_combo.clear()
            self._client_combo.addItem("（全部客戶）", userData=_ALL_CLIENTS)
            try:
                clients = self._container.clients.list_clients(limit=500)
            except Exception as err:
                self._container.system_log.warn(
                    "tasks_page: failed to load clients",
                    detail={"exc": type(err).__name__, "msg": str(err)},
                )
                clients = []
                self._client_combo.addItem(
                    "（載入客戶失敗）", userData=_ALL_CLIENTS
                )
            for c in clients:
                self._client_combo.addItem(c.client_name, userData=c.id)
            if selected is not None:
                idx = self._client_combo.findData(selected)
                if idx >= 0:
                    self._client_combo.setCurrentIndex(idx)
        finally:
            self._client_combo.blockSignals(False)

    def _reload_engagement_combo(self) -> None:
        selected = self._eng_combo.currentData()
        client_data = self._client_combo.currentData()
        self._eng_combo.blockSignals(True)
        try:
            self._eng_combo.clear()
            self._eng_combo.addItem("（全部案件）", userData=_ALL_ENGAGEMENTS)
            try:
                if client_data == _ALL_CLIENTS or client_data is None:
                    engs = self._container.engagements.list_all()
                else:
                    engs = self._container.engagements.list_by_client(int(client_data))
            except Exception as err:
                self._container.system_log.warn(
                    "tasks_page: failed to load engagements for combo",
                    detail={"exc": type(err).__name__, "msg": str(err)},
                )
                engs = []
                self._eng_combo.addItem(
                    "（載入案件失敗）", userData=_ALL_ENGAGEMENTS
                )
            for eng in engs:
                label = f"{eng.engagement_name} [{STATUS_LABELS.get(eng.tax_type, eng.tax_type)}]"
                self._eng_combo.addItem(label, userData=eng.id)
            if selected is not None:
                idx = self._eng_combo.findData(selected)
                if idx >= 0:
                    self._eng_combo.setCurrentIndex(idx)
        finally:
            self._eng_combo.blockSignals(False)

    def _on_client_changed(self) -> None:
        self._reload_engagement_combo()
        self._refresh()

    def _refresh(self) -> None:
        selected_task_ids = self._selected_task_ids()
        current_task_id = self._selected_task_id()
        try:
            if self._filter_key == FilterKey.DUE_TODAY:
                tasks = self._container.tasks.list_due_today(today_iso())
            elif self._filter_key == FilterKey.OVERDUE:
                tasks = self._container.tasks.list_overdue(today_iso())
            else:
                client_data = self._client_combo.currentData() or _ALL_CLIENTS
                eng_data = self._eng_combo.currentData() or _ALL_ENGAGEMENTS
                if eng_data != _ALL_ENGAGEMENTS:
                    tasks = self._container.tasks.list_by_engagement(int(eng_data))
                elif client_data != _ALL_CLIENTS:
                    tasks = self._container.tasks.list_by_client(int(client_data))
                else:
                    tasks = self._container.tasks.list_all()
            self._tasks = self._ordered_tasks_for_display(tasks)
            self._task_by_id = {task.id: task for task in self._tasks}
            load_error = False
        except Exception as err:
            self._container.system_log.warn(
                "tasks_page: failed to load tasks",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            self._tasks = []
            self._task_by_id = {}
            load_error = True

        sorting_enabled = self._table.isSortingEnabled()
        if sorting_enabled:
            self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._tasks))
        client_cache: dict[int, str] = {}
        eng_client_cache: dict[int, int | None] = {}
        for row_idx, task in enumerate(self._tasks):
            title = task.title
            if getattr(task, "parent_task_id", None) is not None:
                title = f"　└ {title}"
            values = {
                "id": str(task.id),
                "client_label": self._client_label_for_task(
                    task, client_cache, eng_client_cache
                ),
                "title": title,
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
        if sorting_enabled:
            self._table.setSortingEnabled(True)

        has_rows = bool(self._tasks) and not load_error
        self._error_label.setVisible(load_error)
        self._table.setVisible(has_rows)
        self._empty_state.setVisible(not load_error and not has_rows)
        self._select_task_ids(
            selected_task_ids,
            current_task_id=current_task_id,
        )

    def _ordered_tasks_for_display(self, tasks: list) -> list:
        by_parent: dict[int | None, list] = {}
        by_id: dict[int, object] = {}
        for task in tasks:
            by_id[task.id] = task
            by_parent.setdefault(getattr(task, "parent_task_id", None), []).append(task)

        ordered: list = []
        roots = [
            task for task in tasks
            if getattr(task, "parent_task_id", None) is None
            or getattr(task, "parent_task_id", None) not in by_id
        ]
        root_ids = {task.id for task in roots}
        for root in roots:
            ordered.append(root)
            ordered.extend(by_parent.get(root.id, []))
        for task in tasks:
            if task.id not in root_ids and task not in ordered:
                ordered.append(task)
        return ordered

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

    def _selected_task_ids(self) -> list[int]:
        selection = self._table.selectionModel()
        if selection is None:
            return []
        ids: list[int] = []
        for index in selection.selectedRows(_COLUMN_ORDER.index("id")):
            item = self._table.item(index.row(), _COLUMN_ORDER.index("id"))
            if item is None:
                continue
            try:
                ids.append(int(item.text()))
            except ValueError:
                continue
        return ids

    def _select_task_ids(
        self,
        task_ids: list[int],
        *,
        current_task_id: int | None = None,
    ) -> None:
        wanted = set(task_ids)
        selection = self._table.selectionModel()
        if selection is None:
            self._on_selection_changed()
            return
        signals_were_blocked = self._table.blockSignals(True)
        selection.clearSelection()
        first_row: int | None = None
        current_row: int | None = None
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COLUMN_ORDER.index("id"))
            if item is None:
                continue
            try:
                task_id = int(item.text())
            except ValueError:
                continue
            if task_id in wanted:
                index = self._table.model().index(
                    row, _COLUMN_ORDER.index("id")
                )
                selection.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                if first_row is None:
                    first_row = row
                if task_id == current_task_id:
                    current_row = row
        focus_row = current_row if current_row is not None else first_row
        if focus_row is not None:
            selection.setCurrentIndex(
                self._table.model().index(
                    focus_row, _COLUMN_ORDER.index("title")
                ),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self._table.blockSignals(signals_were_blocked)
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        selected_ids = self._selected_task_ids()
        single = len(selected_ids) == 1
        selected_task = self._task_by_id.get(selected_ids[0]) if single else None
        terminal = (
            selected_task is not None
            and selected_task.status in {"done", "cancelled"}
        )
        has_status_transition = (
            selected_task is not None
            and bool(allowed_task_status_transitions(selected_task.status))
        )
        self._complete_btn.setEnabled(single and not terminal)
        self._status_btn.setEnabled(
            single
            and has_status_transition
            and not self._status_change_in_progress
        )
        self._delete_btn.setEnabled(single)
        self._bulk_edit_btn.setEnabled(bool(selected_ids))
        self._bulk_delete_btn.setEnabled(bool(selected_ids))
        self._next_step_btn.setEnabled(single)
        self._make_child_btn.setEnabled(single)

    def _client_label_for_task(
        self,
        task,
        client_cache: dict[int, str],
        eng_client_cache: dict[int, int | None],
    ) -> str:
        """Resolve the client name shown directly in the list.

        Prefer the task's own ``client_id`` (backfilled in Slice 20B); fall back to
        the owning engagement's client. The caches keep this O(unique clients) per
        refresh rather than one query per row.
        """
        client_id = task.client_id
        if client_id is None and task.engagement_id is not None:
            if task.engagement_id in eng_client_cache:
                client_id = eng_client_cache[task.engagement_id]
            else:
                eng = self._container.engagements.get_engagement(task.engagement_id)
                client_id = eng.client_id if eng else None
                eng_client_cache[task.engagement_id] = client_id
        if client_id is None:
            return "（全域）"
        if client_id in client_cache:
            return client_cache[client_id]
        client = self._container.clients.get_client(client_id)
        name = client.client_name if client else "（未知客戶）"
        client_cache[client_id] = name
        return name

    # ------------------------------------------------------------------
    # Action handlers

    def _on_new_task(self) -> None:
        eng_data = self._eng_combo.currentData() or _ALL_ENGAGEMENTS
        client_data = self._client_combo.currentData() or _ALL_CLIENTS
        fixed_eng = int(eng_data) if eng_data != _ALL_ENGAGEMENTS else None
        preset_client = int(client_data) if client_data != _ALL_CLIENTS else None
        dlg = NewTaskDialog(
            self._container.tasks,
            engagement_id=fixed_eng,
            parent=self,
            engagements_service=self._container.engagements,
            clients_service=self._container.clients,
            preset_client_id=preset_client,
        )
        if dlg.exec() == NewTaskDialog.DialogCode.Accepted:
            self._refresh()

    def _on_bulk_new_tasks(self) -> None:
        try:
            dlg = BulkCreateTasksDialog(self._container.clients, self)
            if dlg.exec() != BulkCreateTasksDialog.DialogCode.Accepted:
                return
            created = self._container.tasks.create_tasks_bulk(
                dlg.selected_client_ids(),
                dlg.template(),
            )
        except TaskValidationError as err:
            QMessageBox.warning(self, "批量新增失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "批量新增失敗", error_message("task.create.failed"))
            return
        if not created:
            QMessageBox.information(self, "未建立待辦", "沒有建立任何待辦，請確認客戶仍存在。")
        self._refresh()
        self._select_task_ids([task.id for task in created])

    def _on_bulk_edit_tasks(self) -> None:
        task_ids = self._selected_task_ids()
        if not task_ids:
            return
        try:
            dlg = BulkEditTasksDialog(len(task_ids), self)
            if dlg.exec() != BulkEditTasksDialog.DialogCode.Accepted:
                return
            updated = self._container.tasks.update_tasks_bulk(task_ids, dlg.fields())
        except TaskValidationError as err:
            QMessageBox.warning(self, "批量編輯失敗", error_message(err.code))
            return
        except Exception as err:
            self._container.system_log.warn(
                "tasks_page: bulk edit failed",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            QMessageBox.warning(self, "批量編輯失敗", error_message("system.unexpected"))
            return
        if updated != len(task_ids):
            QMessageBox.information(
                self,
                "部分更新",
                f"已更新 {updated} 筆，略過 {len(task_ids) - updated} 筆不符合狀態規則的待辦。",
            )
        self._refresh()

    def _on_bulk_delete_tasks(self) -> None:
        task_ids = self._selected_task_ids()
        if not task_ids:
            return
        reply = QMessageBox.question(
            self,
            "批量刪除待辦",
            f"確定要刪除 {len(task_ids)} 筆待辦？父待辦若仍有子待辦會自動略過。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self._container.tasks.delete_tasks_bulk(task_ids)
        except Exception:
            QMessageBox.warning(self, "批量刪除失敗", error_message("task.delete.failed"))
            return
        if deleted != len(task_ids):
            QMessageBox.information(
                self,
                "部分刪除",
                f"已刪除 {deleted} 筆，略過 {len(task_ids) - deleted} 筆。",
            )
        self._refresh()

    def _on_make_child_task(self) -> None:
        selected_ids = self._selected_task_ids()
        if not selected_ids:
            return
        child_id = selected_ids[0]
        candidates = [
            task for task in self._tasks
            if task.id != child_id and getattr(task, "parent_task_id", None) is None
        ]
        if not candidates:
            QMessageBox.information(self, "無可用父待辦", "目前沒有可作為父層的待辦。")
            return
        try:
            dlg = ParentTaskDialog(candidates, self)
            if dlg.exec() != ParentTaskDialog.DialogCode.Accepted:
                return
            parent_id = dlg.selected_parent_id()
            if parent_id is None:
                return
            self._container.tasks.convert_to_child(child_id, parent_id)
        except TaskValidationError as err:
            QMessageBox.warning(self, "設定失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "設定失敗", error_message("system.unexpected"))
            return
        self._refresh()

    def _on_create_next_step_task(self) -> None:
        parent_id = self._selected_task_id()
        if parent_id is None:
            return
        parent = self._container.tasks.get_task(parent_id)
        if parent is None:
            QMessageBox.warning(self, "新增下一步失敗", error_message("task.not_found"))
            self._refresh()
            return
        default_title = parent.next_step or ""
        title, ok = QInputDialog.getText(
            self,
            "新增下一步",
            "下一步待辦標題：",
            text=default_title,
        )
        if not ok:
            return
        try:
            self._container.tasks.create_child_task(parent_id, title)
        except TaskValidationError as err:
            QMessageBox.warning(self, "新增下一步失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "新增下一步失敗", error_message("system.unexpected"))
            return
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
        if self._status_change_in_progress:
            return
        task_id = self._selected_task_id()
        if task_id is None:
            return
        task = self._task_by_id.get(task_id)
        if task is None:
            return
        allowed_statuses = allowed_task_status_transitions(task.status)
        if not allowed_statuses:
            return
        label_to_value = {
            STATUS_LABELS.get(status, status): status
            for status in allowed_statuses
        }
        choices = sorted(label_to_value)
        label, ok = QInputDialog.getItem(
            self, "切換狀態", "請選擇新狀態：", choices, current=0, editable=False
        )
        if not ok or not label:
            return
        target = label_to_value.get(label)
        if target is None or target == task.status:
            return
        self._status_change_in_progress = True
        self._status_btn.setEnabled(False)
        try:
            self._container.tasks.set_status(task_id, target)
        except TaskValidationError as err:
            QMessageBox.warning(self, "切換失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "切換失敗", error_message("system.unexpected"))
            return
        finally:
            self._status_change_in_progress = False
            self._on_selection_changed()
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
