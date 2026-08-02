"""Scrollable atomic client-profile creation dialog."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n import BUTTON_LABELS, error_message
from ...repositories.tax_registry import TaxRegistryRepository
from ...services.client_leases import LeaseInput
from ...services.client_profiles import ClientProfileValidationError
from ...services.registry.industries import (
    industries_from_registry,
    primary_industry_display,
)
from ...services.clients import ClientValidationError, ClientsService, CreateClientInput
from ..widgets.client_leases_editor import ClientLeasesEditor
from ..widgets.client_profile_form import ClientProfileForm
from ..widgets.date_field import DateField
from ..workers.local_registry_search import LocalRegistrySearchWorker

_log = logging.getLogger(__name__)


class NewClientDialog(QDialog):
    def __init__(
        self,
        services: object,
        parent: QWidget | None = None,
        tax_registry_repo: TaxRegistryRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = services if hasattr(services, "client_profiles") else None
        self._clients: ClientsService = (
            services.clients if self._container is not None else services
        )  # type: ignore[assignment]
        self._registry_repo = tax_registry_repo
        self._registry_results: list = []
        self._registry_prefill: dict | None = None
        self._registry_industries = ()
        self._local_worker: LocalRegistrySearchWorker | None = None
        self.setWindowTitle("新增客戶")
        self.setModal(True)
        self.resize(760, 720)
        self.setMinimumSize(620, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(14)

        if self._registry_repo is not None:
            lookup_box = QGroupBox(
                "從稅籍資料庫查詢（統編、公司名稱或行業代碼／名稱）"
            )
            lookup_layout = QVBoxLayout(lookup_box)
            search_row = QHBoxLayout()
            self._search_input = QLineEdit()
            self._search_input.setPlaceholderText(
                "統一編號（8位數字）、公司名稱或行業代碼／名稱"
            )
            self._search_btn = QPushButton("查詢")
            search_row.addWidget(self._search_input, 1)
            search_row.addWidget(self._search_btn)
            lookup_layout.addLayout(search_row)
            result_row = QHBoxLayout()
            self._result_combo = QComboBox()
            self._result_combo.setPlaceholderText("查詢後選擇結果")
            self._result_combo.setEnabled(False)
            self._fill_btn = QPushButton("帶入登記資料")
            self._fill_btn.setEnabled(False)
            result_row.addWidget(self._result_combo, 1)
            result_row.addWidget(self._fill_btn)
            lookup_layout.addLayout(result_row)
            self._search_status = QLabel("")
            self._search_status.setTextFormat(Qt.TextFormat.PlainText)
            self._search_status.setWordWrap(True)
            lookup_layout.addWidget(self._search_status)
            content_layout.addWidget(lookup_box)
            self._search_btn.clicked.connect(self._on_search)
            self._fill_btn.clicked.connect(self._on_fill)
            self._search_input.returnPressed.connect(self._on_search)

        profile_group = QGroupBox("客戶基本與聯絡資料")
        profile_layout = QVBoxLayout(profile_group)
        self.profile_form = ClientProfileForm()
        profile_layout.addWidget(self.profile_form)
        content_layout.addWidget(profile_group)

        lease_group = QGroupBox("租約明細")
        lease_layout = QVBoxLayout(lease_group)
        self.leases_editor = ClientLeasesEditor(self._container)
        lease_layout.addWidget(self.leases_editor)
        content_layout.addWidget(lease_group)
        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton(BUTTON_LABELS["client_dialog.cancel"])
        self.save_button = QPushButton(BUTTON_LABELS["client_dialog.save"])
        self.save_button.setDefault(True)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)

        self.save_button.clicked.connect(self.on_save)
        self.cancel_button.clicked.connect(self.reject)
        self._expose_compatibility_aliases(content)

    def _expose_compatibility_aliases(self, content: QWidget) -> None:
        form = self.profile_form
        self._client_code = form.client_code
        self._client_name = form.client_name
        self._tax_id = form.tax_id
        self._short_name = form.short_name
        self._contact_name = form.contact_name
        self._contact_phone = form.contact_phone
        self._contact_email = form.contact_email
        self._address = form.registered_address
        self._note = form.note
        self._save_btn = self.save_button
        self.lease_table = self.leases_editor.table
        self.add_lease_button = self.leases_editor.add_button
        self.lease_availability_label = self.leases_editor.availability_label
        # Legacy date fields remain only for old direct ClientsService callers.
        self._lease_start = DateField(required=False, parent=content)
        self._lease_end = DateField(required=False, parent=content)
        self._lease_start.hide()
        self._lease_end.hide()

    def add_staged_lease(self, payload: LeaseInput) -> None:
        if self._container is None:
            raise RuntimeError("multiple leases require ServiceContainer")
        self.leases_editor.add_payload(payload)

    def _on_search(self) -> None:
        if self._registry_repo is None:
            return
        if self._search_is_active():
            return
        self._clear_registry_results()
        query = self._search_input.text().strip()
        if not query:
            self._search_status.setText("請輸入統一編號、公司名稱或行業關鍵字。")
            return
        is_exact_tax_id = len(query) == 8 and query.isdigit()
        if is_exact_tax_id:
            try:
                exact_row = self._registry_repo.find_by_tax_id(query)
            except Exception:
                _log.error("tax_registry.find_by_tax_id failed", exc_info=True)
                self._search_status.setText(
                    "稅籍資料庫查詢失敗，未帶入任何資料。"
                )
                QMessageBox.warning(
                    self,
                    "查詢失敗",
                    "稅籍資料庫查詢發生錯誤，請直接手動輸入欄位資料。",
                )
                return
            if exact_row is not None:
                self._show_registry_results(
                    [exact_row], query, show_empty_dialog=False
                )
                return

        db_path = (
            str(self._container.paths.db_path)
            if self._container is not None
            else self._registry_database_path()
        )
        if db_path:
            self._start_async_search(db_path, query)
            return
        # Compatibility for legacy test/custom callers without ServiceContainer.
        # Production entry points always provide a file-backed database path.
        if not is_exact_tax_id:
            self._run_sync_search(query)
            return
        self._search_status.setText(
            "統編未直接命中；目前無法啟動背景名稱／行業查詢，請手動輸入資料。"
        )

    def _run_sync_search(self, query: str) -> None:
        try:
            results = self._registry_repo.search(query, limit=20)
        except Exception:
            _log.error("tax_registry.search failed", exc_info=True)
            self._search_status.setText("稅籍資料庫查詢失敗，未帶入任何資料。")
            QMessageBox.warning(self, "查詢失敗", "稅籍資料庫查詢發生錯誤，請直接手動輸入欄位資料。")
            return
        self._show_registry_results(list(results), query, show_empty_dialog=True)

    def _registry_database_path(self) -> str | None:
        connection = getattr(self._registry_repo, "_conn", None)
        if connection is None:
            return None
        try:
            rows = connection.execute("PRAGMA database_list").fetchall()
        except Exception:
            return None
        for row in rows:
            if str(row[1]) == "main" and str(row[2]):
                return str(row[2])
        return None

    def _start_async_search(self, db_path: str, query: str) -> None:
        self._search_status.setText("查詢中，請稍候…")
        self._set_search_busy(True)
        worker = LocalRegistrySearchWorker(db_path, query, limit=20, parent=self)
        self._local_worker = worker
        worker.succeeded.connect(
            lambda rows, expected=query: self._show_registry_results(
                list(rows), expected, show_empty_dialog=False
            )
        )
        worker.errored.connect(self._on_async_search_error)
        worker.finished.connect(lambda expected=worker: self._on_search_finished(expected))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _show_registry_results(
        self,
        results: list,
        expected_query: str,
        *,
        show_empty_dialog: bool,
    ) -> None:
        if self._search_input.text().strip() != expected_query:
            self._clear_registry_results()
            self._search_status.setText("查詢條件已變更，舊的搜尋結果已忽略。")
            return
        self._registry_results = list(results)
        self._result_combo.setEnabled(bool(results))
        self._fill_btn.setEnabled(bool(results))
        for index, row in enumerate(results):
            row_dict = dict(row)
            primary = primary_industry_display(row_dict) or ""
            suffix = f"｜{primary}" if primary else ""
            self._result_combo.addItem(
                f"{row['tax_id']}  {row['business_name']} {suffix}".rstrip()
            )
            self._result_combo.setItemData(
                index,
                row["business_address"] or "",
                Qt.ItemDataRole.ToolTipRole,
            )
        if results:
            self._search_status.setText(f"查詢完成，共 {len(results)} 筆；請選擇正確登記主體。")
        else:
            self._search_status.setText("查無符合的公司或行業資料。")
        if not results and show_empty_dialog:
            QMessageBox.information(self, "查無結果", "找不到符合的公司，請確認統編或名稱後再試。")

    def _on_async_search_error(self, code: str) -> None:
        if self._container is not None:
            self._container.system_log.warn(
                "New-client local registry lookup failed", detail={"code": code}
            )
        self._clear_registry_results()
        self._search_status.setText(error_message(code))

    def _on_search_finished(self, worker: object) -> None:
        if self._local_worker is worker:
            self._local_worker = None
            self._set_search_busy(False)

    def _clear_registry_results(self) -> None:
        self._registry_results = []
        self._registry_prefill = None
        self._registry_industries = ()
        self._result_combo.clear()
        self._result_combo.setEnabled(False)
        self._fill_btn.setEnabled(False)

    def _set_search_busy(self, busy: bool) -> None:
        self._search_input.setEnabled(not busy)
        self._search_btn.setEnabled(not busy)
        self._fill_btn.setEnabled(not busy and bool(self._registry_results))
        self.save_button.setEnabled(not busy)

    def _search_is_active(self) -> bool:
        return bool(self._local_worker and self._local_worker.isRunning())

    def _show_search_close_blocked(self) -> None:
        self._search_status.setText("查詢仍在進行，完成後才能關閉視窗。")

    def _on_fill(self) -> None:
        index = self._result_combo.currentIndex()
        if index < 0 or index >= len(self._registry_results):
            return
        row = self._registry_results[index]
        self.profile_form.client_name.setText(row["business_name"] or "")
        self.profile_form.tax_id.setText(row["tax_id"] or "")
        # Registry data is authoritative only for registered address.
        self.profile_form.registered_address.setPlainText(row["business_address"] or "")
        self._registry_prefill = {
            "source_tax_id": row["tax_id"] or "",
            "cache_version": row["cache_version"] if "cache_version" in row.keys() else "",
        }
        self._registry_industries = industries_from_registry(dict(row))
        self.profile_form.client_code.setFocus()

    def _payload(self) -> CreateClientInput:
        values = self.profile_form.values_for_save()
        return CreateClientInput(
            **values,
            lease_start=self._lease_start.validated_value() if self._container is None else None,
            lease_end=self._lease_end.validated_value() if self._container is None else None,
            registry_source_tax_id=(self._registry_prefill or {}).get("source_tax_id"),
            registry_cache_version=(self._registry_prefill or {}).get("cache_version"),
        )

    def on_save(self) -> None:
        if not self.save_button.isEnabled():
            return
        self.save_button.setEnabled(False)
        try:
            payload = self._payload()
            if self._container is None:
                self._clients.create_client(payload)
            else:
                self._container.client_profiles.create_client_with_leases(
                    payload,
                    self.leases_editor.create_inputs(),
                    industries=self._registry_industries or None,
                    industry_source="MOF-BGMOPEN1" if self._registry_industries else None,
                    industry_source_version=(self._registry_prefill or {}).get(
                        "cache_version"
                    )
                    or None,
                )
        except DateField.InvalidInput:
            return self._save_failed(None)
        except (ClientValidationError, ClientProfileValidationError) as exc:
            self.profile_form.focus_for_error(exc.code)
            return self._save_failed(error_message(exc.code))
        except Exception:
            _log.error("client profile create failed", exc_info=True)
            return self._save_failed("客戶與租約未儲存，請檢查資料後再試。")
        self.accept()

    def _save_failed(self, message: str | None) -> None:
        if message:
            QMessageBox.warning(self, "儲存失敗", message)
        self.save_button.setEnabled(True)

    def on_cancel(self) -> None:
        self.reject()

    def accept(self) -> None:
        if self._search_is_active():
            self._show_search_close_blocked()
            return
        super().accept()

    def reject(self) -> None:
        if self._search_is_active():
            self._show_search_close_blocked()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._search_is_active():
            self._show_search_close_blocked()
            event.ignore()
            return
        super().closeEvent(event)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "輸入有誤", message)

    def _focus_first_invalid(self, code: str) -> None:
        self.profile_form.focus_for_error(code)
