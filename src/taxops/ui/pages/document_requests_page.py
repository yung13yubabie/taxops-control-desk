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

from collections.abc import Callable
from dataclasses import dataclass
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
    DocumentItemsMutationResult,
    DocumentRequestValidationError,
    UpdateDocumentRequestInput,
    VALID_ITEM_STATUSES,
    VALID_REQUEST_STATUSES,
)
from ...services.export import ExportValidationError
from ...repositories.document_requests import (
    DocumentRequestItemRow,
    DocumentRequestRow,
)
from ..dialogs.add_document_item_dialog import AddDocumentItemDialog
from ..dialogs.document_item_template_dialog import DocumentItemTemplateDialog
from ..dialogs.generate_message_dialog import GenerateMessageDialog
from ..style import INFO_BG, INFO_FG, TEXT_MUTED, toolbar_icon
from ..widgets.column_settings import ColumnSettings
from ..widgets.empty_state import EmptyState
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

# Fixed status-column width so the batch name can never crush the status cell.
_REQ_STATUS_COL_WIDTH = 110

_ALL_ENGAGEMENTS = -1
_PAGE_SIZE = 50


@dataclass(frozen=True)
class DocumentMutationEvidence:
    operation: str
    engagement_id: int
    request_id: int
    request_before: DocumentRequestRow | None
    request_after: DocumentRequestRow | None
    items_before: tuple[DocumentRequestItemRow, ...]
    affected_items: tuple[DocumentRequestItemRow, ...] = ()
    deleted_items: tuple[DocumentRequestItemRow, ...] = ()
    request_deleted: bool = False

    def expected_items(self) -> tuple[DocumentRequestItemRow, ...]:
        if self.operation == "request.create":
            return self.affected_items
        deleted_ids = {row.id for row in self.deleted_items}
        replacements = {row.id: row for row in self.affected_items}
        result = [
            replacements.get(row.id, row)
            for row in self.items_before
            if row.id not in deleted_ids
        ]
        existing_ids = {row.id for row in self.items_before}
        result.extend(
            row
            for row in self.affected_items
            if row.id not in existing_ids
        )
        return tuple(sorted(result, key=lambda row: row.id))


@dataclass(frozen=True)
class DocumentMutationAck:
    evidence_taken: bool
    readback_succeeded: bool


