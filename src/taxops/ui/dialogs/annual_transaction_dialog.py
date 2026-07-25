"""Add or edit one annual-ledger transaction through the public service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...i18n.errors import ERROR_MESSAGES, error_message
from ...i18n.labels import ANNUAL_TRANSACTION_CATEGORY_LABELS
from ...repositories.annual_transactions import AnnualTransactionRow
from ...services.annual_transactions import MAX_AMOUNT, AnnualTransactionsService


def _sanitized_error_code(exc: BaseException) -> str:
    candidate = getattr(exc, "code", "")
    if not candidate:
        candidate = str(exc)
    if (
        isinstance(candidate, str)
        and candidate.startswith("annual_transactions.")
        and candidate in ERROR_MESSAGES
    ):
        return candidate
    return "system.unexpected"


def _safe_system_log_error(
    system_log: object | None,
    message: str,
    *,
    operation: str,
    exc: BaseException,
    work_item_id: int | None = None,
    transaction_id: int | None = None,
) -> None:
    if system_log is None:
        return
    detail: dict[str, object] = {
        "code": _sanitized_error_code(exc),
        "operation": operation,
    }
    if type(transaction_id) is int:
        detail["transaction_id"] = transaction_id
    if type(work_item_id) is int:
        detail["work_item_id"] = work_item_id
    try:
        system_log.error(message, detail=detail)
    except Exception:
        # Diagnostic persistence must never replace the user-facing failure.
        return


def _schedule_focus(owner: QWidget, target: QWidget) -> None:
    def focus_if_alive() -> None:
        if isValid(owner) and isValid(target):
            target.setFocus()

    QTimer.singleShot(0, owner, focus_if_alive)


@dataclass(frozen=True)
class AnnualTransactionCommitEvidence:
    """Immutable service result that the ledger must read back before success."""

    operation: str
    row: AnnualTransactionRow


class AnnualTransactionDialog(QDialog):
    """Validated transaction form with no in-memory ledger state."""

    committed = Signal()
    committed_evidence = Signal(object)

    def __init__(
        self,
        service: AnnualTransactionsService,
        work_item_id: int,
        *,
        transaction_id: int | None = None,
        system_log: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualTransactionDialog")
        self.setWindowTitle("編輯交易紀錄" if transaction_id else "新增交易紀錄")
        self.setMinimumSize(520, 440)
        self.resize(600, 520)
        self._service = service
        self._system_log = system_log
        self.work_item_id = work_item_id
        self.transaction_id = transaction_id
        self.committed_transaction_id: int | None = None
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.category_combo = QComboBox()
        self.category_combo.setObjectName("AnnualTransactionCategory")
        for category, label in ANNUAL_TRANSACTION_CATEGORY_LABELS.items():
            if category in self._service.CATEGORIES:
                self.category_combo.addItem(label, category)

        self.transaction_date_input = QLineEdit()
        self.transaction_date_input.setObjectName("AnnualTransactionDate")
        self.transaction_date_input.setPlaceholderText("YYYY-MM-DD")
        self.transaction_date_input.setMaxLength(11)

        self.amount_input = QLineEdit()
        self.amount_input.setObjectName("AnnualTransactionAmount")
        self.amount_input.setPlaceholderText("0 至 9,000,000,000,000")

        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("AnnualTransactionReference")

        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("AnnualTransactionNotes")
        self.notes_input.setMinimumHeight(120)

        form.addRow("分類", self.category_combo)
        form.addRow("日期", self.transaction_date_input)
        form.addRow("金額", self.amount_input)
        form.addRow("參考資訊", self.reference_input)
        form.addRow("備註", self.notes_input)
        layout.addLayout(form)

        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("AnnualTransactionFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        self.cancel_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button.setText("儲存")
        self.cancel_button.setText("取消")
        layout.addWidget(self.button_box)

        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.reject)

        if self.transaction_id is not None:
            self._load_transaction()
        else:
            self.transaction_date_input.setText(date.today().isoformat())

    def _load_transaction(self) -> None:
        try:
            row = self._service.get(self.transaction_id)
            if row is None or row.work_item_id != self.work_item_id:
                raise ValueError("annual_transactions.transaction_not_found")
            self.category_combo.setCurrentIndex(
                self.category_combo.findData(row.category)
            )
            self.transaction_date_input.setText(row.transaction_date)
            self.amount_input.setText(str(row.amount))
            self.reference_input.setText(row.reference or "")
            self.notes_input.setPlainText(row.notes or "")
        except Exception as exc:
            _safe_system_log_error(
                self._system_log,
                "annual_transaction_ui.load.failed",
                operation="load",
                exc=exc,
                work_item_id=self.work_item_id,
                transaction_id=self.transaction_id,
            )
            self._show_failure(exc, "讀取交易紀錄失敗，請關閉後再試。")
            self._set_form_enabled(False)

    def _validated_payload(self) -> tuple[str, int, str, str | None, str | None]:
        category = self.category_combo.currentData()
        if category not in self._service.CATEGORIES:
            self.category_combo.setFocus()
            raise ValueError("annual_transactions.category.invalid")

        raw_amount = self.amount_input.text()
        if not raw_amount or not raw_amount.isascii() or not raw_amount.isdecimal():
            self.amount_input.setFocus()
            raise ValueError("annual_transactions.amount.invalid")
        amount = int(raw_amount)
        if not 0 <= amount <= MAX_AMOUNT:
            self.amount_input.setFocus()
            raise ValueError("annual_transactions.amount.invalid")

        transaction_date = self.transaction_date_input.text()
        try:
            if date.fromisoformat(transaction_date).isoformat() != transaction_date:
                raise ValueError
        except ValueError as exc:
            self.transaction_date_input.setFocus()
            raise ValueError("annual_transactions.date.invalid") from exc

        reference = self.reference_input.text()
        if len(reference) > 500:
            self.reference_input.setFocus()
            raise ValueError("annual_transactions.reference.invalid")
        notes = self.notes_input.toPlainText()
        if len(notes) > 4000:
            self.notes_input.setFocus()
            raise ValueError("annual_transactions.notes.invalid")
        return (
            category,
            amount,
            transaction_date,
            reference or None,
            notes or None,
        )

    def save(self) -> None:
        if self._busy:
            return
        try:
            payload = self._validated_payload()
        except ValueError as exc:
            self.feedback_label.setText(error_message(str(exc)))
            return

        self._busy = True
        self._set_form_enabled(False)
        self.feedback_label.setText("處理中，正在儲存交易紀錄。")
        try:
            if self.transaction_id is None:
                row = self._service.add(self.work_item_id, *payload)
            else:
                row = self._service.update(self.transaction_id, *payload)
            self.committed_transaction_id = row.id
            self.committed_evidence.emit(
                AnnualTransactionCommitEvidence(
                    "add" if self.transaction_id is None else "update",
                    row,
                )
            )
            self.committed.emit()
            self.accept()
        except Exception as exc:
            _safe_system_log_error(
                self._system_log,
                "annual_transaction_ui.mutation.failed",
                operation="add" if self.transaction_id is None else "update",
                exc=exc,
                work_item_id=self.work_item_id,
                transaction_id=self.transaction_id,
            )
            self._show_failure(exc, "儲存交易紀錄失敗，輸入內容保持不變。")
            self._busy = False
            self._set_form_enabled(True)
            self._focus_error(getattr(exc, "code", ""))

    def _show_failure(self, exc: BaseException, default: str) -> None:
        code = getattr(exc, "code", "") or (
            str(exc) if str(exc).startswith("annual_transactions.") else ""
        )
        self.feedback_label.setText(error_message(code) if code else default)

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (
            self.category_combo,
            self.transaction_date_input,
            self.amount_input,
            self.reference_input,
            self.notes_input,
            self.save_button,
        ):
            widget.setEnabled(enabled)

    def _focus_error(self, code: str) -> None:
        target = {
            "annual_transactions.category.invalid": self.category_combo,
            "annual_transactions.amount.invalid": self.amount_input,
            "annual_transactions.date.invalid": self.transaction_date_input,
            "annual_transactions.reference.invalid": self.reference_input,
            "annual_transactions.notes.invalid": self.notes_input,
        }.get(code)
        if target is not None:
            _schedule_focus(self, target)


class AnnualTransactionDeleteDialog(QDialog):
    """Collect a mandatory reason before one audited soft deletion."""

    committed = Signal()
    committed_evidence = Signal(object)

    def __init__(
        self,
        service: AnnualTransactionsService,
        transaction_id: int,
        *,
        system_log: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualTransactionDeleteDialog")
        self.setWindowTitle("刪除交易紀錄")
        self.setMinimumSize(460, 280)
        self._service = service
        self._system_log = system_log
        self.transaction_id = transaction_id
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        warning = QLabel(
            "此操作會保留交易與稽核軌跡，但不再納入帳務計算。"
            "請填寫刪除原因。"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.reason_input = QPlainTextEdit()
        self.reason_input.setObjectName("AnnualTransactionDeleteReason")
        self.reason_input.setPlaceholderText("必填，最多 4,000 字")
        self.reason_input.setMinimumHeight(100)
        layout.addWidget(self.reason_input)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.delete_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.cancel_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.delete_button.setText("確認刪除")
        self.cancel_button.setText("取消")
        layout.addWidget(self.button_box)
        self.delete_button.clicked.connect(self.delete_transaction)
        self.cancel_button.clicked.connect(self.reject)

    def delete_transaction(self) -> None:
        if self._busy:
            return
        reason = self.reason_input.toPlainText()
        if not reason.strip() or len(reason) > 4000:
            self.feedback_label.setText(
                error_message("annual_transactions.delete_reason.invalid")
            )
            self.reason_input.setFocus()
            return
        self._busy = True
        self.delete_button.setEnabled(False)
        self.reason_input.setEnabled(False)
        self.feedback_label.setText("處理中，正在刪除交易紀錄。")
        try:
            row = self._service.delete(self.transaction_id, reason)
            if row.id != self.transaction_id or row.deleted_at is None:
                raise RuntimeError("annual_transactions.delete.failed")
            self.committed_evidence.emit(
                AnnualTransactionCommitEvidence("delete", row)
            )
            self.committed.emit()
            self.accept()
        except Exception as exc:
            code = getattr(exc, "code", "") or (
                str(exc)
                if str(exc).startswith("annual_transactions.")
                else ""
            )
            _safe_system_log_error(
                self._system_log,
                "annual_transaction_ui.mutation.failed",
                operation="delete",
                exc=exc,
                transaction_id=self.transaction_id,
            )
            self.feedback_label.setText(
                error_message(code)
                if code
                else "刪除交易紀錄失敗，資料未變更。"
            )
            self._busy = False
            self.delete_button.setEnabled(True)
            self.reason_input.setEnabled(True)
            if code == "annual_transactions.delete_reason.invalid":
                _schedule_focus(self, self.reason_input)
