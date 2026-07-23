"""Presentation-only fields for the annual item editor."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n.status_labels import (
    ANNUAL_DOCUMENT_STATUS_LABELS,
    ANNUAL_FEE_STATUS_LABELS,
    ANNUAL_FILING_STATUS_LABELS,
    ANNUAL_TAX_STATUS_LABELS,
    ANNUAL_WORK_STATUS_LABELS,
    UNKNOWN_STATUS_TEXT,
)
from ...services.annual_work import UpdateAnnualWorkItemInput
from ..style import TEXT_MUTED


_TERMINAL_WORK_STATUSES = frozenset(
    {"completed", "completed_with_exception", "cancelled"}
)


class AnnualItemFields(QScrollArea):
    """Scrollable field surface with no persistence behavior."""

    def __init__(self, annual_work_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualItemScrollArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(10)
        self.setWidget(content)

        context_group = QGroupBox("客戶與年度")
        context_form = QFormLayout(context_group)
        self.client_label = QLabel()
        self.operation_year_input = _readonly_line()
        self.suggested_due_date_input = _readonly_line()
        context_form.addRow("客戶", self.client_label)
        context_form.addRow("作業年度", self.operation_year_input)
        context_form.addRow("系統建議期限", self.suggested_due_date_input)
        layout.addWidget(context_group)

        detail_group = QGroupBox("工作內容")
        detail_form = QFormLayout(detail_group)
        self.title_input = _line(
            "AnnualItemTitle", "輸入清楚可辨識的工作名稱"
        )
        self.tax_year_input = _line(
            "AnnualItemTaxYear", "例如 2026；無則留白"
        )
        self.period_code_input = _line(
            "AnnualItemPeriod", "例如 01–02；無則留白"
        )
        self.due_date_input = _line(
            "AnnualItemDueDate", "YYYY-MM-DD；無則留白"
        )
        detail_form.addRow("工作名稱", self.title_input)
        detail_form.addRow("課稅年度", self.tax_year_input)
        detail_form.addRow("所屬期間", self.period_code_input)
        detail_form.addRow("採用期限", self.due_date_input)
        layout.addWidget(detail_group)

        status_group = QGroupBox("獨立狀態")
        status_form = QFormLayout(status_group)
        self.work_status_combo = QComboBox()
        self.filing_status_combo = QComboBox()
        self.document_status_combo = QComboBox()
        self.tax_status_combo = QComboBox()
        self.fee_status_combo = QComboBox()
        _populate_combo(
            self.work_status_combo,
            ANNUAL_WORK_STATUS_LABELS,
            annual_work_service.WORK_STATUSES,
            omit=_TERMINAL_WORK_STATUSES,
        )
        _populate_combo(
            self.filing_status_combo,
            ANNUAL_FILING_STATUS_LABELS,
            annual_work_service.FILING_STATUSES,
        )
        _populate_combo(
            self.document_status_combo,
            ANNUAL_DOCUMENT_STATUS_LABELS,
            annual_work_service.DOCUMENT_STATUSES,
        )
        _populate_combo(
            self.tax_status_combo,
            ANNUAL_TAX_STATUS_LABELS,
            annual_work_service.TAX_STATUSES,
        )
        _populate_combo(
            self.fee_status_combo,
            ANNUAL_FEE_STATUS_LABELS,
            annual_work_service.FEE_STATUSES,
        )
        status_form.addRow("工作狀態", self.work_status_combo)
        status_form.addRow("申報狀態", self.filing_status_combo)
        status_form.addRow("文件狀態", self.document_status_combo)
        status_form.addRow("稅款狀態", self.tax_status_combo)
        status_form.addRow("服務費狀態", self.fee_status_combo)
        layout.addWidget(status_group)

        notes_group = QGroupBox("備註")
        notes_layout = QVBoxLayout(notes_group)
        notes_hint = QLabel("保留繁體中文、換行與定位字元；上限 100,000 字。")
        notes_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("AnnualItemNotes")
        self.notes_input.setPlaceholderText("輸入客戶特殊要求、交辦內容或處理說明")
        self.notes_input.setMinimumHeight(128)
        notes_layout.addWidget(notes_hint)
        notes_layout.addWidget(self.notes_input)
        layout.addWidget(notes_group)

        transition_group = QGroupBox("完成／取消原因")
        transition_layout = QVBoxLayout(transition_group)
        transition_help = QLabel(
            "完成工作時，若申報、文件、稅款或服務費狀態仍有風險，必須填寫原因；取消也必須填寫原因。"
        )
        transition_help.setWordWrap(True)
        transition_help.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 14px;"
        )
        self.transition_reason_input = QPlainTextEdit()
        self.transition_reason_input.setObjectName("AnnualTransitionReason")
        self.transition_reason_input.setPlaceholderText(
            "輸入例外完成或取消原因（上限 4,000 字）"
        )
        self.transition_reason_input.setMinimumHeight(84)
        transition_layout.addWidget(transition_help)
        transition_layout.addWidget(self.transition_reason_input)
        layout.addWidget(transition_group)

        self.transition_hint = QLabel(
            "有風險時，完成工作會由系統記為例外完成；無風險時記為已完成。取消與重新開啟請使用專用操作。"
        )
        self.transition_hint.setObjectName("AnnualTransitionHint")
        self.transition_hint.setWordWrap(True)
        self.transition_hint.setStyleSheet(
            "background: #FFF7ED; border: 1px solid #FED7AA; "
            "border-radius: 6px; padding: 8px; font-size: 14px;"
        )
        layout.addWidget(self.transition_hint)
        layout.addStretch(1)

    @property
    def editable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.title_input,
            self.tax_year_input,
            self.period_code_input,
            self.due_date_input,
            self.notes_input,
            self.transition_reason_input,
            self.work_status_combo,
            self.filing_status_combo,
            self.document_status_combo,
            self.tax_status_combo,
            self.fee_status_combo,
        )

    def set_values(self, client, context) -> None:
        item = context.item
        self.client_label.setText(client.client_name)
        self.client_label.setToolTip(
            f"{client.client_name}（{client.client_code}）"
        )
        self.operation_year_input.setText(str(context.operation_year))
        self.suggested_due_date_input.setText(
            item.suggested_due_date or "未設定"
        )
        self.title_input.setText(item.title)
        self.tax_year_input.setText(
            "" if item.tax_year is None else str(item.tax_year)
        )
        self.period_code_input.setText(item.period_code or "")
        self.due_date_input.setText(item.due_date or "")
        self.notes_input.setPlainText(item.notes or "")
        self.transition_reason_input.setPlainText(
            item.exception_reason or ""
        )
        _set_combo_value(
            self.work_status_combo, item.work_status, ANNUAL_WORK_STATUS_LABELS
        )
        _set_combo_value(
            self.filing_status_combo,
            item.filing_status,
            ANNUAL_FILING_STATUS_LABELS,
        )
        _set_combo_value(
            self.document_status_combo,
            item.document_status,
            ANNUAL_DOCUMENT_STATUS_LABELS,
        )
        _set_combo_value(
            self.tax_status_combo, item.tax_status, ANNUAL_TAX_STATUS_LABELS
        )
        _set_combo_value(
            self.fee_status_combo, item.fee_status, ANNUAL_FEE_STATUS_LABELS
        )

    def payload(self, expected_updated_at: str) -> UpdateAnnualWorkItemInput:
        raw_tax_year = self.tax_year_input.text()
        try:
            tax_year = int(raw_tax_year) if raw_tax_year else None
        except ValueError:
            tax_year = raw_tax_year
        return UpdateAnnualWorkItemInput(
            title=self.title_input.text(),
            tax_year=tax_year,  # type: ignore[arg-type]
            period_code=self.period_code_input.text() or None,
            due_date=self.due_date_input.text() or None,
            notes=self.notes_input.toPlainText() or None,
            work_status=self.work_status_combo.currentData(),
            filing_status=self.filing_status_combo.currentData(),
            document_status=self.document_status_combo.currentData(),
            tax_status=self.tax_status_combo.currentData(),
            fee_status=self.fee_status_combo.currentData(),
            expected_updated_at=expected_updated_at,
        )

    def focus_for_error(self, code: str) -> QWidget:
        return {
            "annual_work.title.invalid": self.title_input,
            "annual_work.tax_year.invalid": self.tax_year_input,
            "annual_work.period_code.invalid": self.period_code_input,
            "annual_work.due_date.invalid": self.due_date_input,
            "annual_work.notes.invalid": self.notes_input,
        }.get(code, self.title_input)


def _readonly_line() -> QLineEdit:
    field = QLineEdit()
    field.setReadOnly(True)
    return field


def _line(name: str, placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setObjectName(name)
    field.setPlaceholderText(placeholder)
    return field


def _populate_combo(
    combo: QComboBox,
    labels: Mapping[str, str],
    allowed: frozenset[str],
    *,
    omit: frozenset[str] = frozenset(),
) -> None:
    for value, label in labels.items():
        if value in allowed and value not in omit:
            combo.addItem(label, value)


def _set_combo_value(
    combo: QComboBox,
    value: str,
    labels: Mapping[str, str],
) -> None:
    index = combo.findData(value)
    if index < 0:
        combo.addItem(labels.get(value, UNKNOWN_STATUS_TEXT), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)