DocumentMutationHandler = Callable[
    [DocumentMutationEvidence], DocumentMutationAck
]


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
    data_changed = Signal()

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
        self._external_mutation_reload = False
        self._items_only_request_id: int | None = None
        self._request_page = 0
        self._request_total = 0
        self._item_page = 0
        self._item_total = 0
        self._loaded_item_request_id: int | None = None
        self._mutation_handler: DocumentMutationHandler | None = None
        self._pending_mutation: DocumentMutationEvidence | None = None

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
        self._context_banner.setTextFormat(Qt.TextFormat.PlainText)
        self._context_banner.setObjectName("DocRequestsContextBanner")
        self._context_banner.setStyleSheet(
            f"QLabel#DocRequestsContextBanner {{"
            f" background-color: {INFO_BG};"
            f" color: {INFO_FG};"
            " font-size: 14px;"
            " font-weight: 600;"
            " border: 1px solid #93C5FD;"
            " border-radius: 6px;"
            " padding: 8px 12px;"
            "}"
        )
        self._context_banner.setWordWrap(True)
        outer.addWidget(self._context_banner)

        self._recovery_panel = QWidget()
        self._recovery_panel.setObjectName(
            "DocumentMutationRecoveryPanel"
        )
        self._recovery_panel.setStyleSheet(
            "QWidget#DocumentMutationRecoveryPanel {"
            " background-color: #FFF7ED;"
            " border: 1px solid #FDBA74;"
            " border-radius: 6px;"
            "}"
        )
        recovery_layout = QHBoxLayout(self._recovery_panel)
        recovery_layout.setContentsMargins(12, 8, 12, 8)
        recovery_layout.setSpacing(10)
        self._recovery_label = QLabel()
        self._recovery_label.setTextFormat(Qt.TextFormat.PlainText)
        self._recovery_label.setWordWrap(True)
        self._recovery_label.setStyleSheet(
            "font-size: 14px; color: #9A3412;"
        )
        self._recovery_retry_button = QPushButton("重新核對")
        recovery_layout.addWidget(self._recovery_label, 1)
        recovery_layout.addWidget(self._recovery_retry_button)
        self._recovery_panel.hide()
        outer.addWidget(self._recovery_panel)

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
        # No primary here. This page is always embedded — EngagementsPage builds two
        # instances of it, in requests_only and items_only view modes — and the host
        # page already owns the single primary (新增案件). Marking this primary put
        # three competing primaries on one page.
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
        self._mutation_buttons = (
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
        )
        outer.addWidget(toolbar_widget)

        # Empty state shown when no engagements exist at all
        self._no_engagement_label = QLabel(
            "尚未建立任何案件，請先到「案件管理」頁建立案件。"
        )
        self._no_engagement_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_engagement_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 48px;")
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
        rh = self._req_table.horizontalHeader()
        rh.setSectionResizeMode(
            _REQ_COLUMNS.index("request_name"), QHeaderView.ResizeMode.Stretch
        )
        req_status_idx = _REQ_COLUMNS.index("status")
        rh.setSectionResizeMode(req_status_idx, QHeaderView.ResizeMode.Fixed)
        self._req_table.setColumnWidth(req_status_idx, _REQ_STATUS_COL_WIDTH)
        req_layout.addWidget(self._req_table)
        req_page_row = QHBoxLayout()
        self._request_previous_btn = QPushButton("上一頁")
        self._request_next_btn = QPushButton("下一頁")
        self._request_page_label = QLabel("第 1 / 1 頁，共 0 筆")
        req_page_row.addWidget(self._request_previous_btn)
        req_page_row.addWidget(self._request_next_btn)
        req_page_row.addWidget(self._request_page_label, 1)
        req_layout.addLayout(req_page_row)
        self._req_empty_state = EmptyState(
            "尚無索件批次",
            detail="新增批次後即可批量加入文件項目、設定進度並產生訊息。",
            action_text="新增索件批次",
        )
        self._req_empty_state.hide()
        req_layout.addWidget(self._req_empty_state)
        self._splitter.addWidget(req_widget)

        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 4, 0, 0)
        self._request_detail_title = QLabel("尚未選取索件批次")
        self._request_detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self._request_detail_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self._request_detail_meta = QLabel("請從左側選取一筆批次。")
        self._request_detail_meta.setTextFormat(Qt.TextFormat.PlainText)
        self._request_detail_meta.setWordWrap(True)
        self._request_detail_meta.setStyleSheet("color: #475569;")
        self._request_detail_status = QLabel("")
        self._request_detail_status.setTextFormat(Qt.TextFormat.PlainText)
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
        item_page_row = QHBoxLayout()
        self._item_previous_btn = QPushButton("上一頁")
        self._item_next_btn = QPushButton("下一頁")
        self._item_page_label = QLabel("第 1 / 1 頁，共 0 筆")
        item_page_row.addWidget(self._item_previous_btn)
        item_page_row.addWidget(self._item_next_btn)
        item_page_row.addWidget(self._item_page_label, 1)
        item_layout.addLayout(item_page_row)
        self._splitter.addWidget(item_widget)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 2)

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
        if self._req_empty_state.action_button is not None:
            self._req_empty_state.action_button.clicked.connect(self._on_new_request)
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
        self._request_previous_btn.clicked.connect(
            self._previous_request_page
        )
        self._request_next_btn.clicked.connect(self._next_request_page)
        self._item_previous_btn.clicked.connect(self._previous_item_page)
        self._item_next_btn.clicked.connect(self._next_item_page)
        self._recovery_retry_button.clicked.connect(
            self._on_recovery_retry_clicked
        )

    # ------------------------------------------------------------------
    # Public API called by MainWindow / EngagementsPage
    # ------------------------------------------------------------------

    def clear_filter(self) -> None:
        self._engagement_id = None
        self._request_page = 0
        self._item_page = 0

    def refresh_context(self) -> bool:
        self._populate_engagement_combo()
        return self._render_current_view()

    def load_engagement(self, engagement_id: int) -> bool:
        if self._engagement_id != engagement_id:
            self._request_page = 0
            self._item_page = 0
        self._engagement_id = engagement_id
        self._populate_engagement_combo()
        return self._render_current_view()

    def request_id_at(self, row: int) -> int | None:
        if row < 0 or row >= self._req_table.rowCount():
            return None
        item = self._req_table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if type(value) is int else None

    def item_ids(self) -> tuple[int, ...]:
        ids: list[int] = []
        for row in range(self._item_table.rowCount()):
            item = self._item_table.item(row, 0)
            value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if type(value) is int:
                ids.append(value)
        return tuple(ids)

    def select_request_id(self, request_id: int) -> bool:
        if type(request_id) is not int or request_id <= 0:
            return False
        position = self._container.doc_requests.request_position(
            request_id, engagement_id=self._engagement_id
        )
        if position is None:
            return False
        target_page = position // _PAGE_SIZE
        if target_page != self._request_page:
            self._request_page = target_page
            if not self._refresh_requests():
                return False
        for row in range(self._req_table.rowCount()):
            if self.request_id_at(row) == request_id:
                self._req_table.blockSignals(True)
                self._req_table.selectRow(row)
                self._req_table.blockSignals(False)
                return self._apply_request_selection() and (
                    self._selected_request_id() == request_id
                )
        return False

    def select_item_id(self, request_id: int, item_id: int) -> bool:
        if not self.select_request_id(request_id):
            return False
        position = self._container.doc_requests.item_position(
            request_id, item_id
        )
        if position is None:
            return False
        target_page = position // _PAGE_SIZE
        if target_page != self._item_page:
            self._item_page = target_page
            if not self._load_items_for_selected():
                return False
        for row in range(self._item_table.rowCount()):
            cell = self._item_table.item(row, 0)
            if (
                cell is not None
                and cell.data(Qt.ItemDataRole.UserRole) == item_id
            ):
                self._item_table.selectRow(row)
                return self._selected_item_id() == item_id
        return False

    def set_external_mutation_reload(self, enabled: bool) -> None:
        """Let an owning workflow synchronously perform post-commit readback."""
        self._external_mutation_reload = bool(enabled)

    def set_mutation_commit_handler(
        self, handler: DocumentMutationHandler | None
    ) -> None:
        self._mutation_handler = handler

    @property
    def pending_mutation_evidence(
        self,
    ) -> DocumentMutationEvidence | None:
        return self._pending_mutation

    def _show_pending_recovery(self, *, retry_failed: bool = False) -> None:
        self._recovery_label.setText(
            (
                "重新核對仍失敗；資料可能已寫入，請勿重送。"
                "請確認資料庫可用後再按「重新核對」。"
            )
            if retry_failed
            else (
                "資料可能已寫入，請勿重送。"
                "請按「重新核對」確認目前資料。"
            )
        )
        self._recovery_panel.show()
        self._recovery_retry_button.setEnabled(True)
        for button in self._mutation_buttons:
            button.setEnabled(False)

    def _clear_pending_recovery(self) -> None:
        self._recovery_panel.hide()
        self._restore_mutation_buttons_from_selection()

    def _restore_mutation_buttons_from_selection(self) -> None:
        """Restore mutation actions from current widget state without reads."""
        request_selected = len(
            self._req_table.selectionModel().selectedRows(0)
        ) == 1
        item_rows = self._selected_item_rows()
        item_selected = len(item_rows) == 1
        any_items_selected = bool(item_rows)
        items_only_request_loaded = (
            self._view_mode == "items_only"
            and self._items_only_request_id is not None
        )
        self._new_req_btn.setEnabled(True)
        self._edit_req_btn.setEnabled(request_selected)
        self._mark_requested_btn.setEnabled(request_selected)
        self._request_status_btn.setEnabled(request_selected)
        self._follow_up_btn.setEnabled(request_selected)
        self._delete_req_btn.setEnabled(request_selected)
        self._add_item_btn.setEnabled(
            request_selected or items_only_request_loaded
        )
        self._item_status_btn.setEnabled(item_selected)
        self._edit_item_btn.setEnabled(item_selected)
        self._delete_item_btn.setEnabled(item_selected)
        self._bulk_delete_items_btn.setEnabled(any_items_selected)

    def _mutation_is_pending(self) -> bool:
        if self._pending_mutation is None:
            return False
        self._show_pending_recovery()
        return True

    def _on_recovery_retry_clicked(self) -> None:
        self._recovery_retry_button.setEnabled(False)
        if not self.retry_pending_mutation_verification():
            self._show_pending_recovery(retry_failed=True)

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

    def _render_current_view(self) -> bool:
        if self._engagement_id is None:
            return self._render_global_view()
        return self._render_engagement_view()

    def _render_global_view(self) -> bool:
        self._context_label.setText(f"{NAV_LABELS['doc_requests']}(全部)")
        self._no_engagement_label.setVisible(False)
        self._splitter.setVisible(True)
        # Show 所屬案件 column in global mode (default); banner updated post-load.
        col_idx = _REQ_COLUMNS.index("engagement_label")
        self._req_table.setColumnHidden(col_idx, False)
        return self._load_all_requests()

    def _render_engagement_view(self) -> bool:
        engagement_id = self._engagement_id
        if engagement_id is None:
            return self._render_global_view()
        eng = self._container.engagements.get_engagement(engagement_id)
        if eng is None:
            QMessageBox.warning(
                self, "找不到案件", error_message("engagement.not_found")
            )
            self._engagement_id = None
            self._populate_engagement_combo()
            self._render_global_view()
            return False
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
        return self._refresh_requests()

    # ------------------------------------------------------------------
    # Table refresh
    # ------------------------------------------------------------------

    def _update_request_pagination(self) -> None:
        page_count = max(
            1, (self._request_total + _PAGE_SIZE - 1) // _PAGE_SIZE
        )
        self._request_page_label.setText(
            f"第 {self._request_page + 1} / {page_count} 頁，"
            f"共 {self._request_total} 筆"
            + (
                "；尚有更多批次"
                if (self._request_page + 1) * _PAGE_SIZE
                < self._request_total
                else ""
            )
        )
        self._request_previous_btn.setEnabled(self._request_page > 0)
        self._request_next_btn.setEnabled(
            (self._request_page + 1) * _PAGE_SIZE
            < self._request_total
        )

    def _previous_request_page(self) -> None:
        if self._request_page <= 0:
            return
        self._request_page -= 1
        self._refresh_requests()

    def _next_request_page(self) -> None:
        if (self._request_page + 1) * _PAGE_SIZE >= self._request_total:
            return
        self._request_page += 1
        self._refresh_requests()

    def _update_item_pagination(self) -> None:
        page_count = max(1, (self._item_total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._item_page_label.setText(
            f"第 {self._item_page + 1} / {page_count} 頁，"
            f"共 {self._item_total} 筆"
            + (
                "；尚有更多項目"
                if (self._item_page + 1) * _PAGE_SIZE < self._item_total
                else ""
            )
        )
        self._item_previous_btn.setEnabled(self._item_page > 0)
        self._item_next_btn.setEnabled(
            (self._item_page + 1) * _PAGE_SIZE < self._item_total
        )

    def _previous_item_page(self) -> None:
        if self._item_page <= 0:
            return
        self._item_page -= 1
        self._load_items_for_selected()

    def _next_item_page(self) -> None:
        if (self._item_page + 1) * _PAGE_SIZE >= self._item_total:
            return
        self._item_page += 1
        self._load_items_for_selected()

    def _load_all_requests(self) -> bool:
        saved_req_id = self._selected_request_id()
        try:
            self._request_total = self._container.doc_requests.count_all()
            max_page = max(
                0, (self._request_total - 1) // _PAGE_SIZE
            )
            self._request_page = min(self._request_page, max_page)
            reqs = self._container.doc_requests.list_all(
                limit=_PAGE_SIZE,
                offset=self._request_page * _PAGE_SIZE,
            )
        except Exception as err:
            self._container.system_log.error(
                "doc_requests.list_all failed", exc=err
            )
            QMessageBox.warning(
                self, "載入失敗", error_message("system.unexpected")
            )
            if self._external_mutation_reload:
                self._fill_request_table([], None)
            return False
        return self._fill_request_table(reqs, saved_req_id)

    def _refresh_requests(self) -> bool:
        if self._engagement_id is None:
            return self._load_all_requests()
        saved_req_id = self._selected_request_id()
        try:
            self._request_total = (
                self._container.doc_requests.count_by_engagement(
                    self._engagement_id
                )
            )
            max_page = max(
                0, (self._request_total - 1) // _PAGE_SIZE
            )
            self._request_page = min(self._request_page, max_page)
            reqs = self._container.doc_requests.list_by_engagement(
                self._engagement_id,
                limit=_PAGE_SIZE,
                offset=self._request_page * _PAGE_SIZE,
            )
        except Exception as err:
            self._container.system_log.error(
                "doc_requests.list failed", exc=err
            )
            QMessageBox.warning(
                self, "載入失敗", error_message("system.unexpected")
            )
            if self._external_mutation_reload:
                self._fill_request_table([], None)
            return False
        return self._fill_request_table(reqs, saved_req_id)

    def _fill_request_table(self, reqs, saved_req_id: int | None) -> bool:
        self._req_table.blockSignals(True)
        self._req_table.setRowCount(len(reqs))
        has_rows = len(reqs) > 0
        self._req_table.setVisible(has_rows)
        self._req_empty_state.setVisible(not has_rows)
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
                cell = QTableWidgetItem(values[col])
                cell.setData(Qt.ItemDataRole.UserRole, req.id)
                self._req_table.setItem(row_idx, col_idx, cell)
            self._req_table.setRowHeight(row_idx, 52)
        self._req_table.blockSignals(False)
        self._update_request_pagination()
        # Banner only updates in global mode (engagement mode set it earlier).
        if self._engagement_id is None:
            self._context_banner.setText(
                f"現在顯示：全部案件（{len(reqs)} 筆索件批次）"
            )
        if target_row >= 0:
            self._req_table.blockSignals(True)
            self._req_table.selectRow(target_row)
            self._req_table.blockSignals(False)
            return self._apply_request_selection()
        else:
            self._req_table.clearSelection()
            self._item_table.setRowCount(0)
            self._show_no_request_detail()
            self._on_req_selection_changed()
        return True

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

    def load_request_items(self, request_id: int) -> bool:
        """For items_only mode: load items for the given request_id.

        The request table is hidden in this mode, so we bypass the
        selection-driven ``_load_items_for_selected`` and load directly.
        """
        self._items_only_request_id = request_id
        if self._loaded_item_request_id != request_id:
            self._item_page = 0
        self._loaded_item_request_id = request_id
        # Items_only mode: 「新增文件項目」 is always enabled (request_id
        # already known); per-item buttons enable on item selection.
        self._add_item_btn.setEnabled(True)
        try:
            self._item_total = self._container.doc_requests.count_items(
                request_id
            )
            max_page = max(
                0, (self._item_total - 1) // _PAGE_SIZE
            )
            self._item_page = min(self._item_page, max_page)
            items = self._container.doc_requests.list_items(
                request_id,
                limit=_PAGE_SIZE,
                offset=self._item_page * _PAGE_SIZE,
            )
        except Exception as err:
            self._container.system_log.error(
                "doc_request_items.list failed", exc=err
            )
            self._item_table.setRowCount(0)
            return False
        self._render_items(items)
        return True

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
                cell = QTableWidgetItem(values[col])
                cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self._item_table.setItem(row_idx, col_idx, cell)
        self._update_item_pagination()

    def _load_items_for_selected(self) -> bool:
        req_id = self._selected_request_id()
        if req_id is None:
            self._item_table.setRowCount(0)
            self._item_total = 0
            self._update_item_pagination()
            return True
        if self._loaded_item_request_id != req_id:
            self._item_page = 0
        self._loaded_item_request_id = req_id
        try:
            self._item_total = self._container.doc_requests.count_items(req_id)
            max_page = max(0, (self._item_total - 1) // _PAGE_SIZE)
            self._item_page = min(self._item_page, max_page)
            items = self._container.doc_requests.list_items(
                req_id,
                limit=_PAGE_SIZE,
                offset=self._item_page * _PAGE_SIZE,
            )
        except Exception as err:
            self._container.system_log.error(
                "doc_request_items.list failed", exc=err
            )
            self._item_table.setRowCount(0)
            self._on_item_selection_changed()
            return False
        self._render_items(items)
        return True

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_req_selection_changed(self) -> None:
        self._apply_request_selection()

    def _apply_request_selection(self) -> bool:
        has_sel = len(
            self._req_table.selectionModel().selectedRows(0)
        ) == 1
        self._edit_req_btn.setEnabled(has_sel)
        self._mark_requested_btn.setEnabled(has_sel)
        self._request_status_btn.setEnabled(has_sel)
        self._follow_up_btn.setEnabled(has_sel)
        self._delete_req_btn.setEnabled(has_sel)
        self._add_item_btn.setEnabled(has_sel)
        self._generate_btn.setEnabled(has_sel)
        if has_sel:
            self._update_request_detail(self._selected_request_id())
            succeeded = self._load_items_for_selected()
        else:
            self._item_table.setRowCount(0)
            self._show_no_request_detail()
            self._item_status_btn.setEnabled(False)
            self._edit_item_btn.setEnabled(False)
            self._delete_item_btn.setEnabled(False)
            self._bulk_delete_items_btn.setEnabled(False)
            succeeded = True
        if self._pending_mutation is not None:
            for button in self._mutation_buttons:
                button.setEnabled(False)
        return succeeded

    def _on_item_selection_changed(self) -> None:
        rows = self._selected_item_rows()
        single = len(rows) == 1
        multi = len(rows) >= 1
        self._item_status_btn.setEnabled(single)
        self._edit_item_btn.setEnabled(single)
        self._delete_item_btn.setEnabled(single)
        self._bulk_delete_items_btn.setEnabled(multi)
        if self._pending_mutation is not None:
            for button in self._mutation_buttons:
                button.setEnabled(False)

    def _selected_request_id(self) -> int | None:
        # In items_only mode, the request table is hidden — fall back to the
        # explicitly loaded request_id so add/edit/delete item handlers work.
        if self._view_mode == "items_only" and self._items_only_request_id is not None:
            return self._items_only_request_id
        rows = self._req_table.selectionModel().selectedRows(0)
        if len(rows) != 1:
            return None
        value = rows[0].data(Qt.ItemDataRole.UserRole)
        return value if type(value) is int else None

    def _selected_request_row(self) -> int | None:
        rows = self._req_table.selectionModel().selectedRows(0)
        return rows[0].row() if len(rows) == 1 else None

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
        rows = self._item_table.selectionModel().selectedRows(0)
        if len(rows) != 1:
            return None
        value = rows[0].data(Qt.ItemDataRole.UserRole)
        return value if type(value) is int else None

    def _selected_item_row(self) -> int | None:
        rows = self._item_table.selectionModel().selectedRows(0)
        return rows[0].row() if len(rows) == 1 else None

    def _selected_item_rows(self) -> list[int]:
        """Distinct row indices currently selected in the item table."""
        return sorted(
            index.row()
            for index in self._item_table.selectionModel().selectedRows(0)
        )

    def _selected_item_ids(self) -> list[int]:
        ids: list[int] = []
        for row in self._selected_item_rows():
            cell = self._item_table.item(row, 0)
            if cell is None:
                continue
            value = cell.data(Qt.ItemDataRole.UserRole)
            if type(value) is int:
                ids.append(value)
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

    def _snapshot(
        self, request_id: int
    ) -> tuple[DocumentRequestRow, tuple[DocumentRequestItemRow, ...]]:
        snapshot = self._container.doc_requests.read_request_snapshot(
            request_id
        )
        return snapshot.request, snapshot.items

    def _snapshot_for_action(
        self,
        request_id: int,
        *,
        operation: str,
        item_id: int | None = None,
    ) -> (
        tuple[DocumentRequestRow, tuple[DocumentRequestItemRow, ...]]
        | None
    ):
        """Read mutation evidence without misreporting infrastructure errors.

        A missing request is stale UI state and is safe to refresh.  Database
        and other unexpected failures must remain distinguishable: no
        mutation has run yet, so show a retryable read failure and preserve
        the technical cause in the system log.
        """
        try:
            return self._snapshot(request_id)
        except DocumentRequestValidationError as exc:
            QMessageBox.warning(
                self,
                "無法讀取索件資料",
                error_message(exc.code),
            )
            if exc.code == "doc_request.not_found":
                self._refresh_requests()
            return None
        except Exception as err:
            detail: dict[str, object] = {
                "operation": operation,
                "request_id": request_id,
            }
            if item_id is not None:
                detail["item_id"] = item_id
            try:
                log_connection = self._container.system_log.connection
                logger_has_caller_transaction = bool(
                    log_connection.in_transaction
                )
            except Exception:
                # Logger introspection is diagnostic-only.  If its transaction
                # ownership cannot be proven safe, skip the durable log.
                logger_has_caller_transaction = True
            if not logger_has_caller_transaction:
                try:
                    self._container.system_log.error(
                        "document request snapshot failed",
                        exc=err,
                        detail=detail,
                    )
                except Exception:
                    # A logger failure must not mask the original snapshot
                    # failure or turn it into a second user-visible crash.
                    pass
            QMessageBox.warning(
                self,
                "無法讀取索件資料",
                error_message("doc_request.snapshot.failed"),
            )
            return None

    @staticmethod
    def _request_after(
        result: DocumentItemsMutationResult, request_id: int
    ) -> DocumentRequestRow:
        matches = tuple(
            row for row in result.requests_after if row.id == request_id
        )
        if len(matches) != 1:
            raise RuntimeError("doc_request.readback.parent_missing")
        return matches[0]

    def _verify_mutation(
        self, evidence: DocumentMutationEvidence
    ) -> bool:
        request = self._container.doc_requests.get_request(
            evidence.request_id
        )
        if evidence.request_deleted:
            return request is None and all(
                self._container.doc_requests.get_item(item.id) is None
                for item in evidence.items_before
            )
        if request is None:
            return False
        if evidence.request_after is None or request != evidence.request_after:
            return False
        snapshot = self._container.doc_requests.read_request_snapshot(
            evidence.request_id
        )
        return snapshot.items == evidence.expected_items()

    @staticmethod
    def _valid_ack(value: object) -> bool:
        return (
            isinstance(value, DocumentMutationAck)
            and type(value.evidence_taken) is bool
            and type(value.readback_succeeded) is bool
            and not (
                value.readback_succeeded and not value.evidence_taken
            )
        )

    def _deliver_mutation(
        self, evidence: DocumentMutationEvidence
    ) -> bool:
        self._pending_mutation = evidence
        if self._mutation_handler is None:
            try:
                succeeded = self._verify_mutation(evidence)
                ack = DocumentMutationAck(True, succeeded)
            except Exception:
                ack = DocumentMutationAck(True, False)
        else:
            try:
                candidate = self._mutation_handler(evidence)
            except Exception:
                candidate = DocumentMutationAck(False, False)
            ack = (
                candidate
                if self._valid_ack(candidate)
                else DocumentMutationAck(False, False)
            )
        try:
            self.data_changed.emit()
        except Exception:
            pass
        if ack.evidence_taken and ack.readback_succeeded:
            if (
                self._mutation_handler is None
                and not self._refresh_requests()
            ):
                self._show_pending_recovery()
                return False
            self._pending_mutation = None
            self._clear_pending_recovery()
            return True
        self._show_pending_recovery()
        return False

    def retry_pending_mutation_verification(self) -> bool:
        evidence = self._pending_mutation
        if evidence is None:
            return True
        if self._mutation_handler is None:
            try:
                succeeded = self._verify_mutation(evidence)
            except Exception:
                succeeded = False
            ack = DocumentMutationAck(True, succeeded)
        else:
            try:
                candidate = self._mutation_handler(evidence)
            except Exception:
                candidate = DocumentMutationAck(False, False)
            ack = (
                candidate
                if self._valid_ack(candidate)
                else DocumentMutationAck(False, False)
            )
        if ack.evidence_taken and ack.readback_succeeded:
            if (
                self._mutation_handler is None
                and not self._refresh_requests()
            ):
                return False
            self._pending_mutation = None
            self._clear_pending_recovery()
            return True
        return False

    def _on_new_request(self) -> None:
        if self._mutation_is_pending():
            return
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
            request, items = self._container.doc_requests.create_request(
                payload
            )
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
            self._engagement_id = eng_id
            self._populate_engagement_combo()
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.create",
                eng_id,
                request.id,
                None,
                request,
                (),
                tuple(items),
            )
        )

    def _on_edit_request(self) -> None:
        if self._mutation_is_pending():
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        snapshot = self._snapshot_for_action(
            req_id, operation="request.update"
        )
        if snapshot is None:
            return
        existing, items_before = snapshot
        new_name, ok = QInputDialog.getText(
            self,
            "編輯批次名稱",
            "批次名稱",
            text=existing.request_name,
        )
        if not ok:
            return
        try:
            updated = self._container.doc_requests.update_request(
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.update",
                existing.engagement_id,
                req_id,
                existing,
                updated,
                items_before,
            )
        )

    def _on_mark_requested(self) -> None:
        if self._mutation_is_pending():
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        snapshot = self._snapshot_for_action(
            req_id, operation="request.mark_requested"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            updated = self._container.doc_requests.mark_requested(req_id)
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.mark_requested",
                before.engagement_id,
                req_id,
                before,
                updated,
                items_before,
            )
        )

    def _on_set_request_status(self) -> None:
        if self._mutation_is_pending():
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_REQUEST_STATUSES}
        choices = sorted(label_to_value)
        req_row = self._selected_request_row()
        if req_row is None:
            return
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
        snapshot = self._snapshot_for_action(
            req_id, operation="request.status"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            updated = self._container.doc_requests.set_request_status(
                req_id, status
            )
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.status",
                before.engagement_id,
                req_id,
                before,
                updated,
                items_before,
            )
        )

    def _on_follow_up(self) -> None:
        if self._mutation_is_pending():
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        snapshot = self._snapshot_for_action(
            req_id, operation="request.follow_up"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            updated = self._container.doc_requests.add_follow_up(req_id)
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.follow_up",
                before.engagement_id,
                req_id,
                before,
                updated,
                items_before,
            )
        )

    def _on_delete_request(self) -> None:
        if self._mutation_is_pending():
            return
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
        snapshot = self._snapshot_for_action(
            req_id, operation="request.delete"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "request.delete",
                before.engagement_id,
                req_id,
                before,
                None,
                items_before,
                request_deleted=True,
            )
        )

    def _on_add_item(self) -> None:
        if self._mutation_is_pending():
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        snapshot = self._snapshot_for_action(
            req_id, operation="item.add_bulk"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        dlg = AddDocumentItemDialog(self._container.doc_requests, req_id, parent=self)
        if dlg.exec() == AddDocumentItemDialog.DialogCode.Accepted:
            result = dlg.mutation_result
            if not isinstance(result, DocumentItemsMutationResult):
                self.setEnabled(False)
                return
            self._deliver_mutation(
                DocumentMutationEvidence(
                    "item.add_bulk",
                    before.engagement_id,
                    req_id,
                    before,
                    self._request_after(result, req_id),
                    items_before,
                    result.affected_items,
                )
            )

    def _on_edit_item(self) -> None:
        if self._mutation_is_pending():
            return
        item_id = self._selected_item_id()
        if item_id is None:
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        snapshot = self._snapshot_for_action(
            req_id,
            operation="item.update",
            item_id=item_id,
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        item_row = self._selected_item_row()
        if item_row is None:
            return
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
            result = self._container.doc_requests.update_item(
                item_id,
                new_name.strip(),
                with_request=True,
            )
            if not isinstance(result, DocumentItemsMutationResult):
                raise RuntimeError("doc_request_item.result.invalid")
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "item.update",
                before.engagement_id,
                req_id,
                before,
                self._request_after(result, req_id),
                items_before,
                result.affected_items,
            )
        )

    def _on_bulk_delete_items(self) -> None:
        if self._mutation_is_pending():
            return
        ids = self._selected_item_ids()
        if not ids:
            return
        req_id = self._selected_request_id()
        if req_id is None:
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
        snapshot = self._snapshot_for_action(
            req_id, operation="item.delete_bulk"
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            result = self._container.doc_requests.delete_items_bulk(
                ids, with_request=True
            )
            if not isinstance(result, DocumentItemsMutationResult):
                raise RuntimeError("doc_request_item.result.invalid")
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
        if self._deliver_mutation(
            DocumentMutationEvidence(
                "item.delete_bulk",
                before.engagement_id,
                req_id,
                before,
                self._request_after(result, req_id),
                items_before,
                deleted_items=result.deleted_items,
            )
        ):
            QMessageBox.information(
                self,
                "批量刪除完成",
                f"已刪除 {len(result.deleted_items)} 筆文件項目。",
            )

    def _on_delete_item(self) -> None:
        if self._mutation_is_pending():
            return
        item_id = self._selected_item_id()
        if item_id is None:
            return
        req_id = self._selected_request_id()
        if req_id is None:
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
        snapshot = self._snapshot_for_action(
            req_id,
            operation="item.delete",
            item_id=item_id,
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            result = self._container.doc_requests.delete_item(
                item_id, with_request=True
            )
            if not isinstance(result, DocumentItemsMutationResult):
                raise RuntimeError("doc_request_item.result.invalid")
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "item.delete",
                before.engagement_id,
                req_id,
                before,
                self._request_after(result, req_id),
                items_before,
                deleted_items=result.deleted_items,
            )
        )

    def _on_set_item_status(self) -> None:
        if self._mutation_is_pending():
            return
        item_id = self._selected_item_id()
        if item_id is None:
            return
        req_id = self._selected_request_id()
        if req_id is None:
            return
        label_to_value = {STATUS_LABELS.get(s, s): s for s in VALID_ITEM_STATUSES}
        choices = sorted(label_to_value)
        item_row = self._selected_item_row()
        if item_row is None:
            return
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
        snapshot = self._snapshot_for_action(
            req_id,
            operation="item.status",
            item_id=item_id,
        )
        if snapshot is None:
            return
        before, items_before = snapshot
        try:
            result = self._container.doc_requests.set_item_status(
                item_id,
                item_status=target,
                with_request=True,
            )
            if not isinstance(result, DocumentItemsMutationResult):
                raise RuntimeError("doc_request_item.result.invalid")
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
        self._deliver_mutation(
            DocumentMutationEvidence(
                "item.status",
                before.engagement_id,
                req_id,
                before,
                self._request_after(result, req_id),
                items_before,
                result.affected_items,
            )
        )

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
