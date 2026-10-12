"""Dialogs for bulk task operations and parent assignment."""

from __future__ import annotations

from ...i18n.status_labels import label_for

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
    QScrollArea,
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

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
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
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._title = QLineEdit()
        self._title.setMaxLength(200)
        self._title.setPlaceholderText("必填，例如：確認本期進項憑證")
        self._assignee = QLineEdit()
        self._assignee.setPlaceholderText("選填，例如：王小明；留空表示尚未指派")
        self._priority = QComboBox()
        for value in ("normal", "low", "high", "urgent"):
            self._priority.addItem(label_for(PRIORITY_LABELS, value), value)
        self._due_date = DateField(required=False)
        self._next_step = QLineEdit()
        self._next_step.setPlaceholderText("選填，例如：聯絡客戶補件")
        self._notes = QPlainTextEdit()
        self._notes.setTabChangesFocus(True)
        self._notes.setMaximumHeight(90)
        self._notes.setPlaceholderText("選填，補充處理背景或注意事項")
        form.addRow("標題（必填）：", self._title)
        form.addRow("負責人：", self._assignee)
        form.addRow("優先級：", self._priority)
        form.addRow("到期日：", self._due_date)
        form.addRow("下一步：", self._next_step)
        form.addRow("備註：", self._notes)
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
            field = form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
            label.setBuddy(field._edit if isinstance(field, DateField) else field)
            field.setAccessibleName(label.text())
        self._due_date._edit.setAccessibleName("到期日，選填，西元年月日")
        self._due_date.setToolTip("選填，西元年-月-日，例如：2026-10-31；留空表示無到期日")
        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        _ok.setDefault(True)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)
        self.resize(560, 520)

        for a, b in [
            (self._clients, self._title),
            (self._title, self._assignee),
            (self._assignee, self._priority),
            (self._priority, self._due_date._edit),
            (self._due_date._edit, self._due_date._clear_btn),
            (self._due_date._clear_btn, self._due_date._cal_btn),
            (self._due_date._cal_btn, self._next_step),
            (self._next_step, self._notes),
            (self._notes, _ok),
        ]:
            self.setTabOrder(a, b)

        self._initial_input = self._input_snapshot()

    def _input_snapshot(self) -> tuple:
        return (tuple(self.selected_client_ids()), self._title.text(), self._assignee.text(),
                self._priority.currentData(), self._due_date.raw_text(), self._next_step.text(), self._notes.toPlainText())

    def reject(self) -> None:
        if self._input_snapshot() != self._initial_input:
            answer = QMessageBox.question(self, "放棄未儲存內容？", "批量待辦尚未儲存。要放棄本次輸入嗎？", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                return
        super().reject()

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
        self._row_widgets: list[QWidget] = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        layout.addWidget(QLabel(f"將套用到 {task_count} 筆待辦。只會更新已勾選欄位。"))

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._status_enabled, self._status = self._combo_row(
            [("todo", label_for(STATUS_LABELS, "todo")),
             ("doing", label_for(STATUS_LABELS, "doing")),
             ("waiting_client", label_for(STATUS_LABELS, "waiting_client")),
             ("waiting_internal_review", label_for(STATUS_LABELS, "waiting_internal_review")),
             ("done", label_for(STATUS_LABELS, "done")),
             ("cancelled", label_for(STATUS_LABELS, "cancelled"))]
        )
        self._priority_enabled, self._priority = self._combo_row(
            [(v, label_for(PRIORITY_LABELS, v)) for v in ("normal", "low", "high", "urgent")]
        )
        self._assignee_enabled, self._assignee = self._line_row()
        self._assignee.setPlaceholderText("例如：王小明；勾選更新後留空會清除")
        self._due_enabled = QCheckBox("更新")
        self._due_date = DateField(required=False)
        due_row = QHBoxLayout()
        due_row.addWidget(self._due_enabled)
        due_row.addWidget(self._due_date)
        due_box = QWidget()
        due_box.setLayout(due_row)
        self._next_enabled, self._next_step = self._line_row()
        self._next_step.setPlaceholderText("例如：聯絡客戶；勾選更新後留空會清除")
        self._notes_enabled = QCheckBox("更新")
        self._notes = QPlainTextEdit()
        self._notes.setTabChangesFocus(True)
        self._notes.setMaximumHeight(90)
        self._notes.setPlaceholderText("選填，補充處理背景或注意事項")
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
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
            field = form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
            label.setBuddy(field._edit if isinstance(field, DateField) else field)
            field.setAccessibleName(label.text())
        self._due_date._edit.setAccessibleName("到期日，選填，西元年月日")
        self._due_date.setToolTip("選填，西元年-月-日，例如：2026-10-31；留空表示無到期日")
        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        _ok.setDefault(True)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)
        self.resize(560, 520)

        for a, b in [
            (self._status, self._priority),
            (self._priority, self._assignee),
            (self._assignee, self._next_step),
            (self._next_step, self._notes),
            (self._notes, _ok),
        ]:
            self.setTabOrder(a, b)

        self._initial_input = self._input_snapshot()

    def _input_snapshot(self) -> tuple:
        return (self._status_enabled.isChecked(), self._status.currentData(), self._priority_enabled.isChecked(), self._priority.currentData(),
                self._assignee_enabled.isChecked(), self._assignee.text(), self._due_enabled.isChecked(), self._due_date.raw_text(),
                self._next_enabled.isChecked(), self._next_step.text(), self._notes_enabled.isChecked(), self._notes.toPlainText())

    def reject(self) -> None:
        if self._input_snapshot() != self._initial_input:
            answer = QMessageBox.question(self, "放棄未儲存內容？", "批量修改尚未套用。要放棄本次輸入嗎？", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                return
        super().reject()

    def _line_row(self) -> tuple[QCheckBox, QLineEdit]:
        checkbox = QCheckBox("更新")
        field = QLineEdit()
        row = QHBoxLayout()
        row.addWidget(checkbox)
        row.addWidget(field)
        box = QWidget()
        box.setLayout(row)
        self._row_widgets.append(box)
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
        self._row_widgets.append(box)
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

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
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
        _ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        _ok.setDefault(True)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)
        self.resize(560, 520)

        self.setTabOrder(self._list, _ok)

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
