"""Document requests page: engagement combo + request list + items split view.

This page can run in two modes:

- Engagement mode: ``_engagement_id`` is set; the page lists doc requests for
  that engagement only.
- Global mode: ``_engagement_id is None``; the page lists every active doc
  request across all engagements.

The engagement combo at the top owns the switch between the two modes. When
the page is reached via sidebar nav (which fires ``clear_filter()``) it
falls back to global mode; ``load_engagement(id)`` is what the engagements
page uses to drill into a specific engagement.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import NAV_LABELS, error_message
from ...i18n.status_labels import STATUS_LABELS, status_to_label
from ...services.container import ServiceContainer
from ...services.document_requests import (
    CreateDocumentRequestInput,
    DocumentRequestValidationError,
    UpdateDocumentRequestInput,
    VALID_ITEM_STATUSES,
    VALID_REQUEST_STATUSES,
)
from ...services.export import ExportValidationError
from ..dialogs.add_document_item_dialog import AddDocumentItemDialog
from ..dialogs.document_item_template_dialog import DocumentItemTemplateDialog
from ..dialogs.generate_message_dialog import GenerateMessageDialog
from ..style import toolbar_icon
from ..widgets.column_settings import ColumnSettings
from ..widgets.flow_layout import FlowLayout

_REQ_COLUMNS = (
    "id",
    "engagement_label",
    "request_name",
    "tax_type",
    "period_name",
    "status",
    "follow_up_count",
    "requested_at",
    "due_date",
)

_REQ_HEADERS = {
    "id": "編號",
    "engagement_label": "所屬案件",
    "request_name": "批次名稱",
    "tax_type": "稅種",
    "period_name": "期間",
    "status": "狀態",
    "follow_up_count": "催件次數",
    "requested_at": "發出時間",
    "due_date": "截止日",
}

_ITEM_COLUMNS = ("id", "item_name", "item_status", "notes")
_ITEM_HEADERS = {
    "id": "編號",
    "item_name": "文件名稱",
    "item_status": "狀態",
    "notes": "備註",
}

# Slice 21C: required cols per table (cannot be hidden via context menu).
_REQ_CORE_COLS = frozenset({"request_name", "status"})
_ITEM_CORE_COLS = frozenset({"item_name", "item_status"})

_ALL_ENGAGEMENTS = -1


class DocumentRequestsPage(QWidget):
    """Doc requests page.

    ``view_mode`` controls which half of the splitter is visible (Slice 22):

    * ``"full"`` (default): legacy splitter — request table + item table.
    * ``"requests_only"``: only request table; item table + item buttons hidden.
      Double-clicking a request row emits :attr:`drill_to_items` so the parent
      EngagementsPage can switch its QStackedWidget to the items_only page.
    * ``"items_only"``: only item table; request table + request-level buttons
      hidden. Parent calls :meth:`load_request_items` to populate.
    """

    back_to_engagements = Signal()
    drill_to_items = Signal(int)  # request_id — fires in requests_only mode

    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
        embedded: bool = False,
        view_mode: str = "full",
    ) -> None:
        super().__init__(parent)
        if view_mode not in {"full", "requests_only", "items_only"}:
            raise ValueError(f"invalid view_mode: {view_mode!r}")
        self._container = container
        self._engagement_id: int | None = None
        self._embedded = embedded
        self._view_mode = view_mode
        self._items_only_request_id: int | None = None

        outer = QVBoxLayout(self)
        margin = 0 if embedded else 24
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(12)

        # Header row: back button + page title (hidden in embedded mode)
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(8)
        self._back_btn = QPushButton("← 返回案件")
        self._context_label = QLabel(NAV_LABELS["doc_requests"])
        self._context_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        hdr_row.addWidget(self._back_btn)
        hdr_row.addWidget(self._context_label)
        hdr_row.addStretch(1)
        outer.addLayout(hdr_row)
        if embedded:
            self._back_btn.hide()
            self._context_label.hide()

        # Context banner — visible in both standalone and embedded modes so
        # the user always knows whose doc requests are on screen.
        self._context_banner = QLabel("現在顯示：全部案件")
        self._context_banner.setObjectName("DocRequestsContextBanner")
        self._context_banner.setStyleSheet(
            "QLabel#DocRequestsContextBanner {"
            " background-color: #DBEAFE;"
            " color: #1E3A8A;"
            " font-size: 13px;"
            " font-weight: 600;"
            " border: 1px solid #93C5FD;"
            " border-radius: 6px;"
            " padding: 8px 12px;"
            "}"
        )
        self._context_banner.setWordWrap(True)
        outer.addWidget(self._context_banner)

        # Engagement selector row (hidden in embedded mode — the parent
        # EngagementsPage picks the engagement via its master list).
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._eng_combo_label = QLabel("案件：")
        filter_row.addWidget(self._eng_combo_label)
        self._engagement_combo = QComboBox()
        self._engagement_combo.setMinimumWidth(360)
        filter_row.addWidget(self._engagement_combo)
        filter_row.addStretch(1)
        outer.addLayout(filter_row)
        if embedded:
            self._eng_combo_label.hide()
            self._engagement_combo.hide()

        # Toolbar — FlowLayout so buttons wrap onto a second row when the
        # window narrows (RWD); replaces the previous QHBoxLayout that
        # truncated buttons.
        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        self._new_req_btn = QPushButton("新增索件批次")
        self._edit_req_btn = QPushButton("編輯批次")
        self._mark_requested_btn = QPushButton("標記已發出")
        self._request_status_btn = QPushButton("設定進度")
        self._follow_up_btn = QPushButton("催件 +1")
        self._delete_req_btn = QPushButton("刪除批次")
        self._add_item_btn = QPushButton("新增文件項目")
        self._edit_item_btn = QPushButton("編輯項目")
        self._delete_item_btn = QPushButton("刪除項目")
        self._bulk_delete_items_btn = QPushButton("批量刪除項目")
        self._item_status_btn = QPushButton("切換項目狀態")
        self._generate_btn = QPushButton("產生訊息")
        self._export_btn = QPushButton("匯出缺件清單")

        self._back_btn.setIcon(toolbar_icon("back"))
        self._new_req_btn.setIcon(toolbar_icon("new"))
        self._edit_req_btn.setIcon(toolbar_icon("edit"))
        self._mark_requested_btn.setIcon(toolbar_icon("complete"))
        self._request_status_btn.setIcon(toolbar_icon("edit"))
        self._follow_up_btn.setIcon(toolbar_icon("trial"))
        self._delete_req_btn.setIcon(toolbar_icon("delete"))
        self._add_item_btn.setIcon(toolbar_icon("new"))
        self._edit_item_btn.setIcon(toolbar_icon("edit"))
        self._delete_item_btn.setIcon(toolbar_icon("delete"))
        self._bulk_delete_items_btn.setIcon(toolbar_icon("delete"))
        self._item_status_btn.setIcon(toolbar_icon("edit"))
        self._generate_btn.setIcon(toolbar_icon("trial"))
        self._export_btn.setIcon(toolbar_icon("export"))

        self._new_req_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._edit_req_btn.setEnabled(False)
        self._mark_requested_btn.setEnabled(False)
        self._request_status_btn.setEnabled(False)
        self._follow_up_btn.setEnabled(False)
        self._delete_req_btn.setEnabled(False)
        self._add_item_btn.setEnabled(False)
        self._edit_item_btn.setEnabled(False)
        self._delete_item_btn.setEnabled(False)
        self._bulk_delete_items_btn.setEnabled(False)
        self._item_status_btn.setEnabled(False)
        self._generate_btn.setEnabled(False)

        for btn in (
            self._new_req_btn,
            self._edit_req_btn,
            self._mark_requested_btn,
            self._request_status_btn,
            self._follow_up_btn,
            self._delete_req_btn,
            self._add_item_btn,
            self._edit_item_btn,
            self._delete_item_btn,
            self._bulk_delete_items_btn,
            self._item_status_btn,
            self._generate_btn,
            self._export_btn,
        ):
            toolbar.addWidget(btn)
        outer.addWidget(toolbar_widget)

        # Empty state shown when no engagements exist at all
        self._no_engagement_label = QLabel(
            "尚未建立任何案件，請先到「案件管理」頁建立案件。"
        )
        self._no_engagement_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_engagement_label.setStyleSheet("color: #777; padding: 48px;")
        self._no_engagement_label.setVisible(False)
        outer.addWidget(self._no_engagement_label)

        # Splitter: left request list + right detail/actions area.
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        req_widget = QWidget()
        req_layout = QVBoxLayout(req_widget)
        req_layout.setContentsMargins(0, 0, 0, 4)
        req_layout.addWidget(QLabel("索件批次"))
        self._req_table = QTableWidget(0, len(_REQ_COLUMNS))
        self._req_table.setHorizontalHeaderLabels(
            [_REQ_HEADERS[c] for c in _REQ_COLUMNS]
        )
        self._req_table.verticalHeader().setVisible(False)
        self._req_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._req_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._req_table.setMinimumWidth(320)
        self._req_table.setMaximumWidth(520)
        rh = self._req_table.horizontalHeader()
        rh.setSectionResizeMode(
            _REQ_COLUMNS.index("request_name"), QHeaderView.ResizeMode.Stretch
        )
        req_layout.addWidget(self._req_table)
        self._splitter.addWidget(req_widget)

        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 4, 0, 0)
        self._request_detail_title = QLabel("尚未選取索件批次")
        self._request_detail_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self._request_detail_meta = QLabel("請從左側選取一筆批次。")
        self._request_detail_meta.setWordWrap(True)
        self._request_detail_meta.setStyleSheet("color: #475569;")
        self._request_detail_status = QLabel("")
        self._request_detail_status.setWordWrap(True)
        self._request_detail_status.setStyleSheet("color: #334155;")
        item_layout.addWidget(self._request_detail_title)
        item_layout.addWidget(self._request_detail_meta)
        item_layout.addWidget(self._request_detail_status)
        item_layout.addWidget(QLabel("文件項目"))
        self._item_table = QTableWidget(0, len(_ITEM_COLUMNS))
        self._item_table.setHorizontalHeaderLabels(
            [_ITEM_HEADERS[c] for c in _ITEM_COLUMNS]
        )
        self._item_table.verticalHeader().setVisible(False)
        self._item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._item_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._item_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        ih = self._item_table.horizontalHeader()
        ih.setSectionResizeMode(
            _ITEM_COLUMNS.index("item_name"), QHeaderView.ResizeMode.Stretch
        )
        item_layout.addWidget(self._item_table)
        self._splitter.addWidget(item_widget)

        outer.addWidget(self._splitter, stretch=1)
        self._request_rows_by_id: dict[int, object] = {}

        # Slice 22 v0.14.3 — view_mode visibility for drill-down inside the
        # EngagementsPage QStackedWidget. Default "full" preserves legacy.
        if self._view_mode == "requests_only":
            item_widget.hide()
            for btn in (
                self._add_item_btn,
                self._edit_item_btn,
                self._delete_item_btn,
                self._bulk_delete_items_btn,
                self._item_status_btn,
            ):
                btn.hide()
            self._req_table.doubleClicked.connect(self._on_req_row_double_clicked)
        elif self._view_mode == "items_only":
            req_widget.hide()
            self._context_banner.hide()
            self._eng_combo_label.hide()
            self._engagement_combo.hide()
            for btn in (
                self._new_req_btn,
                self._edit_req_btn,
                self._mark_requested_btn,
                self._request_status_btn,
                self._follow_up_btn,
                self._delete_req_btn,
                self._generate_btn,
                self._export_btn,
            ):
                btn.hide()

        # Slice 21C: install column settings (hide/show + persist widths)
        self._req_col_settings = ColumnSettings(
            table=self._req_table,
            table_id="doc_requests",
            all_cols=_REQ_COLUMNS,
            core_cols=_REQ_CORE_COLS,
            headers=_REQ_HEADERS,
            settings=container.settings,
        )
        self._req_col_settings.install()
        for col in (
            "id",
            "tax_type",
            "period_name",
            "follow_up_count",
            "requested_at",
            "due_date",
        ):
            self._req_table.setColumnHidden(_REQ_COLUMNS.index(col), True)
        self._item_col_settings = ColumnSettings(
            table=self._item_table,
            table_id="doc_items",
            all_cols=_ITEM_COLUMNS,
            core_cols=_ITEM_CORE_COLS,
            headers=_ITEM_HEADERS,
            settings=container.settings,
        )
        self._item_col_settings.install()

        self._back_btn.clicked.connect(self.back_to_engagements)
        self._engagement_combo.currentIndexChanged.connect(
            self._on_engagement_combo_changed
        )
        self._new_req_btn.clicked.connect(self._on_new_request)
        self._edit_req_btn.clicked.connect(self._on_edit_request)
        self._mark_requested_btn.clicked.connect(self._on_mark_requested)
        self._request_status_btn.clicked.connect(self._on_set_request_status)
        self._follow_up_btn.clicked.connect(self._on_follow_up)
        self._delete_req_btn.clicked.connect(self._on_delete_request)
        self._add_item_btn.clicked.connect(self._on_add_item)
        self._edit_item_btn.clicked.connect(self._on_edit_item)
        self._delete_item_btn.clicked.connect(self._on_delete_item)
        self._bulk_delete_items_btn.clicked.connect(self._on_bulk_delete_items)
        self._item_status_btn.clicked.connect(self._on_set_item_status)
        self._generate_btn.clicked.connect(self._on_generate_message)
        self._export_btn.clicked.connect(self._on_export)
        self._req_table.itemSelectionChanged.connect(self._on_req_selection_changed)
        self._item_table.itemSelectionChanged.connect(self._on_item_selection_changed)

    # ------------------------------------------------------------------
    # Public API called by MainWindow / EngagementsPage
    # ------------------------------------------------------------------

    def clear_filter(self) -> None:
        self._engagement_id = None

    def refresh_context(self) -> None:
        self._populate_engagement_combo()
        self._render_current_view()

    def load_engagement(self, engagement_id: int) -> None:
        self._engagement_id = engagement_id
        self._populate_engagement_combo()
        self._render_current_view()

    # ------------------------------------------------------------------
    # Combo population and selection sync
    # ------------------------------------------------------------------

    def _engagement_label(self, eng, client_name: str) -> str:
        return f"{client_name} — {eng.engagement_name} — {eng.period_name}"

    def _populate_engagement_combo(self) -> None:
        self._engagement_combo.blockSignals(True)
        try:
            self._engagement_combo.clear()
            self._engagement_combo.addItem("全部案件", userData=_ALL_ENGAGEMENTS)
            try:
                engagements = self._container.engagements.list_all()
            except Exception as err:
                self._container.system_log.error(
                    "engagements.list_all failed", exc=err
                )
                engagements = []
            client_names: dict[int, str] = {}
            for eng in engagements:
                if eng.client_id not in client_names:
                    client = self._container.clients.get_client(eng.client_id)
                    client_names[eng.client_id] = (
                        client.client_name if client else "(未知客戶)"
                    )
                self._engagement_combo.addItem(
                    self._engagement_label(eng, client_names[eng.client_id]),
                    userData=eng.id,
                )
            target = (
                _ALL_ENGAGEMENTS
                if self._engagement_id is None
                else self._engagement_id
            )
            idx = self._engagement_combo.findData(target)
            if idx < 0:
                idx = 0
                self._engagement_id = None
            self._engagement_combo.setCurrentIndex(idx)
        finally:
            self._engagement_combo.blockSignals(False)

    def _on_engagement_combo_changed(self) -> None:
        data = self._engagement_combo.currentData()
        if data is None or data == _ALL_ENGAGEMENTS:
            self._engagement_id = None
        else:
            self._engagement_id = int(data)
        self._render_current_view()

    # ------------------------------------------------------------------
    # View rendering
    # ------------------------------------------------------------------

    def _render_current_view(self) -> None:
        if self._engagement_id is None:
            self._render_global_view()
        else:
            self._render_engagement_view()

    def _render_global_view(self) -> None:
        self._context_label.setText(f"{NAV_LABELS['doc_requests']}(全部)")
        self._no_engagement_label.setVisible(False)
        self._splitter.setVisible(True)
        # Show 所屬案件 column in global mode (default); banner updated post-load.
        col_idx = _REQ_COLUMNS.index("engagement_label")
        self._req_table.setColumnHidden(col_idx, False)
        self._load_all_requests()

    def _render_engagement_view(self) -> None:
        assert self._engagement_id is not None
        eng = self._container.engagements.get_engagement(self._engagement_id)
        if eng is None:
            QMessageBox.warning(
                self, "找不到案件", error_message("engagement.not_found")
            )
            self._engagement_id = None
            self._populate_engagement_combo()
            self._render_global_view()
            return
        client = self._container.clients.get_client(eng.client_id)
        client_part = f"【{client.client_name}】" if client else ""
        label = (
            f"{NAV_LABELS['doc_requests']} — "
            f"{client_part}{eng.engagement_name}({status_to_label(eng.status)})"
        )
        self._context_label.setText(label)
        client_name = client.client_name if client else "(未知客戶)"
        self._context_banner.setText(
            f"現在顯示：{client_name} — {eng.engagement_name}"
        )
        self._no_engagement_label.setVisible(False)
        self._splitter.setVisible(True)
        # 所屬案件 column is redundant when filtered to one engagement; hide it.
        col_idx = _REQ_COLUMNS.index("engagement_label")
        self._req_table.setColumnHidden(col_idx, True)
        self._refresh_requests()

    # ------------------------------------------------------------------
    # Table refresh
    # ------------------------------------------------------------------

    def _load_all_requests(self) -> None:
        saved_req_id = self._selected_request_id()
        try:
            reqs = self._container.doc_requests.list_all()
        except Exception as err:
            self._container.system_log.error(
                "doc_requests.list_all failed", exc=err
            )
            QMessageBox.warning(
                self, "載入失敗", error_message("system.unexpected")
            )
            return
        self._fill_request_table(reqs, saved_req_id)

    def _refresh_requests(self) -> None:
        if self._engagement_id is None:
            self._load_all_requests()
            return
        saved_req_id = self._selected_request_id()
        try:
            reqs = self._container.doc_requests.list_by_engagement(
                self._engagement_id
            )
        except Exception as err:
            self._container.system_log.error(
                "doc_requests.list failed", exc=err
            )
            QMessageBox.warning(
                self, "載入失敗", error_message("system.unexpected")
            )
            return
        self._fill_request_table(reqs, saved_req_id)

    def _fill_request_table(self, reqs, saved_req_id: int | None) -> None:
        self._req_table.setRowCount(len(reqs))
        self._request_rows_by_id = {req.id: req for req in reqs}
        labels = self._engagement_label_map(reqs)
        target_row = -1
        for row_idx, req in enumerate(reqs):
            if saved_req_id is not None and req.id == saved_req_id:
                target_row = row_idx
            values = {
                "id": str(req.id),
                "engagement_label": labels.get(req.engagement_id, ""),
                "request_name": f"{req.request_name}\n{req.period_name} · {status_to_label(req.tax_type)}",
                "tax_type": status_to_label(req.tax_type),
                "period_name": req.period_name,
                "status": status_to_label(req.status),
                "follow_up_count": str(req.follow_up_count),
                "requested_at": req.requested_at or "",
                "due_date": req.due_date or "",
            }
            for col_idx, col in enumerate(_REQ_COLUMNS):
                self._req_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(values[col])
                )
            self._req_table.setRowHeight(row_idx, 52)
        # Banner only updates in global mode (engagement mode set it earlier).
        if self._engagement_id is None:
            self._context_banner.setText(
                f"現在顯示：全部案件（{len(reqs)} 筆索件批次）"
            )
        if target_row >= 0:
            self._req_table.selectRow(target_row)
            # selectRow may not fire itemSelectionChanged when the same row is
            # already selected (no-op), so force an item reload to keep the
            # item table in sync with the request's current items.
            self._update_request_detail(saved_req_id)
            self._load_items_for_selected()
        else:
            self._req_table.clearSelection()
            self._item_table.setRowCount(0)
            self._show_no_request_detail()
            self._on_req_selection_changed()

    def _engagement_label_map(self, reqs) -> dict[int, str]:
        """Build engagement_id -> '客戶名 — 案件名' for the rows we are about to render.

        Single query per unique engagement; client cache shared across rows.
        """
        result: dict[int, str] = {}
        client_cache: dict[int, str] = {}
        for eng_id in {r.engagement_id for r in reqs}:
            eng = self._container.engagements.get_engagement(eng_id)
            if eng is None:
                result[eng_id] = "(已刪除案件)"
                continue
            if eng.client_id not in client_cache:
                client = self._container.clients.get_client(eng.client_id)
                client_cache[eng.client_id] = (
                    client.client_name if client else "(未知客戶)"
                )
            result[eng_id] = (
                f"{client_cache[eng.client_id]} — {eng.engagement_name}"
            )
        return result

    def _on_req_row_double_clicked(self, _index) -> None:
        """In requests_only mode, double-clicking a row drills to items_only
        page in the parent QStackedWidget via :attr:`drill_to_items`."""
        req_id = self._selected_request_id()
        if req_id is not None:
            self.drill_to_items.emit(req_id)

    def load_request_items(self, request_id: int) -> None:
        """For items_only mode: load items for the given request_id.

        The request table is hidden in this mode, so we bypass the
        selection-driven ``_load_items_for_selected`` and load directly.
        """
        self._items_only_request_id = request_id
        # Items_only mode: 「新增文件項目」 is always enabled (request_id
        # already known); per-item buttons enable on item selection.
        self._add_item_btn.setEnabled(True)
        try:
            items = self._container.doc_requests.list_items(request_id)
        except Exception as err:
            self._container.system_log.error(
                "doc_request_items.list failed", exc=err
            )
            self._item_table.setRowCount(0)
            return
        self._render_items(items)

    def _render_items(self, items) -> None:
        self._item_table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            values = {
                "id": str(item.id),
                "item_name": item.item_name,
                "item_status": status_to_label(item.item_status),
                "notes": item.notes or "",
            }
            for col_idx, col in enumerate(_ITEM_COLUMNS):
                self._item_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(values[col])
                )

    def _load_items_for_selected(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            self._item_table.setRowCount(0)
            return
        try:
            items = self._container.doc_requests.list_items(req_id)
        except Exception as err:
            self._container.system_log.error(
                "doc_request_items.list failed", exc=err
            )
            return

        self._item_table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            values = {
                "id": str(item.id),
                "item_name": item.item_name,
                "item_status": status_to_label(item.item_status),
                "notes": item.notes or "",
            }
            for col_idx, col in enumerate(_ITEM_COLUMNS):
                self._item_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(values[col])
                )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_req_selection_changed(self) -> None:
        has_sel = bool(self._req_table.selectedItems())
        self._edit_req_btn.setEnabled(has_sel)
        self._mark_requested_btn.setEnabled(has_sel)
        self._request_status_btn.setEnabled(has_sel)
        self._follow_up_btn.setEnabled(has_sel)
        self._delete_req_btn.setEnabled(has_sel)
        self._add_item_btn.setEnabled(has_sel)
        self._generate_btn.setEnabled(has_sel)
        if has_sel:
            self._update_request_detail(self._selected_request_id())
            self._load_items_for_selected()
        else:
            self._item_table.setRowCount(0)
            self._show_no_request_detail()
            self._item_status_btn.setEnabled(False)
            self._edit_item_btn.setEnabled(False)
            self._delete_item_btn.setEnabled(False)

    def _on_item_selection_changed(self) -> None:
        rows = self._selected_item_rows()
        single = len(rows) == 1
        multi = len(rows) >= 1
        self._item_status_btn.setEnabled(single)
        self._edit_item_btn.setEnabled(single)
        self._delete_item_btn.setEnabled(single)
        self._bulk_delete_items_btn.setEnabled(multi)

    def _selected_request_id(self) -> int | None:
        # In items_only mode, the request table is hidden — fall back to the
        # explicitly loaded request_id so add/edit/delete item handlers work.
        if self._view_mode == "items_only" and self._items_only_request_id is not None:
            return self._items_only_request_id
        items = self._req_table.selectedItems()
        if not items:
            return None
        row = self._req_table.row(items[0])
        id_item = self._req_table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _show_no_request_detail(self) -> None:
        self._request_detail_title.setText("尚未選取索件批次")
        self._request_detail_meta.setText("請從左側選取一筆批次。")
        self._request_detail_status.setText("")

    def _update_request_detail(self, request_id: int | None) -> None:
        if request_id is None:
            self._show_no_request_detail()
            return
        req = self._request_rows_by_id.get(request_id)
        if req is None:
            self._show_no_request_detail()
            return
        engagement_label = self._engagement_label_map([req]).get(req.engagement_id, "")
        self._request_detail_title.setText(req.request_name)
        self._request_detail_meta.setText(
            f"{engagement_label}\n期間：{req.period_name}　稅種：{status_to_label(req.tax_type)}"
        )
        due = req.due_date or "未設定"
        requested = req.requested_at or "尚未發出"
        self._request_detail_status.setText(
            f"狀態：{status_to_label(req.status)}　催件：{req.follow_up_count}　發出：{requested}　截止：{due}"
        )

    def _selected_item_id(self) -> int | None:
        items = self._item_table.selectedItems()
        if not items:
            return None
        row = self._item_table.row(items[0])
        id_cell = self._item_table.item(row, 0)
        return int(id_cell.text()) if id_cell else None

    def _selected_item_rows(self) -> list[int]:
        """Distinct row indices currently selected in the item table."""
        rows: set[int] = set()
        for item in self._item_table.selectedItems():
            rows.add(self._item_table.row(item))
        return sorted(rows)

    def _selected_item_ids(self) -> list[int]:
        ids: list[int] = []
        for row in self._selected_item_rows():
            cell = self._item_table.item(row, 0)
            if cell is None:
                continue
            try:
                ids.append(int(cell.text()))
            except ValueError:
                continue
        return ids

    # ------------------------------------------------------------------
    # Engagement picker (global-mode 新增索件批次)
    # ------------------------------------------------------------------

    def _pick_engagement_id(self) -> int | None:
        try:
            engagements = self._container.engagements.list_all()
        except Exception as err:
            self._container.system_log.error(
                "engagements.list_all failed", exc=err
            )
            QMessageBox.warning(
                self, "新增失敗", error_message("system.unexpected")
            )
            return None
        if not engagements:
            QMessageBox.information(
                self,
                "尚未建立案件",
                "目前沒有任何案件。請先到「案件管理」頁建立至少一個案件，再回到此頁新增索件批次。",
            )
            return None
        client_names: dict[int, str] = {}
        labels: list[str] = []
        label_to_id: dict[str, int] = {}
        for eng in engagements:
            if eng.client_id not in client_names:
                client = self._container.clients.get_client(eng.client_id)
                client_names[eng.client_id] = (
                    client.client_name if client else "(未知客戶)"
                )
            label = self._engagement_label(eng, client_names[eng.client_id])
            labels.append(label)
            label_to_id[label] = eng.id
        chosen, ok = QInputDialog.getItem(
            self,
            "選擇案件",
            "請選擇要新增索件批次的案件：",
            labels,
            current=0,
            editable=False,
        )
        if not ok or not chosen:
            return None
        return label_to_id.get(chosen)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new_request(self) -> None:
        eng_id = self._engagement_id
        global_mode = eng_id is None
        if global_mode:
            eng_id = self._pick_engagement_id()
            if eng_id is None:
                return
        eng = self._container.engagements.get_engagement(eng_id)
        if eng is None:
            QMessageBox.warning(
                self, "找不到案件", error_message("engagement.not_found")
            )
            return
        dlg = DocumentItemTemplateDialog(
            self._container, tax_type=eng.tax_type, parent=self
        )
        if dlg.exec() != DocumentItemTemplateDialog.DialogCode.Accepted:
            return
        item_names = dlg.selected_items()
        payload = CreateDocumentRequestInput(
            engagement_id=eng_id,
            tax_type=eng.tax_type,
            period_name=eng.period_name,
            item_names=item_names,
        )
        try:
            self._container.doc_requests.create_request(payload)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "新增失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request.create failed", exc=err
            )
            QMessageBox.warning(
                self, "新增失敗", error_message("doc_request.create.failed")
            )
            return
        if global_mode:
            self.load_engagement(eng_id)
        else:
            self._refresh_requests()

    def _on_edit_request(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        existing = self._container.doc_requests.get_request(req_id)
        if existing is None:
            QMessageBox.warning(self, "找不到索件批次", error_message("doc_request.not_found"))
            self._refresh_requests()
            return
        new_name, ok = QInputDialog.getText(
            self,
            "編輯批次名稱",
            "批次名稱",
            text=existing.request_name,
        )
        if not ok:
            return
        try:
            self._container.doc_requests.update_request(
                req_id,
                UpdateDocumentRequestInput(
                    request_name=new_name,
                    due_date=existing.due_date,
                    notes=existing.notes,
                ),
            )
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "編輯批次失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error("doc_request.update failed", exc=err)
            QMessageBox.warning(
                self, "編輯批次失敗", error_message("system.unexpected")
            )
            return
        self._refresh_requests()

    def _on_mark_requested(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        try:
            self._container.doc_requests.mark_requested(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "操作失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request.mark_requested failed", exc=err
            )
            QMessageBox.warning(
                self, "操作失敗", error_message("system.unexpected")
            )
            return
        self._refresh_requests()

    def _on_set_request_status(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_REQUEST_STATUSES}
        choices = sorted(label_to_value)
        req_row = self._req_table.currentRow()
        cur_label = (
            self._req_table.item(req_row, _REQ_COLUMNS.index("status"))
            or QTableWidgetItem()
        ).text()
        current_idx = choices.index(cur_label) if cur_label in choices else 0
        label, ok = QInputDialog.getItem(
            self,
            "設定進度",
            "請選擇目前索件進度",
            choices,
            current=current_idx,
            editable=False,
        )
        if not ok or not label:
            return
        status = label_to_value.get(label)
        if status is None:
            return
        try:
            self._container.doc_requests.set_request_status(req_id, status)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "設定進度失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request.set_request_status failed", exc=err
            )
            QMessageBox.warning(
                self, "設定進度失敗", error_message("system.unexpected")
            )
            return
        self._refresh_requests()

    def _on_follow_up(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        try:
            self._container.doc_requests.add_follow_up(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "操作失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request.add_follow_up failed", exc=err
            )
            QMessageBox.warning(
                self, "操作失敗", error_message("system.unexpected")
            )
            return
        self._refresh_requests()

    def _on_delete_request(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            "確定要刪除這個索件批次？刪除後將無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.doc_requests.delete_request(req_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request.delete failed", exc=err
            )
            QMessageBox.warning(
                self, "刪除失敗", error_message("doc_request.delete.failed")
            )
            return
        self._refresh_requests()

    def _on_add_item(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        dlg = AddDocumentItemDialog(self._container.doc_requests, req_id, parent=self)
        if dlg.exec() == AddDocumentItemDialog.DialogCode.Accepted:
            self._refresh_requests()

    def _on_edit_item(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        item_row = self._item_table.currentRow()
        cur_name = (
            self._item_table.item(item_row, _ITEM_COLUMNS.index("item_name"))
            or QTableWidgetItem()
        ).text()
        new_name, ok = QInputDialog.getText(
            self,
            "編輯項目名稱",
            "新名稱：",
            text=cur_name,
        )
        if not ok or not new_name.strip():
            return
        try:
            self._container.doc_requests.update_item(item_id, new_name.strip())
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "編輯失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request_item.update failed", exc=err
            )
            QMessageBox.warning(
                self, "編輯失敗", error_message("doc_request_item.update.failed")
            )
            return
        self._refresh_requests()

    def _on_bulk_delete_items(self) -> None:
        ids = self._selected_item_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self,
            "確認批量刪除",
            f"確定要刪除選取的 {len(ids)} 筆文件項目？此操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self._container.doc_requests.delete_items_bulk(ids)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "批量刪除失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request_item.bulk_delete failed", exc=err
            )
            QMessageBox.warning(
                self, "批量刪除失敗", error_message("doc_request_item.delete.failed")
            )
            return
        QMessageBox.information(
            self, "批量刪除完成", f"已刪除 {count} 筆文件項目。"
        )
        self._refresh_requests()

    def _on_delete_item(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            "確定要刪除此文件項目？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.doc_requests.delete_item(item_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request_item.delete failed", exc=err
            )
            QMessageBox.warning(
                self, "刪除失敗", error_message("doc_request_item.delete.failed")
            )
            return
        self._refresh_requests()

    def _on_set_item_status(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_ITEM_STATUSES}
        choices = sorted(label_to_value)
        item_row = self._item_table.currentRow()
        cur_item_label = (
            self._item_table.item(item_row, _ITEM_COLUMNS.index("item_status"))
            or QTableWidgetItem()
        ).text()
        current_idx = choices.index(cur_item_label) if cur_item_label in choices else 0
        label, ok = QInputDialog.getItem(
            self,
            "切換項目狀態",
            "請選擇新狀態：",
            choices,
            current=current_idx,
            editable=False,
        )
        if not ok or not label:
            return
        target = label_to_value.get(label)
        if target is None:
            return
        try:
            self._container.doc_requests.set_item_status(
                item_id, item_status=target
            )
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(self, "切換失敗", error_message(exc.code))
            return
        except Exception as err:
            self._container.system_log.error(
                "doc_request_item.set_status failed", exc=err
            )
            QMessageBox.warning(
                self, "切換失敗", error_message("system.unexpected")
            )
            return
        self._refresh_requests()

    def _on_generate_message(self) -> None:
        req_id = self._selected_request_id()
        if req_id is None:
            return
        dlg = GenerateMessageDialog(
            gen_svc=self._container.gen_messages,
            templates_svc=self._container.templates,
            request_id=req_id,
            parent=self,
        )
        dlg.exec()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "匯出缺件清單",
            "缺件清單.xlsx",
            "Excel 檔案 (*.xlsx)",
        )
        if not path:
            return
        try:
            count = self._container.export.export_missing_items_xlsx(
                output_path=Path(path),
                engagement_id=self._engagement_id,
            )
        except ExportValidationError as err:
            QMessageBox.critical(self, "匯出失敗", error_message(err.code))
            return
        except Exception as err:
            self._container.system_log.error("export.missing_items failed", exc=err)
            QMessageBox.critical(
                self, "匯出失敗", error_message("export.save_failed")
            )
            return
        if count == 0:
            QMessageBox.information(self, "匯出完成", error_message("export.no_rows"))
        else:
            QMessageBox.information(
                self, "匯出完成", f"已匯出 {count} 筆缺件項目至：\n{path}"
            )
