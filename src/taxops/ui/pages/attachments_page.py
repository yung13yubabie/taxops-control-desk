"""Attachments page: upload and manage evidence files per engagement."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QAction, QDesktopServices, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QGridLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QLineEdit,
    QTabBar,
    QToolButton,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:  # PySide6 ships QtPdf on the supported Windows build.
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except Exception:  # pragma: no cover - fallback for minimal Qt installs.
    QPdfDocument = None  # type: ignore[assignment]
    QPdfView = None  # type: ignore[assignment]

from ...i18n import error_message
from ...security.image_guard import ImageGuardError, validate_image_file
from ...services.attachments import AttachmentValidationError, UploadAttachmentInput
from ...services.container import ServiceContainer
from ..navigation import NavigationTarget
from ..action_registry import PAGE_ENGAGEMENTS, PAGE_CLIENTS
from .. import tokens
from ..widgets.buttons import make_button, set_button_role
from ..widgets.page_shell import PageHeader, ActionBar, build_page_layout
from ..widgets.inspector import Inspector
from ..widgets.empty_state import EmptyState
from ..dialogs.edit_client_dialog import EditClientDialog
from ..widgets.today_work_panel import TodayWorkPanel, all_engagements

_log = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})
_TEXT_EXTS = frozenset({".txt", ".csv", ".log", ".xml", ".json", ".md"})

_COLUMNS = ("id", "original_filename", "extension", "file_size", "status", "uploaded_at")
_HEADERS = {
    "id": "編號",
    "original_filename": "原始檔名",
    "extension": "副檔名",
    "file_size": "大小",
    "status": "狀態",
    "uploaded_at": "加入時間",
}
_STATUS_LABELS = {
    "uploaded": "待核對",
    "classified": "已分類",
    "needs_review": "待檢查",
    "accepted": "已驗收",
    "rejected": "已退回",
    "archived": "已封存",
    "on_hold": "法務保留",
}
_FILE_FILTER = (
    "允許的檔案 (*.pdf *.jpg *.jpeg *.png *.xlsx *.xls *.docx *.doc *.txt *.csv)"
    ";;所有檔案 (*)"
)
_ALL = -1

_PREVIEW_NONE = 0
_PREVIEW_IMAGE = 1
_PREVIEW_TEXT = 2
_PREVIEW_META = 3
_PREVIEW_PDF = 4


def _plain_label(text: str) -> QLabel:
    lbl = QLabel(str(text))
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    return lbl


class _AttachmentInfoDialog(QDialog):
    def __init__(self, att, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("附件資訊")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        form.setSpacing(10)
        form.addRow("編號：", _plain_label(str(att.id)))
        form.addRow("原始檔名：", _plain_label(att.original_filename))
        form.addRow("檔案位置：", _plain_label(att.stored_filename))
        form.addRow("副檔名：", _plain_label(att.extension))
        size_kb = f"{att.file_size / 1024:.1f} KB ({att.file_size:,} bytes)"
        form.addRow("大小：", _plain_label(size_kb))
        form.addRow("SHA-256：", _plain_label(att.file_hash_sha256))
        form.addRow("MIME 類型：", _plain_label(att.mime_type))
        form.addRow("狀態：", _plain_label(_STATUS_LABELS.get(att.status, att.status)))
        form.addRow("上傳者：", _plain_label(att.uploaded_by))
        form.addRow("上傳時間：", _plain_label(att.uploaded_at))
        if att.accepted_by:
            form.addRow("驗收者：", _plain_label(att.accepted_by))
        if att.accepted_at:
            form.addRow("驗收時間：", _plain_label(att.accepted_at))
        if att.notes:
            form.addRow("備註：", _plain_label(att.notes))
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(self.accept)
        form.addRow("", close_btn)


class AttachmentsPage(QWidget):
    navigate_requested = Signal(object)

    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._attachments: list = []
        self._engagement_labels: dict[int, str] = {}
        self._owner_labels: dict[int, str] = {}
        self._load_error = False
        self._context_error = False
        self._review_mode = False
        self._page = 0
        self._page_size = 50
        self._today_dialog: QDialog | None = None
        self.setObjectName("DocumentWorkbench")
        self._header = PageHeader("收件核對")
        outer = build_page_layout(self._header, dense=True)
        self.setLayout(outer)
        self._today_btn = make_button("提醒載入中", role="secondary")
        self._today_btn.setAccessibleName("待辦與索件提醒")
        self._today_btn.clicked.connect(self._show_today_work)
        self._header.add_action(self._today_btn)
        self._upload_btn = make_button("新增附件", role="primary", icon_role="new")
        self._upload_btn.clicked.connect(self._on_upload)
        self._header.add_action(self._upload_btn)

        self._toolbar_widget = ActionBar()
        self._toolbar_layout = self._toolbar_widget.layout()
        filters = QWidget()
        filter_row = QHBoxLayout(filters)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(tokens.SPACING_SM)
        self._owner_kind = QComboBox()
        self._owner_kind.addItem("全部來源", "all")
        self._owner_kind.addItem("案件附件", "engagement")
        self._owner_kind.addItem("租約附件", "lease")
        self._owner_kind.setAccessibleName("附件來源範圍")
        filter_row.addWidget(self._owner_kind)
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumContentsLength(12)
        self._eng_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._eng_combo.setAccessibleName("案件範圍，租約附件不屬於案件")
        filter_row.addWidget(self._eng_combo, 1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜尋檔名、客戶、案件或租約")
        self._search.setAccessibleName("搜尋收件列表")
        self._search.setClearButtonEnabled(True)
        self._search.setMaxLength(150)
        self._search.setMinimumWidth(245)
        filter_row.addWidget(self._search, 2)
        self._toolbar_widget.add_leading_widget(filters, stretch=1)
        self._refresh_btn = make_button("重新整理", role="quiet", icon_role="refresh")
        self._refresh_btn.clicked.connect(self.refresh_context)
        self._toolbar_widget.add_tool_action(self._refresh_btn)
        self._preview_btn = make_button("查看附件", role="secondary")
        self._preview_btn.clicked.connect(self._toggle_review)
        self._toolbar_widget.add_tool_action(self._preview_btn, role="secondary")
        outer.addWidget(self._toolbar_widget)

        self._status_tabs = QTabBar()
        self._status_tabs.setObjectName("ReceiptStages")
        self._status_tabs.setExpanding(False)
        self._status_tabs.setAccessibleName("附件狀態篩選")
        for label, key in (("待核對", "pending"), ("已驗收", "accepted"), ("已退回", "rejected"), ("全部有效附件", "all")):
            index = self._status_tabs.addTab(label)
            self._status_tabs.setTabData(index, key)
        outer.addWidget(self._status_tabs)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._today_panel = TodayWorkPanel(container)
        self._today_panel.setMinimumWidth(190)
        self._today_panel.setMaximumWidth(240)
        self._today_panel.navigate_requested.connect(self.navigate_requested)
        self._today_panel.summary_changed.connect(self._today_btn.setText)
        self._splitter.addWidget(self._today_panel)

        self._table_panel = QWidget()
        table_layout = QVBoxLayout(self._table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(tokens.SPACING_SM)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([_HEADERS[c] for c in _COLUMNS])
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(4, 100)
        self._table.setColumnWidth(5, 110)
        for column in (0, 2, 3):
            self._table.setColumnHidden(column, True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.setAccessibleName("收件列表，選取附件以查看狀態、期限及下一步")
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemActivated.connect(lambda _item: self._show_review())
        table_layout.addWidget(self._table, 1)
        self._empty_state = EmptyState("尚無附件", detail="選擇案件後新增；租約附件可從客戶管理加入。", action_text="開啟客戶管理", action_icon="nav-clients")
        self._empty_label = self._empty_state.title_label
        self._empty_state.action_button.clicked.connect(self._open_clients)
        table_layout.addWidget(self._empty_state, 1)
        self._error_label = QLabel("無法載入收件。請重新整理，或重新選擇有效案件。")
        self._error_label.setObjectName("ReceiptError")
        self._error_label.setWordWrap(True)
        table_layout.addWidget(self._error_label, 1)
        self._error_label.hide()
        pagination = QHBoxLayout()
        self._result_count = QLabel()
        self._result_count.setObjectName("PageSubtitle")
        pagination.addWidget(self._result_count, 1)
        self._previous_btn = make_button("上一頁", role="quiet")
        self._next_btn = make_button("下一頁", role="quiet")
        self._previous_btn.clicked.connect(lambda: self._change_page(-1))
        self._next_btn.clicked.connect(lambda: self._change_page(1))
        pagination.addWidget(self._previous_btn)
        pagination.addWidget(self._next_btn)
        table_layout.addLayout(pagination)
        self._splitter.addWidget(self._table_panel)

        self._review_panel = QWidget()
        review_layout = QVBoxLayout(self._review_panel)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(tokens.SPACING_SM)
        self._inspector = Inspector(placeholder="選取附件，查看所屬資料與核對狀態。")
        self._inspector.setMinimumWidth(285)
        self._inspector.layout().setContentsMargins(tokens.SPACING_MD, tokens.SPACING_MD, tokens.SPACING_MD, tokens.SPACING_MD)
        self._inspector.layout().setSpacing(tokens.SPACING_SM)
        self._inspector.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._inspector.subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        self._preview_body = self._build_preview_panel()
        review_layout.addWidget(self._inspector, 1)
        self._action_box = QWidget()
        self._review_actions = QGridLayout(self._action_box)
        self._review_actions.setContentsMargins(0, 0, 0, 0)
        self._review_actions.setSpacing(tokens.SPACING_SM)
        self._manual_btn = make_button("開啟索件核對", role="secondary")
        self._manual_btn.clicked.connect(self._on_manual_review)
        self._accept_btn = make_button("標記已驗收", role="secondary")
        self._accept_btn.clicked.connect(self._on_accept)
        self._reject_btn = make_button("標記退回", role="secondary")
        self._reject_btn.clicked.connect(self._on_reject)
        self._more_btn = QToolButton()
        self._more_btn.setText("更多")
        self._more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_btn.setAccessibleName("更多附件操作，資訊、開啟、位置與刪除")
        self._file_menu = QMenu(self._more_btn)
        # Preserve actual buttons for existing callers; menu and code share a path.
        self._file_actions = []
        for name, label, handler, role in (
            ("_info_btn", "檔案資訊", self._on_show_info, "quiet"),
            ("_open_btn", "用系統程式開啟", self._on_open_system, "quiet"),
            ("_location_btn", "檔案位置", self._on_open_location, "quiet"),
            ("_delete_btn", "刪除附件", self._on_delete, "danger"),
        ):
            button = make_button(label, role=role, parent=self)
            button.hide()
            button.clicked.connect(handler)
            setattr(self, name, button)
            action = self._file_menu.addAction(label)
            action.triggered.connect(button.click)
            self._file_actions.append(action)
        self._location_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._location_btn.customContextMenuRequested.connect(self._show_location_menu)
        self._copy_url_action = self._file_menu.addAction("複製 file:// URL", self._on_copy_selected_url)
        self._more_btn.setMenu(self._file_menu)
        self._review_actions.addWidget(self._manual_btn, 0, 0, 1, 3)
        self._review_actions.addWidget(self._accept_btn, 1, 0)
        self._review_actions.addWidget(self._reject_btn, 1, 1)
        self._review_actions.addWidget(self._more_btn, 1, 2)
        review_layout.addWidget(self._action_box)
        self._splitter.addWidget(self._review_panel)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setStretchFactor(2, 2)
        self._splitter.setSizes([210, 620, 350])
        outer.addWidget(self._splitter, 1)
        self._feedback = QLabel()
        self._feedback.setTextFormat(Qt.TextFormat.PlainText)
        self._feedback.setWordWrap(True)
        self._feedback.setObjectName("ReceiptFeedback")
        self._feedback.hide()
        outer.addWidget(self._feedback)
        self._eng_combo.currentIndexChanged.connect(self._scope_changed)
        self._owner_kind.currentIndexChanged.connect(self._owner_kind_changed)
        self._search.textChanged.connect(self._filter_changed)
        self._status_tabs.currentChanged.connect(self._filter_changed)
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._search_shortcut.activated.connect(self._search.setFocus)
        QWidget.setTabOrder(self._today_btn, self._upload_btn)
        QWidget.setTabOrder(self._upload_btn, self._owner_kind)
        QWidget.setTabOrder(self._owner_kind, self._eng_combo)
        QWidget.setTabOrder(self._eng_combo, self._search)
        QWidget.setTabOrder(self._search, self._refresh_btn)
        QWidget.setTabOrder(self._refresh_btn, self._status_tabs)
        QWidget.setTabOrder(self._status_tabs, self._table)
        self.refresh_context()

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._preview_title = self._inspector.title_label
        self._association_label = QLabel()
        self._association_label.setTextFormat(Qt.TextFormat.PlainText)
        self._association_label.setWordWrap(True)
        self._association_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self._association_label)
        self._facts_label = QLabel()
        self._facts_label.setTextFormat(Qt.TextFormat.PlainText)
        self._facts_label.setWordWrap(True)
        self._facts_label.setObjectName("ReceiptFacts")
        layout.addWidget(self._facts_label)
        self._context_warning = QLabel()
        self._context_warning.setTextFormat(Qt.TextFormat.PlainText)
        self._context_warning.setWordWrap(True)
        self._context_warning.setObjectName("ReceiptError")
        self._context_warning.hide()
        layout.addWidget(self._context_warning)
        self._help_btn = make_button("核對說明", role="link")
        self._help_btn.setCheckable(True)
        self._help_text = QLabel("附件只連結案件或索件批次，尚未連結到個別索件項目。\n驗收附件不會自動完成索件；請逐項人工確認。租約附件只歸屬租約。")
        self._help_text.setWordWrap(True)
        self._help_text.hide()
        self._help_btn.toggled.connect(self._toggle_help)

        self._preview_stack = QStackedWidget()

        no_sel = QLabel("（選擇附件以預覽）")
        no_sel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_stack.addWidget(no_sel)  # index 0

        self._preview_image = QLabel()
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setMinimumSize(80, 80)
        self._preview_stack.addWidget(self._preview_image)  # index 1

        self._preview_text = QPlainTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_stack.addWidget(self._preview_text)  # index 2

        self._preview_meta = QLabel()
        self._preview_meta.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._preview_meta.setTextFormat(Qt.TextFormat.PlainText)
        self._preview_meta.setWordWrap(True)
        self._preview_meta.setContentsMargins(4, 4, 4, 4)
        self._preview_stack.addWidget(self._preview_meta)  # index 3

        if QPdfDocument is not None and QPdfView is not None:
            self._preview_pdf_doc = QPdfDocument(self)
            self._preview_pdf = QPdfView()
            self._preview_pdf.setDocument(self._preview_pdf_doc)
            self._preview_pdf.setZoomMode(QPdfView.ZoomMode.FitInView)
            self._preview_stack.addWidget(self._preview_pdf)  # index 4
        else:
            self._preview_pdf_doc = None
            self._preview_pdf = None

        self._preview_stack.setCurrentIndex(_PREVIEW_NONE)
        self._preview_stack.setMinimumHeight(100)
        layout.addWidget(self._preview_stack, 1)
        layout.addWidget(self._help_btn)
        layout.addWidget(self._help_text)
        return panel

    def open_context(self, engagement_id: int, attachment_id: int | None = None) -> None:
        if self._container.engagements.get_engagement(engagement_id) is None:
            raise ValueError("案件已刪除或所屬客戶已停用。")
        rows = self._container.attachments.list_by_engagement(engagement_id)
        if attachment_id is not None and not any(row.id == attachment_id for row in rows):
            raise ValueError("附件已刪除或不屬於這個案件。")
        self._owner_kind.setCurrentIndex(0)
        self._search.clear()
        self._status_tabs.setCurrentIndex(3)
        self._load_engagements()
        index = self._eng_combo.findData(engagement_id)
        if index < 0:
            raise ValueError("找不到這個案件。")
        self._eng_combo.setCurrentIndex(index)
        self._load_attachments()
        if attachment_id is not None:
            self._select_attachment_id(attachment_id)

    def clear_filter(self) -> None:
        self._owner_kind.setCurrentIndex(0)
        self._page = 0
        self._search.clear()
        self._status_tabs.setCurrentIndex(0)
        self._eng_combo.setCurrentIndex(0)
        self.refresh_context()

    def refresh_context(self) -> None:
        self._feedback.hide()
        self._load_engagements()
        self._today_panel.refresh()

    def _load_engagements(self) -> None:
        selected_id = self._eng_combo.currentData()
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("所有案件／租約", _ALL)
        self._engagement_labels = {}
        self._context_error = False
        try:
            clients = {}
            for eng in all_engagements(self._container):
                if eng.client_id not in clients:
                    client = self._container.clients.get_client(eng.client_id)
                    clients[eng.client_id] = f"{client.client_code} · {client.client_name}" if client is not None else "客戶資料不可用"
                label = f"{clients[eng.client_id]} / {eng.engagement_name}"
                self._engagement_labels[eng.id] = label
                self._eng_combo.addItem(label, eng.id)
                self._eng_combo.setItemData(self._eng_combo.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        except Exception as exc:
            self._context_error = True
            self._container.system_log.warn("attachments: failed to load engagements", detail={"exc": type(exc).__name__, "msg": str(exc)})
        index = self._eng_combo.findData(selected_id)
        if selected_id not in (None, _ALL) and index < 0:
            # A removed scope must not silently broaden to another customer's files.
            self._eng_combo.addItem("原案件已失效，請重新選擇範圍", selected_id)
            index = self._eng_combo.count() - 1
        self._eng_combo.setCurrentIndex(max(index, 0))
        self._eng_combo.blockSignals(False)
        self._load_attachments()

    def _open_clients(self) -> None:
        self.navigate_requested.emit(NavigationTarget(PAGE_CLIENTS))

    def _scope_changed(self) -> None:
        self._page = 0
        self._load_attachments()

    def _owner_kind_changed(self) -> None:
        lease_only = self._owner_kind.currentData() == "lease"
        if lease_only:
            self._eng_combo.blockSignals(True)
            self._eng_combo.setCurrentIndex(0)
            self._eng_combo.blockSignals(False)
        self._eng_combo.setEnabled(not lease_only)
        self._page = 0
        self._load_attachments()

    def _filter_changed(self, *_args) -> None:
        self._page = 0
        self._render_table()

    def _change_page(self, delta: int) -> None:
        self._page = max(0, self._page + delta)
        self._render_table()

    def _load_attachments(self) -> None:
        eng_id = self._eng_combo.currentData()
        self._attachments = []
        self._owner_labels = {}
        self._load_error = self._context_error or (eng_id != _ALL and eng_id not in self._engagement_labels)
        try:
            if not self._load_error:
                # Existing API returns the complete active ownership set. The UI
                # presents bounded pages and searches this complete local result.
                rows = self._container.attachments.list_all() if eng_id == _ALL else self._container.attachments.list_by_engagement(eng_id)
                clients = {}
                leases = {}
                for att in rows:
                    if att.engagement_id is not None:
                        self._owner_labels[att.id] = self._engagement_labels.get(att.engagement_id, "案件資料已失效")
                    elif att.lease_id is not None and att.client_id is not None:
                        if att.client_id not in clients:
                            client = self._container.clients.get_client(att.client_id)
                            clients[att.client_id] = f"{client.client_code} · {client.client_name}" if client is not None else "客戶資料已失效"
                        if att.lease_id not in leases:
                            lease = self._container.client_leases.get_lease(att.lease_id)
                            leases[att.lease_id] = lease.lease_name if lease is not None else "租約已失效"
                        self._owner_labels[att.id] = f"{clients[att.client_id]} / 租約：{leases[att.lease_id]}"
                    else:
                        self._owner_labels[att.id] = "附件歸屬不完整"
                kind = self._owner_kind.currentData()
                self._attachments = [att for att in rows if kind == "all" or (kind == "lease" and att.lease_id is not None) or (kind == "engagement" and att.engagement_id is not None)]
        except Exception as exc:
            self._load_error = True
            self._attachments = []
            self._container.system_log.warn("attachments: failed to load attachments", detail={"exc": type(exc).__name__, "msg": str(exc)})
        self._render_table()

    def _filtered_attachments(self) -> list:
        stage = self._status_tabs.tabData(self._status_tabs.currentIndex())
        query = self._search.text().strip().casefold()
        return [att for att in self._attachments if self._in_stage(att, stage) and query in f"{att.original_filename} {self._owner_labels.get(att.id, '')}".casefold()]

    @staticmethod
    def _in_stage(att, key) -> bool:
        return key == "all" or (att.status in {"uploaded", "classified", "needs_review"} if key == "pending" else att.status == key)

    def _select_attachment_id(self, attachment_id: int) -> None:
        rows = self._filtered_attachments()
        position = next((index for index, att in enumerate(rows) if att.id == attachment_id), None)
        if position is None:
            raise ValueError("附件已失效或不在目前範圍。")
        self._page = position // self._page_size
        self._render_table()
        self._table.selectRow(position % self._page_size)

    def _render_table(self, *_args) -> None:
        old_item = self._table.item(self._table.currentRow(), 0)
        old_id = old_item.text() if old_item else None
        self._status_tabs.blockSignals(True)
        for index, label in enumerate(("待核對", "已驗收", "已退回", "全部有效附件")):
            key = self._status_tabs.tabData(index)
            count = sum(self._in_stage(att, key) for att in self._attachments)
            self._status_tabs.setTabText(index, f"{label} {count}")
        self._status_tabs.blockSignals(False)
        filtered = self._filtered_attachments()
        pages = max(1, (len(filtered) + self._page_size - 1) // self._page_size)
        self._page = min(self._page, pages - 1)
        visible = filtered[self._page * self._page_size:(self._page + 1) * self._page_size]
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for att in visible:
            row = self._table.rowCount()
            self._table.insertRow(row)
            context = self._owner_labels.get(att.id, "附件歸屬不完整")
            vals = {
                "id": str(att.id), "original_filename": f"{att.original_filename}\n{context}",
                "extension": att.extension, "file_size": f"{att.file_size / 1024:.1f} KB",
                "status": _STATUS_LABELS.get(att.status, att.status), "uploaded_at": att.uploaded_at[:10],
            }
            for col, key in enumerate(_COLUMNS):
                item = QTableWidgetItem(vals[key])
                item.setToolTip(vals[key])
                self._table.setItem(row, col, item)
            self._table.setRowHeight(row, tokens.RECEIPT_ROW_HEIGHT)
            if str(att.id) == old_id:
                self._table.selectRow(row)
        self._table.blockSignals(False)
        count = self._table.rowCount()
        self._table.setVisible(bool(count) and not self._load_error)
        self._empty_state.setVisible(not count and not self._load_error)
        self._empty_label.setText("沒有符合條件的附件" if self._attachments else "尚無附件")
        self._empty_state.detail_label.setText("可清除搜尋或切換狀態。" if self._attachments else "選擇案件後新增；租約附件可從客戶管理加入。")
        self._empty_state.action_button.setVisible(not self._attachments)
        self._error_label.setVisible(self._load_error)
        self._result_count.setText("收件載入失敗" if self._load_error else f"{len(filtered)} 份附件 · 第 {self._page + 1} / {pages} 頁")
        self._previous_btn.setEnabled(self._page > 0 and not self._load_error)
        self._next_btn.setEnabled(self._page + 1 < pages and not self._load_error)
        self._on_selection_changed()

    def resizeEvent(self, event) -> None:
        if event is not None:
            super().resizeEvent(event)
        if not hasattr(self, "_review_panel"):
            return
        compact = self.width() < 1000
        self._today_panel.setVisible(self.width() >= 1180)
        self._preview_btn.setVisible(compact)
        self._association_label.setVisible(not compact)
        self._status_tabs.setVisible(not (compact and self._review_mode))
        controls = (self._manual_btn, self._accept_btn, self._reject_btn, self._more_btn)
        for control in controls:
            self._review_actions.removeWidget(control)
        if compact:
            for column, control in enumerate(controls):
                self._review_actions.addWidget(control, 0, column)
        else:
            self._review_actions.addWidget(self._manual_btn, 0, 0, 1, 3)
            self._review_actions.addWidget(self._accept_btn, 1, 0)
            self._review_actions.addWidget(self._reject_btn, 1, 1)
            self._review_actions.addWidget(self._more_btn, 1, 2)
        self._table_panel.setVisible(not compact or not self._review_mode)
        self._review_panel.setVisible(not compact or self._review_mode)
        self._preview_btn.setText("返回附件列表" if compact and self._review_mode else "附件預覽")

    def _toggle_review(self) -> None:
        self._review_mode = not self._review_mode
        self.resizeEvent(None)
        if not self._review_mode:
            self._table.setFocus()

    def _show_review(self) -> None:
        if self._selected_attachment() is None:
            return
        self._review_mode = True
        self.resizeEvent(None)
        self._manual_btn.setFocus()

    def _show_today_work(self) -> None:
        if self._today_panel.isVisible():
            self._today_panel._list.setFocus()
            return
        if self._today_dialog is not None:
            self._today_dialog.raise_()
            self._today_dialog.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("待辦與索件提醒")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.resize(500, 460)
        layout = QVBoxLayout(dialog)
        panel = TodayWorkPanel(self._container)
        layout.addWidget(panel)
        close = QPushButton("返回收件核對")
        close.clicked.connect(dialog.reject)
        layout.addWidget(close)
        def navigate(target):
            dialog.accept()
            QTimer.singleShot(0, lambda: self.navigate_requested.emit(target))
        panel.navigate_requested.connect(navigate)
        dialog.finished.connect(lambda _result: setattr(self, "_today_dialog", None))
        self._today_dialog = dialog
        panel.refresh()
        dialog.open()

    def _toggle_help(self, checked: bool) -> None:
        self._help_text.setVisible(checked)

    def _on_manual_review(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        try:
            current = self._container.attachments.get(att.id)
            if current is None or current.status == "archived" or current.engagement_id != att.engagement_id or current.lease_id != att.lease_id or current.client_id != att.client_id or current.request_id != att.request_id:
                raise ValueError("附件已失效或歸屬已變更，請重新整理收件。")
            if att.engagement_id is None:
                self._open_lease_owner(att)
                return
            eng = self._container.engagements.get_engagement(att.engagement_id)
            if eng is None:
                raise ValueError("案件已刪除或所屬客戶已停用。")
            if att.request_id is not None:
                request = self._container.doc_requests.get_request(att.request_id)
                if request is None or request.engagement_id != eng.id:
                    raise ValueError("原索件批次已失效，未自動改連結。")
            self.navigate_requested.emit(NavigationTarget(PAGE_ENGAGEMENTS, engagement_id=eng.id, request_id=att.request_id))
        except ValueError as exc:
            QMessageBox.warning(self, "無法開啟核對", str(exc))
        except Exception as exc:
            self._container.system_log.warn("attachment review navigation failed", detail={"exc": type(exc).__name__})
            QMessageBox.warning(self, "無法開啟核對", "讀取核對資料失敗，請重新整理後再試。")

    def _open_lease_owner(self, att) -> None:
        lease = self._container.client_leases.get_lease(att.lease_id)
        client = self._container.clients.get_client(att.client_id)
        if lease is None or client is None or lease.client_id != client.id:
            raise ValueError("租約或客戶已失效，未開啟其他客戶資料。")
        dialog = EditClientDialog(self._container, client, parent=self)
        dialog.setWindowTitle(f"租約管理：{client.client_name} / {lease.lease_name}")
        for row, entry in enumerate(dialog.leases_editor._entries):
            if entry.lease_id == lease.id:
                dialog.leases_editor.table.selectRow(row)
                break
        QTimer.singleShot(0, lambda: dialog.scroll_area.ensureWidgetVisible(dialog.leases_editor))
        dialog.exec()
        self.refresh_context()

    def _on_copy_selected_url(self) -> None:
        att = self._selected_attachment()
        if att is not None:
            self._copy_file_url(att)

    def _selected_attachment(self):
        rows = self._table.selectedItems()
        if not rows:
            return None
        row = self._table.row(rows[0])
        id_item = self._table.item(row, 0)  # column 0 為 "id"
        if id_item is None:
            return None
        try:
            att_id = int(id_item.text())
        except ValueError:
            return None
        return next((a for a in self._attachments if a.id == att_id), None)

    def _resolve_att_file_path(self, att, *, notify: bool) -> Path | None:
        try:
            return self._container.attachments.resolve_file_path(att.id)
        except AttachmentValidationError as err:
            message = error_message(err.code)
        except Exception as exc:
            self._container.system_log.warn(
                "attachments: failed to resolve stored file",
                detail={
                    "attachment_id": att.id,
                    "exc": type(exc).__name__,
                    "msg": str(exc),
                },
            )
            message = error_message("attachment.not_found")
        if notify:
            QMessageBox.warning(self, "無法存取附件", message)
        return None

    def _att_file_url(self, att) -> str | None:
        path = self._resolve_att_file_path(att, notify=True)
        if path is None:
            return None
        return QUrl.fromLocalFile(str(path)).toString()

    def _on_selection_changed(self) -> None:
        att = self._selected_attachment()
        has = att is not None
        self._action_box.setVisible(has)
        set_button_role(self._upload_btn, "secondary" if has else "primary")
        set_button_role(self._manual_btn, "primary" if has else "secondary")
        self._accept_btn.setEnabled(has and att.status != "accepted")
        self._reject_btn.setEnabled(has and att.status != "rejected")
        for control in (self._manual_btn, self._delete_btn, self._info_btn, self._open_btn, self._location_btn, self._copy_url_action, self._more_btn):
            control.setEnabled(has)
        for action in self._file_actions:
            action.setEnabled(has)
        self._preview_btn.setEnabled(has or self._review_mode)
        if not has:
            self._inspector.clear()
            self._update_preview(None)
            return
        self._inspector.begin_update()
        self._inspector.set_title(att.original_filename, subtitle=self._owner_labels.get(att.id, "附件歸屬不完整"))
        self._inspector.add_widget(self._preview_body)
        self._help_btn.setChecked(False)
        self._context_warning.hide()
        status = _STATUS_LABELS.get(att.status, att.status)
        self._manual_btn.setText("開啟索件核對" if att.engagement_id is not None else "管理此客戶租約")
        try:
            if att.engagement_id is None:
                lease = self._container.client_leases.get_lease(att.lease_id) if att.lease_id is not None else None
                if lease is None or lease.client_id != att.client_id:
                    raise ValueError("租約已失效或附件歸屬不一致，請確認資料。")
                self._association_label.setText("租約附件")
                lease_state = {"active": "有效", "expired": "已到期", "terminated": "已終止"}.get(lease.status, lease.status)
                self._facts_label.setText(f"附件：{status} · 租約：{lease_state}\n租約迄日：{lease.end_date or '未設定'}\n下一步：查看租約與附件，不涉及索件清單。")
            else:
                request = None
                if att.request_id is not None:
                    request = self._container.doc_requests.get_request(att.request_id)
                    if request is None or request.engagement_id != att.engagement_id:
                        raise ValueError("原索件批次已失效，未自動改連結。")
                self._association_label.setText(f"索件批次：{request.request_name}" if request else "尚未指定索件批次")
                summary = self._container.doc_requests.summary_by_engagement(att.engagement_id)
                due = request.due_date if request else None
                self._facts_label.setText(f"{status} · 索件期限 {due or '未設定'}\n全案缺件 {summary.missing} · 不完整 {summary.incomplete} · 待確認 {summary.pending_confirm}")
        except Exception as exc:
            self._facts_label.setText(f"附件：{status}")
            self._context_warning.setText(str(exc) if isinstance(exc, ValueError) else "核對摘要讀取失敗。請重新整理，未顯示舊摘要。")
            self._context_warning.show()
            self._manual_btn.setEnabled(False)
        self._update_preview(att)

    def _update_preview(self, att) -> None:
        if att is None:
            self._preview_stack.setCurrentIndex(_PREVIEW_NONE)
            return

        file_path = self._resolve_att_file_path(att, notify=False)
        if file_path is None:
            self._preview_meta.setText(
                f"無法預覽附件：{error_message('attachment.not_found')}"
            )
            self._preview_stack.setCurrentIndex(_PREVIEW_META)
            return
        ext = att.extension.lower()

        if ext == ".pdf" and self._preview_pdf_doc is not None:
            status = self._preview_pdf_doc.load(str(file_path))
            if status == QPdfDocument.Error.None_:
                self._preview_stack.setCurrentIndex(_PREVIEW_PDF)
                return

        if ext in _IMAGE_EXTS:
            self._preview_image.clear()
            try:
                validate_image_file(file_path)
            except (ImageGuardError, OSError) as exc:
                _log.warning(
                    "preview: rejected unsafe image %s: %s",
                    file_path,
                    exc,
                )
                self._preview_meta.setText(
                    "圖片無法預覽：檔案格式或像素尺寸超過安全限制。\n"
                    f"檔案：{att.original_filename}"
                )
                self._preview_stack.setCurrentIndex(_PREVIEW_META)
                return
            pixmap = QPixmap(str(file_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    480, 480,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_image.setPixmap(scaled)
                self._preview_stack.setCurrentIndex(_PREVIEW_IMAGE)
                return

        if ext in _TEXT_EXTS:
            try:
                with file_path.open(
                    "r", encoding="utf-8", errors="replace"
                ) as handle:
                    text = handle.read(4096)
                self._preview_text.setPlainText(text)
                self._preview_stack.setCurrentIndex(_PREVIEW_TEXT)
                return
            except OSError:
                _log.warning("preview: failed to read %s", file_path, exc_info=True)

        size_kb = f"{att.file_size / 1024:.1f} KB"
        self._preview_meta.setText(
            f"檔案：{att.original_filename}\n"
            f"位置：{file_path}\n"
            f"大小：{size_kb}\n"
            f"類型：{att.mime_type}\n"
            f"狀態：{_STATUS_LABELS.get(att.status, att.status)}\n"
            f"上傳：{att.uploaded_at}"
        )
        self._preview_stack.setCurrentIndex(_PREVIEW_META)

    def _on_upload(self) -> None:
        eng_id = self._eng_combo.currentData()
        selected = self._selected_attachment()
        lease_target = selected is not None and selected.engagement_id is None and selected.lease_id is not None
        if not lease_target and (not eng_id or eng_id == _ALL):
            QMessageBox.warning(self, "選擇附件歸屬", "請先選擇案件，或選取要追加檔案的租約附件。新租約請由「資料與工具 → 客戶管理 → 租約管理」建立。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "選擇附件", "", _FILE_FILTER)
        if not path:
            return
        try:
            if lease_target:
                self._container.attachments.upload_lease_attachment(selected.client_id, selected.lease_id, Path(path))
            else:
                self._container.attachments.upload_attachment(UploadAttachmentInput(engagement_id=eng_id, request_id=None, source_path=Path(path)))
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "上傳失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "上傳失敗", error_message("attachment.upload.failed"))
            return
        self._load_attachments()
        self._feedback.setText("附件已新增。")
        self._feedback.show()

    def _on_accept(self) -> None:
        att = self._selected_attachment()
        if att is None or att.status == "accepted":
            return
        try:
            self._container.attachments.accept_attachment(att.id)
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "操作失敗", error_message("attachment.accept.failed"))
            return
        self._load_attachments()
        self._feedback.setText("附件已驗收；索件項目需另行人工確認。")
        self._feedback.show()

    def _on_reject(self) -> None:
        att = self._selected_attachment()
        if att is None or att.status == "rejected":
            return
        try:
            self._container.attachments.reject_attachment(att.id)
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "操作失敗", error_message("attachment.reject.failed"))
            return
        self._load_attachments()
        self._feedback.setText("附件已退回，可於「已退回」查看。")
        self._feedback.show()

    def _on_delete(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        reply = QMessageBox.question(
            self,
            "確認刪除附件",
            f"確定要刪除附件「{att.original_filename}」？\n"
            "附件會從清單隱藏並保留稽核紀錄。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.attachments.delete_attachment(att.id)
        except AttachmentValidationError as err:
            QMessageBox.critical(self, "刪除失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "刪除失敗", error_message("attachment.delete.failed"))
            return
        self._load_attachments()

    def _on_show_info(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        dlg = _AttachmentInfoDialog(att, self)
        dlg.exec()

    def _on_open_system(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        file_path = self._resolve_att_file_path(att, notify=True)
        if file_path is None:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
        if not opened:
            QMessageBox.warning(
                self,
                "開啟失敗",
                "系統無法開啟附件，請確認檔案關聯與存取權限",
            )

    def _show_location_menu(self, pos) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        menu = QMenu(self._more_btn)
        copy_url_action = QAction("複製 file:// URL", menu)
        copy_url_action.triggered.connect(lambda _=False, a=att: self._copy_file_url(a))
        menu.addAction(copy_url_action)
        menu.exec(self._more_btn.mapToGlobal(pos))

    def _copy_file_url(self, att) -> None:
        url = self._att_file_url(att)
        if url is None:
            return
        QApplication.clipboard().setText(url)

    def _on_open_location(self) -> None:
        att = self._selected_attachment()
        if att is None:
            return
        file_path = self._resolve_att_file_path(att, notify=True)
        if file_path is None:
            return
        folder = file_path.parent
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        if not opened:
            QMessageBox.warning(
                self,
                "開啟失敗",
                "系統無法開啟附件資料夾，請確認存取權限",
            )
