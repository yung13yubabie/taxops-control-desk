"""Annual-work task panel backed by the shared workflow task store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.tasks import TaskRow
from ...services.container import ServiceContainer
from ...services.tasks import allowed_task_status_transitions

_PAGE_SIZE = 50
_PRIORITIES = (
    ("低", "low"),
    ("一般", "normal"),
    ("高", "high"),
    ("緊急", "urgent"),
)
_STATUS_LABELS = {
    "todo": "待處理",
    "doing": "處理中",
    "waiting_client": "等客戶",
    "waiting_internal_review": "等內部覆核",
    "done": "已完成",
    "cancelled": "已取消",
}
_PRIORITY_LABELS = {value: label for label, value in _PRIORITIES}


@dataclass(frozen=True)
class TaskMutationEvidence:
    operation: str
    row_before: TaskRow | None
    row_after: TaskRow | None
    count_before: int


class AnnualTaskPanel(QWidget):
    """Bounded annual-specific tasks with post-commit readback recovery."""

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
        self._rows: tuple[TaskRow, ...] = ()
        self._pending_mutation: TaskMutationEvidence | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        scope = QLabel(
            "年度工作待辦｜只列出綁定此年度工作明細的待辦；一般案件待辦不會混入。"
        )
        scope.setWordWrap(True)
        scope.setStyleSheet("font-size: 14px; color: #334155;")
        layout.addWidget(scope)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self.title_input = QLineEdit()
        self.title_input.setMaxLength(200)
        self.title_input.setPlaceholderText("例如：完成 115 年度營所稅申報")
        self.assignee_input = QLineEdit()
        self.assignee_input.setMaxLength(100)
        self.due_date_input = QLineEdit()
        self.due_date_input.setMaxLength(20)
        self.due_date_input.setPlaceholderText("YYYY-MM-DD")
        self.priority_combo = QComboBox()
        for label, value in _PRIORITIES:
            self.priority_combo.addItem(label, value)
        self.priority_combo.setCurrentIndex(
            self.priority_combo.findData("normal")
        )
        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(72)
        self.notes_input.setPlaceholderText("可保留換行的處理說明")
        form.addRow("待辦名稱：", self.title_input)
        compact = QHBoxLayout()
        compact.addWidget(QLabel("承辦："))
        compact.addWidget(self.assignee_input, 1)
        compact.addWidget(QLabel("期限："))
        compact.addWidget(self.due_date_input)
        compact.addWidget(QLabel("優先："))
        compact.addWidget(self.priority_combo)
        form.addRow("", compact)
        form.addRow("備註：", self.notes_input)
        layout.addWidget(form_widget)

        action_row = QHBoxLayout()
        self.create_button = QPushButton("建立年度待辦")
        self.complete_button = QPushButton("完成年度待辦")
        self.status_combo = QComboBox()
        self.status_button = QPushButton("更新待辦狀態")
        self.delete_button = QPushButton("刪除年度待辦")
        self.retry_button = QPushButton("重新核對待辦")
        self.retry_button.hide()
        action_row.addWidget(self.create_button)
        action_row.addStretch(1)
        action_row.addWidget(self.status_combo)
        action_row.addWidget(self.status_button)
        action_row.addWidget(self.complete_button)
        action_row.addWidget(self.delete_button)
        action_row.addWidget(self.retry_button)
        layout.addLayout(action_row)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("編號", "待辦", "狀態", "優先", "承辦", "期限", "最後更新")
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
        self.previous_button = QPushButton("待辦上一頁")
        self.next_button = QPushButton("待辦下一頁")
        page_row.addWidget(self.page_label)
        page_row.addStretch(1)
        page_row.addWidget(self.previous_button)
        page_row.addWidget(self.next_button)
        layout.addLayout(page_row)

        self.create_button.clicked.connect(self._create)
        self.complete_button.clicked.connect(self._complete)
        self.status_button.clicked.connect(self._set_status)
        self.delete_button.clicked.connect(self._delete)
        self.retry_button.clicked.connect(self.retry_pending_verification)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self._render()

    @property
    def pending_mutation_evidence(self) -> TaskMutationEvidence | None:
        return self._pending_mutation

    def set_context(self, engagement_id: int | None) -> bool:
        self._engagement_id = engagement_id
        self._page = 0
        self.setEnabled(engagement_id is not None)
        if engagement_id is None:
            self._total = 0
            self._rows = ()
            self.feedback_label.setText("請先建立或連結正式案件，再建立年度待辦。")
            self._render()
            return True
        return self.reload()

    def task_ids(self) -> tuple[int, ...]:
        return tuple(row.id for row in self._rows)

    def selected_task_id(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        item = self.table.item(indexes[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if type(value) is int else None

    def row_for_task_id(self, task_id: int) -> TaskRow | None:
        return next((row for row in self._rows if row.id == task_id), None)

    def _selected_row(self) -> TaskRow | None:
        selected_id = self.selected_task_id()
        return self.row_for_task_id(selected_id) if selected_id is not None else None

    def reload(self) -> bool:
        try:
            total = self._container.tasks.count_by_annual_work_item(self.item_id)
            last_page = max(0, (total - 1) // _PAGE_SIZE)
            self._page = min(self._page, last_page)
            rows = tuple(
                self._container.tasks.list_by_annual_work_item(
                    self.item_id,
                    order_by="updated_at",
                    order_dir="DESC",
                    limit=_PAGE_SIZE,
                    offset=self._page * _PAGE_SIZE,
                )
            )
        except Exception as exc:
            self._read_failed(exc, committed=self._pending_mutation is not None)
            return False
        self._total = total
        self._rows = rows
        self._render()
        return True

    def _verify_pending(self, evidence: TaskMutationEvidence) -> None:
        expected_count = evidence.count_before + (
            1 if evidence.operation == "create" else -1 if evidence.operation == "delete" else 0
        )
        if (
            self._container.tasks.count_by_annual_work_item(self.item_id)
            != expected_count
        ):
            raise RuntimeError("task readback count mismatch")
        target = evidence.row_after or evidence.row_before
        if target is None:
            raise RuntimeError("task evidence missing")
        stored = self._container.tasks.get_task(target.id)
        if evidence.operation == "delete":
            if stored is not None:
                raise RuntimeError("task delete readback mismatch")
        elif stored != evidence.row_after:
            raise RuntimeError("task row readback mismatch")

    def _finish_mutation(self, evidence: TaskMutationEvidence) -> bool:
        self._pending_mutation = evidence
        self._commit_observer()
        try:
            self._verify_pending(evidence)
            self._page = 0
            if not self.reload():
                raise RuntimeError("task page readback failed")
            target = evidence.row_after or evidence.row_before
            if evidence.operation != "delete" and target is not None:
                self._select_id(target.id)
        except Exception as exc:
            self._read_failed(exc, committed=True)
            return False
        self._pending_mutation = None
        self.retry_button.hide()
        self._restore_buttons()
        messages = {
            "create": "待辦已建立並完成資料核對。",
            "complete": "待辦已完成並完成資料核對。",
            "status": "待辦狀態已更新並完成資料核對。",
            "delete": "待辦已刪除並完成資料核對。",
        }
        self.feedback_label.setText(messages[evidence.operation])
        if evidence.operation == "create":
            self._clear_form()
        return True

    def retry_pending_verification(self) -> bool:
        evidence = self._pending_mutation
        if evidence is None:
            succeeded = self.reload()
            if succeeded:
                self.retry_button.hide()
                self._restore_buttons()
                self.feedback_label.setText("待辦已重新讀取。")
            return succeeded
        try:
            self._verify_pending(evidence)
            self._page = 0
            if not self.reload():
                raise RuntimeError("task page readback failed")
            target = evidence.row_after or evidence.row_before
            if evidence.operation != "delete" and target is not None:
                self._select_id(target.id)
        except Exception as exc:
            self._read_failed(exc, committed=True)
            return False
        self._pending_mutation = None
        self.retry_button.hide()
        self._restore_buttons()
        if evidence.operation == "create":
            self._clear_form()
        self.feedback_label.setText("待辦異動已重新核對，未重複送出。")
        return True

    def _create(self) -> None:
        if self._pending_mutation is not None or self._engagement_id is None:
            return
        try:
            count_before = self._container.tasks.count_by_annual_work_item(
                self.item_id
            )
            row = self._container.annual_work.create_linked_task(
                self.item_id,
                title=self.title_input.text(),
                assignee=self.assignee_input.text() or None,
                due_date=self.due_date_input.text() or None,
                priority=self.priority_combo.currentData(),
                notes=self.notes_input.toPlainText() or None,
            )
        except Exception as exc:
            self._mutation_failed(exc, "建立年度待辦失敗，資料未變更。")
            return
        self._finish_mutation(
            TaskMutationEvidence("create", None, row, count_before)
        )

    def _complete(self) -> None:
        selected = self._selected_row()
        if selected is None or self._pending_mutation is not None:
            return
        try:
            count_before = self._container.tasks.count_by_annual_work_item(
                self.item_id
            )
            row = self._container.tasks.complete_task(selected.id)
        except Exception as exc:
            self._mutation_failed(exc, "完成年度待辦失敗，資料未變更。")
            return
        self._finish_mutation(
            TaskMutationEvidence("complete", selected, row, count_before)
        )

    def _set_status(self) -> None:
        selected = self._selected_row()
        status = self.status_combo.currentData()
        if (
            selected is None
            or self._pending_mutation is not None
            or type(status) is not str
        ):
            return
        try:
            count_before = self._container.tasks.count_by_annual_work_item(
                self.item_id
            )
            row = self._container.tasks.set_status(selected.id, status)
        except Exception as exc:
            self._mutation_failed(exc, "更新待辦狀態失敗，資料未變更。")
            return
        self._finish_mutation(
            TaskMutationEvidence("status", selected, row, count_before)
        )

    def _delete(self) -> None:
        selected = self._selected_row()
        if selected is None or self._pending_mutation is not None:
            return
        try:
            count_before = self._container.tasks.count_by_annual_work_item(
                self.item_id
            )
            self._container.tasks.delete_task(selected.id)
        except Exception as exc:
            self._mutation_failed(exc, "刪除年度待辦失敗，資料未變更。")
            return
        self._finish_mutation(
            TaskMutationEvidence("delete", selected, None, count_before)
        )

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
                row_data.title,
                _STATUS_LABELS.get(row_data.status, row_data.status),
                _PRIORITY_LABELS.get(row_data.priority, row_data.priority),
                row_data.assignee or "—",
                row_data.due_date or "—",
                row_data.updated_at,
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

    def _selection_changed(self) -> None:
        self.status_combo.clear()
        selected = self._selected_row()
        if selected is not None:
            for status in sorted(allowed_task_status_transitions(selected.status)):
                self.status_combo.addItem(
                    _STATUS_LABELS.get(status, status), status
                )
        self._restore_buttons()

    def _select_id(self, task_id: int) -> bool:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole) == task_id
            ):
                self.table.selectRow(row)
                return True
        return False

    def _restore_buttons(self) -> None:
        locked = self._pending_mutation is not None
        has_context = self._engagement_id is not None
        selected = self._selected_row()
        transitions = (
            allowed_task_status_transitions(selected.status)
            if selected is not None
            else frozenset()
        )
        self.create_button.setEnabled(has_context and not locked)
        self.complete_button.setEnabled(
            selected is not None
            and selected.status not in {"done", "cancelled"}
            and not locked
        )
        self.status_combo.setEnabled(bool(transitions) and not locked)
        self.status_button.setEnabled(bool(transitions) and not locked)
        self.delete_button.setEnabled(selected is not None and not locked)

    def _read_failed(self, exc: BaseException, *, committed: bool) -> None:
        self.feedback_label.setText(
            (
                "資料可能已寫入，請勿重送。待辦核對失敗，請按「重新核對待辦」。"
                if committed
                else f"待辦讀取失敗：{self._message(exc)}"
            )
        )
        self.retry_button.show()
        self._restore_buttons()

    def _mutation_failed(self, exc: BaseException, prefix: str) -> None:
        self.feedback_label.setText(f"{prefix} {self._message(exc)}")

    def _clear_form(self) -> None:
        self.title_input.clear()
        self.assignee_input.clear()
        self.due_date_input.clear()
        self.priority_combo.setCurrentIndex(
            self.priority_combo.findData("normal")
        )
        self.notes_input.clear()

    @staticmethod
    def _message(exc: BaseException) -> str:
        code = getattr(exc, "code", "system.unexpected")
        return error_message(code if isinstance(code, str) else "system.unexpected")
