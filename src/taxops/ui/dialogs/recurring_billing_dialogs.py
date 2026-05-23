"""Dialogs for recurring billing: plan, line, confirm, skip."""

from __future__ import annotations

import html
import json
import logging

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
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.recurring_billing import LineRow, OccurrenceRow, PlanRow
from ...services.recurring_billing import (
    ConfirmOccurrenceInput,
    CreateLineInput,
    CreatePlanInput,
    RecurringBillingError,
    RecurringBillingService,
    UpdateLineInput,
    UpdatePlanInput,
)
from ..widgets.date_field import DateField
from ._shared import TAX_TYPE_CHOICES

_log = logging.getLogger(__name__)

_FREQ_CHOICES = [
    ("monthly",       "月開（每月）"),
    ("quarterly",     "季開（每季）"),
    ("semiannual",    "半年開（每半年）"),
    ("annual",        "年開（每年）"),
    ("custom_months", "自訂月份"),
]

_MONTH_NAMES = [
    "1月","2月","3月","4月","5月","6月",
    "7月","8月","9月","10月","11月","12月",
]


class PlanDialog(QDialog):
    """Create or edit a recurring billing plan."""

    def __init__(
        self,
        svc: RecurringBillingService,
        client_id: int,
        plan: PlanRow | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._client_id = client_id
        self._plan = plan

        self.setWindowTitle("新增方案" if plan is None else "編輯方案")
        self.setModal(True)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setMaxLength(200)
        self._name.setPlaceholderText("必填")
        form.addRow(QLabel("方案名稱 *"), self._name)

        self._freq = QComboBox()
        for val, lbl in _FREQ_CHOICES:
            self._freq.addItem(lbl, userData=val)
        form.addRow(QLabel("週期"), self._freq)

        self._issue_day = QSpinBox()
        self._issue_day.setRange(1, 31)
        self._issue_day.setSuffix(" 日")
        form.addRow(QLabel("開立日"), self._issue_day)

        self._months_label = QLabel("指定月份")
        self._months_widget = QWidget()
        months_row = QHBoxLayout(self._months_widget)
        months_row.setContentsMargins(0, 0, 0, 0)
        months_row.setSpacing(4)
        self._month_checks: list[QCheckBox] = []
        for name in _MONTH_NAMES:
            cb = QCheckBox(name)
            cb.setFixedWidth(52)
            self._month_checks.append(cb)
            months_row.addWidget(cb)
        months_row.addStretch()
        form.addRow(self._months_label, self._months_widget)

        self._start_date = DateField(required=True)
        form.addRow(QLabel("開始日期 *"), self._start_date)

        self._end_date = DateField(required=False)
        form.addRow(QLabel("結束日期"), self._end_date)

        self._notice_days = QSpinBox()
        self._notice_days.setRange(0, 365)
        self._notice_days.setSuffix(" 天")
        self._notice_days.setValue(7)
        form.addRow(QLabel("提前通知天數"), self._notice_days)

        self._contract_ref = QLineEdit()
        self._contract_ref.setMaxLength(200)
        self._contract_ref.setPlaceholderText("選填")
        form.addRow(QLabel("合約編號"), self._contract_ref)

        self._notes = QTextEdit()
        self._notes.setFixedHeight(68)
        form.addRow(QLabel("備註"), self._notes)

        outer.addLayout(form)

        buttons = QDialogButtonBox()
        label = "新增方案" if plan is None else "儲存變更"
        self._save_btn = buttons.addButton(label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._freq.currentIndexChanged.connect(self._on_freq_changed)
        self._save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)

        self._populate(plan)
        self._on_freq_changed()

    def _populate(self, plan: PlanRow | None) -> None:
        if plan is None:
            return
        self._name.setText(plan.plan_name)
        idx = self._freq.findData(plan.frequency)
        if idx >= 0:
            self._freq.setCurrentIndex(idx)
        self._issue_day.setValue(plan.issue_day)
        self._start_date.set_value(plan.start_date)
        self._end_date.set_value(plan.end_date)
        self._notice_days.setValue(plan.advance_notice_days)
        self._contract_ref.setText(plan.contract_ref or "")
        self._notes.setPlainText(plan.notes or "")
        if plan.frequency == "custom_months":
            try:
                selected = set(json.loads(plan.months_json))
                for i, cb in enumerate(self._month_checks):
                    cb.setChecked((i + 1) in selected)
            except (ValueError, TypeError):
                pass

    def _on_freq_changed(self) -> None:
        is_custom = self._freq.currentData() == "custom_months"
        self._months_label.setVisible(is_custom)
        self._months_widget.setVisible(is_custom)

    def _build_months_json(self) -> str:
        months = [i + 1 for i, cb in enumerate(self._month_checks) if cb.isChecked()]
        return json.dumps(months)

    def _on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            start = self._start_date.validated_value()
        except DateField.InvalidInput:
            self._save_btn.setEnabled(True)
            return
        try:
            end = self._end_date.validated_value()
        except DateField.InvalidInput:
            self._save_btn.setEnabled(True)
            return
        if start is None:
            QMessageBox.warning(self, "輸入有誤", "請輸入開始日期")
            self._save_btn.setEnabled(True)
            return
        if self._freq.currentData() == "custom_months":
            if not any(cb.isChecked() for cb in self._month_checks):
                QMessageBox.warning(self, "輸入有誤", "自訂月份模式必須至少選擇一個月份")
                self._save_btn.setEnabled(True)
                return
        try:
            if self._plan is None:
                self._svc.create_plan(CreatePlanInput(
                    client_id=self._client_id,
                    plan_name=self._name.text(),
                    frequency=self._freq.currentData(),
                    issue_day=self._issue_day.value(),
                    months_json=self._build_months_json(),
                    start_date=start,
                    end_date=end,
                    advance_notice_days=self._notice_days.value(),
                    contract_ref=self._contract_ref.text() or None,
                    notes=self._notes.toPlainText() or None,
                ))
            else:
                self._svc.update_plan(self._plan.id, UpdatePlanInput(
                    plan_name=self._name.text(),
                    frequency=self._freq.currentData(),
                    issue_day=self._issue_day.value(),
                    months_json=self._build_months_json(),
                    start_date=start,
                    end_date=end,
                    advance_notice_days=self._notice_days.value(),
                    contract_ref=self._contract_ref.text() or None,
                    notes=self._notes.toPlainText() or None,
                ))
        except RecurringBillingError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            self._save_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("PlanDialog save failed")
            QMessageBox.warning(self, "儲存失敗", error_message("system.unexpected"))
            self._save_btn.setEnabled(True)
            return
        self.accept()


class LineDialog(QDialog):
    """Add or edit a billing line."""

    def __init__(
        self,
        svc: RecurringBillingService,
        plan_id: int,
        line: LineRow | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._plan_id = plan_id
        self._line = line

        self.setWindowTitle("新增明細" if line is None else "編輯明細")
        self.setModal(True)
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._bill_to = QLineEdit()
        self._bill_to.setMaxLength(200)
        self._bill_to.setPlaceholderText("必填，例：台積電EDA部")
        form.addRow(QLabel("開立對象 *"), self._bill_to)

        self._amount = QLineEdit()
        self._amount.setPlaceholderText("整數，例：120000")
        form.addRow(QLabel("金額 (NT$) *"), self._amount)

        self._desc = QLineEdit()
        self._desc.setMaxLength(500)
        self._desc.setPlaceholderText("選填")
        form.addRow(QLabel("說明"), self._desc)

        self._tax_type = QComboBox()
        self._tax_type.addItem("（不指定）", userData=None)
        for val, lbl in TAX_TYPE_CHOICES:
            self._tax_type.addItem(lbl, userData=val)
        form.addRow(QLabel("稅目"), self._tax_type)

        self._sort_order = QSpinBox()
        self._sort_order.setRange(0, 999)
        form.addRow(QLabel("排序"), self._sort_order)

        outer.addLayout(form)

        buttons = QDialogButtonBox()
        label = "新增明細" if line is None else "儲存變更"
        self._save_btn = buttons.addButton(label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)

        if line is not None:
            self._populate(line)

    def _populate(self, line: LineRow) -> None:
        self._bill_to.setText(line.bill_to_name)
        self._amount.setText(str(line.amount))
        self._desc.setText(line.description or "")
        idx = self._tax_type.findData(line.tax_type)
        if idx >= 0:
            self._tax_type.setCurrentIndex(idx)
        self._sort_order.setValue(line.sort_order)

    def _on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            amount = int(self._amount.text().strip())
        except ValueError:
            QMessageBox.warning(self, "輸入有誤", "金額必須為整數")
            self._save_btn.setEnabled(True)
            return
        try:
            if self._line is None:
                self._svc.create_line(CreateLineInput(
                    plan_id=self._plan_id,
                    bill_to_name=self._bill_to.text(),
                    amount=amount,
                    description=self._desc.text() or None,
                    tax_type=self._tax_type.currentData(),
                    sort_order=self._sort_order.value(),
                ))
            else:
                self._svc.update_line(self._line.id, UpdateLineInput(
                    bill_to_name=self._bill_to.text(),
                    amount=amount,
                    description=self._desc.text() or None,
                    tax_type=self._tax_type.currentData(),
                    sort_order=self._sort_order.value(),
                ))
        except RecurringBillingError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            self._save_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("LineDialog save failed")
            QMessageBox.warning(self, "儲存失敗", error_message("system.unexpected"))
            self._save_btn.setEnabled(True)
            return
        self.accept()


class ConfirmOccurrenceDialog(QDialog):
    """Verify and confirm an occurrence."""

    def __init__(
        self,
        svc: RecurringBillingService,
        occurrence: OccurrenceRow,
        line: LineRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._occ = occurrence

        self.setWindowTitle("確認開立")
        self.setModal(True)
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        outer.addWidget(QLabel(
            f"<b>{html.escape(line.bill_to_name)}</b>　預計開立日：{occurrence.expected_issue_date}"
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._amount = QLineEdit()
        self._amount.setText(str(line.amount))
        form.addRow(QLabel("確認金額 (NT$) *"), self._amount)

        self._issue_date = DateField(required=False)
        self._issue_date.set_value(occurrence.expected_issue_date)
        form.addRow(QLabel("實際開立日"), self._issue_date)

        self._invoice_no = QLineEdit()
        self._invoice_no.setMaxLength(50)
        self._invoice_no.setPlaceholderText("選填，最多 50 字元")
        form.addRow(QLabel("發票號碼"), self._invoice_no)

        self._notes = QTextEdit()
        self._notes.setFixedHeight(56)
        form.addRow(QLabel("備註"), self._notes)

        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton("確認開立", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)

    def _on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            amount = int(self._amount.text().strip())
        except ValueError:
            QMessageBox.warning(self, "輸入有誤", "金額必須為整數")
            self._save_btn.setEnabled(True)
            return
        try:
            issue_date = self._issue_date.validated_value()
        except DateField.InvalidInput:
            self._save_btn.setEnabled(True)
            return
        try:
            self._svc.confirm_occurrence(self._occ.id, ConfirmOccurrenceInput(
                confirmed_amount=amount,
                confirmed_invoice_no=self._invoice_no.text() or None,
                confirmed_issue_date=issue_date,
                notes=self._notes.toPlainText() or None,
            ))
        except RecurringBillingError as err:
            QMessageBox.warning(self, "操作失敗", error_message(err.code))
            self._save_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("ConfirmOccurrenceDialog save failed")
            QMessageBox.warning(self, "操作失敗", error_message("system.unexpected"))
            self._save_btn.setEnabled(True)
            return
        self.accept()


class SkipOccurrenceDialog(QDialog):
    """Skip an occurrence with optional reason."""

    def __init__(
        self,
        svc: RecurringBillingService,
        occurrence: OccurrenceRow,
        line: LineRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = svc
        self._occ = occurrence

        self.setWindowTitle("跳過此筆開立")
        self.setModal(True)
        self.setMinimumWidth(380)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        outer.addWidget(QLabel(
            f"<b>{html.escape(line.bill_to_name)}</b>　{occurrence.expected_issue_date}"
        ))
        outer.addWidget(QLabel("確定跳過這筆開立嗎？請填寫跳過原因。"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._reason = QTextEdit()
        self._reason.setFixedHeight(80)
        self._reason.setPlaceholderText("必填")
        form.addRow(QLabel("跳過原因 *"), self._reason)

        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self._skip_btn = buttons.addButton("確定跳過", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        outer.addWidget(buttons)

        self._skip_btn.clicked.connect(self._on_skip)
        cancel_btn.clicked.connect(self.reject)

    def _on_skip(self) -> None:
        self._skip_btn.setEnabled(False)
        reason = self._reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "輸入有誤", "請填寫跳過原因")
            self._skip_btn.setEnabled(True)
            return
        try:
            self._svc.skip_occurrence(self._occ.id, reason)
        except RecurringBillingError as err:
            QMessageBox.warning(self, "操作失敗", error_message(err.code))
            self._skip_btn.setEnabled(True)
            return
        except Exception:
            _log.exception("SkipOccurrenceDialog failed")
            QMessageBox.warning(self, "操作失敗", error_message("system.unexpected"))
            self._skip_btn.setEnabled(True)
            return
        self.accept()
