"""Annual workbench: office-wide annual work list with a detail inspector.

Follows the master-detail template established by `clients_page.py`. Three things
changed from the first version of this screen:

The KPI strip showed all eight overview metrics permanently, so a quiet office saw
eight tiles reading zero. Tiles now carry only work that needs doing, only when its
count is non-zero, and an all-clear sentence replaces the strip when nothing does.
The two counts that merely describe the result set — 工作數 and 客戶數 — are reported
in the result line instead.

The table carried thirteen columns, which pushed the client name and the work title
into ellipses. Five core columns stay in the list; the four detailed statuses and the
three balance figures moved into the inspector, where they have room for a label.

Selecting a row used to repeat that row underneath as one paragraph of plain text.
The inspector replaces it, and 開啟明細 lives there too, so it exists only once a row
is selected.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.compliance import WORK_TYPE_LABELS
from ...i18n import NAV_LABELS
from ...repositories.annual_work import AnnualOverviewMetrics, AnnualWorkOverviewRow
from ...services.annual_work import AnnualWorkStatusPresentation
from ...services.container import ServiceContainer
from .. import tokens
from ..dialogs.annual_item_dialog import AnnualItemDialog
from ..dialogs.annual_workspace_dialog import AnnualWorkspaceDialog
from ..dialogs.compliance_profile_dialog import ComplianceProfileDialog
from ..style import toolbar_icon
from ..widgets.annual_overview_table import AnnualOverviewTable, format_twd
from ..widgets.buttons import make_icon_button
from ..widgets.empty_state import EmptyState
from ..widgets.inspector import Inspector
from ..widgets.page_shell import ActionBar, PageHeader

_PAGE_SIZE = 100
_RISK_OPTIONS = (
    ("全部風險", None),
    ("作業異常", "exception"),
    ("憑證缺件", "document_missing"),
    ("客戶款短缺", "collection_shortfall"),
    ("稅款未繳", "unpaid_tax"),
    ("服務費未收", "outstanding_fee"),
    ("超收／溢付", "overage"),
)

# Order and wording are a contract: `metric_value_labels` is read positionally.
_METRIC_TITLES = (
    "工作數",
    "客戶數",
    "異常數",
    "缺件風險數",
    "收款短缺",
    "未繳稅",
    "未收服務費",
    "超收筆數",
)

# A tile earns its place by naming work that needs doing. 工作數 and 客戶數 count
# what the filter matched, which is the result line's job, so they are never tiles.
ACTIONABLE_METRIC_INDEXES: tuple[int, ...] = (2, 3, 4, 5, 6, 7)

# Five columns fit 1366x768 beside the inspector without horizontal scrolling.
# The remaining eight stay populated but hidden — the inspector reads them, and
# hiding rather than dropping them keeps every value one selection away.
CORE_COLUMNS: tuple[int, ...] = (
    AnnualOverviewTable.CLIENT_COLUMN,
    AnnualOverviewTable.TITLE_COLUMN,
    AnnualOverviewTable.WORK_TYPE_COLUMN,
    AnnualOverviewTable.DUE_DATE_COLUMN,
    AnnualOverviewTable.WORK_STATUS_COLUMN,
)

_ALL_CLEAR_TEXT = "目前沒有需要處理的年度工作風險。"

# `docs/product_object_model.md`: annual work is the single source of truth for
# compliance status, and no other object may be read to answer whether a filing is
# done. The inspector says so rather than leaving the reader to assume it.
_AUTHORITY_NOTE = (
    "年度工作是法遵狀態的唯一依據；連結的待辦或流程執行完成，不代表本項年度工作已完成。"
)


def _metric_cells(
    metrics: AnnualOverviewMetrics,
) -> tuple[tuple[object, ...], tuple[str, ...]]:
    """Raw values and their display text, in `_METRIC_TITLES` order."""
    raw: tuple[object, ...] = (
        metrics.item_count,
        metrics.client_count,
        metrics.exception_count,
        metrics.document_risk_count,
        metrics.collection_shortfall_total,
        metrics.unpaid_tax_total,
        metrics.outstanding_fee_total,
        metrics.overage_count,
    )
    text: tuple[str, ...] = (
        str(metrics.item_count),
        str(metrics.client_count),
        str(metrics.exception_count),
        str(metrics.document_risk_count),
        format_twd(metrics.collection_shortfall_total),
        format_twd(metrics.unpaid_tax_total),
        format_twd(metrics.outstanding_fee_total),
        str(metrics.overage_count),
    )
    return raw, text


class AnnualWorkbenchPage(QWidget):
    """Read-only office-wide overview; mutation happens in the item dialog."""

    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualWorkbenchPage")
        self._container = container
        self._filter_key = ""
        self._page = 0
        self._total = 0
        self._rows: list[AnnualWorkOverviewRow] = []
        self._presentations: list[AnnualWorkStatusPresentation] = []
        self._refreshing = False
        self._detail_open = False
        self._visible_metric_titles: tuple[str, ...] = ()

        page_font = self.font()
        page_font.setPixelSize(tokens.FONT_BODY)
        self.setFont(page_font)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACING_MD)

        # ── Header: the page's single primary, plus the rules entry ─────
        self.header = PageHeader(NAV_LABELS["annual_workbench"])
        self.title_label = self.header.title_label
        self.profile_button = QPushButton("年度法遵設定")
        self.profile_button.setObjectName("AnnualComplianceProfile")
        self.profile_button.setIcon(toolbar_icon("settings"))
        self.header.add_action(self.profile_button, role=tokens.ROLE_SECONDARY)
        self.create_button = QPushButton("建立年度工作")
        self.create_button.setObjectName("AnnualFutureAction")
        self.create_button.setIcon(toolbar_icon("add"))
        self.header.add_action(self.create_button, role=tokens.ROLE_PRIMARY)
        # Kept for the navigation contract, which reads the page's forward action.
        self.future_action_button = self.create_button
        outer.addWidget(self.header)

        # ── One filter bar: year, search, work type, risk ──────────────
        self.action_bar = ActionBar()

        self.operation_year_combo = QComboBox()
        self.operation_year_combo.setObjectName("AnnualOperationYearFilter")
        self.operation_year_combo.addItem("全部年度", None)
        current_year = datetime.date.today().year
        for year in range(current_year + 1, current_year - 11, -1):
            self.operation_year_combo.addItem(str(year), year)
        self.operation_year_combo.setMaximumWidth(120)

        self.client_search_input = QLineEdit()
        self.client_search_input.setObjectName("AnnualClientSearch")
        self.client_search_input.setPlaceholderText("搜尋客戶代號、名稱或工作標題")
        self.client_search_input.setMaxLength(100)
        self.client_search_input.setMinimumWidth(160)

        self.work_type_combo = QComboBox()
        self.work_type_combo.setObjectName("AnnualWorkTypeFilter")
        self.work_type_combo.addItem("全部工作類型", None)
        for work_type, label in WORK_TYPE_LABELS.items():
            self.work_type_combo.addItem(label, work_type)
        # A maximum bounds the minimum too, so one long work-type label cannot
        # push the page's minimum width past the fixed-desktop budget.
        self.work_type_combo.setMaximumWidth(190)

        self.risk_combo = QComboBox()
        self.risk_combo.setObjectName("AnnualRiskFilter")
        for label, code in _RISK_OPTIONS:
            self.risk_combo.addItem(label, code)
        self.risk_combo.setMaximumWidth(150)

        self.filter_bar = QWidget()
        self.filter_bar.setObjectName("AnnualFilterBar")
        filter_row = QHBoxLayout(self.filter_bar)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(tokens.SPACING_SM)
        filter_row.addWidget(self.operation_year_combo)
        filter_row.addWidget(self.client_search_input, 1)
        filter_row.addWidget(self.work_type_combo)
        filter_row.addWidget(self.risk_combo)
        self.action_bar.add_leading_widget(self.filter_bar, stretch=1)

        self.apply_button = QPushButton("套用")
        self.apply_button.setObjectName("AnnualApplyFilter")
        self.action_bar.add_work_action(
            self.apply_button, role=tokens.ROLE_SECONDARY
        )
        self.clear_button = QPushButton("清除")
        self.clear_button.setObjectName("AnnualClearFilter")
        self.action_bar.add_work_action(self.clear_button, role=tokens.ROLE_QUIET)
        self.refresh_button = self.action_bar.add_tool_icon(
            "refresh", tooltip="重新整理", accessible_name="重新整理"
        )
        outer.addWidget(self.action_bar)

        self._filter_notice = QLabel()
        self._filter_notice.setObjectName("AnnualFilterNotice")
        self._filter_notice.setWordWrap(True)
        self._filter_notice.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        self._filter_notice.hide()
        outer.addWidget(self._filter_notice)

        # ── KPI strip: only what needs action ──────────────────────────
        self._metrics_row = QWidget()
        self._metrics_row.setObjectName("AnnualMetrics")
        # One scoped rule rather than eight identical inline stylesheets. A global
        # #AnnualMetricTile rule belongs in style.py, which this stage does not own.
        self._metrics_row.setStyleSheet(
            f"QLabel#AnnualMetricTile {{ background-color: {tokens.SURFACE_SECTION}; "
            f"border: 1px solid {tokens.BORDER}; "
            f"border-radius: {tokens.RADIUS_MD}px; padding: 5px 10px; }}"
        )
        metrics_layout = QHBoxLayout(self._metrics_row)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(tokens.SPACING_SM)
        self.metric_value_labels: list[QLabel] = []
        for title in _METRIC_TITLES:
            label = QLabel(f"{title} 0")
            label.setObjectName("AnnualMetricTile")
            label.hide()
            self.metric_value_labels.append(label)
            metrics_layout.addWidget(label)
        self.metrics_clear_label = QLabel(_ALL_CLEAR_TEXT)
        self.metrics_clear_label.setObjectName("HintText")
        metrics_layout.addWidget(self.metrics_clear_label)
        metrics_layout.addStretch(1)
        outer.addWidget(self._metrics_row)

        # ── Empty state replaces the body rather than framing an empty table ──
        self.empty_state = EmptyState(
            "目前沒有符合篩選條件的年度工作",
            detail="可調整上方年度、客戶、工作類型或風險條件後重新查詢。",
            action_text="建立第一筆年度工作",
        )
        outer.addWidget(self.empty_state, stretch=1)

        # ── Master-detail body ─────────────────────────────────────────
        self.overview_table = AnnualOverviewTable()

        self.inspector = Inspector(
            placeholder="選取左側年度工作後，可在此查看各項狀態與帳款摘要。",
            min_width=300,
        )
        self.open_detail_button = QPushButton("開啟明細")
        self.open_detail_button.setObjectName("AnnualOpenDetail")
        self.open_detail_button.setIcon(toolbar_icon("open"))
        # Registered on the inspector, so it inherits the placeholder state and
        # stays hidden until a row is selected.
        self.inspector.add_action(self.open_detail_button)

        list_column = QWidget()
        list_layout = QVBoxLayout(list_column)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(tokens.SPACING_SM)
        list_layout.addWidget(self.overview_table, stretch=1)

        page_row = QHBoxLayout()
        page_row.setSpacing(tokens.SPACING_XS)
        # Chevron icons replace the ◀ ▶ glyphs that were baked into the labels.
        self.previous_button = make_icon_button(
            "chevron-left", tooltip="上一頁", accessible_name="上一頁"
        )
        self.previous_button.setObjectName("AnnualPreviousPage")
        self.next_button = make_icon_button(
            "chevron-right", tooltip="下一頁", accessible_name="下一頁"
        )
        self.next_button.setObjectName("AnnualNextPage")
        self.page_label = QLabel("第 1 頁 / 共 0 頁")
        self.page_label.setObjectName("HintText")
        page_row.addWidget(self.previous_button)
        page_row.addWidget(self.next_button)
        page_row.addWidget(self.page_label)
        page_row.addStretch(1)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        page_row.addWidget(self.feedback_label, 1)
        list_layout.addLayout(page_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("AnnualDesktopSplitter")
        # Ignored vertically keeps the page's minimum height inside the
        # fixed-desktop budget; the splitter takes whatever height is left.
        self.splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.splitter.addWidget(list_column)
        self.splitter.addWidget(self.inspector)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        outer.addWidget(self.splitter, 1)

        self.create_button.clicked.connect(self._open_create_dialog)
        if self.empty_state.action_button is not None:
            self.empty_state.action_button.clicked.connect(self._open_create_dialog)
        self.profile_button.clicked.connect(self._open_profile_dialog)
        self.apply_button.clicked.connect(self._apply_filters)
        self.clear_button.clicked.connect(self._clear_filters)
        self.refresh_button.clicked.connect(self._refresh)
        self.client_search_input.returnPressed.connect(self._apply_filters)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.overview_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.open_detail_button.clicked.connect(self._open_selected_detail)
        self.overview_table.itemDoubleClicked.connect(
            lambda _item: self._open_selected_detail()
        )

        self._apply_column_visibility()
        self._update_pagination()
        self._refresh()

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    def _apply_column_visibility(self) -> None:
        for column in range(self.overview_table.columnCount()):
            self.overview_table.setColumnHidden(column, column not in CORE_COLUMNS)

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------

    def refresh_context(self) -> None:
        self._refresh()

    def visible_metric_titles(self) -> tuple[str, ...]:
        """Titles of the tiles currently shown, in `_METRIC_TITLES` order."""
        return self._visible_metric_titles

    def clear_filter(self) -> None:
        self._filter_key = ""
        self._filter_notice.clear()
        self._filter_notice.hide()
        self._clear_filters()

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key.strip()
        self._filter_notice.setText(
            "已套用導覽篩選；請使用上方條件縮小年度工作範圍。"
            if self._filter_key
            else ""
        )
        self._filter_notice.setVisible(bool(self._filter_key))

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _open_create_dialog(self) -> None:
        dialog = AnnualWorkspaceDialog(self._container, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _open_profile_dialog(self) -> None:
        dialog = ComplianceProfileDialog(self._container, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_feedback("年度法遵設定已儲存，可開始建立年度工作。")

    def _open_selected_detail(self) -> None:
        if self._detail_open:
            return
        row_index = self._selected_row_index()
        if row_index is None:
            self._set_feedback("請先選取要開啟的年度工作。", error=True)
            self.overview_table.setFocus()
            return
        self._detail_open = True
        self.open_detail_button.setEnabled(False)
        try:
            item_id = self._rows[row_index].item.id
            dialog = AnnualItemDialog(self._container, item_id, parent=self)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted or getattr(
                dialog, "has_committed_change", False
            ):
                self._refresh()
        except Exception as exc:
            try:
                self._container.system_log.error(
                    "annual_work.item_dialog.open_failed", exc=exc
                )
            except Exception:
                pass
            self._set_feedback("開啟年度工作明細失敗，請稍後再試。", error=True)
        finally:
            self._detail_open = False
            self.open_detail_button.setEnabled(True)

    # ------------------------------------------------------------------
    # Selection and inspector
    # ------------------------------------------------------------------

    def _selected_row_index(self) -> int | None:
        selected = self.overview_table.selectionModel().selectedRows()
        if len(selected) != 1:
            return None
        row_index = selected[0].row()
        return row_index if 0 <= row_index < len(self._rows) else None

    def _on_selection_changed(self) -> None:
        row_index = self._selected_row_index()
        if row_index is None:
            # Dropping the selection empties the panel rather than leaving the
            # previous row's detail on screen.
            self.inspector.clear()
            return
        self._populate_inspector(row_index)

    def _populate_inspector(self, row_index: int) -> None:
        row = self._rows[row_index]
        item = row.item
        status = self._presentations[row_index]
        work_type = WORK_TYPE_LABELS.get(item.work_type, "未知工作類型")

        self.inspector.begin_update()
        self.inspector.set_title(
            item.title, subtitle=f"{work_type}｜作業年度 {row.operation_year}"
        )

        self.inspector.add_section("基本資訊")
        self.inspector.add_field("客戶", f"{row.client_name}（{row.client_code}）")
        self.inspector.add_field("工作類型", work_type)
        self.inspector.add_field("作業年度", str(row.operation_year))
        self.inspector.add_field(
            "稅務年度", "" if item.tax_year is None else str(item.tax_year)
        )
        # Two deadline columns exist by design; the labels say which is which so a
        # reader never has to guess whether a date was adopted or merely proposed.
        self.inspector.add_field("採用期限", item.due_date or "")
        self.inspector.add_field("建議期限", item.suggested_due_date or "")

        self.inspector.add_section("各項狀態")
        self.inspector.add_field("作業狀態", status.work_status_label)
        self.inspector.add_field("申報狀態", status.filing_status_label)
        self.inspector.add_field("憑證狀態", status.document_status_label)
        self.inspector.add_field("稅款狀態", status.tax_status_label)
        self.inspector.add_field("服務費狀態", status.fee_status_label)
        self.inspector.add_note(_AUTHORITY_NOTE)

        self.inspector.add_section("帳款摘要")
        self.inspector.add_field(
            "收款短缺", format_twd(row.balance.collection_shortfall)
        )
        self.inspector.add_field("未繳稅", format_twd(row.balance.unpaid_tax))
        self.inspector.add_field(
            "未收服務費", format_twd(row.balance.outstanding_fee)
        )

        self.inspector.add_section("例外與備註")
        self.inspector.add_field("例外原因", item.exception_reason or "")
        self.inspector.add_field("備註", item.notes or "", multiline=True)

    # ------------------------------------------------------------------
    # Filters and loading
    # ------------------------------------------------------------------

    def _filters(self) -> dict[str, object]:
        filters: dict[str, object] = {
            "order_by": "due_date",
            "order_dir": "ASC",
        }
        operation_year = self.operation_year_combo.currentData()
        work_type = self.work_type_combo.currentData()
        risk = self.risk_combo.currentData()
        query = self.client_search_input.text().strip()
        if operation_year is not None:
            filters["operation_year"] = operation_year
        if work_type is not None:
            filters["work_type"] = work_type
        if risk is not None:
            filters["risk"] = risk
        if query:
            filters["query"] = query
        return filters

    def _set_feedback(self, text: str, *, error: bool = False) -> None:
        """Show a result line. Failures are red at the error type size."""
        name = "ErrorText" if error else ""
        if self.feedback_label.objectName() != name:
            self.feedback_label.setObjectName(name)
            style = self.feedback_label.style()
            if style is not None:
                style.unpolish(self.feedback_label)
                style.polish(self.feedback_label)
        self.feedback_label.setText(text)

    def _set_busy(self, busy: bool) -> None:
        for button in (self.apply_button, self.clear_button, self.refresh_button):
            button.setEnabled(not busy)
        if busy:
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
        else:
            self._update_pagination()
        if busy:
            self._set_feedback("處理中，正在讀取年度工作總覽…")
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            )

    def _refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._set_busy(True)
        try:
            filters = self._filters()
            rows: list[AnnualWorkOverviewRow] | None = None
            metrics: AnnualOverviewMetrics | None = None
            errors: list[Exception] = []
            try:
                metrics = self._container.annual_work.overview_metrics(filters)
            except Exception as exc:
                errors.append(exc)
            if metrics is not None:
                last_page = max(0, (metrics.item_count - 1) // _PAGE_SIZE)
                self._page = min(self._page, last_page)
            try:
                rows = self._container.annual_work.search_overview(
                    filters,
                    limit=_PAGE_SIZE,
                    offset=self._page * _PAGE_SIZE,
                )
            except Exception as exc:
                errors.append(exc)
            if errors or rows is None or metrics is None:
                self._show_refresh_failure(errors[0] if errors else None)
                return

            self._rows = list(rows)
            self._presentations = [
                self._container.annual_work.present_statuses(row.item)
                for row in self._rows
            ]
            self.overview_table.set_rows(self._rows, self._presentations)
            self._show_body(bool(self._rows))
            self._total = metrics.item_count
            self._set_metrics(metrics)
            self.overview_table.clearSelection()
            self._on_selection_changed()
            self._set_feedback(
                f"已更新，共 {metrics.item_count} 筆工作、"
                f"{metrics.client_count} 家客戶。"
            )
        except Exception as exc:
            self._show_refresh_failure(exc)
        finally:
            self._set_busy(False)
            self._refreshing = False

    def _show_body(self, has_rows: bool) -> None:
        """The empty state replaces the master-detail body, it does not sit above it."""
        self.empty_state.setVisible(not has_rows)
        self.splitter.setVisible(has_rows)

    def _show_refresh_failure(self, exc: BaseException | None) -> None:
        self._clear_results()
        try:
            self._container.system_log.error(
                "annual_work.overview.ui_load_failed",
                exc=exc,
            )
        except Exception:
            pass
        self._set_feedback("載入失敗，請稍後重新整理。", error=True)

    def _clear_results(self) -> None:
        self._rows = []
        self._presentations = []
        self._page = 0
        self._total = 0
        self.overview_table.set_rows((), ())
        self._show_body(False)
        self._set_metrics(AnnualOverviewMetrics())
        self.inspector.clear()
        self._update_pagination()

    def _set_metrics(self, metrics: AnnualOverviewMetrics) -> None:
        raw, text = _metric_cells(metrics)
        shown: list[str] = []
        for index, title in enumerate(_METRIC_TITLES):
            label = self.metric_value_labels[index]
            label.setText(f"{title} {text[index]}")
            label.setToolTip(label.text())
            actionable = index in ACTIONABLE_METRIC_INDEXES and raw[index] != 0
            label.setVisible(actionable)
            if actionable:
                shown.append(title)
        self._visible_metric_titles = tuple(shown)
        # Eight tiles reading zero told the reader nothing. One sentence does.
        self.metrics_clear_label.setVisible(not shown)

    def _apply_filters(self) -> None:
        self._page = 0
        self._refresh()

    def _clear_filters(self) -> None:
        self.operation_year_combo.setCurrentIndex(0)
        self.client_search_input.clear()
        self.work_type_combo.setCurrentIndex(0)
        self.risk_combo.setCurrentIndex(0)
        self._page = 0
        self._refresh()

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _previous_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._refresh()

    def _next_page(self) -> None:
        if (self._page + 1) * _PAGE_SIZE < self._total:
            self._page += 1
            self._refresh()

    def _update_pagination(self) -> None:
        page_count = (self._total + _PAGE_SIZE - 1) // _PAGE_SIZE
        shown_page = self._page + 1 if page_count else 1
        self.page_label.setText(f"第 {shown_page} 頁 / 共 {page_count} 頁")
        self.previous_button.setEnabled(self._page > 0)
        self.next_button.setEnabled((self._page + 1) * _PAGE_SIZE < self._total)
