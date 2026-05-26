"""Dialogs for bulk task operations and parent assignment."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n.status_labels import PRIORITY_LABELS, STATUS_LABELS
from ...services.tasks import BulkTaskTemplate
from ..widgets.date_field import DateField


class BulkCreateTasksDialog(QDialog):
    def __init__(self, clients_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量新增待辦")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel("選擇客戶後，會為每個客戶建立一筆相同內容的待辦。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._clients = QListWidget()
        self._clients.setMinimumHeight(180)
        for client in clients_service.list_clients(limit=1000):
            item = QListWidgetItem(client.client_name)
            item.setData(Qt.ItemDataRole.UserRole, client.id)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._clients.addItem(item)
        layout.addWidget(self._clients)

        form = QFormLayout()
        self._title = QLineEdit()
        self._assignee = QLineEdit()
        self._priority = QComboBox()
        for value in ("normal", "low", "high", "urgent"):
            self._priority.addItem(PRIORITY_LABELS.get(value, value), value)
        self._due_date = DateField(required=False)
        self._next_step = QLineEdit()
        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(90)
        form.addRow("標題：", self._title)
        form.addRow("負責人：", self._assignee)
        form.addRow("優先級：", self._priority)
        form.addRow("到期日：", self._due_date)
        form.addRow("下一步：", self._next_step)
        form.addRow("備註：", self._notes)
        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def selected_client_ids(self) -> list[int]:
        ids: list[int] = []
        for row in range(self._clients.count()):
            item = self._clients.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def template(self) -> BulkTaskTemplate:
        return BulkTaskTemplate(
            title=self._title.text(),
            assignee=self._assignee.text(),
            due_date=self._due_date.validated_value(),
            priority=str(self._priority.currentData()),
            next_step=self._next_step.text(),
            notes=self._notes.toPlainText(),
        )

    def accept(self) -> None:
        if not self.selected_client_ids():
            QMessageBox.warning(self, "資料不足", "請至少選擇一位客戶")
            return
        if not self._title.text().strip():
            QMessageBox.warning(self, "資料不足", "請輸入待辦標題")
            return
        try:
            self._due_date.validated_value()
        except DateField.InvalidInput:
            QMessageBox.warning(self, "日期錯誤", "請輸入有效的到期日")
            return
        super().accept()


class BulkEditTasksDialog(QDialog):
    def __init__(self, task_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量編輯待辦")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"將套用到 {task_count} 筆待辦。只會更新已勾選欄位。"))

        form = QFormLayout()
        self._status_enabled, self._status = self._combo_row(
            [("todo", STATUS_LABELS.get("todo", "todo")),
             ("doing", STATUS_LABELS.get("doing", "doing")),
             ("waiting_client", STATUS_LABELS.get("waiting_client", "waiting_client")),
             ("waiting_internal_review", STATUS_LABELS.get("waiting_internal_review", "waiting_internal_review")),
             ("done", STATUS_LABELS.get("done", "done")),
             ("cancelled", STATUS_LABELS.get("cancelled", "cancelled"))]
        )
        self._priority_enabled, self._priority = self._combo_row(
            [(v, PRIORITY_LABELS.get(v, v)) for v in ("normal", "low", "high", "urgent")]
        )
        self._assignee_enabled, self._assignee = self._line_row()
        self._due_enabled = QCheckBox("更新")
        self._due_date = DateField(required=False)
        due_row = QHBoxLayout()
        due_row.addWidget(self._due_enabled)
        due_row.addWidget(self._due_date)
        due_box = QWidget()
        due_box.setLayout(due_row)
        self._next_enabled, self._next_step = self._line_row()
        self._notes_enabled = QCheckBox("更新")
        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(90)
        notes_row = QHBoxLayout()
        notes_row.addWidget(self._notes_enabled)
        notes_row.addWidget(self._notes)
        notes_box = QWidget()
        notes_box.setLayout(notes_row)

        form.addRow("狀態：", self._status_enabled.parentWidget())
        form.addRow("優先級：", self._priority_enabled.parentWidget())
        form.addRow("負責人：", self._assignee_enabled.parentWidget())
        form.addRow("到期日：", due_box)
        form.addRow("下一步：", self._next_enabled.parentWidget())
        form.addRow("備註：", notes_box)
        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _line_row(self) -> tuple[QCheckBox, QLineEdit]:
        checkbox = QCheckBox("更新")
        field = QLineEdit()
        row = QHBoxLayout()
        row.addWidget(checkbox)
        row.addWidget(field)
        box = QWidget()
        box.setLayout(row)
        return checkbox, field

    def _combo_row(self, values: list[tuple[str, str]]) -> tuple[QCheckBox, QComboBox]:
        checkbox = QCheckBox("更新")
        combo = QComboBox()
        for value, label in values:
            combo.addItem(label, value)
        row = QHBoxLayout()
        row.addWidget(checkbox)
        row.addWidget(combo)
        box = QWidget()
        box.setLayout(row)
        return checkbox, combo

    def fields(self) -> dict:
        fields: dict = {}
        if self._status_enabled.isChecked():
            fields["status"] = self._status.currentData()
        if self._priority_enabled.isChecked():
            fields["priority"] = self._priority.currentData()
        if self._assignee_enabled.isChecked():
            fields["assignee"] = self._assignee.text()
        if self._due_enabled.isChecked():
            fields["due_date"] = self._due_date.validated_value()
        if self._next_enabled.isChecked():
            fields["next_step"] = self._next_step.text()
        if self._notes_enabled.isChecked():
            fields["notes"] = self._notes.toPlainText()
        return fields

    def accept(self) -> None:
        try:
            fields = self.fields()
        except DateField.InvalidInput:
            QMessageBox.warning(self, "日期錯誤", "請輸入有效的到期日")
            return
        if not fields:
            QMessageBox.warning(self, "資料不足", "請至少勾選一個要更新的欄位")
            return
        super().accept()


class ParentTaskDialog(QDialog):
    def __init__(self, candidates, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("選擇父待辦")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("請選擇要作為父層的待辦。"))
        self._list = QListWidget()
        for task in candidates:
            item = QListWidgetItem(f"#{task.id} {task.title}")
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            self._list.addItem(item)
        layout.addWidget(self._list)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def selected_parent_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def accept(self) -> None:
        if self.selected_parent_id() is None:
            QMessageBox.warning(self, "資料不足", "請選擇父待辦")
            return
        super().accept()
