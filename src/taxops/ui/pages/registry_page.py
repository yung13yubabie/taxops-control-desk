"""工商 / 稅籍查詢頁 — MOF 本地快取 + 官方 GCIS 單筆補查."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.gcis import GCISQueryError, query_gcis_by_tax_id
from ...services.registry.industries import (
    industry_display_lines,
    primary_industry_display,
)
from ...services.container import ServiceContainer
from ..dialogs.registry_apply_dialog import RegistryApplyDialog
from ..style import TEXT_MUTED, toolbar_icon
from ..widgets.buttons import set_button_role
from ..workers.local_registry_search import LocalRegistrySearchWorker

_log = logging.getLogger(__name__)
_RESULT_FIELDS: tuple[tuple[str, str], ...] = (
    ("tax_id", "統一編號"),
    ("business_name", "公司名稱"),
    ("business_address", "登記地址"),
    ("organization_type", "組織型態"),
    ("registered_date_roc", "設立日期（民國）"),
    ("business_status", "登記狀態"),
    ("source", "資料來源"),
    ("industries", "行業資料"),
)

_NOT_FOUND_MSG = "本地快取查無此統一編號，可能是快取未更新或資料來源未涵蓋。"


class _GCISWorker(QThread):
    succeeded = Signal(object)
    errored = Signal(str)

    def __init__(self, tax_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tax_id = tax_id

    def run(self) -> None:
        try:
            self.succeeded.emit(query_gcis_by_tax_id(self._tax_id))
        except GCISQueryError as err:
            self.errored.emit(err.code)
        except Exception:
            _log.exception("unexpected GCIS lookup failure")
            self.errored.emit("system.unexpected")


class RegistryPage(QWidget):
    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._result: sqlite3.Row | Mapping[str, object] | None = None
        self._gcis_worker: _GCISWorker | None = None
        self._local_worker: LocalRegistrySearchWorker | None = None

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
        self._query_edit.setPlaceholderText(
            "輸入統一編號（8位數）、公司名稱或行業代碼／名稱"
        )
        self._query_edit.returnPressed.connect(self._on_search_local)
        search_layout.addWidget(self._query_edit, stretch=1)

        self._search_btn = QPushButton("查詢本地快取")
        self._search_btn.setIcon(toolbar_icon("refresh"))
        self._search_btn.clicked.connect(self._on_search_local)
        search_layout.addWidget(self._search_btn)

        self._gcis_btn = QPushButton("GCIS 工商查詢")
        self._gcis_btn.setToolTip("依統一編號向經濟部 GCIS 官方 API 單筆補查")
        self._gcis_btn.clicked.connect(self._on_search_gcis)
        search_layout.addWidget(self._gcis_btn)

        layout.addWidget(search_group)

        self._status_label = QLabel("")
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        layout.addWidget(self._status_label)

        self._results_table = QTableWidget(0, 4)
        self._results_table.setHorizontalHeaderLabels(
            ["統一編號", "登記名稱", "登記地址", "主要行業"]
        )
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._results_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.setMaximumHeight(180)
        self._results_table.setVisible(False)
        self._results_table.itemSelectionChanged.connect(self._on_result_selected)
        layout.addWidget(self._results_table)

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
        apply_layout = QVBoxLayout(apply_group)
        apply_layout.setSpacing(8)

        client_search_row = QHBoxLayout()
        client_search_label = QLabel("搜尋客戶：")
        client_search_label.setTextFormat(Qt.TextFormat.PlainText)
        client_search_row.addWidget(client_search_label)
        self._client_filter_edit = QLineEdit()
        self._client_filter_edit.setPlaceholderText("輸入客戶代碼或名稱，可找到前 500 筆以外的客戶")
        client_search_row.addWidget(self._client_filter_edit, stretch=1)
        self._client_filter_btn = QPushButton("篩選")
        client_search_row.addWidget(self._client_filter_btn)
        apply_layout.addLayout(client_search_row)

        client_select_row = QHBoxLayout()

        client_label = QLabel("選擇客戶：")
        client_label.setTextFormat(Qt.TextFormat.PlainText)
        client_select_row.addWidget(client_label)

        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(240)
        client_select_row.addWidget(self._client_combo, stretch=1)

        self._apply_btn = QPushButton("套用至客戶主檔")
        # Applying the lookup is the only action here that changes stored data;
        # the two query buttons are searches and must not be primary.
        set_button_role(self._apply_btn, "primary")
        self._apply_btn.setIcon(toolbar_icon("save"))
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_to_client)
        client_select_row.addWidget(self._apply_btn)
        apply_layout.addLayout(client_select_row)

        layout.addWidget(apply_group)
        layout.addStretch()

        self._client_filter_btn.clicked.connect(self._on_filter_clients)
        self._client_filter_edit.returnPressed.connect(self._on_filter_clients)
        self._load_clients()

    def refresh_context(self) -> None:
        """Reload client choices when the page becomes active."""
        self._load_clients()

    def has_active_operation(self) -> bool:
        """Return whether an official or large local lookup owns a live thread."""
        # Ownership ends only after the queued result/error signals and Qt's
        # deferred deletion have completed, not merely when run() returns.
        return self._gcis_worker is not None or self._local_worker is not None

    def _set_search_busy(self, busy: bool) -> None:
        """Keep local and online searches mutually exclusive."""
        self._query_edit.setEnabled(not busy)
        self._search_btn.setEnabled(not busy)
        self._gcis_btn.setEnabled(not busy)

    def _load_clients(self, query: str = "") -> None:
        selected_id = self._client_combo.currentData()
        self._client_combo.clear()
        self._client_combo.addItem("— 請選擇客戶 —", None)
        try:
            if query:
                clients = self._container.clients.search_clients(
                    query,
                    limit=100,
                    offset=0,
                )
            else:
                clients = self._container.clients.list_clients(limit=500, offset=0)
        except Exception:
            _log.warning("failed to load clients into registry page combo")
            self._client_combo.addItem("（客戶資料載入失敗，請重新整理）", None)
            return
        for c in clients:
            self._client_combo.addItem(f"{c.client_code}  {c.client_name}", c.id)
        if selected_id is not None:
            for i in range(self._client_combo.count()):
                if self._client_combo.itemData(i) == selected_id:
                    self._client_combo.setCurrentIndex(i)
                    break

    def _on_filter_clients(self) -> None:
        query = self._client_filter_edit.text().strip()
        self._load_clients(query)
        if query and self._client_combo.count() == 1:
            self._status_label.setText("找不到符合的客戶，請改用客戶代碼或名稱關鍵字。")

    def _clear_result(self, status_msg: str) -> None:
        self._status_label.setText(status_msg)
        self._result_group.setVisible(False)
        self._apply_btn.setEnabled(False)
        self._result = None
        self._results_table.setRowCount(0)
        self._results_table.setVisible(False)

    def _on_search_local(self) -> None:
        query = self._query_edit.text().strip()
        if not query:
            self._clear_result("請輸入統一編號、公司名稱或行業關鍵字後再查詢。")
            return
        if self._local_worker is not None or self._gcis_worker is not None:
            return
        if len(query) == 8 and query.isdigit():
            try:
                exact_row = self._container.tax_registry_repo.find_by_tax_id(query)
            except Exception:
                _log.error("exact local registry lookup failed", exc_info=True)
                self._clear_result("查詢失敗，請稍後再試。")
                return
            if exact_row is not None:
                self._populate_results_table([dict(exact_row)])
                self._status_label.setText("查詢完成，共 1 筆。")
                return
        self._clear_result("正在搜尋大量本機登記資料，請稍候…")
        self._set_search_busy(True)
        worker = LocalRegistrySearchWorker(
            str(self._container.paths.db_path), query, limit=50, parent=self
        )
        self._local_worker = worker

        def on_error(code: str) -> None:
            self._container.system_log.warn(
                "Local registry lookup failed",
                detail={"code": code, "query_length": len(query)},
            )
            self._clear_result(error_message(code))

        def on_destroyed() -> None:
            if self._local_worker is worker:
                self._local_worker = None
                try:
                    self._set_search_busy(self.has_active_operation())
                except RuntimeError:
                    # Parent page may already be destroyed during app shutdown.
                    pass

        worker.succeeded.connect(
            lambda rows, expected=query: self._show_local_results(rows, expected)
        )
        worker.errored.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        worker.destroyed.connect(on_destroyed)
        worker.start()

    def _show_local_results(
        self,
        rows: list[dict[str, object]],
        expected_query: str | None = None,
    ) -> None:
        if (
            expected_query is not None
            and self._query_edit.text().strip() != expected_query
        ):
            self._clear_result("查詢條件已變更，舊的搜尋結果已忽略。")
            return
        if not rows:
            self._clear_result(_NOT_FOUND_MSG)
            return
        self._populate_results_table(rows)
        self._status_label.setText(
            f"查詢完成，共 {len(rows)} 筆；請選擇正確登記主體"
        )

    def _populate_results_table(self, rows: list[dict[str, object]]) -> None:
        self._results_table.blockSignals(True)
        self._results_table.setRowCount(len(rows))
        for row_index, result in enumerate(rows):
            values = (
                str(result.get("tax_id") or ""),
                str(result.get("business_name") or ""),
                str(result.get("business_address") or ""),
                primary_industry_display(result) or "此來源未提供主要行業",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, result)
                self._results_table.setItem(row_index, column, item)
        self._results_table.blockSignals(False)
        self._results_table.setVisible(True)
        self._results_table.selectRow(0)
        self._set_result(rows[0])

    def _on_result_selected(self) -> None:
        row = self._results_table.currentRow()
        if row < 0:
            return
        item = self._results_table.item(row, 0)
        result = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(result, dict):
            self._set_result(result)

    def _set_result(self, result: Mapping[str, object]) -> None:
        self._result = result
        for field_key, _ in _RESULT_FIELDS:
            if field_key == "industries":
                lines = industry_display_lines(result)
                value = "\n".join(lines) if lines else "此來源未提供行業資料"
            else:
                value = str(result.get(field_key) or "")
            self._result_labels[field_key].setText(value)
            self._result_labels[field_key].setToolTip(value)
        self._result_group.setVisible(True)
        self._apply_btn.setEnabled(True)

    def _on_search_gcis(self) -> None:
        tax_id = self._query_edit.text().strip()
        if len(tax_id) != 8 or not tax_id.isdigit():
            self._clear_result("GCIS 線上補查僅支援 8 位數統一編號。")
            return
        if self._gcis_worker is not None or self._local_worker is not None:
            return
        self._clear_result("正在查詢經濟部 GCIS 官方資料…")
        self._set_search_busy(True)

        worker = _GCISWorker(tax_id, self)
        self._gcis_worker = worker

        def on_error(code: str) -> None:
            self._container.system_log.warn(
                "GCIS official lookup failed",
                detail={"code": code, "tax_id_suffix": tax_id[-3:]},
            )
            self._clear_result(error_message(code))

        def on_destroyed() -> None:
            if self._gcis_worker is worker:
                self._gcis_worker = None
                try:
                    self._set_search_busy(self.has_active_operation())
                except RuntimeError:
                    # Parent page may already be destroyed during app shutdown.
                    pass

        worker.succeeded.connect(
            lambda result, expected=tax_id: self._show_gcis_result(result, expected)
        )
        worker.errored.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        worker.destroyed.connect(on_destroyed)
        worker.start()

    def _show_gcis_result(
        self,
        result: dict[str, str] | None,
        expected_tax_id: str | None = None,
    ) -> None:
        if (
            expected_tax_id is not None
            and self._query_edit.text().strip() != expected_tax_id
        ):
            self._clear_result("查詢條件已變更，舊的 GCIS 結果已忽略。")
            return
        if result is None:
            self._clear_result(
                "GCIS 官方查無可用資料；這不代表該統編不存在，可能是資料類型或介接權限未涵蓋。"
            )
            return
        self._set_result(result)
        self._status_label.setText("GCIS 官方線上補查完成。")

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
            QMessageBox.information(self, "套用完成", "客戶資料已依官方登記資料更新。")
