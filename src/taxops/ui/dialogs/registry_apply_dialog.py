"""Dialog showing field differences between a registry record and a client record.

The user selects which fields to apply. On confirm, calls ClientsService.update_client().
Only fields that differ between the registry record and the client are shown.
"""

from __future__ import annotations

import logging
import sqlite3

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
from ...services.clients import UpdateClientInput
from ...services.container import ServiceContainer

_log = logging.getLogger(__name__)

# (client_field, display_label, registry_column)
_MAPPABLE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("client_name", "客戶名稱", "business_name"),
    ("address", "地址", "business_address"),
    ("tax_id", "統一編號", "tax_id"),
)


class RegistryApplyDialog(QDialog):
    """Show field diff, let user pick fields to apply from registry to client."""

    def __init__(
        self,
        registry_row: sqlite3.Row,
        client_row: ClientRow,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry_row = registry_row
        self._client_row = client_row
        self._container = container
        self._checkboxes: dict[str, QCheckBox] = {}

        self.setWindowTitle("套用稅籍資料至客戶主檔")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info = QLabel(f"客戶：{client_row.client_code}  {client_row.client_name}")
        info.setStyleSheet("font-weight: 600; font-size: 14px;")
        info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(info)

        diff_group = QGroupBox("欄位差異比較（勾選要套用的欄位）")
        form = QFormLayout(diff_group)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        for client_field, label_text, reg_col in _MAPPABLE_FIELDS:
            client_val = str(getattr(client_row, client_field) or "")
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
            current_lbl.setStyleSheet("color: #555;")
            row_layout.addWidget(current_lbl, stretch=1)

            arrow_lbl = QLabel("→")
            row_layout.addWidget(arrow_lbl)

            new_lbl = QLabel(f"新值：{reg_val or '（空白）'}")
            new_lbl.setTextFormat(Qt.TextFormat.PlainText)
            new_lbl.setStyleSheet("color: #2563EB; font-weight: 500;")
            row_layout.addWidget(new_lbl, stretch=1)

            form.addRow(f"{label_text}：", row_widget)

        if not self._checkboxes:
            no_diff_lbl = QLabel("所有可比對欄位均與客戶資料相同，無需更新。")
            no_diff_lbl.setStyleSheet("color: #555;")
            form.addRow(no_diff_lbl)

        layout.addWidget(diff_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("確認套用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not self._checkboxes:
            self._ok_btn.setEnabled(False)

    def _on_save(self) -> None:
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
        new_address = _reg("business_address") if "address" in selected else _client("address")
        new_tax_id = _reg("tax_id") if "tax_id" in selected else _client("tax_id")

        payload = UpdateClientInput(
            client_code=self._client_row.client_code,
            client_name=new_client_name,
            tax_id=new_tax_id,
            short_name=self._client_row.short_name,
            contact_name=self._client_row.contact_name,
            contact_phone=self._client_row.contact_phone,
            contact_email=self._client_row.contact_email,
            address=new_address,
            note=self._client_row.note,
        )

        try:
            self._container.clients.update_client(self._client_row.id, payload)
        except Exception as exc:
            _log.error("registry apply to client failed", exc_info=True)
            code = getattr(exc, "code", "registry.apply.failed")
            QMessageBox.critical(self, "套用失敗", error_message(code))
            return

        self.accept()
