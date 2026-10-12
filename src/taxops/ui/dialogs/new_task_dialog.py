"""New task dialog with client + engagement cascade."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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

_log = logging.getLogger(__name__)

_NO_CLIENT = -1
_NO_ENGAGEMENT = -1
_MAX_CONTEXT_ROWS = 10000

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
        self._clients_failed = False
        self._engagements_failed = False
        self._context_limit_hit = False
        self._retry_ids = None
        self._context_missing = False

        self.setWindowTitle("新增待辦")
        self.setModal(True)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        self._load_error = QLabel()
        self._load_error.setWordWrap(True)
        outer.addWidget(self._load_error)
        self._retry_btn = QPushButton("重新載入客戶與案件")
        self._retry_btn.clicked.connect(self._retry_context)
        outer.addWidget(self._retry_btn)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._client_combo: QComboBox | None = None
        self._eng_combo: QComboBox | None = None

        if engagement_id is None:
            # Cascade mode: client picker + dependent engagement picker.
            self._client_combo = QComboBox()
            self._client_combo.addItem("（不指定客戶）", userData=_NO_CLIENT)
            self._configure_combo(self._client_combo)
            self._load_clients()
            form.addRow(QLabel("關聯客戶"), self._client_combo)

            self._eng_combo = QComboBox()
            self._configure_combo(self._eng_combo)
            form.addRow(QLabel("關聯案件"), self._eng_combo)

            self._client_combo.currentIndexChanged.connect(self._on_client_changed)
            if preset_client_id is not None:
                idx = self._client_combo.findData(preset_client_id)
                if idx >= 0:
                    self._client_combo.setCurrentIndex(idx)
                else:
                    self._reload_engagement_combo()
                    self._clients_failed = True
                    self._context_missing = True
                    self._retry_ids = (preset_client_id, None)
            else:
                self._reload_engagement_combo()
        # else: fixed engagement mode — both combos omitted; engagement_id locked.

        self._title = QLineEdit()
        self._title.setMaxLength(200)
        self._title.setPlaceholderText("必填，例如：確認本期進項憑證")

        self._assignee = QLineEdit()
        self._assignee.setMaxLength(100)
        self._assignee.setPlaceholderText("選填，例如：王小明；留空表示尚未指派")

        self._due_date = DateField(required=False)

        self._priority = QComboBox()
        for value, label in _PRIORITY_CHOICES:
            self._priority.addItem(label, userData=value)
        self._priority.setCurrentIndex(
            max(0, self._priority.findData("normal"))
        )

        self._next_step = QLineEdit()
        self._next_step.setMaxLength(500)
        self._next_step.setPlaceholderText("選填，例如：聯絡客戶補交銀行對帳單")

        self._notes = QTextEdit()
        self._notes.setTabChangesFocus(True)
        self._notes.setFixedHeight(68)
        self._notes.setPlaceholderText("選填，補充處理背景或注意事項")

        form.addRow(QLabel("標題 *"), self._title)
        form.addRow(QLabel("負責人"), self._assignee)
        form.addRow(QLabel("到期日"), self._due_date)
        form.addRow(QLabel("優先級"), self._priority)
        form.addRow(QLabel("下一步"), self._next_step)
        form.addRow(QLabel("備註"), self._notes)
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
            field = form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
            label.setBuddy(field._edit if isinstance(field, DateField) else field)
            field.setAccessibleName(label.text())
        self._due_date._edit.setAccessibleName("到期日，選填，西元年月日")
        self._due_date.setToolTip("選填，西元年-月-日，例如：2026-10-31；留空表示無到期日")

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton("新增待辦", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        for a, b in [
            (self._title, self._assignee),
            (self._assignee, self._due_date._edit),
            (self._due_date._edit, self._due_date._clear_btn),
            (self._due_date._clear_btn, self._due_date._cal_btn),
            (self._due_date._cal_btn, self._priority),
            (self._priority, self._next_step),
            (self._next_step, self._notes),
            (self._notes, self._save_btn),
        ]:
            self.setTabOrder(a, b)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)
        self._update_load_state()
        self.resize(560, 520)
        self._initial_input = self._input_snapshot()

    def _input_snapshot(self) -> tuple:
        return (self._title.text(), self._assignee.text(), self._due_date.raw_text(),
                self._priority.currentData(), self._next_step.text(), self._notes.toPlainText(),
                self._client_combo.currentData() if self._client_combo else None,
                self._eng_combo.currentData() if self._eng_combo else None)

    def reject(self) -> None:
        if self._input_snapshot() != self._initial_input:
            answer = QMessageBox.question(self, "放棄未儲存內容？", "待辦尚未儲存。要放棄本次輸入嗎？", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                return
        super().reject()

    @staticmethod
    def _configure_combo(combo: QComboBox) -> None:
        combo.setMinimumContentsLength(16)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.currentTextChanged.connect(combo.setToolTip)

    def _load_clients(self) -> None:
        if self._client_combo is None:
            return
        previous = self._client_combo.currentData()
        self._client_combo.clear()
        self._client_combo.addItem("（不指定客戶）", _NO_CLIENT)
        self._clients_failed = False
        try:
            if self._clients_service is not None:
                offset = 0
                seen = set()
                while True:
                    rows = self._clients_service.list_clients(limit=500, offset=offset)
                    if offset + len(rows) > _MAX_CONTEXT_ROWS:
                        self._context_limit_hit = True
                        raise ValueError("client selector row limit")
                    for client in rows:
                        if client.id in seen:
                            raise ValueError("duplicate client page")
                        seen.add(client.id)
                        self._client_combo.addItem(client.client_name, client.id)
                    if len(rows) < 500:
                        break
                    offset += len(rows)
        except Exception:
            _log.warning("new_task_dialog: failed to load clients", exc_info=True)
            self._clients_failed = True
            self._client_combo.clear()
            self._client_combo.addItem("客戶載入失敗，請重試", _NO_CLIENT)
        index = self._client_combo.findData(previous)
        if index >= 0:
            self._client_combo.setCurrentIndex(index)

    def _update_load_state(self) -> None:
        failed = self._clients_failed or self._engagements_failed
        message = "無法載入客戶或案件，尚未新增待辦。請重新載入後再儲存。"
        if self._context_limit_hit:
            message = "客戶或案件超過此視窗的 10,000 筆載入上限。請從指定案件新增待辦，避免遺漏關聯。"
        if self._context_missing:
            message = "原選定的客戶或案件已失效，未自動改為無關聯。請取消後重新開啟待辦，或重試載入。"
        self._load_error.setText(message if failed else "")
        self._load_error.setVisible(failed)
        self._retry_btn.setVisible(failed)
        if hasattr(self, "_save_btn"):
            self._save_btn.setEnabled(not failed)

    def _retry_context(self) -> None:
        self._context_limit_hit = False
        self._context_missing = False
        if self._retry_ids is None:
            self._retry_ids = (
                self._client_combo.currentData() if self._client_combo else None,
                self._eng_combo.currentData() if self._eng_combo else None,
            )
        client_id, engagement_id = self._retry_ids
        if self._client_combo is not None:
            self._client_combo.blockSignals(True)
            try:
                self._load_clients()
                if not self._clients_failed and client_id not in (None, _NO_CLIENT):
                    index = self._client_combo.findData(client_id)
                    if index < 0:
                        self._clients_failed = True
                        self._context_missing = True
                    else:
                        self._client_combo.setCurrentIndex(index)
            finally:
                self._client_combo.blockSignals(False)
        if not self._clients_failed:
            self._reload_engagement_combo()
            if not self._engagements_failed and self._eng_combo is not None and engagement_id not in (None, _NO_ENGAGEMENT):
                index = self._eng_combo.findData(engagement_id)
                if index < 0:
                    self._engagements_failed = True
                    self._context_missing = True
                else:
                    self._eng_combo.setCurrentIndex(index)
        if not self._clients_failed and not self._engagements_failed:
            self._retry_ids = None
        self._update_load_state()

    def _on_client_changed(self) -> None:
        self._reload_engagement_combo()

    def _reload_engagement_combo(self) -> None:
        if self._eng_combo is None:
            return
        self._engagements_failed = False
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
                engs = []
                seen = set()
                while True:
                    if client_data is None or client_data == _NO_CLIENT:
                        rows = self._engagements_service.list_all(limit=200, offset=len(engs))
                    else:
                        rows = self._engagements_service.list_by_client(int(client_data), limit=200, offset=len(engs))
                    if len(engs) + len(rows) > _MAX_CONTEXT_ROWS:
                        self._context_limit_hit = True
                        raise ValueError("engagement selector row limit")
                    for eng in rows:
                        if eng.id in seen:
                            raise ValueError("duplicate engagement page")
                        seen.add(eng.id)
                    engs.extend(rows)
                    if len(rows) < 200:
                        break
            except Exception:
                _log.warning(
                    "new_task_dialog: failed to load engagements", exc_info=True
                )
                engs = []
                self._engagements_failed = True
                self._eng_combo.clear()
                self._eng_combo.addItem("案件載入失敗，請重試", _NO_ENGAGEMENT)
            for eng in engs:
                self._eng_combo.addItem(eng.engagement_name, userData=eng.id)
            if previous is not None:
                idx = self._eng_combo.findData(previous)
                if idx >= 0:
                    self._eng_combo.setCurrentIndex(idx)
        finally:
            self._eng_combo.blockSignals(False)
            self._update_load_state()

    def on_save(self) -> None:
        if self._clients_failed or self._engagements_failed:
            return
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
