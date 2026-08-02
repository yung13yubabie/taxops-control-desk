"""Dialog showing field differences between a registry record and a client record.

The user selects which fields to apply. On confirm, calls ClientsService.update_client().
Only fields that differ between the registry record and the client are shown.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.clients import ClientRow
from ..style import TEXT_MUTED
from ...services.clients import UpdateClientInput
from ...services.registry.industries import industries_from_registry, industry_display_lines
from ...services.container import ServiceContainer

_log = logging.getLogger(__name__)

# (client_field, display_label, registry_column)
_MAPPABLE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("client_name", "客戶名稱", "business_name"),
    ("address", "設籍／登記地址", "business_address"),
    ("tax_id", "統一編號", "tax_id"),
)


class RegistryApplyDialog(QDialog):
    """Show field diff, let user pick fields to apply from registry to client."""

    def __init__(
        self,
        registry_row: sqlite3.Row | Mapping[str, object],
        client_row: ClientRow,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry_row = registry_row
        self._client_row = client_row
        self._container = container
        self._checkboxes: dict[str, QCheckBox] = {}
        registry_mapping = dict(registry_row)
        self._registry_industries = industries_from_registry(registry_mapping)

        self.setWindowTitle("套用稅籍資料至客戶主檔")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info = QLabel(f"客戶：{client_row.client_code}  {client_row.client_name}")
        info.setStyleSheet("font-weight: 600; font-size: 14px;")
        info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(info)

        self.address_notice = QLabel(
            "工商資料只更新登記地址，既有聯絡地址不會被覆寫；若原本兩者相同，套用後會改為分開管理。"
        )
        self.address_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.address_notice.setWordWrap(True)
        self.address_notice.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.address_notice)

        diff_group = QGroupBox("欄位差異比較（勾選要套用的欄位）")
        form = QFormLayout(diff_group)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        for client_field, label_text, reg_col in _MAPPABLE_FIELDS:
            client_value_field = (
                "registered_address" if client_field == "address" else client_field
            )
            client_value = getattr(client_row, client_value_field)
            if client_field == "address" and client_value is None:
                client_value = client_row.address
            client_val = str(client_value or "")
            reg_val = str(registry_row[reg_col] or "")
            if client_val == reg_val:
                continue
            cb = QCheckBox()
            cb.setChecked(True)
            self._checkboxes[client_field] = cb

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(cb)

            current_lbl = QLabel(f"目前：{client_val or '（空白）'}")
            current_lbl.setTextFormat(Qt.TextFormat.PlainText)
            current_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
            row_layout.addWidget(current_lbl, stretch=1)

            arrow_lbl = QLabel("→")
            row_layout.addWidget(arrow_lbl)

            new_lbl = QLabel(f"新值：{reg_val or '（空白）'}")
            new_lbl.setTextFormat(Qt.TextFormat.PlainText)
            new_lbl.setStyleSheet("color: #2563EB; font-weight: 500;")
            row_layout.addWidget(new_lbl, stretch=1)

            form.addRow(f"{label_text}：", row_widget)

        if self._registry_industries:
            cb = QCheckBox()
            cb.setChecked(True)
            self._checkboxes["industries"] = cb
            self.industry_checkbox = cb
            registry_industries = "\n".join(industry_display_lines(registry_mapping))
            industry_row = QWidget()
            industry_layout = QHBoxLayout(industry_row)
            industry_layout.setContentsMargins(0, 0, 0, 0)
            industry_layout.addWidget(cb)
            industry_value = QLabel(registry_industries)
            industry_value.setTextFormat(Qt.TextFormat.PlainText)
            industry_value.setWordWrap(True)
            industry_value.setToolTip(registry_industries)
            industry_layout.addWidget(industry_value, 1)
            form.addRow("行業資料：", industry_row)

        if not self._checkboxes:
            no_diff_lbl = QLabel("所有可比對欄位均與客戶資料相同，無需更新。")
            no_diff_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
            form.addRow(no_diff_lbl)

        layout.addWidget(diff_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("確認套用")
        self._ok_btn.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not self._checkboxes:
            self._ok_btn.setEnabled(False)

    def _on_save(self) -> None:
        if not self._ok_btn.isEnabled():
            return
        selected = {k for k, cb in self._checkboxes.items() if cb.isChecked()}
        if not selected:
            QMessageBox.warning(self, "未選取欄位", error_message("registry.apply.no_fields"))
            return

        def _client(field: str) -> str | None:
            return getattr(self._client_row, field)

        def _reg(col: str) -> str | None:
            val = self._registry_row[col]
            return str(val) if val else None

        new_client_name = (
            _reg("business_name") if "client_name" in selected else _client("client_name")
        ) or ""
        new_address = (
            _reg("business_address")
            if "address" in selected
            else (self._client_row.registered_address or self._client_row.address)
        )
        new_tax_id = _reg("tax_id") if "tax_id" in selected else _client("tax_id")

        preserved_contact_address = self._client_row.contact_address
        contact_same_after_apply = bool(
            self._client_row.contact_address_same
            and preserved_contact_address == new_address
        )
        payload = UpdateClientInput(
            client_code=self._client_row.client_code,
            client_name=new_client_name,
            tax_id=new_tax_id,
            short_name=self._client_row.short_name,
            contact_name=self._client_row.contact_name,
            contact_phone=self._client_row.contact_phone,
            contact_email=self._client_row.contact_email,
            registered_address=new_address,
            contact_address=preserved_contact_address,
            contact_address_same=contact_same_after_apply,
            note=self._client_row.note,
        )

        registry = dict(self._registry_row)
        source_version = str(registry.get("cache_version") or "") or None
        source = str(registry.get("source") or "") or (
            "MOF-BGMOPEN1" if "cache_version" in registry else None
        )
        self._ok_btn.setEnabled(False)
        try:
            self._container.registry_client.apply_to_existing(
                self._client_row.id,
                payload,
                industries=self._registry_industries if "industries" in selected else None,
                source=source,
                source_version=source_version,
            )
        except Exception as exc:
            _log.error("registry apply to client failed", exc_info=True)
            code = getattr(exc, "code", "registry.apply.failed")
            if not isinstance(code, str) or not code.startswith(
                ("client.", "client_industry.", "registry.")
            ):
                code = "registry.apply.failed"
            QMessageBox.critical(self, "套用失敗", error_message(code))
            self._ok_btn.setEnabled(True)
            return

        self.accept()
