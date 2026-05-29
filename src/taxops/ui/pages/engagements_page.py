"""Engagements page: three-layer drill-down (Slice 22 / v0.14.3).

Replaces the Slice 21B vertical splitter master-detail with a
``QStackedWidget`` so the three levels (case → request batch → document
item) live on their own pages:

* Page 0 — engagement list (master)
* Page 1 — ``DocumentRequestsPage`` in ``view_mode='requests_only'``
  (only the request-batch table is visible)
* Page 2 — ``DocumentRequestsPage`` in ``view_mode='items_only'``
  (only the document-item table is visible)

A breadcrumb above the stack shows the current depth and lets the user
jump back to any ancestor level.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.clock import today_iso
from ...i18n import NAV_LABELS, error_message
from ...i18n.status_labels import STATUS_LABELS, status_to_label
from ...services.container import ServiceContainer
from ...services.engagements import EngagementValidationError
from ..action_registry import FilterKey
from ..dialogs.edit_engagement_dialog import EditEngagementDialog
from ..dialogs.new_engagement_dialog import NewEngagementDialog
from ..style import toolbar_icon
from ..widgets.column_settings import ColumnSettings
from ..widgets.flow_layout import FlowLayout
from .document_requests_page import DocumentRequestsPage

_COLUMN_ORDER = (
    "id",
    "client_label",
    "engagement_name",
    "tax_type",
    "period_name",
    "status",
    "owner",
    "due_date",
    "updated_at",
)

_TABLE_HEADERS = {
    "id": "編號",
    "client_label": "客戶",
    "engagement_name": "案件名稱",
    "tax_type": "稅種",
    "period_name": "期間",
    "status": "狀態",
    "owner": "負責人",
    "due_date": "截止日",
    "updated_at": "更新時間",
}

# Slice 21C: cols the user cannot hide via header context menu.
_CORE_COLS = frozenset({"client_label", "engagement_name", "status"})


_ALL_CLIENTS = -1

# QStackedWidget page indices.
_PAGE_LIST = 0
_PAGE_REQUESTS = 1
_PAGE_ITEMS = 2


class EngagementsPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._current_client_id: int = _ALL_CLIENTS
        self._current_engagement_id: int | None = None
        self._current_request_id: int | None = None
        self._engagement_rows_by_id: dict[int, object] = {}
        self._engagement_client_labels: dict[int, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(10)

        # Breadcrumb row — three buttons that act as jump targets.
        breadcrumb_row = QHBoxLayout()
        breadcrumb_row.setSpacing(4)
        self._bc_root_btn = QPushButton(NAV_LABELS["engagements"])
        self._bc_root_btn.setStyleSheet(self._breadcrumb_style(active=True))
        self._bc_root_btn.clicked.connect(self._show_master)
        self._bc_sep1 = QLabel(" › ")
        self._bc_engagement_btn = QPushButton("")
        self._bc_engagement_btn.setStyleSheet(self._breadcrumb_style())
        self._bc_engagement_btn.clicked.connect(self._show_requests)
        self._bc_sep2 = QLabel(" › ")
        self._bc_request_btn = QPushButton("")
        self._bc_request_btn.setStyleSheet(self._breadcrumb_style())
        self._bc_request_btn.clicked.connect(self._show_items)
        for w in (
            self._bc_root_btn,
            self._bc_sep1,
            self._bc_engagement_btn,
            self._bc_sep2,
            self._bc_request_btn,
        ):
            breadcrumb_row.addWidget(w)
        breadcrumb_row.addStretch(1)
        outer.addLayout(breadcrumb_row)

        # QStackedWidget: three drill-down pages.
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, stretch=1)

        # Page 0 — master engagement list.
        self._master_page = self._build_master_page()
        self._stack.addWidget(self._master_page)

        # Page 1 — requests_only DocumentRequestsPage.
        self._requests_page = DocumentRequestsPage(
            container, embedded=True, view_mode="requests_only"
        )
        self._requests_page.drill_to_items.connect(self._on_drill_to_items)
        self._stack.addWidget(self._requests_page)

        # Backward-compatible alias used by 21B-era tests.
        self._doc_requests_widget = self._requests_page

        # Page 2 — items_only DocumentRequestsPage.
        self._items_page = DocumentRequestsPage(
            container, embedded=True, view_mode="items_only"
        )
        self._stack.addWidget(self._items_page)

        self._filter_key: str = ""
        self._show_master()
        self._on_load_and_refresh()

    # ------------------------------------------------------------------
    # Master engagement list (page 0)
    # ------------------------------------------------------------------

    def _build_master_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("客戶："))
        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(260)
        filter_row.addWidget(self._client_combo)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        self._new_btn = QPushButton("新增案件")
        self._edit_btn = QPushButton("編輯案件")
        self._status_btn = QPushButton("切換狀態")
        self._delete_btn = QPushButton("刪除案件")
        self._open_btn = QPushButton("進入索件 →")
        self._refresh_btn = QPushButton("重新整理")

        self._new_btn.setIcon(toolbar_icon("new"))
        self._edit_btn.setIcon(toolbar_icon("edit"))
        self._status_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._open_btn.setIcon(toolbar_icon("export"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))

        self._new_btn.setEnabled(False)
        self._edit_btn.setEnabled(False)
        self._status_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._open_btn.setEnabled(False)

        for btn in (
            self._new_btn,
            self._edit_btn,
            self._status_btn,
            self._delete_btn,
            self._open_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        layout.addWidget(toolbar_widget)

        self._empty_label = QLabel("請先選擇客戶，或此客戶尚無案件。")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #777; padding: 24px;")
        layout.addWidget(self._empty_label)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        self._table.setHorizontalHeaderLabels(
            [_TABLE_HEADERS[c] for c in _COLUMN_ORDER]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setMinimumWidth(340)
        self._table.setMaximumWidth(560)
        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(
            _COLUMN_ORDER.index("engagement_name"), QHeaderView.ResizeMode.Stretch
        )
        content_splitter.addWidget(self._table)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 8, 0, 0)
        detail_layout.setSpacing(8)
        self._detail_title = QLabel("尚未選取案件")
        self._detail_title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self._detail_client = QLabel("請從左側選取一筆案件。")
        self._detail_client.setWordWrap(True)
        self._detail_client.setStyleSheet("color: #475569;")
        self._detail_meta = QLabel("")
        self._detail_meta.setWordWrap(True)
        self._detail_meta.setStyleSheet("color: #334155;")
        self._detail_notes = QLabel("")
        self._detail_notes.setWordWrap(True)
        self._detail_notes.setStyleSheet("color: #64748B;")
        detail_layout.addWidget(self._detail_title)
        detail_layout.addWidget(self._detail_client)
        detail_layout.addWidget(self._detail_meta)
        detail_layout.addWidget(self._detail_notes)
        detail_layout.addStretch(1)
        content_splitter.addWidget(detail_panel)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        layout.addWidget(content_splitter, stretch=1)

        self._client_combo.currentIndexChanged.connect(self._on_client_changed)
        self._new_btn.clicked.connect(self._on_new_engagement)
        self._edit_btn.clicked.connect(self._on_edit_engagement)
        self._status_btn.clicked.connect(self._on_set_status)
        self._delete_btn.clicked.connect(self._on_delete)
        self._open_btn.clicked.connect(self._on_open_engagement)
        self._refresh_btn.clicked.connect(self._on_load_and_refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_open_engagement)

        self._col_settings = ColumnSettings(
            table=self._table,
            table_id="engagements",
            all_cols=_COLUMN_ORDER,
            core_cols=_CORE_COLS,
            headers=_TABLE_HEADERS,
            settings=self._container.settings,
        )
        self._col_settings.install()
        for col in ("id", "tax_type", "period_name", "owner", "due_date", "updated_at"):
            self._table.setColumnHidden(_COLUMN_ORDER.index(col), True)
        return page

    # ------------------------------------------------------------------
    # Breadcrumb / page navigation
    # ------------------------------------------------------------------

    def _breadcrumb_style(self, *, active: bool = False) -> str:
        color = "#2563EB" if active else "#64748B"
        weight = "600" if active else "500"
        return (
            "QPushButton { background: transparent; border: none; "
            f"color: {color}; font-size: 13px; font-weight: {weight}; "
            "padding: 4px 6px; }"
            "QPushButton:hover { color: #1D4ED8; }"
            "QPushButton:disabled { color: #94A3B8; }"
        )

    def _show_master(self) -> None:
        self._stack.setCurrentIndex(_PAGE_LIST)
        self._bc_engagement_btn.hide()
        self._bc_sep1.hide()
        self._bc_request_btn.hide()
        self._bc_sep2.hide()

    def _show_requests(self) -> None:
        if self._current_engagement_id is None:
            return
        self._stack.setCurrentIndex(_PAGE_REQUESTS)
        self._bc_engagement_btn.show()
        self._bc_sep1.show()
        self._bc_request_btn.hide()
        self._bc_sep2.hide()

    def _show_items(self) -> None:
        if self._current_request_id is None:
            return
        self._stack.setCurrentIndex(_PAGE_ITEMS)
        self._bc_engagement_btn.show()
        self._bc_sep1.show()
        self._bc_request_btn.show()
        self._bc_sep2.show()

    def _on_open_engagement(self, *_args) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        self._drill_to_engagement(eng_id)

    def _drill_to_engagement(self, engagement_id: int) -> None:
        eng = self._container.engagements.get_engagement(engagement_id)
        if eng is None:
            QMessageBox.warning(
                self, "找不到案件", error_message("engagement.not_found")
            )
            self._refresh_engagements()
            return
        self._current_engagement_id = engagement_id
        self._current_request_id = None
        self._requests_page.load_engagement(engagement_id)
        self._bc_engagement_btn.setText(eng.engagement_name)
        self._show_requests()

    def _on_drill_to_items(self, request_id: int) -> None:
        try:
            req = self._container.doc_requests.get_request(request_id)
        except Exception:
            req = None
        self._current_request_id = request_id
        self._items_page.load_request_items(request_id)
        label = req.period_name if req else f"#{request_id}"
        self._bc_request_btn.setText(label)
        self._show_items()

    # ------------------------------------------------------------------
    # Public API — kept for backward compatibility with 21B tests + main_window
    # ------------------------------------------------------------------

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._refresh_engagements()
        self._show_master()

    def clear_filter(self) -> None:
        self._filter_key = ""
        self._current_client_id = _ALL_CLIENTS
        self._show_master()

    def refresh_context(self) -> None:
        self._on_load_and_refresh()
        self._requests_page.refresh_context()

    # Slice 21B alias retained for tests.
    def _sync_embedded_to_selection(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            self._requests_page.clear_filter()
            self._requests_page.refresh_context()
        else:
            self._requests_page.load_engagement(eng_id)

    # ------------------------------------------------------------------
    # Engagement list refresh
    # ------------------------------------------------------------------

    def _on_load_and_refresh(self) -> None:
        saved_id = self._current_client_id
        self._client_combo.blockSignals(True)
        self._client_combo.clear()
        self._client_combo.addItem("全部客戶", userData=_ALL_CLIENTS)
        try:
            clients = self._container.clients.search_clients("", limit=500)
        except Exception as err:
            self._container.system_log.error("clients.list in engagements failed", exc=err)
            clients = []
        for client in clients:
            label = f"{client.client_code}  {client.client_name}"
            self._client_combo.addItem(label, userData=client.id)
        self._client_combo.blockSignals(False)

        restore_idx = 0
        for i in range(self._client_combo.count()):
            if self._client_combo.itemData(i) == saved_id:
                restore_idx = i
                break
        self._client_combo.setCurrentIndex(restore_idx)
        self._current_client_id = self._client_combo.currentData()
        self._new_btn.setEnabled(self._current_client_id != _ALL_CLIENTS)
        self._refresh_engagements()

    def _on_client_changed(self, idx: int) -> None:
        if idx < 0:
            self._current_client_id = _ALL_CLIENTS
            self._new_btn.setEnabled(False)
            self._refresh_engagements()
            return
        self._current_client_id = self._client_combo.itemData(idx)
        self._new_btn.setEnabled(self._current_client_id != _ALL_CLIENTS)
        self._refresh_engagements()

    def _refresh_engagements(self) -> None:
        try:
            if self._filter_key == FilterKey.UPCOMING:
                today = today_iso()
                until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=7)).isoformat()
                rows = self._container.engagements.list_upcoming(today, until)
            elif self._filter_key == FilterKey.OVERDUE:
                rows = self._container.engagements.list_overdue(today_iso())
            elif self._current_client_id == _ALL_CLIENTS:
                rows = self._container.engagements.list_all()
            else:
                rows = self._container.engagements.list_by_client(self._current_client_id)
        except Exception as err:
            self._container.system_log.error("engagements.list failed", exc=err)
            QMessageBox.warning(self, "載入失敗", error_message("system.unexpected"))
            return

        self._engagement_rows_by_id = {eng.id: eng for eng in rows}
        self._engagement_client_labels = {}
        self._table.setRowCount(len(rows))
        for row_idx, eng in enumerate(rows):
            client = self._container.clients.get_client(eng.client_id)
            client_label = client.client_name if client else "(未知客戶)"
            self._engagement_client_labels[eng.id] = client_label
            values = {
                "id": str(eng.id),
                "client_label": client_label,
                "engagement_name": f"{eng.engagement_name}\n{eng.period_name} · {status_to_label(eng.tax_type)}",
                "tax_type": status_to_label(eng.tax_type),
                "period_name": eng.period_name,
                "status": status_to_label(eng.status),
                "owner": eng.owner or "",
                "due_date": eng.due_date or "",
                "updated_at": eng.updated_at,
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setToolTip(values[col])
                self._table.setItem(row_idx, col_idx, item)
            self._table.setRowHeight(row_idx, 54)

        has_rows = len(rows) > 0
        self._empty_label.setVisible(not has_rows)
        self._table.setVisible(has_rows)
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._edit_btn.setEnabled(has_sel)
        self._status_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._open_btn.setEnabled(has_sel)
        # 21B legacy sync — populate the requests page so tests that read
        # ``_doc_requests_widget._engagement_id`` after selectRow keep passing
        # without forcing a drill-down navigation.
        eng_id = self._selected_engagement_id()
        self._update_engagement_detail(eng_id)
        if eng_id is None:
            self._requests_page.clear_filter()
        else:
            self._requests_page.load_engagement(eng_id)

    def _selected_engagement_id(self) -> int | None:
        items = self._table.selectedItems()
        if not items:
            return None
        row = self._table.row(items[0])
        id_item = self._table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _show_no_engagement_detail(self) -> None:
        self._detail_title.setText("尚未選取案件")
        self._detail_client.setText("請從左側選取一筆案件。")
        self._detail_meta.setText("")
        self._detail_notes.setText("")

    def _update_engagement_detail(self, engagement_id: int | None) -> None:
        if engagement_id is None:
            self._show_no_engagement_detail()
            return
        eng = self._engagement_rows_by_id.get(engagement_id)
        if eng is None:
            self._show_no_engagement_detail()
            return
        client_label = self._engagement_client_labels.get(engagement_id, "(未知客戶)")
        self._detail_title.setText(eng.engagement_name)
        self._detail_client.setText(f"客戶：{client_label}")
        due = eng.due_date or "未設定"
        owner = eng.owner or "未設定"
        self._detail_meta.setText(
            f"期間：{eng.period_name}　稅種：{status_to_label(eng.tax_type)}　狀態：{status_to_label(eng.status)}\n"
            f"負責人：{owner}　截止日：{due}"
        )
        self._detail_notes.setText(eng.notes or "")

    # ------------------------------------------------------------------
    # CRUD handlers
    # ------------------------------------------------------------------

    def _on_new_engagement(self) -> None:
        if self._current_client_id is None:
            return
        dialog = NewEngagementDialog(
            self._container.engagements,
            self._current_client_id,
            parent=self,
        )
        if dialog.exec() == NewEngagementDialog.DialogCode.Accepted:
            self._refresh_engagements()

    def _on_edit_engagement(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        dialog = EditEngagementDialog(
            self._container.engagements,
            eng,
            parent=self,
        )
        if dialog.exec() == EditEngagementDialog.DialogCode.Accepted:
            self._refresh_engagements()

    def _on_set_status(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        allowed = self._container.engagements.valid_next_statuses(eng_id)
        choices = sorted(
            STATUS_LABELS.get(s, s) for s in allowed if s != eng.status
        )
        if not choices:
            QMessageBox.information(self, "無可用狀態", "此案件目前無法切換到其他狀態。")
            return
        choice_label, ok = QInputDialog.getItem(
            self,
            "切換案件狀態",
            f"目前狀態：{status_to_label(eng.status)}\n請選擇目標狀態：",
            choices,
            editable=False,
        )
        if not ok or not choice_label:
            return
        label_to_value = {v: k for k, v in STATUS_LABELS.items()}
        target = label_to_value.get(choice_label)
        if target is None:
            return
        try:
            self._container.engagements.set_status(eng_id, target)
        except EngagementValidationError as exc:
            QMessageBox.warning(self, "切換失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "切換失敗", error_message("engagement.update.failed"))
            return
        self._refresh_engagements()

    def _on_delete(self) -> None:
        eng_id = self._selected_engagement_id()
        if eng_id is None:
            return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(self, "找不到案件", error_message("engagement.not_found"))
            self._refresh_engagements()
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除案件「{eng.engagement_name}」（{eng.period_name}）？\n"
            "資料將標記為已刪除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.engagements.delete_engagement(eng_id)
        except EngagementValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception:
            QMessageBox.warning(self, "刪除失敗", error_message("engagement.delete.failed"))
            return
        self._refresh_engagements()
