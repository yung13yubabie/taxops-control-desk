"""Clients page: list view + search/filter/sort/pagination + CRUD actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import datetime
import logging

from ...core.clock import today_iso
from ...i18n import BUTTON_LABELS, NAV_LABELS, TABLE_HEADERS, error_message

_log = logging.getLogger(__name__)
from ...services.clients import ClientValidationError
from ...services.container import ServiceContainer
from ..dialogs.bulk_import_wizard import BulkImportWizard
from ..dialogs.edit_client_dialog import EditClientDialog
from ..dialogs.new_client_dialog import NewClientDialog
from ..style import toolbar_icon

_PAGE_SIZE = 50

_COLUMN_ORDER: tuple[str, ...] = (
    "id",
    "client_code",
    "tax_id",
    "client_name",
    "short_name",
    "contact_name",
    "contact_phone",
    "contact_email",
    "address",
    "note",
    "lease_start",
    "lease_end",
    "updated_at",
)

# Columns hidden by default; user can toggle them via the "欄位顯示" menu.
_DEFAULT_HIDDEN: frozenset[str] = frozenset({"id", "address", "note", "lease_start"})

_DEFAULT_SORT_COL = "client_code"
_DEFAULT_SORT_DIR = "ASC"
_ID_COL_IDX = _COLUMN_ORDER.index("id")
_DELETED_FG = QColor(160, 160, 160)


class ClientsPage(QWidget):
    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._page = 0
        self._total = 0
        self._sort_col = _DEFAULT_SORT_COL
        self._sort_dir = _DEFAULT_SORT_DIR
        self._hidden_cols: set[str] = set(_DEFAULT_HIDDEN)
        self._filter_key: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel(NAV_LABELS["clients"])
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        outer.addWidget(title)

        # Search row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜尋客戶代號、名稱或統一編號")
        self._search_input.setMaxLength(100)
        self._search_btn = QPushButton("搜尋")
        self._clear_btn = QPushButton("清除")
        self._count_label = QLabel("共 0 筆")
        self._count_label.setStyleSheet("color: #555;")
        self._show_deleted_check = QCheckBox("顯示已刪除客戶")
        search_row.addWidget(self._search_input, 1)
        search_row.addWidget(self._search_btn)
        search_row.addWidget(self._clear_btn)
        search_row.addWidget(self._show_deleted_check)
        search_row.addStretch(0)
        search_row.addWidget(self._count_label)
        outer.addLayout(search_row)

        # Action toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_btn = QPushButton(BUTTON_LABELS["clients.new"])
        self._edit_btn = QPushButton("編輯客戶")
        self._delete_btn = QPushButton("刪除客戶")
        self._restore_btn = QPushButton("復原客戶")
        self._purge_btn = QPushButton("永久刪除")
        self._bulk_btn = QPushButton("批量匯入")
        self._cols_btn = QPushButton("欄位顯示 ▾")
        self._refresh_btn = QPushButton(BUTTON_LABELS["clients.refresh"])

        self._new_btn.setIcon(toolbar_icon("new"))
        self._edit_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._restore_btn.setIcon(toolbar_icon("refresh"))
        self._purge_btn.setIcon(toolbar_icon("delete"))
        self._bulk_btn.setIcon(toolbar_icon("bulk"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))

        self._edit_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._restore_btn.setEnabled(False)
        self._purge_btn.setEnabled(False)

        for btn in (
            self._new_btn,
            self._edit_btn,
            self._delete_btn,
            self._restore_btn,
            self._purge_btn,
            self._bulk_btn,
            self._cols_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        # Empty state label
        self._empty_label = QLabel("尚無客戶資料。請按「新增客戶」建立第一筆資料。")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #777; padding: 24px;")
        outer.addWidget(self._empty_label)

        # Table with sortable headers
        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        headers = TABLE_HEADERS["clients"]
        self._table.setHorizontalHeaderLabels(
            [headers[col] for col in _COLUMN_ORDER]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header_view = self._table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(
            _COLUMN_ORDER.index("client_name"), QHeaderView.ResizeMode.Stretch
        )
        header_view.setSectionsClickable(True)
        header_view.setSortIndicatorShown(True)
        header_view.setSortIndicator(
            _COLUMN_ORDER.index(_DEFAULT_SORT_COL), Qt.SortOrder.AscendingOrder
        )
        outer.addWidget(self._table, stretch=1)

        # Pagination row
        page_row = QHBoxLayout()
        page_row.setSpacing(8)
        self._prev_btn = QPushButton("◀ 上一頁")
        self._next_btn = QPushButton("下一頁 ▶")
        self._page_label = QLabel("")
        self._page_label.setStyleSheet("color: #555;")
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        page_row.addWidget(self._prev_btn)
        page_row.addWidget(self._next_btn)
        page_row.addStretch(1)
        page_row.addWidget(self._page_label)  # shows "第 X–Y 筆 / 共 Z 筆"
        outer.addLayout(page_row)

        # Connect signals
        self._new_btn.clicked.connect(self.on_new_client)
        self._edit_btn.clicked.connect(self.on_edit_client)
        self._delete_btn.clicked.connect(self.on_delete_client)
        self._restore_btn.clicked.connect(self.on_restore_client)
        self._purge_btn.clicked.connect(self.on_purge_client)
        self._bulk_btn.clicked.connect(self.on_bulk_import)
        self._cols_btn.clicked.connect(self._on_cols_menu)
        self._refresh_btn.clicked.connect(self.on_refresh)
        self._show_deleted_check.toggled.connect(self._on_show_deleted_toggled)
        self._search_btn.clicked.connect(self._on_search)
        self._clear_btn.clicked.connect(self._on_clear_search)
        self._search_input.returnPressed.connect(self._on_search)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(lambda _: self.on_edit_client())
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn.clicked.connect(self._on_next_page)
        header_view.sectionClicked.connect(self._on_header_clicked)

        self.on_refresh()

    # ------------------------------------------------------------------
    # Column visibility
    # ------------------------------------------------------------------

    def _on_cols_menu(self) -> None:
        headers = TABLE_HEADERS["clients"]
        menu = QMenu(self)
        for col in _COLUMN_ORDER:
            label = headers.get(col, col)
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col not in self._hidden_cols)
            action.setData(col)
        chosen = menu.exec(self._cols_btn.mapToGlobal(self._cols_btn.rect().bottomLeft()))
        if chosen is None:
            return
        col = chosen.data()
        if chosen.isChecked():
            self._hidden_cols.discard(col)
        else:
            self._hidden_cols.add(col)
        self._apply_column_visibility()

    def _apply_column_visibility(self) -> None:
        for col_idx, col in enumerate(_COLUMN_ORDER):
            self._table.setColumnHidden(col_idx, col in self._hidden_cols)

    # ------------------------------------------------------------------
    # Search / pagination / sort
    # ------------------------------------------------------------------

    def _on_search(self) -> None:
        self._filter_key = ""  # manual search overrides dashboard filter
        self._page = 0
        self.on_refresh()

    def _on_clear_search(self) -> None:
        self._filter_key = ""
        self._search_input.clear()
        self._page = 0
        self.on_refresh()

    def _on_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.on_refresh()

    def _on_next_page(self) -> None:
        if (self._page + 1) * _PAGE_SIZE < self._total:
            self._page += 1
            self.on_refresh()

    def _on_header_clicked(self, col_idx: int) -> None:
        col_name = _COLUMN_ORDER[col_idx]
        if self._sort_col == col_name:
            self._sort_dir = "DESC" if self._sort_dir == "ASC" else "ASC"
        else:
            self._sort_col = col_name
            self._sort_dir = "ASC"
        self._page = 0
        qt_order = (
            Qt.SortOrder.AscendingOrder
            if self._sort_dir == "ASC"
            else Qt.SortOrder.DescendingOrder
        )
        self._table.horizontalHeader().setSortIndicator(col_idx, qt_order)
        self.on_refresh()

    def _update_pagination_controls(self) -> None:
        self._prev_btn.setEnabled(self._page > 0)
        has_next = (self._page + 1) * _PAGE_SIZE < self._total
        self._next_btn.setEnabled(has_next)
        if self._total == 0:
            self._page_label.setText("共 0 筆")
        else:
            start = self._page * _PAGE_SIZE + 1
            end = min((self._page + 1) * _PAGE_SIZE, self._total)
            self._page_label.setText(f"第 {start}–{end} 筆 / 共 {self._total} 筆")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_show_deleted_toggled(self) -> None:
        self._page = 0
        self.on_refresh()

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._search_input.clear()
        self._page = 0
        self.on_refresh()

    def clear_filter(self) -> None:
        self._filter_key = ""

    def refresh_context(self) -> None:
        """Reload client rows when the page becomes active."""
        self.on_refresh()

    def _on_selection_changed(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            self._edit_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._restore_btn.setEnabled(False)
            self._purge_btn.setEnabled(False)
            return
        rows = self._table.selectedItems()
        row_idx = self._table.row(rows[0])
        deleted_item = self._table.item(row_idx, _ID_COL_IDX)
        is_deleted = bool(deleted_item.data(Qt.ItemDataRole.UserRole)) if deleted_item else False
        self._edit_btn.setEnabled(not is_deleted)
        self._delete_btn.setEnabled(not is_deleted)
        self._restore_btn.setEnabled(is_deleted)
        self._purge_btn.setEnabled(is_deleted)

    def _selected_client_id(self) -> int | None:
        """Always return client.id from the id column — never row index."""
        rows = self._table.selectedItems()
        if not rows:
            return None
        row = self._table.row(rows[0])
        id_item = self._table.item(row, _ID_COL_IDX)
        return int(id_item.text()) if id_item else None

    def on_new_client(self) -> None:
        registry_repo = None
        try:
            if self._container.tax_registry_repo.count() > 0:
                registry_repo = self._container.tax_registry_repo
        except Exception as err:
            self._container.system_log.warn(
                "tax_registry.count failed — registry lookup hidden",
                detail={"exc": type(err).__name__},
            )
        dialog = NewClientDialog(
            self._container.clients,
            parent=self,
            tax_registry_repo=registry_repo,
        )
        if dialog.exec() == NewClientDialog.DialogCode.Accepted:
            self.on_refresh()

    def on_edit_client(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            return
        client = self._container.clients.get_client(client_id)
        if client is None:
            QMessageBox.warning(self, "找不到客戶", error_message("client.not_found"))
            self.on_refresh()
            return
        dialog = EditClientDialog(self._container.clients, client, parent=self)
        if dialog.exec() == EditClientDialog.DialogCode.Accepted:
            self.on_refresh()

    def on_delete_client(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            return
        client = self._container.clients.get_client(client_id)
        if client is None:
            QMessageBox.warning(self, "找不到客戶", error_message("client.not_found"))
            self.on_refresh()
            return
        reply = QMessageBox.question(
            self,
            "確認停用",
            f"確定要停用客戶「{client.client_name}」（{client.client_code}）？\n\n"
            "停用後客戶將不再顯示於列表，但資料仍保留於資料庫。\n"
            "如需復原，請聯絡系統維護人員。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.clients.delete_client(client_id)
        except ClientValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception as err:
            _log.error("clients.delete failed", exc_info=err)
            QMessageBox.warning(self, "刪除失敗", error_message("client.delete.failed"))
            return
        self.on_refresh()

    def on_restore_client(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            return
        try:
            self._container.clients.restore_client(client_id)
        except ClientValidationError as exc:
            QMessageBox.warning(self, "復原失敗", error_message(exc.code))
            return
        except Exception as err:
            _log.error("clients.restore failed", exc_info=err)
            QMessageBox.warning(self, "復原失敗", error_message("client.restore.failed"))
            return
        self.on_refresh()

    def on_purge_client(self) -> None:
        client_id = self._selected_client_id()
        if client_id is None:
            return
        reply = QMessageBox.question(
            self,
            "永久刪除客戶",
            "此操作會永久移除已封存客戶，且不能復原。\n"
            "若客戶仍有案件資料，系統會阻止刪除。\n\n"
            "確定要永久刪除？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.clients.purge_client(client_id)
        except ClientValidationError as exc:
            QMessageBox.warning(self, "永久刪除失敗", error_message(exc.code))
            return
        except Exception as err:
            _log.error("clients.purge failed", exc_info=err)
            QMessageBox.warning(self, "永久刪除失敗", error_message("client.purge.failed"))
            return
        self.on_refresh()

    def on_bulk_import(self) -> None:
        wizard = BulkImportWizard(
            self._container.clients,
            self._container.clients_repo,
            parent=self,
        )
        if wizard.exec() == BulkImportWizard.DialogCode.Accepted:
            self.on_refresh()

    def on_refresh(self) -> None:
        from ..action_registry import FilterKey
        query = self._search_input.text()
        include_deleted = self._show_deleted_check.isChecked()
        try:
            if self._filter_key == FilterKey.LEASE_EXPIRING:
                today = today_iso()
                until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=30)).isoformat()
                rows = self._container.clients.list_lease_expiring_soon(today, until)
                self._total = len(rows)
                start = self._page * _PAGE_SIZE
                rows = rows[start : start + _PAGE_SIZE]
            else:
                search_svc = getattr(self._container, "search", None)
                if not include_deleted and search_svc is not None and search_svc.is_fts_eligible(query):
                    all_rows = search_svc.search_clients(query.strip())
                    self._total = len(all_rows)
                    start = self._page * _PAGE_SIZE
                    rows = all_rows[start : start + _PAGE_SIZE]
                else:
                    self._total = self._container.clients.count_clients(query, include_deleted=include_deleted)
                    rows = self._container.clients.search_clients(
                        query,
                        order_by=self._sort_col,
                        order_dir=self._sort_dir,
                        limit=_PAGE_SIZE,
                        offset=self._page * _PAGE_SIZE,
                        include_deleted=include_deleted,
                    )
        except Exception as err:
            self._container.system_log.error("clients.list failed", exc=err)
            QMessageBox.warning(self, "載入失敗", error_message("client.list.failed"))
            return

        q = self._search_input.text().strip()
        self._count_label.setText(f"符合 {self._total} 筆" if q else f"共 {self._total} 筆")
        self._table.setRowCount(len(rows))
        for row_idx, client in enumerate(rows):
            is_deleted = client.deleted_at is not None
            values = {
                "id": str(client.id),
                "client_code": client.client_code,
                "tax_id": client.tax_id or "",
                "client_name": client.client_name,
                "short_name": client.short_name or "",
                "contact_name": client.contact_name or "",
                "contact_phone": client.contact_phone or "",
                "contact_email": client.contact_email or "",
                "address": client.address or "",
                "note": client.note or "",
                "lease_start": client.lease_start or "",
                "lease_end": client.lease_end or "",
                "updated_at": client.updated_at,
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setToolTip(values[col])
                if is_deleted:
                    item.setForeground(_DELETED_FG)
                if col == "id":
                    item.setData(Qt.ItemDataRole.UserRole, is_deleted)
                self._table.setItem(row_idx, col_idx, item)

        self._empty_label.setVisible(self._total == 0)
        self._table.setVisible(self._total > 0)
        self._update_pagination_controls()
        self._apply_column_visibility()
