"""Scrollable atomic client-profile creation dialog."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
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
from ...services.clients import ClientValidationError, ClientsService, CreateClientInput
from ..widgets.client_leases_editor import ClientLeasesEditor
from ..widgets.client_profile_form import ClientProfileForm
from ..widgets.date_field import DateField

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
            lookup_box = QGroupBox("從稅籍資料庫查詢（輸入統編或公司名稱）")
            lookup_layout = QVBoxLayout(lookup_box)
            search_row = QHBoxLayout()
            self._search_input = QLineEdit()
            self._search_input.setPlaceholderText("統一編號（8位數字）或公司名稱關鍵字")
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
        self._registry_results = []
        self._registry_prefill = None
        self._result_combo.clear()
        self._result_combo.setEnabled(False)
        self._fill_btn.setEnabled(False)
        query = self._search_input.text().strip()
        if not query:
            return
        try:
            results = self._registry_repo.search(query, limit=20)
        except Exception:
            _log.error("tax_registry.search failed", exc_info=True)
            QMessageBox.warning(self, "查詢失敗", "稅籍資料庫查詢發生錯誤，請直接手動輸入欄位資料。")
            return
        self._registry_results = list(results)
        self._result_combo.setEnabled(bool(results))
        self._fill_btn.setEnabled(bool(results))
        for index, row in enumerate(results):
            self._result_combo.addItem(f"{row['tax_id']}  {row['business_name']}")
            self._result_combo.setItemData(
                index,
                row["business_address"] or "",
                Qt.ItemDataRole.ToolTipRole,
            )
        if not results:
            QMessageBox.information(self, "查無結果", "找不到符合的公司，請確認統編或名稱後再試。")

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
                    payload, self.leases_editor.create_inputs()
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

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "輸入有誤", message)

    def _focus_first_invalid(self, code: str) -> None:
        self.profile_form.focus_for_error(code)
