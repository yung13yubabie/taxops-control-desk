"""Template create/edit dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
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
from ...i18n.status_labels import TEMPLATE_TYPE_LABELS
from ...repositories.templates import TemplateRow
from ...services.templates import (
    CreateTemplateInput,
    TemplateValidationError,
    TemplatesService,
    UpdateTemplateInput,
)

_TYPE_CHOICES = [
    ("initial_request", TEMPLATE_TYPE_LABELS["initial_request"]),
    ("follow_up", TEMPLATE_TYPE_LABELS["follow_up"]),
    ("custom", TEMPLATE_TYPE_LABELS["custom"]),
]

_BODY_FOCUS_ERRORS = frozenset({
    "template.body.required",
    "template.body.syntax_error",
    "template.unknown_variable",
})


class TemplateFormDialog(QDialog):
    def __init__(
        self,
        svc: TemplatesService,
        existing: TemplateRow | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._existing = existing

        is_edit = existing is not None
        self.setWindowTitle("編輯模板" if is_edit else "新增模板")
        self.setModal(True)
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setMaxLength(200)
        self._name.setPlaceholderText("必填")

        self._type = QComboBox()
        for value, label in _TYPE_CHOICES:
            self._type.addItem(label, userData=value)

        self._body = QTextEdit()
        self._body.setMinimumHeight(180)
        self._body.setPlaceholderText(
            "輸入模板內容，可使用 {{ client_name }}、{{ period_name }}、"
            "{{ tax_type_name }}、{{ missing_items }}、{{ invalid_items }}、"
            "{{ incomplete_items }}、{{ due_date }}"
        )

        form.addRow(QLabel("模板名稱 *"), self._name)
        form.addRow(QLabel("模板類型"), self._type)
        form.addRow(QLabel("模板內容 *"), self._body)
        outer.addLayout(form)

        buttons = QDialogButtonBox()
        save_label = "儲存編輯" if is_edit else "新增模板"
        self._save_btn = buttons.addButton(save_label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)

        if is_edit:
            assert existing is not None
            self._name.setText(existing.name)
            idx = self._type.findData(existing.template_type)
            if idx >= 0:
                self._type.setCurrentIndex(idx)
            self._body.setPlainText(existing.body)
            if existing.is_builtin:
                self._name.setEnabled(False)
                self._type.setEnabled(False)
                self._body.setEnabled(False)
                self._save_btn.setEnabled(False)
        else:
            idx = self._type.findData("custom")
            if idx >= 0:
                self._type.setCurrentIndex(idx)

    def on_save(self) -> None:
        name = self._name.text()
        template_type = self._type.currentData()
        body = self._body.toPlainText()

        try:
            if self._existing is None:
                self._svc.create_template(
                    CreateTemplateInput(name=name, template_type=template_type, body=body)
                )
            else:
                self._svc.update_template(
                    self._existing.id,
                    UpdateTemplateInput(name=name, template_type=template_type, body=body),
                )
        except TemplateValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            if err.code == "template.name.required":
                self._name.setFocus()
            elif err.code in _BODY_FOCUS_ERRORS:
                self._body.setFocus()
            return
        except Exception:
            code = "template.update.failed" if self._existing else "template.create.failed"
            QMessageBox.warning(self, "操作失敗", error_message(code))
            return
        self.accept()
