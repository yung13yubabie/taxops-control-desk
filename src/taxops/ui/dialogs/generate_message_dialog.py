"""Generate message dialog: template selector + preview + save."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.generated_messages import GeneratedMessageRow
from ...services.generated_messages import (
    GenerateMessageInput,
    GeneratedMessageValidationError,
    GeneratedMessagesService,
)
from ...services.templates import TemplateValidationError, TemplatesService
from ..style import DANGER_COLOR

_log = logging.getLogger(__name__)


class GenerateMessageDialog(QDialog):
    def __init__(
        self,
        gen_svc: GeneratedMessagesService,
        templates_svc: TemplatesService,
        request_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._gen_svc = gen_svc
        self._templates_svc = templates_svc
        self._request_id = request_id

        self.setWindowTitle("產生催件訊息")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(400)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._template_combo = QComboBox()
        form.addRow(QLabel("選擇模板"), self._template_combo)
        outer.addLayout(form)

        self._template_error_label = QLabel("載入模板清單失敗，請關閉後重試")
        self._template_error_label.setStyleSheet(f"color: {DANGER_COLOR};")
        self._template_error_label.hide()
        outer.addWidget(self._template_error_label)

        outer.addWidget(QLabel("訊息預覽"))
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("請選擇模板以預覽訊息內容")
        outer.addWidget(self._preview, stretch=1)

        buttons = QDialogButtonBox()
        self._copy_btn = buttons.addButton("複製訊息", QDialogButtonBox.ButtonRole.ActionRole)
        self._save_btn = buttons.addButton("儲存並關閉", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        outer.addWidget(buttons)

        self._copy_btn.clicked.connect(self._on_copy)
        self._save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)

        self._load_templates()

        try:
            self._variables = gen_svc.build_variables(request_id)
        except GeneratedMessageValidationError as err:
            QMessageBox.warning(self, "無法產生訊息", error_message(err.code))
            self._variables = {}

    def _load_templates(self) -> None:
        try:
            templates = self._templates_svc.list_all()
            self._template_error_label.hide()
        except Exception as err:
            _log.warning(
                "generate_message_dialog: failed to load templates: %s: %s",
                type(err).__name__, err,
            )
            self._template_error_label.show()
            self._template_combo.setEnabled(False)
            templates = []
        self._template_combo.clear()
        self._template_combo.addItem("— 請選擇 —", userData=None)
        for tmpl in templates:
            self._template_combo.addItem(tmpl.name, userData=tmpl.id)

    def _on_template_changed(self) -> None:
        template_id = self._template_combo.currentData()
        if template_id is None or not self._variables:
            self._preview.setPlainText("")
            self._save_btn.setEnabled(False)
            self._copy_btn.setEnabled(False)
            return
        try:
            body = self._templates_svc.render_template(template_id, self._variables)
            self._preview.setPlainText(body)
            self._save_btn.setEnabled(True)
            self._copy_btn.setEnabled(True)
        except TemplateValidationError as err:
            self._preview.setPlainText(f"[預覽失敗：{error_message(err.code)}]")
            self._save_btn.setEnabled(False)
            self._copy_btn.setEnabled(False)

    def _generate(self) -> GeneratedMessageRow | None:
        template_id = self._template_combo.currentData()
        if template_id is None:
            return None
        try:
            return self._gen_svc.generate(
                GenerateMessageInput(request_id=self._request_id, template_id=template_id)
            )
        except GeneratedMessageValidationError as err:
            QMessageBox.warning(self, "儲存失敗", error_message(err.code))
        except Exception:
            QMessageBox.warning(self, "儲存失敗", error_message("gen_message.save_failed"))
        return None

    def _on_copy(self) -> None:
        body = self._preview.toPlainText()
        if body:
            QApplication.clipboard().setText(body)

    def _on_save(self) -> None:
        if self._generate() is not None:
            self.accept()
