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
from ...services.container import ServiceContainer

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
        "annual_work_title",
        "annual_operation_year",
        "annual_due_date",
        "annual_work_status",
        "annual_document_status",
        "annual_tax_status",
        "annual_fee_status",
        "annual_exception_reason",
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
        "annual_work_title",
        "annual_operation_year",
        "annual_due_date",
        "annual_work_status",
        "annual_document_status",
        "annual_tax_status",
        "annual_fee_status",
        "annual_exception_reason",
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
        "annual_work_title",
        "annual_operation_year",
        "annual_due_date",
        "annual_work_status",
        "annual_document_status",
        "annual_tax_status",
        "annual_fee_status",
        "annual_exception_reason",
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
        *,
        container: ServiceContainer | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._existing = existing
        self._container = container

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
            "年度欄位：年度工作臺 > 年度法遵設定／年度工作明細。\n"
            "產生訊息時，系統會依所選客戶／案件／索件自動帶入。"
        )
        self._variable_help.setWordWrap(True)
        self._variable_help.setObjectName("HelpText")
        outer.addWidget(self._variable_help)

        example_row = QHBoxLayout()
        example_row.addWidget(QLabel("真實客戶範例"))
        self._example_client = QComboBox()
        self._example_client.setObjectName("TemplateExampleClient")
        self._example_client.setMinimumWidth(280)
        example_row.addWidget(self._example_client, 1)
        example_row.addWidget(QLabel("下方預覽只讀，不會修改客戶資料"))
        outer.addLayout(example_row)

        self._example_preview = QTextEdit()
        self._example_preview.setObjectName("TemplateExamplePreview")
        self._example_preview.setReadOnly(True)
        self._example_preview.setMinimumHeight(90)
        self._example_preview.setMaximumHeight(140)
        self._example_preview.setPlaceholderText(
            "選擇客戶並輸入模板內容後，這裡會顯示真實資料套版結果。"
        )
        outer.addWidget(self._example_preview)

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
        self._example_client.currentIndexChanged.connect(
            self._refresh_example_preview
        )
        self._body.textChanged.connect(self._refresh_example_preview)

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
        self._load_example_clients()
        self._refresh_variable_list()
        self._refresh_example_preview()

    def _load_example_clients(self) -> None:
        self._example_client.clear()
        if self._container is None:
            self._example_client.addItem("此入口未提供客戶預覽", None)
            self._example_client.setEnabled(False)
            return
        try:
            clients = self._container.clients.search_clients("", limit=500)
        except Exception:
            clients = []
        self._example_client.addItem("請選擇範例客戶", None)
        for client in clients:
            self._example_client.addItem(
                f"{client.client_code}  {client.client_name}", client.id
            )

    def _refresh_example_preview(self, _value: object = None) -> None:
        client_id = self._example_client.currentData()
        body = self._body.toPlainText()
        if self._container is None or not isinstance(client_id, int) or not body.strip():
            self._example_preview.clear()
            return
        try:
            variables = self._container.gen_messages.build_client_example_variables(
                client_id
            )
            rendered = self._svc.render_body_preview(body, variables)
        except TemplateValidationError:
            self._example_preview.setPlainText("模板內容尚未完成，修正欄位或語法後會立即預覽。")
            return
        except Exception:
            self._example_preview.setPlainText("真實客戶範例載入失敗，請重新選擇客戶。")
            return
        self._example_preview.setPlainText(rendered)

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
