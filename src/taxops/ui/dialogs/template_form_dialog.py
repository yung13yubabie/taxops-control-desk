"""Template create/edit dialog.

The editor is the top of the form. The field-source explanation that used to occupy
that position sits in a collapsed disclosure at the bottom, and the real-data preview
sits in a second one, so the default state has exactly one vertical scroll region —
the body editor — and fits without an outer scroll area.

The available-field list is grouped by where each value comes from and filtered by a
search box. Double-click still inserts, and the exact text that will be inserted is
shown before the user commits to it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
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
    QPushButton,
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
from .. import icons, tokens
from ..widgets.buttons import make_button, set_button_role

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

# Categories for the field list, in the order they are shown. Every value in
# `VARIABLE_INFO` declares one of these as its source.
_SOURCE_ORDER: tuple[str, ...] = (
    "客戶資料",
    "案件資料",
    "索件批次",
    "索件文件",
    "固定開立",
    "年度工作臺",
)

_BODY_FOCUS_ERRORS = frozenset({
    "template.body.required",
    "template.body.syntax_error",
    "template.unknown_variable",
})

_NO_SELECTION = "—"

# Roles for the item data the field list carries. A category header carries no
# variable key, which is how insertion and detail lookup tell the two apart.
_VARIABLE_KEY_ROLE = Qt.ItemDataRole.UserRole


class UnknownVariableSource(KeyError):
    """Raised when a template variable declares a source with no category.

    Falling back to an "other" bucket would hide the new source behind a plausible
    grouping; the dialog refuses to build instead.
    """


def insertion_text(label: str) -> str:
    """The exact text a double-click inserts for a field label."""
    return f"【{label}】"


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
        is_builtin = bool(existing is not None and existing.is_builtin)
        if is_builtin:
            self.setWindowTitle("內建模板（唯讀）")
        else:
            self.setWindowTitle("編輯模板" if is_edit else "新增模板")
        self.setModal(True)
        self.setMinimumWidth(760)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACING_XL, tokens.SPACING_XL, tokens.SPACING_XL, tokens.SPACING_XL
        )
        outer.setSpacing(tokens.SPACING_MD)

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

        # Built-in templates say so here rather than leaving the user to discover
        # that every field is dead.
        self._builtin_note = QLabel(error_message("template.builtin.readonly"))
        self._builtin_note.setWordWrap(True)
        self._builtin_note.setVisible(is_builtin)
        outer.addWidget(self._builtin_note)

        # ── Editor and field picker, side by side ───────────────────
        body_area = QHBoxLayout()
        body_area.setSpacing(tokens.SPACING_SM)

        body_col = QVBoxLayout()
        body_col.setSpacing(tokens.SPACING_XS)
        body_col.addWidget(QLabel("模板內容 *"))
        body_col.addWidget(self._body)

        var_col = QVBoxLayout()
        var_col.setSpacing(tokens.SPACING_XS)
        self._var_title = QLabel()
        self._var_title.setWordWrap(True)
        var_col.addWidget(self._var_title)

        self._var_search = QLineEdit()
        self._var_search.setPlaceholderText("搜尋欄位名稱或來源")
        self._var_search.setClearButtonEnabled(True)
        self._var_search.setMaxLength(50)
        var_col.addWidget(self._var_search)

        self._var_list = QListWidget()
        self._var_list.setMinimumWidth(240)
        self._var_list.setMaximumWidth(280)
        var_col.addWidget(self._var_list, stretch=1)

        # The inserted text is shown before the user commits to inserting it: the
        # list shows 客戶名稱 but the body receives 【客戶名稱】.
        self._insert_format = QLabel()
        self._insert_format.setWordWrap(True)
        self._insert_format.setMinimumWidth(240)
        self._insert_format.setMaximumWidth(280)
        var_col.addWidget(self._insert_format)

        self._var_detail = QLabel()
        self._var_detail.setWordWrap(True)
        self._var_detail.setMinimumWidth(240)
        self._var_detail.setMaximumWidth(280)
        self._var_detail.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        var_col.addWidget(self._var_detail)

        body_area.addLayout(body_col, stretch=3)
        body_area.addLayout(var_col, stretch=1)
        outer.addLayout(body_area, stretch=1)

        # ── Real-data preview, collapsed ────────────────────────────
        example_content = QWidget()
        example_layout = QVBoxLayout(example_content)
        example_layout.setContentsMargins(0, tokens.SPACING_XS, 0, 0)
        example_layout.setSpacing(tokens.SPACING_XS)
        example_row = QHBoxLayout()
        example_row.setSpacing(tokens.SPACING_SM)
        example_row.addWidget(QLabel("真實客戶範例"))
        self._example_client = QComboBox()
        self._example_client.setObjectName("TemplateExampleClient")
        self._example_client.setMinimumWidth(280)
        example_row.addWidget(self._example_client, 1)
        example_layout.addLayout(example_row)
        example_layout.addWidget(QLabel("下方預覽只讀，不會修改客戶資料"))
        self._example_preview = QTextEdit()
        self._example_preview.setObjectName("TemplateExamplePreview")
        self._example_preview.setReadOnly(True)
        self._example_preview.setMinimumHeight(90)
        self._example_preview.setMaximumHeight(140)
        self._example_preview.setPlaceholderText(
            "選擇客戶並輸入模板內容後，這裡會顯示真實資料套版結果。"
        )
        example_layout.addWidget(self._example_preview)
        self._example_toggle = _disclosure_button("真實資料預覽")
        outer.addWidget(self._example_toggle)
        outer.addWidget(example_content)

        # ── Field-source explanation, collapsed ─────────────────────
        help_content = QWidget()
        help_layout = QVBoxLayout(help_content)
        help_layout.setContentsMargins(0, tokens.SPACING_XS, 0, 0)
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
        help_layout.addWidget(self._variable_help)
        self._help_toggle = _disclosure_button("欄位來源說明")
        outer.addWidget(self._help_toggle)
        outer.addWidget(help_content)

        self._disclosures: dict[QPushButton, QWidget] = {
            self._example_toggle: example_content,
            self._help_toggle: help_content,
        }
        for toggle, content in self._disclosures.items():
            content.setVisible(False)
            toggle.toggled.connect(
                lambda checked, t=toggle: self._on_disclosure_toggled(t, checked)
            )

        # ── Footer: one primary, cancel secondary ───────────────────
        buttons = QDialogButtonBox()
        save_label = "儲存編輯" if is_edit else "新增模板"
        self._save_btn = buttons.addButton(
            save_label, QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        set_button_role(self._save_btn, tokens.ROLE_PRIMARY)
        set_button_role(cancel_btn, tokens.ROLE_SECONDARY)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        for a, b in [
            (self._name, self._type),
            (self._type, self._body),
            (self._body, self._var_search),
            (self._var_search, self._var_list),
            (self._var_list, self._save_btn),
        ]:
            self.setTabOrder(a, b)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)
        self._var_list.itemDoubleClicked.connect(self._on_insert_variable)
        self._var_list.currentItemChanged.connect(self._on_variable_selected)
        self._var_search.textChanged.connect(lambda _text: self._refresh_variable_list())
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
            if is_builtin:
                self._name.setEnabled(False)
                self._type.setEnabled(False)
                self._body.setEnabled(False)
                self._var_list.setEnabled(False)
                self._var_search.setEnabled(False)
                self._save_btn.setEnabled(False)
                self._save_btn.setToolTip(
                    error_message("template.builtin.readonly")
                )
        else:
            idx = self._type.findData("custom")
            if idx >= 0:
                self._type.setCurrentIndex(idx)
        self._load_example_clients()
        self._refresh_variable_list()
        self._refresh_example_preview()

    # ── Disclosures ─────────────────────────────────────────────────

    def _on_disclosure_toggled(self, toggle: QPushButton, checked: bool) -> None:
        content = self._disclosures[toggle]
        content.setVisible(checked)
        toggle.setIcon(
            icons.icon("chevron-down" if checked else "chevron-right", tokens.TEXT)
        )

    def disclosure_states(self) -> dict[str, bool]:
        """Each disclosure's label and whether it is expanded. Used by tests."""
        return {toggle.text(): toggle.isChecked() for toggle in self._disclosures}

    # ── Real-data preview ───────────────────────────────────────────

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

    # ── Field list ──────────────────────────────────────────────────

    def _on_insert_variable(self, item: QListWidgetItem) -> None:
        key = item.data(_VARIABLE_KEY_ROLE)
        if key is None:
            # A category header, not a field. Inserting 【客戶資料】 would produce an
            # unknown-variable error at save time.
            return
        self._body.insertPlainText(insertion_text(item.text()))
        self._body.setFocus()

    def _variable_keys_for_type(self, template_type: str) -> tuple[str, ...]:
        return _VARIABLES_BY_TYPE.get(
            template_type,
            tuple(sorted(ALLOWED_VARIABLES, key=lambda value: VARIABLE_LABELS[value])),
        )

    def _matches_search(self, key: str, needle: str) -> bool:
        if not needle:
            return True
        info = VARIABLE_INFO[key]
        haystack = f"{VARIABLE_LABELS[key]} {info.source} {info.description}"
        return needle in haystack

    def _refresh_variable_list(self) -> None:
        template_type = str(self._type.currentData() or "custom")
        type_label = TEMPLATE_TYPE_LABELS.get(template_type, template_type)
        keys = self._variable_keys_for_type(template_type)
        needle = self._var_search.text().strip()

        grouped: dict[str, list[str]] = {}
        for key in keys:
            if not self._matches_search(key, needle):
                continue
            source = VARIABLE_INFO[key].source
            if source not in _SOURCE_ORDER:
                raise UnknownVariableSource(
                    f"variable {key!r} declares source {source!r}, which is not one "
                    f"of {list(_SOURCE_ORDER)}; add the category before shipping it"
                )
            grouped.setdefault(source, []).append(key)

        self._var_title.setText(f"可用欄位：{type_label}（雙擊插入）")
        self._var_list.clear()
        for source in _SOURCE_ORDER:
            group = grouped.get(source)
            if not group:
                continue
            header = QListWidgetItem(source)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self._var_list.addItem(header)
            for key in group:
                item = QListWidgetItem(VARIABLE_LABELS[key])
                item.setData(_VARIABLE_KEY_ROLE, key)
                info = VARIABLE_INFO[key]
                item.setToolTip(
                    f"插入格式：{insertion_text(VARIABLE_LABELS[key])}\n"
                    f"來源：{info.source}\n{info.description}\n{info.empty_behavior}"
                )
                self._var_list.addItem(item)

        first = self._first_variable_row()
        if first is None:
            self._var_detail.setText(
                f"沒有符合「{needle}」的欄位，請改用其他關鍵字。"
                if needle
                else "此類型沒有可用欄位。"
            )
            self._insert_format.setText(f"插入格式：{_NO_SELECTION}")
            return
        self._var_list.setCurrentRow(first)

    def _first_variable_row(self) -> int | None:
        for row in range(self._var_list.count()):
            item = self._var_list.item(row)
            if item is not None and item.data(_VARIABLE_KEY_ROLE) is not None:
                return row
        return None

    def variable_list_entries(self) -> tuple[tuple[str, str | None], ...]:
        """Every row as (text, variable key). Headers carry `None`. Used by tests."""
        rows: list[tuple[str, str | None]] = []
        for row in range(self._var_list.count()):
            item = self._var_list.item(row)
            if item is None:
                continue
            key = item.data(_VARIABLE_KEY_ROLE)
            rows.append((item.text(), None if key is None else str(key)))
        return tuple(rows)

    def _on_variable_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        key = None if current is None else current.data(_VARIABLE_KEY_ROLE)
        if current is None or key is None:
            self._var_detail.clear()
            self._insert_format.setText(f"插入格式：{_NO_SELECTION}")
            return
        info = VARIABLE_INFO[str(key)]
        self._insert_format.setText(
            f"插入格式：{insertion_text(current.text())}"
        )
        self._var_detail.setText(
            f"來源：{info.source}\n"
            f"取值：{info.description}\n"
            f"空值：{info.empty_behavior}"
        )

    # ── Save ────────────────────────────────────────────────────────

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


def _disclosure_button(label: str) -> QPushButton:
    """A quiet checkable row that shows or hides the section beneath it."""
    button = make_button(label, role=tokens.ROLE_QUIET, icon_role="chevron-right")
    button.setIconSize(QSize(tokens.ICON_SIZE_MD, tokens.ICON_SIZE_MD))
    button.setCheckable(True)
    button.setChecked(False)
    return button
