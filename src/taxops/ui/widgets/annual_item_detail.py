"""Editable annual-work detail backed only by ``AnnualWorkService``."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...i18n.errors import error_message
from ...services.container import ServiceContainer
from .annual_item_fields import AnnualItemFields


_TERMINAL_WORK_STATUSES = frozenset(
    {"completed", "completed_with_exception", "cancelled"}
)


class AnnualItemDetail(QWidget):
    """Form for one persisted annual item.

    The widget keeps only the optimistic-lock token required by the public
    service contract. After every successful mutation it re-reads the item.
    """

    saved = Signal()
    mutation_committed = Signal()

    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualItemDetail")
        self._container = container
        self.item_id = item_id
        self.updated_at_token = ""
        self._busy = False
        self._load_valid = False
        self._work_status = ""
        self._pending_focus: QWidget | None = None

        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("AnnualItemFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        outer.addWidget(self.feedback_label)

        self.fields = AnnualItemFields(self._container.annual_work, self)
        self.scroll_area = self.fields
        outer.addWidget(self.fields, 1)
        for name in (
            "client_label",
            "operation_year_input",
            "suggested_due_date_input",
            "title_input",
            "tax_year_input",
            "period_code_input",
            "due_date_input",
            "notes_input",
            "transition_reason_input",
            "transition_hint",
            "work_status_combo",
            "filing_status_combo",
            "document_status_combo",
            "tax_status_combo",
            "fee_status_combo",
        ):
            setattr(self, name, getattr(self.fields, name))

        action_row = QHBoxLayout()
        self.complete_button = QPushButton("完成工作")
        self.cancel_button = QPushButton("取消此工作")
        self.restore_button = QPushButton("還原")
        self.reopen_button = QPushButton("重新開啟")
        self.retry_read_button = QPushButton("重新讀取")
        self.save_button = QPushButton("儲存明細")
        for button in (
            self.complete_button,
            self.cancel_button,
            self.restore_button,
            self.reopen_button,
        ):
            button.hide()
        action_row.addWidget(self.complete_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.reopen_button)
        self.retry_read_button.hide()
        action_row.addWidget(self.retry_read_button)
        action_row.addStretch(1)
        action_row.addWidget(self.save_button)
        outer.addLayout(action_row)

        self.save_button.clicked.connect(self.save)
        self.complete_button.clicked.connect(self.complete)
        self.cancel_button.clicked.connect(self.cancel_item)
        self.restore_button.clicked.connect(self.restore)
        self.reopen_button.clicked.connect(self.reopen)
        self.retry_read_button.clicked.connect(self.retry_read)
        self._load()

    def _load(self, *, after_commit: bool = False) -> bool:
        try:
            context = self._container.annual_work.get_item_context(self.item_id)
            client = self._container.clients.get_client(context.client_id)
            if client is None:
                raise RuntimeError("client context missing")
            item = context.item
            self._container.annual_work.present_statuses(item)
            self.fields.set_values(client, context)
            self.updated_at_token = item.updated_at
            self._work_status = item.work_status
            self._load_valid = True
            self.feedback_label.clear()
            self._apply_control_state()
            return True
        except Exception as exc:
            self._load_valid = False
            if after_commit:
                self.feedback_label.setText(
                    "資料已寫入但重新讀取失敗；為避免覆寫新資料，"
                    "編輯操作已停用，請重新讀取或關閉視窗。"
                )
                self._log_failure(exc)
            else:
                self._show_failure(
                    exc, default="讀取年度工作明細失敗，請稍後再試。"
                )
            self._apply_control_state()
            return False

    def reload(self) -> None:
        """Re-read this item through the public service."""
        self._load()

    def retry_read(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "處理中，正在重新讀取年度工作明細。")
        try:
            if self._load():
                self.feedback_label.setText("年度工作明細已重新讀取。")
        finally:
            self._set_busy(False)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _update_transition_controls(self, work_status: str) -> None:
        terminal = work_status in _TERMINAL_WORK_STATUSES
        self.complete_button.setVisible(not terminal)
        self.cancel_button.setVisible(not terminal)
        self.restore_button.setVisible(work_status == "cancelled")
        self.reopen_button.setVisible(
            work_status in {"completed", "completed_with_exception"}
        )
        enabled = self._load_valid and not self._busy
        for button in (
            self.complete_button,
            self.cancel_button,
            self.restore_button,
            self.reopen_button,
        ):
            button.setEnabled(enabled)
        self.work_status_combo.setEnabled(enabled and not terminal)

    def save(self) -> bool:
        """Save the form and emit ``saved`` for the dialog's close-on-save path."""
        return self._save(emit_saved=True)

    def save_in_place(self) -> bool:
        """Save the form without closing its parent dialog."""
        return self._save(emit_saved=False)

    def _save(self, *, emit_saved: bool) -> bool:
        if self._busy:
            return False
        self._set_busy(True, "處理中，正在儲存年度工作明細。")
        try:
            previous_token = self.updated_at_token
            updated = self._container.annual_work.update_item_details(
                self.item_id, self.fields.payload(self.updated_at_token)
            )
            committed = self._record_mutation(updated, previous_token)
            if not self._load(after_commit=committed):
                return False
            self.feedback_label.setText("年度工作明細已儲存。")
            if emit_saved:
                self.saved.emit()
            return True
        except Exception as exc:
            self._show_failure(exc, default="儲存失敗，輸入內容保持不變。")
            self._focus_error(getattr(exc, "code", ""))
            return False
        finally:
            self._set_busy(False)

    def complete(self) -> None:
        reason = self.transition_reason_input.toPlainText()
        self._run_transition(
            lambda: self._container.annual_work.complete_item(
                self.item_id,
                exception_reason=reason or None,
            ),
            processing="處理中，正在完成年度工作。",
            success=lambda: (
                "年度工作已例外完成。"
                if self._work_status == "completed_with_exception"
                else "年度工作已完成。"
            ),
            action_name="完成年度工作",
        )

    def cancel_item(self) -> None:
        reason = self.transition_reason_input.toPlainText()
        self._run_transition(
            lambda: self._container.annual_work.cancel_item(
                self.item_id, reason
            ),
            processing="處理中，正在取消年度工作。",
            success="年度工作已取消。",
            action_name="取消年度工作",
        )

    def restore(self) -> None:
        self._run_transition(
            lambda: self._container.annual_work.restore_item(self.item_id),
            processing="處理中，正在還原年度工作。",
            success="年度工作已還原。",
            action_name="還原年度工作",
        )

    def reopen(self) -> None:
        self._run_transition(
            lambda: self._container.annual_work.set_work_status(
                self.item_id, "in_progress"
            ),
            processing="處理中，正在重新開啟年度工作。",
            success="年度工作已重新開啟。",
            action_name="重新開啟年度工作",
        )

    def _run_transition(
        self,
        operation,
        *,
        processing: str,
        success: str | Callable[[], str],
        action_name: str,
    ) -> None:
        if self._busy:
            return
        self._set_busy(True, processing)
        details_committed = False
        operation_started = False
        try:
            previous_token = self.updated_at_token
            updated = self._container.annual_work.update_item_details(
                self.item_id, self.fields.payload(previous_token)
            )
            details_committed = self._record_mutation(
                updated, previous_token
            )
            operation_started = True
            transition_token = self.updated_at_token
            transitioned = operation()
            transition_committed = self._record_mutation(
                transitioned, transition_token
            )
            if not self._load(
                after_commit=details_committed or transition_committed
            ):
                return
            self.feedback_label.setText(
                success() if callable(success) else success
            )
            self.saved.emit()
        except Exception as exc:
            if details_committed and operation_started:
                self.feedback_label.setText(
                    f"明細已儲存，但{action_name}失敗；"
                    "目前內容已保留，請確認後重試。"
                )
                self._log_failure(exc)
                self._pending_focus = self.transition_reason_input
            else:
                self._show_failure(
                    exc, default="操作失敗，輸入內容保持不變。"
                )
                if operation_started:
                    self._pending_focus = self.transition_reason_input
                else:
                    self._focus_error(getattr(exc, "code", ""))
        finally:
            self._set_busy(False)

    def _record_mutation(self, item, previous_token: str) -> bool:
        self.updated_at_token = item.updated_at
        self._work_status = item.work_status
        committed = item.updated_at != previous_token
        if committed:
            self.mutation_committed.emit()
        return committed

    def _focus_error(self, code: str) -> None:
        self._pending_focus = self.fields.focus_for_error(code)

    def _show_failure(self, exc: BaseException, *, default: str) -> None:
        code = getattr(exc, "code", "")
        text = error_message(code) if code else default
        self.feedback_label.setText(text)
        self._log_failure(exc)

    def _log_failure(self, exc: BaseException) -> None:
        try:
            self._container.system_log.error(
                "annual_work.item.ui_failed", exc=exc
            )
        except Exception:
            pass

    def _set_form_enabled(self, enabled: bool) -> None:
        for field in (*self.fields.editable_widgets, self.save_button):
            field.setEnabled(enabled)

    def _apply_control_state(self) -> None:
        enabled = self._load_valid and not self._busy
        self._set_form_enabled(enabled)
        self.retry_read_button.setVisible(not self._load_valid)
        self.retry_read_button.setEnabled(not self._busy)
        self._update_transition_controls(self._work_status)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self._apply_control_state()
        if busy:
            self.feedback_label.setText(message)
            self.feedback_label.repaint()
        else:
            if self._pending_focus is not None:
                target = self._pending_focus
                if isValid(self) and isValid(target):
                    self.scroll_area.ensureWidgetVisible(target)
                QTimer.singleShot(
                    0,
                    lambda: _focus_if_valid(self, target),
                )
                self._pending_focus = None


def _focus_if_valid(owner: QWidget, target: QWidget) -> None:
    if isValid(owner) and isValid(target):
        target.setFocus(Qt.FocusReason.OtherFocusReason)
