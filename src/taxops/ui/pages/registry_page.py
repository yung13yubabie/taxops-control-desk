"""工商 / 稅籍查詢頁 — 本地快取查詢 + 套用至客戶主檔.

GCIS 線上查詢尚未開放（需官方 API 驗證），按鈕保持 disabled。
查詢不到時只顯示「本地快取無資料」，絕不顯示「公司不存在」。
"""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import DISABLED_TOOLTIP
from ...services.container import ServiceContainer
from ..dialogs.registry_apply_dialog import RegistryApplyDialog
from ..style import toolbar_icon

_log = logging.getLogger(__name__)

_RESULT_FIELDS: tuple[tuple[str, str], ...] = (
    ("tax_id", "統一編號"),
    ("business_name", "公司名稱"),
    ("business_address", "地址"),
    ("organization_type", "組織型態"),
    ("registered_date_roc", "設立日期（民國）"),
)

_NOT_FOUND_MSG = "本地快取查無此統一編號，可能是快取未更新或資料來源未涵蓋。"


class RegistryPage(QWidget):
    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._result: sqlite3.Row | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("工商 / 稅籍查詢")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        search_group = QGroupBox("查詢條件")
        search_layout = QHBoxLayout(search_group)
        search_layout.setSpacing(8)

        self._query_edit = QLineEdit()
        self._query_edit.setPlaceholderText("輸入統一編號（8位數）或公司名稱關鍵字")
        self._query_edit.returnPressed.connect(self._on_search_local)
        search_layout.addWidget(self._query_edit, stretch=1)

        self._search_btn = QPushButton("查詢本地快取")
        self._search_btn.setIcon(toolbar_icon("refresh"))
        self._search_btn.clicked.connect(self._on_search_local)
        search_layout.addWidget(self._search_btn)

        self._gcis_btn = QPushButton("GCIS 工商查詢")
        self._gcis_btn.setEnabled(False)
        self._gcis_btn.setToolTip(DISABLED_TOOLTIP)
        search_layout.addWidget(self._gcis_btn)

        layout.addWidget(search_group)

        self._status_label = QLabel("")
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #555; font-size: 13px;")
        layout.addWidget(self._status_label)

        self._result_group = QGroupBox("查詢結果")
        result_form = QFormLayout(self._result_group)
        result_form.setHorizontalSpacing(16)
        result_form.setVerticalSpacing(8)

        self._result_labels: dict[str, QLabel] = {}
        for field_key, field_label in _RESULT_FIELDS:
            lbl = QLabel("")
            lbl.setTextFormat(Qt.TextFormat.PlainText)
            lbl.setWordWrap(True)
            self._result_labels[field_key] = lbl
            result_form.addRow(f"{field_label}：", lbl)

        self._result_group.setVisible(False)
        layout.addWidget(self._result_group)

        apply_group = QGroupBox("套用至客戶主檔")
        apply_layout = QHBoxLayout(apply_group)
        apply_layout.setSpacing(8)

        client_label = QLabel("選擇客戶：")
        client_label.setTextFormat(Qt.TextFormat.PlainText)
        apply_layout.addWidget(client_label)

        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(240)
        apply_layout.addWidget(self._client_combo, stretch=1)

        self._apply_btn = QPushButton("套用至客戶主檔")
        self._apply_btn.setIcon(toolbar_icon("save"))
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_to_client)
        apply_layout.addWidget(self._apply_btn)

        layout.addWidget(apply_group)
        layout.addStretch()

        self._load_clients()

    def _load_clients(self) -> None:
        self._client_combo.clear()
        self._client_combo.addItem("— 請選擇客戶 —", None)
        try:
            clients = self._container.clients.list_clients(limit=500, offset=0)
        except Exception:
            _log.warning("failed to load clients into registry page combo")
            return
        for c in clients:
            self._client_combo.addItem(f"{c.client_code}  {c.client_name}", c.id)

    def _clear_result(self, status_msg: str) -> None:
        self._status_label.setText(status_msg)
        self._result_group.setVisible(False)
        self._apply_btn.setEnabled(False)
        self._result = None

    def _on_search_local(self) -> None:
        query = self._query_edit.text().strip()
        if not query:
            self._clear_result("請輸入統一編號或公司名稱後再查詢。")
            return

        try:
            rows = self._container.tax_registry_repo.search(query, limit=1)
        except Exception:
            _log.error("local registry search failed", exc_info=True)
            self._clear_result("查詢失敗，請稍後再試。")
            return

        if not rows:
            self._clear_result(_NOT_FOUND_MSG)
            return

        self._result = rows[0]
        self._status_label.setText("查詢完成。")

        for field_key, _ in _RESULT_FIELDS:
            val = self._result[field_key] if self._result[field_key] else ""
            self._result_labels[field_key].setText(str(val))

        self._result_group.setVisible(True)
        self._apply_btn.setEnabled(True)

    def _on_apply_to_client(self) -> None:
        if self._result is None:
            QMessageBox.warning(self, "無查詢結果", "請先查詢稅籍資料後再套用。")
            return

        client_id: int | None = self._client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, "未選擇客戶", "請先選擇要更新的客戶。")
            return

        try:
            client_row = self._container.clients.get_client(client_id)
        except Exception:
            _log.error("get_client failed in registry apply", exc_info=True)
            QMessageBox.critical(self, "錯誤", "無法載入客戶資料，請稍後再試。")
            return

        if client_row is None:
            QMessageBox.warning(self, "找不到客戶", "找不到選取的客戶資料。")
            return

        dlg = RegistryApplyDialog(
            registry_row=self._result,
            client_row=client_row,
            container=self._container,
            parent=self,
        )
        if dlg.exec() == RegistryApplyDialog.DialogCode.Accepted:
            self._load_clients()
            QMessageBox.information(self, "套用完成", "客戶資料已依稅籍快取更新。")
