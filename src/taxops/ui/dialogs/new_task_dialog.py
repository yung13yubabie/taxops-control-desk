"""New task dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...i18n.status_labels import PRIORITY_LABELS
from ...services.tasks import CreateTaskInput, TaskValidationError, TasksService

_PRIORITY_CHOICES = [
    ("urgent", PRIORITY_LABELS["urgent"]),
    ("high", PRIORITY_LABELS["high"]),
    ("normal", PRIORITY_LABELS["normal"]),
    ("low", PRIORITY_LABELS["low"]),
]


class NewTaskDialog(QDialog):
    def __init__(
        self,
        tasks_service: TasksService,
        engagement_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = tasks_service
        self._engagement_id = engagement_id

        self.setWindowTitle("新增待辦")
        self.setModal(True)
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._title = QLineEdit()
        self._title.setMaxLength(200)
        self._title.setPlaceholderText("必填")

        self._assignee = QLineEdit()
        self._assignee.setMaxLength(100)

        self._due_date = QDateEdit()
        self._due_date.setCalendarPopup(True)
        self._due_date.setSpecialValueText("（不設定）")
        self._due_date.setDate(self._due_date.minimumDate())

        self._priority = QComboBox()
        for value, label in _PRIORITY_CHOICES:
            self._priority.addItem(label, userData=value)
        self._priority.setCurrentIndex(
            max(0, self._priority.findData("normal"))
        )

        self._next_step = QLineEdit()
        self._next_step.setMaxLength(500)
        self._next_step.setPlaceholderText("選填，下一步行動說明")

        self._notes = QTextEdit()
        self._notes.setFixedHeight(68)

        form.addRow(QLabel("標題 *"), self._title)
        form.addRow(QLabel("負責人"), self._assignee)
        form.addRow(QLabel("到期日"), self._due_date)
        form.addRow(QLabel("優先級"), self._priority)
        form.addRow(QLabel("下一步"), self._next_step)
        form.addRow(QLabel("備註"), self._notes)
        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton("新增待辦", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)

    def on_save(self) -> None:
        due = self._due_date.date()
        is_set = due != self._due_date.minimumDate()
        due_str = due.toString("yyyy-MM-dd") if is_set else None

        payload = CreateTaskInput(
            engagement_id=self._engagement_id,
            title=self._title.text(),
            assignee=self._assignee.text() or None,
            due_date=due_str,
            priority=self._priority.currentData(),
            next_step=self._next_step.text() or None,
            notes=self._notes.toPlainText() or None,
        )
        try:
            self._svc.create_task(payload)
        except TaskValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            if err.code == "task.title.required":
                self._title.setFocus()
            return
        except Exception:
            QMessageBox.warning(self, "新增失敗", error_message("task.create.failed"))
            return
        self.accept()
