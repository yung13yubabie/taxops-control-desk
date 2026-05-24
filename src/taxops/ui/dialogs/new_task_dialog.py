"""New task dialog with client + engagement cascade."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt

_log = logging.getLogger(__name__)
from PySide6.QtWidgets import (
    QComboBox,
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
from ...services.clients import ClientsService
from ...services.engagements import EngagementsService
from ...services.tasks import CreateTaskInput, TaskValidationError, TasksService
from ..widgets.date_field import DateField

_NO_CLIENT = -1
_NO_ENGAGEMENT = -1

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
        engagement_id: int | None = None,
        parent: QWidget | None = None,
        engagements_service: EngagementsService | None = None,
        clients_service: ClientsService | None = None,
        preset_client_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = tasks_service
        self._engagements_service = engagements_service
        self._clients_service = clients_service
        self._fixed_engagement_id = engagement_id

        self.setWindowTitle("新增待辦")
        self.setModal(True)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._client_combo: QComboBox | None = None
        self._eng_combo: QComboBox | None = None

        if engagement_id is None:
            # Cascade mode: client picker + dependent engagement picker.
            self._client_combo = QComboBox()
            self._client_combo.addItem("（不指定客戶）", userData=_NO_CLIENT)
            if clients_service is not None:
                try:
                    for c in clients_service.list_clients(limit=500):
                        self._client_combo.addItem(c.client_name, userData=c.id)
                except Exception:
                    _log.warning(
                        "new_task_dialog: failed to load clients", exc_info=True
                    )
            form.addRow(QLabel("關聯客戶"), self._client_combo)

            self._eng_combo = QComboBox()
            form.addRow(QLabel("關聯案件"), self._eng_combo)

            self._client_combo.currentIndexChanged.connect(self._on_client_changed)
            if preset_client_id is not None:
                idx = self._client_combo.findData(preset_client_id)
                if idx >= 0:
                    self._client_combo.setCurrentIndex(idx)
                else:
                    self._reload_engagement_combo()
            else:
                self._reload_engagement_combo()
        # else: fixed engagement mode — both combos omitted; engagement_id locked.

        self._title = QLineEdit()
        self._title.setMaxLength(200)
        self._title.setPlaceholderText("必填")

        self._assignee = QLineEdit()
        self._assignee.setMaxLength(100)

        self._due_date = DateField(required=False)

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

    def _on_client_changed(self) -> None:
        self._reload_engagement_combo()

    def _reload_engagement_combo(self) -> None:
        if self._eng_combo is None:
            return
        previous = self._eng_combo.currentData()
        self._eng_combo.blockSignals(True)
        try:
            self._eng_combo.clear()
            self._eng_combo.addItem("（不綁案件）", userData=_NO_ENGAGEMENT)
            if self._engagements_service is None:
                return
            client_data = (
                self._client_combo.currentData() if self._client_combo else None
            )
            try:
                if client_data is None or client_data == _NO_CLIENT:
                    engs = self._engagements_service.list_all()
                else:
                    engs = self._engagements_service.list_by_client(int(client_data))
            except Exception:
                _log.warning(
                    "new_task_dialog: failed to load engagements", exc_info=True
                )
                engs = []
            for eng in engs:
                self._eng_combo.addItem(eng.engagement_name, userData=eng.id)
            if previous is not None:
                idx = self._eng_combo.findData(previous)
                if idx >= 0:
                    self._eng_combo.setCurrentIndex(idx)
        finally:
            self._eng_combo.blockSignals(False)

    def on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            due_date = self._due_date.validated_value()
        except DateField.InvalidInput:
            self._save_btn.setEnabled(True)
            return

        if self._fixed_engagement_id is not None:
            eng_id: int | None = self._fixed_engagement_id
            client_id: int | None = None
        else:
            eng_data = self._eng_combo.currentData() if self._eng_combo else _NO_ENGAGEMENT
            client_data = (
                self._client_combo.currentData() if self._client_combo else _NO_CLIENT
            )
            eng_id = None if eng_data in (_NO_ENGAGEMENT, None) else int(eng_data)
            client_id = None if client_data in (_NO_CLIENT, None) else int(client_data)
        try:
            payload = CreateTaskInput(
                engagement_id=eng_id,
                client_id=client_id,
                title=self._title.text(),
                assignee=self._assignee.text() or None,
                due_date=due_date,
                priority=self._priority.currentData(),
                next_step=self._next_step.text() or None,
                notes=self._notes.toPlainText() or None,
            )
            self._svc.create_task(payload)
        except TaskValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            if err.code == "task.title.required":
                self._title.setFocus()
            self._save_btn.setEnabled(True)
            return
        except Exception:
            QMessageBox.warning(self, "新增失敗", error_message("task.create.failed"))
            self._save_btn.setEnabled(True)
            return
        self.accept()
