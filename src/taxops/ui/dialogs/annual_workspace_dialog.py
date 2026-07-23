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
    QLineEdit,
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
_PRECHECK_FAILURE = "無法讀取目前的年度工作，請稍後再試。"
_CLIENT_SEARCH_FAILURE = "載入客戶失敗，請稍後再試。"
_CLIENT_RESULT_LIMIT = 100


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._expected_drafts: tuple[WorkDraft, ...] = ()
        self._confirming = False
        self.setObjectName("AnnualWorkspaceDialog")
        self.setWindowTitle("建立年度工作")
        self.setModal(True)
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

        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("AnnualWorkspaceFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("客戶（必填）"))
        self.client_search_input = QLineEdit()
        self.client_search_input.setObjectName("AnnualWorkspaceClientSearch")
        self.client_search_input.setPlaceholderText("輸入客戶代號或名稱")
        self.client_search_input.setMaxLength(100)
        self.client_search_input.setMinimumWidth(130)
        selector_row.addWidget(self.client_search_input)
        self.client_search_button = QPushButton("搜尋客戶")
        self.client_search_button.setObjectName("AnnualWorkspaceClientSearchButton")
        selector_row.addWidget(self.client_search_button)
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("AnnualWorkspaceClient")
        self.client_combo.setMinimumWidth(220)
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

        self.client_search_button.clicked.connect(self._search_clients)
        self.client_search_input.returnPressed.connect(self._search_clients)
        self.client_search_input.textChanged.connect(self._invalidate_preview)
        self.load_button.clicked.connect(self._load_preview)
        self.add_custom_button.clicked.connect(self._add_custom)
        self.confirm_button.clicked.connect(self._confirm)
        self.cancel_button.clicked.connect(self.reject)
        self.client_combo.currentIndexChanged.connect(self._invalidate_preview)
        self.operation_year_spin.valueChanged.connect(self._invalidate_preview)
        self.preview_table.selection_changed.connect(self._update_confirm_enabled)
        self._search_clients(preselected_client_id=preselected_client_id)

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

    def _search_clients(
        self,
        _checked: bool = False,
        *,
        preselected_client_id: int | None = None,
    ) -> None:
        if self._confirming:
            return
        self._invalidate_preview()
        query = self.client_search_input.text().strip()
        self.client_search_button.setEnabled(False)
        self.feedback_label.setText("處理中，正在搜尋客戶。")
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            total = self._container.clients.count_clients(
                query,
                include_deleted=False,
                has_note=False,
            )
            clients = self._container.clients.search_clients(
                query,
                order_by="client_code",
                order_dir="ASC",
                limit=_CLIENT_RESULT_LIMIT,
                offset=0,
                include_deleted=False,
                has_note=False,
            )
            selected_client = None
            if type(preselected_client_id) is int and preselected_client_id > 0:
                selected_client = self._container.clients.get_client(
                    preselected_client_id
                )
        except Exception as exc:
            self.client_combo.clear()
            self.feedback_label.setText(_CLIENT_SEARCH_FAILURE)
            self._log_safe("annual_work.dialog.client_search_failed", exc)
            self.client_search_button.setEnabled(True)
            return

        self.client_combo.clear()
        self.client_combo.addItem("請選擇客戶", None)
        for client in clients:
            self.client_combo.addItem(
                f"{client.client_code}｜{client.client_name}", client.id
            )
        if selected_client is not None:
            selected_index = self.client_combo.findData(selected_client.id)
            if selected_index < 0:
                self.client_combo.insertItem(
                    1,
                    f"{selected_client.client_code}｜{selected_client.client_name}",
                    selected_client.id,
                )
                selected_index = 1
            self.client_combo.setCurrentIndex(selected_index)
        if total > _CLIENT_RESULT_LIMIT:
            self.feedback_label.setText(
                f"找到 {total} 位客戶，目前顯示前 {_CLIENT_RESULT_LIMIT} 位，"
                "請輸入更完整的代號或名稱。"
            )
        else:
            self.feedback_label.setText(f"找到 {total} 位客戶。")
        self.client_search_button.setEnabled(True)

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
        self.client_search_input.setEnabled(enabled)
        self.client_search_button.setEnabled(enabled)
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
            before_snapshot = self._container.annual_work.get_workspace_snapshot(
                client_id, self.operation_year_spin.value()
            )
            before_keys = (
                {item.item_key for item in before_snapshot.items}
                if before_snapshot is not None
                else set()
            )
        except Exception as exc:
            self.feedback_label.setText(_PRECHECK_FAILURE)
            self._log_safe("annual_work.dialog.snapshot_precheck_failed", exc)
            self._confirming = False
            self._set_payload_enabled(True)
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
            if snapshot is None:
                raise RuntimeError("annual workspace snapshot missing")
            selected_by_key = {draft.item_key: draft for draft in selected}
            selected_keys = set(selected_by_key)
            snapshot_by_key = {item.item_key: item for item in snapshot.items}
            new_keys = selected_keys - before_keys
            if (
                snapshot.workspace.id != result.workspace.id
                or not selected_keys.issubset(snapshot_by_key)
                or len(new_keys) != result.inserted_item_count
            ):
                raise RuntimeError("annual workspace snapshot mismatch")
            for item_key in new_keys:
                draft = selected_by_key[item_key]
                item = snapshot_by_key[item_key]
                if (
                    item.work_type != draft.work_type
                    or item.title != draft.title
                    or item.tax_year != draft.tax_year
                    or item.period_code != draft.period_code
                    or item.suggested_due_date != draft.suggested_due_date
                    or item.due_date != draft.suggested_due_date
                ):
                    raise RuntimeError("annual workspace item verification mismatch")
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
