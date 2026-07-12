"""Template create/edit dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...i18n.status_labels import TEMPLATE_TYPE_LABELS
from ...repositories.templates import TemplateRow
from ...services.templates import (
    ALLOWED_VARIABLES,
    CreateTemplateInput,
    TemplateValidationError,
    TemplatesService,
    UpdateTemplateInput,
    VARIABLE_INFO,
    VARIABLE_LABELS,
)

_TYPE_CHOICES = [
    ("initial_request", TEMPLATE_TYPE_LABELS["initial_request"]),
    ("follow_up", TEMPLATE_TYPE_LABELS["follow_up"]),
    ("payment_follow_up", TEMPLATE_TYPE_LABELS["payment_follow_up"]),
    ("custom", TEMPLATE_TYPE_LABELS["custom"]),
]

_VARIABLES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "initial_request": (
        "client_name",
        "tax_id",
        "contact_person",
        "engagement_name",
        "period_name",
        "tax_type_name",
        "missing_items",
        "invalid_items",
        "incomplete_items",
        "due_date",
        "notes",
    ),
    "follow_up": (
        "client_name",
        "contact_person",
        "engagement_name",
        "period_name",
        "tax_type_name",
        "missing_items",
        "invalid_items",
        "incomplete_items",
        "due_date",
        "notes",
    ),
    "payment_follow_up": (
        "client_name",
        "tax_id",
        "contact_person",
        "payment_records",
        "outstanding_amount",
        "overdue_amount",
        "payment_due_date",
        "notes",
    ),
}

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
        self.setMinimumWidth(760)

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
            "輸入模板內容。雙擊右側欄位即可插入。\n"
            "例如：【客戶名稱】、【截止日】。不支援運算或控制流程。"
        )

        form.addRow(QLabel("模板名稱 *"), self._name)
        form.addRow(QLabel("模板類型"), self._type)
        outer.addLayout(form)

        self._variable_help = QLabel(
            "可用欄位不是在此輸入資料；雙擊只會插入欄位標記。\n"
            "客戶欄位：客戶管理 > 新增／編輯客戶。\n"
            "帳款欄位：固定開立 > 方案明細與待開立紀錄；目前代表待開立排程，"
            "不是收款或欠款帳本。\n"
            "期限欄位：案件管理 > 索件管理 > 索件期限。\n"
            "備註欄位：案件管理 > 索件管理 > 索件備註。\n"
            "產生訊息時，系統會依所選客戶／案件／索件自動帶入。"
        )
        self._variable_help.setWordWrap(True)
        self._variable_help.setObjectName("HelpText")
        outer.addWidget(self._variable_help)

        body_area = QHBoxLayout()
        body_area.setSpacing(8)

        body_col = QVBoxLayout()
        body_col.setSpacing(4)
        body_col.addWidget(QLabel("模板內容 *"))
        body_col.addWidget(self._body)

        var_col = QVBoxLayout()
        var_col.setSpacing(4)
        self._var_title = QLabel()
        self._var_title.setWordWrap(True)
        var_col.addWidget(self._var_title)
        self._var_list = QListWidget()
        self._var_list.setMinimumWidth(220)
        self._var_list.setMaximumWidth(260)
        var_col.addWidget(self._var_list)
        self._var_detail = QLabel()
        self._var_detail.setWordWrap(True)
        self._var_detail.setMinimumWidth(220)
        self._var_detail.setMaximumWidth(260)
        self._var_detail.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        var_col.addWidget(self._var_detail)

        body_area.addLayout(body_col, stretch=3)
        body_area.addLayout(var_col, stretch=1)
        outer.addLayout(body_area)

        buttons = QDialogButtonBox()
        save_label = "儲存編輯" if is_edit else "新增模板"
        self._save_btn = buttons.addButton(save_label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        for a, b in [
            (self._name, self._type),
            (self._type, self._body),
            (self._body, self._save_btn),
        ]:
            self.setTabOrder(a, b)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)
        self._var_list.itemDoubleClicked.connect(self._on_insert_variable)
        self._var_list.currentItemChanged.connect(self._on_variable_selected)
        self._type.currentIndexChanged.connect(self._refresh_variable_list)

        if is_edit:
            self._name.setText(existing.name)
            idx = self._type.findData(existing.template_type)
            if idx >= 0:
                self._type.setCurrentIndex(idx)
            self._body.setPlainText(self._svc.body_for_edit(existing.body))
            if existing.is_builtin:
                self._name.setEnabled(False)
                self._type.setEnabled(False)
                self._body.setEnabled(False)
                self._var_list.setEnabled(False)
                self._save_btn.setEnabled(False)
        else:
            idx = self._type.findData("custom")
            if idx >= 0:
                self._type.setCurrentIndex(idx)
        self._refresh_variable_list()

    def _on_insert_variable(self, item: QListWidgetItem) -> None:
        self._body.insertPlainText(f"【{item.text()}】")
        self._body.setFocus()

    def _refresh_variable_list(self) -> None:
        template_type = str(self._type.currentData() or "custom")
        type_label = TEMPLATE_TYPE_LABELS.get(template_type, template_type)
        keys = _VARIABLES_BY_TYPE.get(
            template_type,
            tuple(sorted(ALLOWED_VARIABLES, key=lambda value: VARIABLE_LABELS[value])),
        )
        self._var_title.setText(f"可用欄位：{type_label}（雙擊插入）")
        self._var_list.clear()
        for key in keys:
            item = QListWidgetItem(VARIABLE_LABELS[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            info = VARIABLE_INFO[key]
            item.setToolTip(
                f"來源：{info.source}\n{info.description}\n{info.empty_behavior}"
            )
            self._var_list.addItem(item)
        if self._var_list.count():
            self._var_list.setCurrentRow(0)
        else:
            self._var_detail.clear()

    def _on_variable_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._var_detail.clear()
            return
        key = str(current.data(Qt.ItemDataRole.UserRole))
        info = VARIABLE_INFO[key]
        self._var_detail.setText(
            f"來源：{info.source}\n"
            f"取值：{info.description}\n"
            f"空值：{info.empty_behavior}"
        )

    def on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            name = self._name.text()
            template_type = self._type.currentData()
            body = self._body.toPlainText()
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
            self._save_btn.setEnabled(True)
            return
        except Exception:
            code = "template.update.failed" if self._existing else "template.create.failed"
            QMessageBox.warning(self, "操作失敗", error_message(code))
            self._save_btn.setEnabled(True)
            return
        self.accept()
