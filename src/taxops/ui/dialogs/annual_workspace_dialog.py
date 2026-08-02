"""Preview, edit and confirm one client's annual workspace."""

from __future__ import annotations

import datetime
import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
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
from ...services.annual_work import (
    AnnualWorkError,
    AnnualWorkValidationError,
    AnnualWorkspaceResult,
    AnnualWorkspaceSnapshot,
)
from ...services.compliance_rules import WorkDraft
from ...services.container import ServiceContainer
from ..style import TEXT_MUTED
from .compliance_profile_dialog import ComplianceProfileDialog
from ..widgets.annual_preview_table import AnnualPreviewTable
from ..workers.annual_client_search import (
    AnnualClientSearchResult,
    AnnualClientSearchWorker,
    annual_client_search_coordinator,
)


_SNAPSHOT_FAILURE = "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
_PRECHECK_FAILURE = "無法讀取目前的年度工作，請稍後再試。"
_CLIENT_RESULT_LIMIT = 100


@dataclass
class _InputError(Exception):
    message: str
    widget: QWidget


def _verify_confirmed_snapshot(
    before: AnnualWorkspaceSnapshot | None,
    result: AnnualWorkspaceResult,
    after: AnnualWorkspaceSnapshot | None,
    selected: tuple[WorkDraft, ...],
) -> None:
    """Verify the full persisted result without mutating UI or database state."""
    if after is None:
        raise RuntimeError("annual workspace snapshot missing")
    before_keys = (
        {item.item_key for item in before.items} if before is not None else set()
    )
    selected_by_key = {draft.item_key: draft for draft in selected}
    selected_keys = set(selected_by_key)
    snapshot_by_key = {item.item_key: item for item in after.items}
    result_item_ids = {item.item_key: item.id for item in result.items}
    snapshot_item_ids = {item.item_key: item.id for item in after.items}
    new_keys = selected_keys - before_keys
    if (
        after.workspace.id != result.workspace.id
        or len(after.items) != len(result.items)
        or snapshot_item_ids != result_item_ids
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
        self._loading = False
        self._search_request_token = 0
        self._search_workers: dict[int, AnnualClientSearchWorker] = {}
        self._pending_search: tuple[int, str, int | None] | None = None
        self._search_coordinator = annual_client_search_coordinator()
        self._close_after_search = False
        self._accept_after_search = False
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
        self.profile_button = QPushButton("設定法遵檔案")
        self.profile_button.setObjectName("AnnualWorkspaceProfile")
        outer.addLayout(selector_row)

        self.preview_table = AnnualPreviewTable()
        outer.addWidget(self.preview_table, 1)

        table_actions = QHBoxLayout()
        table_actions.addWidget(self.profile_button)
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
        self.client_search_input.textChanged.connect(
            self._on_search_query_changed
        )
        self.load_button.clicked.connect(self._load_preview)
        self.profile_button.clicked.connect(self._open_profile)
        self.add_custom_button.clicked.connect(self._add_custom)
        self.confirm_button.clicked.connect(self._confirm)
        self.cancel_button.clicked.connect(self.reject)
        self.client_combo.currentIndexChanged.connect(self._invalidate_preview)
        self.operation_year_spin.valueChanged.connect(self._invalidate_preview)
        self.preview_table.selection_changed.connect(self._update_confirm_enabled)
        if (
            type(preselected_client_id) is int
            and preselected_client_id > 0
        ):
            self.client_combo.addItem("正在載入客戶…", preselected_client_id)
            self.client_combo.setCurrentIndex(0)
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

    def _open_profile(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            self.feedback_label.setText("請先選擇客戶，再設定年度法遵檔案。")
            self.client_combo.setFocus()
            return
        dialog = ComplianceProfileDialog(
            self._container,
            preselected_client_id=client_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.feedback_label.setText("年度法遵設定已儲存，正在重新載入預覽。")
            self._load_preview()

    def _search_clients(
        self,
        _checked: bool = False,
        *,
        preselected_client_id: int | None = None,
    ) -> None:
        if self._confirming or self._close_after_search:
            return
        self._invalidate_preview()
        self._search_request_token += 1
        token = self._search_request_token
        request = (
            token,
            self.client_search_input.text().strip(),
            preselected_client_id,
        )
        if self._search_workers:
            self._pending_search = request
            for worker in tuple(self._search_workers.values()):
                worker.cancel()
            self.feedback_label.setText("正在切換搜尋條件…")
            return
        self._start_client_search(request)

    def _start_client_search(
        self, request: tuple[int, str, int | None]
    ) -> None:
        token, query, preselected_client_id = request
        worker = AnnualClientSearchWorker(
            str(self._container.paths.db_path),
            query,
            token,
            limit=_CLIENT_RESULT_LIMIT,
            preselected_client_id=preselected_client_id,
        )
        self._search_coordinator.register(worker)
        self._search_workers[token] = worker
        self.client_combo.setEnabled(False)
        self.load_button.setEnabled(False)
        self.feedback_label.setText("正在搜尋客戶…")
        worker.succeeded.connect(self._on_client_search_succeeded)
        worker.errored.connect(self._on_client_search_errored)
        worker.finished.connect(self._on_client_search_worker_finished)
        worker.start()

    def _on_search_query_changed(self, _text: str) -> None:
        self._invalidate_preview()
        self._search_request_token += 1
        self._pending_search = None
        self.client_combo.clear()
        self.client_combo.addItem("搜尋條件已變更，請重新搜尋", None)
        self.feedback_label.setText("搜尋條件已變更，請重新搜尋。")
        for worker in tuple(self._search_workers.values()):
            worker.cancel()

    def _on_client_search_succeeded(
        self, result: AnnualClientSearchResult
    ) -> None:
        if (
            result.request_token != self._search_request_token
            or result.normalized_query
            != self.client_search_input.text().strip()
        ):
            return
        self.client_combo.clear()
        self.client_combo.addItem("請選擇客戶", None)
        for client in result.choices:
            self.client_combo.addItem(
                f"{client.client_code}｜{client.client_name}", client.id
            )
        if result.preselected is not None:
            selected_index = self.client_combo.findData(result.preselected.id)
            if selected_index < 0:
                self.client_combo.insertItem(
                    1,
                    (
                        f"{result.preselected.client_code}｜"
                        f"{result.preselected.client_name}"
                    ),
                    result.preselected.id,
                )
                selected_index = 1
            self.client_combo.setCurrentIndex(selected_index)
        if result.has_more:
            self.feedback_label.setText(
                "結果超過 100 筆，僅顯示前 100 筆，請輸入更精確關鍵字。"
            )
        else:
            self.feedback_label.setText(
                f"找到 {len(result.choices)} 筆客戶。"
            )

    def _on_client_search_errored(self, token: int, _code: str) -> None:
        if token != self._search_request_token:
            return
        self.client_combo.clear()
        self.feedback_label.setText("載入客戶失敗，請稍後再試。")
        self._log_safe("annual_work.dialog.client_search_failed")

    def _on_client_search_worker_finished(self) -> None:
        worker = self.sender()
        if not isinstance(worker, AnnualClientSearchWorker):
            return
        token = worker.request_token
        worker = self._search_workers.pop(token, None)
        if (
            self._pending_search is not None
            and not self._close_after_search
            and not self._accept_after_search
        ):
            pending = self._pending_search
            self._pending_search = None
            self._start_client_search(pending)
            return
        if token == self._search_request_token:
            self.client_search_button.setEnabled(
                not self._close_after_search and not self._accept_after_search
            )
        if not self._search_workers:
            controls_enabled = (
                not self._close_after_search and not self._accept_after_search
            )
            self.client_combo.setEnabled(controls_enabled)
            self.load_button.setEnabled(controls_enabled)
        if not self._search_workers:
            if self._accept_after_search:
                QDialog.accept(self)
            elif self._close_after_search:
                QDialog.reject(self)

    def accept(self) -> None:
        if self._search_workers:
            self._accept_after_search = True
            self._pending_search = None
            self.client_search_button.setEnabled(False)
            for worker in tuple(self._search_workers.values()):
                worker.cancel()
            return
        super().accept()

    def reject(self) -> None:
        if self._search_workers:
            self._close_after_search = True
            self._pending_search = None
            self.client_search_button.setEnabled(False)
            self.feedback_label.setText("正在停止客戶搜尋，請稍候…")
            for worker in tuple(self._search_workers.values()):
                worker.cancel()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._search_workers:
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)

    def _load_preview(self) -> None:
        if self._confirming or self._loading:
            return
        self._loading = True
        client_id = self._selected_client_id()
        if client_id is None:
            self.feedback_label.setText("請先選擇客戶。")
            self.client_combo.setFocus(Qt.FocusReason.OtherFocusReason)
            self._loading = False
            return
        self.load_button.setEnabled(False)
        self.feedback_label.setText("處理中，正在載入年度工作預覽。")
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
            self._loading = False
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
            if any(
                unicodedata.category(char) in {"Cc", "Cf"} for char in title
            ):
                raise _InputError("欄位不可包含控制或隱藏字元", widgets.title)
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
            period_code = widgets.period_code.text().strip()
            if any(
                unicodedata.category(char) in {"Cc", "Cf"}
                for char in period_code
            ):
                raise _InputError("欄位不可包含控制或隱藏字元", widgets.period_code)
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
            focus = (
                self.preview_table.row_widgets(0).selected
                if self.preview_table.rowCount()
                else self.preview_table
            )
            raise _InputError("請至少勾選一項年度工作。", focus)
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

    def _restore_after_confirm_failure(
        self,
        message: str,
        *,
        log_event: str | None = None,
        exc: Exception | None = None,
        focus: QWidget | None = None,
    ) -> None:
        self.feedback_label.setText(message)
        if log_event is not None:
            self._log_safe(log_event, exc)
        self._confirming = False
        self._set_payload_enabled(True)
        if focus is not None:
            focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def _confirm(self) -> None:
        if self._confirming:
            return
        self._confirming = True
        self._set_payload_enabled(False)
        try:
            client_id = self._selected_client_id()
            if client_id is None:
                raise _InputError("請先選擇客戶。", self.client_combo)
            if not self._expected_drafts:
                raise _InputError("預覽已過期，請重新載入後再試。", self.load_button)
            selected = self._selected_drafts()
        except _InputError as exc:
            self._restore_after_confirm_failure(
                exc.message, focus=exc.widget
            )
            return

        try:
            before_snapshot = self._container.annual_work.get_workspace_snapshot(
                client_id, self.operation_year_spin.value()
            )
        except Exception as exc:
            self._restore_after_confirm_failure(
                _PRECHECK_FAILURE,
                log_event="annual_work.dialog.snapshot_precheck_failed",
                exc=exc,
            )
            return

        try:
            result = self._container.annual_work.confirm_preview_selection(
                client_id,
                self.operation_year_spin.value(),
                expected_drafts=self._expected_drafts,
                selected_drafts=selected,
            )
        except Exception as exc:
            self._restore_after_confirm_failure(
                self._error_text(exc, loading=False),
                log_event="annual_work.dialog.confirm_failed",
                exc=exc,
            )
            return

        try:
            snapshot = self._container.annual_work.get_workspace_snapshot(
                client_id, self.operation_year_spin.value()
            )
            _verify_confirmed_snapshot(
                before_snapshot, result, snapshot, selected
            )
        except Exception as exc:
            self._restore_after_confirm_failure(
                _SNAPSHOT_FAILURE,
                log_event="annual_work.dialog.snapshot_verify_failed",
                exc=exc,
            )
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
