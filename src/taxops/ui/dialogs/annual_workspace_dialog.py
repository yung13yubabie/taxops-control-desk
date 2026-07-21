"""Preview, edit and confirm one client's annual workspace."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...repositories.annual_work import MAX_WORKSPACE_ITEMS
from ...services.annual_work import AnnualWorkError, AnnualWorkValidationError
from ...services.compliance_rules import WorkDraft
from ...services.container import ServiceContainer
from ..style import TEXT_MUTED
from ..widgets.annual_preview_table import AnnualPreviewTable


_SNAPSHOT_FAILURE = "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"


@dataclass
class _InputError(Exception):
    message: str
    widget: QWidget


class AnnualWorkspaceDialog(QDialog):
    def __init__(
        self,
        container: ServiceContainer,
        preselected_client_id: int | None = None,
        operation_year: int | None = None,
    ) -> None:
        super().__init__()
        self._container = container
        self._expected_drafts: tuple[WorkDraft, ...] = ()
        self._confirming = False
        self.setObjectName("AnnualWorkspaceDialog")
        self.setWindowTitle("建立年度工作")
        self.resize(900, 540)
        self.setMinimumSize(700, 450)
        font = self.font()
        font.setPixelSize(14)
        self.setFont(font)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(9)

        intro = QLabel(
            "先依客戶法遵檔案載入標準工作，可調整內容、取消不需要的項目，或新增自訂工作。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
        outer.addWidget(intro)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("客戶（必填）"))
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("AnnualWorkspaceClient")
        self.client_combo.setMinimumWidth(260)
        self.client_combo.addItem("請選擇客戶", None)
        try:
            clients = container.clients.list_clients(limit=500, offset=0)
        except Exception as exc:
            clients = []
            self._log_safe("annual_work.dialog.client_list_failed", exc)
        for client in clients:
            self.client_combo.addItem(
                f"{client.client_code}｜{client.client_name}", client.id
            )
        if preselected_client_id is not None:
            index = self.client_combo.findData(preselected_client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
        selector_row.addWidget(self.client_combo, 1)
        selector_row.addWidget(QLabel("作業年度"))
        self.operation_year_spin = QSpinBox()
        self.operation_year_spin.setObjectName("AnnualWorkspaceYear")
        self.operation_year_spin.setRange(1912, 9999)
        selected_year = (
            operation_year
            if type(operation_year) is int and 1912 <= operation_year <= 9999
            else datetime.date.today().year
        )
        self.operation_year_spin.setValue(selected_year)
        selector_row.addWidget(self.operation_year_spin)
        self.load_button = QPushButton("載入預覽")
        self.load_button.setObjectName("AnnualWorkspaceLoad")
        selector_row.addWidget(self.load_button)
        outer.addLayout(selector_row)

        self.preview_table = AnnualPreviewTable()
        outer.addWidget(self.preview_table, 1)

        table_actions = QHBoxLayout()
        self.add_custom_button = QPushButton("新增自訂列")
        self.add_custom_button.setObjectName("AnnualWorkspaceAddCustom")
        self.add_custom_button.setEnabled(False)
        table_actions.addWidget(self.add_custom_button)
        table_actions.addStretch(1)
        outer.addLayout(table_actions)

        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("AnnualWorkspaceFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        outer.addWidget(self.feedback_label)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("AnnualWorkspaceCancel")
        self.confirm_button = QPushButton("確認建立")
        self.confirm_button.setObjectName("AnnualWorkspaceConfirm")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setDefault(True)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.confirm_button)
        outer.addLayout(bottom)

        self.load_button.clicked.connect(self._load_preview)
        self.add_custom_button.clicked.connect(self._add_custom)
        self.confirm_button.clicked.connect(self._confirm)
        self.cancel_button.clicked.connect(self.reject)
        self.client_combo.currentIndexChanged.connect(self._invalidate_preview)
        self.operation_year_spin.valueChanged.connect(self._invalidate_preview)
        self.preview_table.selection_changed.connect(self._update_confirm_enabled)

    @property
    def expected_drafts(self) -> tuple[WorkDraft, ...]:
        return self._expected_drafts

    def _log_safe(self, message: str, exc: Exception | None = None) -> None:
        try:
            self._container.system_log.error(message, exc=exc)
        except Exception:
            pass

    def _invalidate_preview(self, _value: object = None) -> None:
        if not self._expected_drafts and self.preview_table.rowCount() == 0:
            return
        self._expected_drafts = ()
        self.preview_table.clear_drafts()
        self.add_custom_button.setEnabled(False)
        self.confirm_button.setEnabled(False)
        self.feedback_label.setText("客戶或作業年度已變更，請重新載入預覽。")

    def _selected_client_id(self) -> int | None:
        value = self.client_combo.currentData()
        return value if type(value) is int and value > 0 else None

    def _load_preview(self) -> None:
        if self._confirming:
            return
        client_id = self._selected_client_id()
        if client_id is None:
            self.feedback_label.setText("請先選擇客戶。")
            self.client_combo.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self.load_button.setEnabled(False)
        self.feedback_label.setText("處理中，正在載入年度工作預覽。")
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            drafts = tuple(
                self._container.annual_work.preview(
                    client_id, self.operation_year_spin.value()
                )
            )
            self._expected_drafts = drafts
            self.preview_table.set_standard_drafts(drafts)
            self.add_custom_button.setEnabled(True)
            self.feedback_label.setText(f"已載入 {len(drafts)} 項年度工作預覽。")
            self._update_confirm_enabled()
        except Exception as exc:
            self._expected_drafts = ()
            self.preview_table.clear_drafts()
            self.add_custom_button.setEnabled(False)
            self.confirm_button.setEnabled(False)
            self.feedback_label.setText(self._error_text(exc, loading=True))
            self._log_safe("annual_work.dialog.preview_failed", exc)
        finally:
            self.load_button.setEnabled(True)

    def _add_custom(self) -> None:
        if self._confirming or not self._expected_drafts:
            return
        if self.preview_table.rowCount() >= MAX_WORKSPACE_ITEMS:
            self.feedback_label.setText("項目數超過上限 500，請減少後再試。")
            return
        self.preview_table.add_custom_draft(self.operation_year_spin.value())
        self._update_confirm_enabled()

    def _update_confirm_enabled(self) -> None:
        self.confirm_button.setEnabled(
            not self._confirming and bool(self._expected_drafts)
        )

    def _selected_drafts(self) -> tuple[WorkDraft, ...]:
        selected: list[WorkDraft] = []
        year = self.operation_year_spin.value()
        for row in range(self.preview_table.rowCount()):
            if not self.preview_table.is_checked(row):
                continue
            widgets = self.preview_table.row_widgets(row)
            title = widgets.title.text().strip()
            if not title:
                raise _InputError("工作標題不可空白。", widgets.title)
            if len(title) > 500:
                raise _InputError("工作標題不可超過 500 字。", widgets.title)
            raw_year = widgets.tax_year.text().strip()
            if raw_year:
                try:
                    tax_year = int(raw_year)
                except ValueError:
                    raise _InputError("稅務年度須為 1912 至 9999。", widgets.tax_year)
                if not 1912 <= tax_year <= 9999:
                    raise _InputError("稅務年度須為 1912 至 9999。", widgets.tax_year)
            if len(widgets.period_code.text().strip()) > 50:
                raise _InputError("期間不可超過 50 字。", widgets.period_code)
            raw_due = widgets.due_date.text().strip()
            if raw_due:
                try:
                    normalized = datetime.date.fromisoformat(raw_due).isoformat()
                except ValueError:
                    raise _InputError("到期日須為 YYYY-MM-DD 格式。", widgets.due_date)
                if normalized != raw_due:
                    raise _InputError("到期日須為 YYYY-MM-DD 格式。", widgets.due_date)
            selected.append(self.preview_table.draft_for_row(row, year))
        if not selected:
            raise _InputError("請至少勾選一項年度工作。", self.preview_table)
        return tuple(selected)

    def _set_payload_enabled(self, enabled: bool) -> None:
        self.client_combo.setEnabled(enabled)
        self.operation_year_spin.setEnabled(enabled)
        self.load_button.setEnabled(enabled)
        self.add_custom_button.setEnabled(enabled and bool(self._expected_drafts))
        self.preview_table.set_payload_enabled(enabled)
        self.cancel_button.setEnabled(enabled)
        if enabled:
            self._update_confirm_enabled()
        else:
            self.confirm_button.setEnabled(False)

    def _confirm(self) -> None:
        if self._confirming:
            return
        self._confirming = True
        self._set_payload_enabled(False)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            client_id = self._selected_client_id()
            if client_id is None:
                raise _InputError("請先選擇客戶。", self.client_combo)
            if not self._expected_drafts:
                raise _InputError("預覽已過期，請重新載入後再試。", self.load_button)
            selected = self._selected_drafts()
        except _InputError as exc:
            self._confirming = False
            self._set_payload_enabled(True)
            self.feedback_label.setText(exc.message)
            exc.widget.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        try:
            result = self._container.annual_work.confirm_preview_selection(
                client_id,
                self.operation_year_spin.value(),
                expected_drafts=self._expected_drafts,
                selected_drafts=selected,
            )
        except Exception as exc:
            self.feedback_label.setText(self._error_text(exc, loading=False))
            self._log_safe("annual_work.dialog.confirm_failed", exc)
            self._confirming = False
            self._set_payload_enabled(True)
            return

        try:
            snapshot = self._container.annual_work.get_workspace_snapshot(
                client_id, self.operation_year_spin.value()
            )
            selected_keys = {draft.item_key for draft in selected}
            if (
                snapshot is None
                or snapshot.workspace.id != result.workspace.id
                or not selected_keys.issubset(
                    {item.item_key for item in snapshot.items}
                )
            ):
                raise RuntimeError("annual workspace snapshot mismatch")
        except Exception as exc:
            self.feedback_label.setText(_SNAPSHOT_FAILURE)
            self._log_safe("annual_work.dialog.snapshot_verify_failed", exc)
            self._confirming = False
            self._set_payload_enabled(True)
            return

        if result.inserted_item_count > 0:
            self.feedback_label.setText(
                f"建立成功，已新增 {result.inserted_item_count} 項年度工作。"
            )
        else:
            self.feedback_label.setText("此年度工作已存在，未新增重複資料。")
        self.accept()

    @staticmethod
    def _error_text(exc: Exception, *, loading: bool) -> str:
        code = exc.code if isinstance(exc, AnnualWorkError) else ""
        if code == "annual_work.profile_not_found":
            return "此客戶尚未設定年度法遵檔案。"
        if code == "annual_work.enabled_items.empty":
            return "此客戶的年度法遵檔案未啟用任何工作類型。"
        if code in {
            "annual_work.drafts.profile_mismatch",
            "annual_work.profile_mismatch",
        }:
            return "預覽已過期，請重新載入後再試。"
        if code == "annual_work.transaction.busy":
            return "資料庫忙碌中，請稍後再試。"
        if "too_many" in code:
            return "項目數超過上限 500，請減少後再試。"
        if code == "annual_work.client_not_found":
            return "所選客戶不存在或已停用，請重新選擇。"
        if isinstance(exc, AnnualWorkValidationError):
            return "輸入資料驗證失敗，請檢查後再試。"
        return "載入預覽失敗，請稍後再試。" if loading else "建立年度工作失敗，請稍後再試。"
