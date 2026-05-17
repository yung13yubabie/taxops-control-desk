"""Mismatch review dialog — lets user choose whether to adopt registry data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.clients import ClientRow
from ...repositories.registry_matches import MatchResultRow
from ...services.clients import ClientValidationError, ClientsService, UpdateClientInput

_log = logging.getLogger(__name__)


@dataclass
class MismatchItem:
    match_row: MatchResultRow
    client: ClientRow


_COL_TAX_ID = 0
_COL_CLIENT_CODE = 1
_COL_CLIENT_NAME = 2
_COL_REGISTRY_NAME = 3
_COL_ADOPT_NAME = 4
_COL_CLIENT_ADDR = 5
_COL_REGISTRY_ADDR = 6
_COL_ADOPT_ADDR = 7

_HEADERS = [
    "統一編號",
    "客戶代號",
    "目前名稱",
    "財政部名稱",
    "採用名稱",
    "目前地址",
    "財政部地址",
    "採用地址",
]


class MismatchReviewDialog(QDialog):
    """Editable table showing mismatch rows; user picks which fields to overwrite."""

    def __init__(
        self,
        items: list[MismatchItem],
        clients_service: ClientsService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items = items
        self._svc = clients_service
        self._checkboxes: list[tuple[QCheckBox | None, QCheckBox | None]] = []

        self.setWindowTitle(f"衝突審查 — {len(items)} 筆名稱不符")
        self.setModal(True)
        self.setMinimumSize(1050, 500)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        info = QLabel(
            f"以下 {len(items)} 筆客戶，其名稱或地址與財政部稅籍資料不符。\n"
            "勾選「採用名稱」或「採用地址」後按「套用選取變更」，"
            "系統將更新客戶資料並寫入稽核紀錄。未勾選的欄位保持原值不變。"
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        self._table = QTableWidget(len(items), len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_CLIENT_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_REGISTRY_NAME, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self._table)

        self._populate_table()

        sel_row = QHBoxLayout()
        sel_all_name = QPushButton("全選名稱")
        sel_all_addr = QPushButton("全選地址")
        clr_all = QPushButton("全部取消")
        sel_all_name.clicked.connect(lambda: self._set_all(True, "name"))
        sel_all_addr.clicked.connect(lambda: self._set_all(True, "addr"))
        clr_all.clicked.connect(lambda: self._set_all(False, "both"))
        for btn in (sel_all_name, sel_all_addr, clr_all):
            sel_row.addWidget(btn)
        sel_row.addStretch()
        outer.addLayout(sel_row)

        btns = QDialogButtonBox()
        apply_btn = btns.addButton("套用選取變更", QDialogButtonBox.ButtonRole.AcceptRole)
        skip_btn = btns.addButton("略過，保留原值", QDialogButtonBox.ButtonRole.RejectRole)
        apply_btn.setDefault(True)
        outer.addWidget(btns)

        apply_btn.clicked.connect(self._on_apply)
        skip_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------

    def _parse_diffs(self, item: MismatchItem) -> dict:
        if item.match_row.differences_json:
            try:
                return json.loads(item.match_row.differences_json)
            except Exception:
                _log.warning(
                    "malformed differences_json for match id=%s, returning empty diff",
                    item.match_row.id,
                )
        return {}

    def _populate_table(self) -> None:
        for row_idx, item in enumerate(self._items):
            diffs = self._parse_diffs(item)
            registry_name = diffs.get("name", {}).get("registry", item.match_row.matched_name or "")
            registry_addr = diffs.get("address", {}).get("registry", item.match_row.matched_address or "")

            has_name_diff = "name" in diffs
            has_addr_diff = "address" in diffs

            def _cell(text: str, highlight: bool = False) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                if highlight:
                    it.setBackground(Qt.GlobalColor.yellow)
                return it

            self._table.setItem(row_idx, _COL_TAX_ID, _cell(item.client.tax_id or ""))
            self._table.setItem(row_idx, _COL_CLIENT_CODE, _cell(item.client.client_code))
            self._table.setItem(row_idx, _COL_CLIENT_NAME, _cell(item.client.client_name, has_name_diff))
            self._table.setItem(row_idx, _COL_REGISTRY_NAME, _cell(registry_name, has_name_diff))
            self._table.setItem(row_idx, _COL_CLIENT_ADDR, _cell(item.client.address or "", has_addr_diff))
            self._table.setItem(row_idx, _COL_REGISTRY_ADDR, _cell(registry_addr, has_addr_diff))

            name_cb: QCheckBox | None = None
            addr_cb: QCheckBox | None = None

            if has_name_diff:
                name_cb = QCheckBox()
                self._table.setCellWidget(row_idx, _COL_ADOPT_NAME, self._centered(name_cb))
            else:
                self._table.setItem(row_idx, _COL_ADOPT_NAME, QTableWidgetItem("—"))

            if has_addr_diff:
                addr_cb = QCheckBox()
                self._table.setCellWidget(row_idx, _COL_ADOPT_ADDR, self._centered(addr_cb))
            else:
                self._table.setItem(row_idx, _COL_ADOPT_ADDR, QTableWidgetItem("—"))

            self._checkboxes.append((name_cb, addr_cb))

    def _centered(self, widget: QWidget) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        return container

    def _set_all(self, checked: bool, which: Literal["name", "addr", "both"]) -> None:
        for name_cb, addr_cb in self._checkboxes:
            if which in ("name", "both") and name_cb is not None:
                name_cb.setChecked(checked)
            if which in ("addr", "both") and addr_cb is not None:
                addr_cb.setChecked(checked)

    def _on_apply(self) -> None:
        to_update: list[tuple[MismatchItem, bool, bool]] = []
        for i, (name_cb, addr_cb) in enumerate(self._checkboxes):
            adopt_name = name_cb is not None and name_cb.isChecked()
            adopt_addr = addr_cb is not None and addr_cb.isChecked()
            if adopt_name or adopt_addr:
                to_update.append((self._items[i], adopt_name, adopt_addr))

        if not to_update:
            QMessageBox.information(self, "未選取任何變更", "沒有勾選任何欄位，將關閉視窗並保留原值。")
            self.accept()
            return

        ok_count = 0
        fail_msgs: list[str] = []

        for item, adopt_name, adopt_addr in to_update:
            client = item.client
            diffs = self._parse_diffs(item)

            new_name = (
                diffs.get("name", {}).get("registry", client.client_name)
                if adopt_name
                else client.client_name
            )
            new_address = (
                diffs.get("address", {}).get("registry", client.address or "")
                if adopt_addr
                else (client.address or "")
            )

            payload = UpdateClientInput(
                client_code=client.client_code,
                client_name=new_name,
                tax_id=client.tax_id,
                short_name=client.short_name,
                contact_name=client.contact_name,
                contact_phone=client.contact_phone,
                contact_email=client.contact_email,
                address=new_address or None,
                note=client.note,
            )
            try:
                self._svc.update_client(client.id, payload)
                ok_count += 1
            except ClientValidationError as exc:
                _log.warning("mismatch apply failed for %s: %s", client.client_code, exc.code)
                fail_msgs.append(f"{client.client_code}：{error_message(exc.code)}")
            except Exception as exc:
                _log.error("mismatch apply unexpected error for %s: %s", client.client_code, exc, exc_info=True)
                fail_msgs.append(f"{client.client_code}：{error_message('system.unexpected')}")

        summary = f"已更新 {ok_count} 筆客戶資料。"
        if fail_msgs:
            summary += f"\n\n失敗 {len(fail_msgs)} 筆：\n" + "\n".join(fail_msgs[:10])

        if ok_count == 0 and fail_msgs:
            QMessageBox.warning(self, "套用失敗", summary)
            return
        QMessageBox.information(self, "套用完成", summary)
        self.accept()
