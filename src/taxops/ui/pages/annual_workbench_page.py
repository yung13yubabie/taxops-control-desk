"""Fixed-desktop annual compliance overview for the whole office."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.compliance import WORK_TYPE_LABELS
from ...i18n import NAV_LABELS
from ...repositories.annual_work import AnnualOverviewMetrics, AnnualWorkOverviewRow
from ...services.annual_work import AnnualWorkStatusPresentation
from ...services.container import ServiceContainer
from ..dialogs.annual_workspace_dialog import AnnualWorkspaceDialog
from ..dialogs.annual_item_dialog import AnnualItemDialog
from ..style import TEXT_MUTED
from ..widgets.annual_overview_table import AnnualOverviewTable, format_twd
from ..widgets.empty_state import EmptyState


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


class AnnualWorkbenchPage(QWidget):
    """Read-only office-wide overview; mutation actions remain for Task 3."""

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

        page_font = self.font()
        page_font.setPixelSize(14)
        self.setFont(page_font)
        self.setStyleSheet(
            "QLabel#EmptyStateTitle, QLabel#EmptyStateBody, "
            "QPushButton#AnnualFutureAction { font-size: 14px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(8)

        heading = QHBoxLayout()
        self.title_label = QLabel(NAV_LABELS["annual_workbench"])
        self.title_label.setObjectName("PageTitle")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        heading.addWidget(self.title_label)
        heading.addStretch(1)
        self.create_button = QPushButton("建立年度工作")
        self.create_button.setObjectName("AnnualFutureAction")
        self.future_action_button = self.create_button
        heading.addWidget(self.create_button)
        outer.addLayout(heading)

        self._filter_notice = QLabel()
        self._filter_notice.setObjectName("AnnualFilterNotice")
        self._filter_notice.setWordWrap(True)
        self._filter_notice.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
        self._filter_notice.hide()
        outer.addWidget(self._filter_notice)

        filter_group = QGroupBox("篩選條件")
        filter_grid = QGridLayout(filter_group)
        filter_grid.setContentsMargins(10, 8, 10, 8)
        filter_grid.setHorizontalSpacing(8)
        filter_grid.setVerticalSpacing(6)

        self.operation_year_combo = QComboBox()
        self.operation_year_combo.setObjectName("AnnualOperationYearFilter")
        self.operation_year_combo.addItem("全部年度", None)
        current_year = datetime.date.today().year
        for year in range(current_year + 1, current_year - 11, -1):
            self.operation_year_combo.addItem(str(year), year)

        self.client_search_input = QLineEdit()
        self.client_search_input.setObjectName("AnnualClientSearch")
        self.client_search_input.setPlaceholderText("搜尋客戶代號、名稱或工作標題")
        self.client_search_input.setMaxLength(100)

        self.work_type_combo = QComboBox()
        self.work_type_combo.setObjectName("AnnualWorkTypeFilter")
        self.work_type_combo.addItem("全部工作類型", None)
        for work_type, label in WORK_TYPE_LABELS.items():
            self.work_type_combo.addItem(label, work_type)

        self.risk_combo = QComboBox()
        self.risk_combo.setObjectName("AnnualRiskFilter")
        for label, code in _RISK_OPTIONS:
            self.risk_combo.addItem(label, code)

        filters = (
            ("作業年度", self.operation_year_combo),
            ("客戶關鍵字", self.client_search_input),
            ("工作類型", self.work_type_combo),
            ("風險", self.risk_combo),
        )
        for column, (label, control) in enumerate(filters):
            filter_grid.addWidget(QLabel(label), 0, column)
            filter_grid.addWidget(control, 1, column)
        filter_grid.setColumnStretch(1, 1)

        action_row = QHBoxLayout()
        self.apply_button = QPushButton("套用")
        self.apply_button.setObjectName("AnnualApplyFilter")
        self.clear_button = QPushButton("清除")
        self.clear_button.setObjectName("AnnualClearFilter")
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setObjectName("AnnualRefresh")
        action_row.addWidget(self.apply_button)
        action_row.addWidget(self.clear_button)
        action_row.addWidget(self.refresh_button)
        action_row.addStretch(1)
        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("AnnualFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
        action_row.addWidget(self.feedback_label, 1)
        filter_grid.addLayout(action_row, 2, 0, 1, 4)
        outer.addWidget(filter_group)

        metrics_widget = QWidget()
        metrics_widget.setObjectName("AnnualMetrics")
        metrics_grid = QGridLayout(metrics_widget)
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(4)
        self.metric_value_labels: list[QLabel] = []
        for index, title in enumerate(_METRIC_TITLES):
            label = QLabel(f"{title} 0")
            label.setObjectName(f"AnnualMetric{index}")
            label.setStyleSheet(
                "background: #F8FAFC; border: 1px solid #E2E8F0; "
                "border-radius: 6px; padding: 5px 8px; font-size: 14px;"
            )
            self.metric_value_labels.append(label)
            metrics_grid.addWidget(label, index // 4, index % 4)
        outer.addWidget(metrics_widget)

        self.overview_table = AnnualOverviewTable()
        self.empty_state = EmptyState(
            "目前沒有符合篩選條件的年度工作",
            detail="可調整上方年度、客戶、工作類型或風險條件後重新查詢。",
        )
        self.table_stack = QStackedWidget()
        self.table_stack.setObjectName("AnnualOverviewStack")
        self.table_stack.addWidget(self.empty_state)
        self.table_stack.addWidget(self.overview_table)
        detail_group = QGroupBox("選取工作完整資訊")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        self.detail_label = QLabel("請選取表格中的工作項目。")
        self.detail_label.setObjectName("AnnualSelectionDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self.detail_label)
        detail_actions = QHBoxLayout()
        detail_actions.addStretch(1)
        self.open_detail_button = QPushButton("開啟明細")
        self.open_detail_button.setObjectName("AnnualOpenDetail")
        detail_actions.addWidget(self.open_detail_button)
        detail_layout.addLayout(detail_actions)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("AnnualDesktopSplitter")
        self.splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.splitter.addWidget(self.table_stack)
        self.splitter.addWidget(detail_group)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([320, 88])
        outer.addWidget(self.splitter, 1)

        page_row = QHBoxLayout()
        self.previous_button = QPushButton("◀ 上一頁")
        self.previous_button.setObjectName("AnnualPreviousPage")
        self.next_button = QPushButton("下一頁 ▶")
        self.next_button.setObjectName("AnnualNextPage")
        self.page_label = QLabel("第 1 頁 / 共 0 頁")
        self.page_label.setObjectName("AnnualPageLabel")
        page_row.addWidget(self.previous_button)
        page_row.addWidget(self.next_button)
        page_row.addStretch(1)
        page_row.addWidget(self.page_label)
        outer.addLayout(page_row)

        self.create_button.clicked.connect(self._open_create_dialog)
        self.apply_button.clicked.connect(self._apply_filters)
        self.clear_button.clicked.connect(self._clear_filters)
        self.refresh_button.clicked.connect(self._refresh)
        self.client_search_input.returnPressed.connect(self._apply_filters)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.overview_table.itemSelectionChanged.connect(
            self._show_selected_detail
        )
        self.open_detail_button.clicked.connect(self._open_selected_detail)
        self.overview_table.itemDoubleClicked.connect(
            lambda _item: self._open_selected_detail()
        )

        self._update_pagination()
        self._refresh()

    def refresh_context(self) -> None:
        self._refresh()

    def _open_create_dialog(self) -> None:
        dialog = AnnualWorkspaceDialog(self._container, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _open_selected_detail(self) -> None:
        if self._detail_open:
            return
        row_index = self._selected_row_index()
        if row_index is None:
            self.feedback_label.setText("請先選取要開啟的年度工作。")
            self.overview_table.setFocus()
            return
        self._detail_open = True
        self.open_detail_button.setEnabled(False)
        try:
            item_id = self._rows[row_index].item.id
            dialog = AnnualItemDialog(self._container, item_id, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._refresh()
        except Exception as exc:
            try:
                self._container.system_log.error(
                    "annual_work.item_dialog.open_failed", exc=exc
                )
            except Exception:
                pass
            self.feedback_label.setText("開啟年度工作明細失敗，請稍後再試。")
        finally:
            self._detail_open = False
            self.open_detail_button.setEnabled(True)

    def _selected_row_index(self) -> int | None:
        selected = self.overview_table.selectionModel().selectedRows()
        if len(selected) != 1:
            return None
        row_index = selected[0].row()
        return row_index if 0 <= row_index < len(self._rows) else None

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

    def _set_busy(self, busy: bool) -> None:
        for button in (self.apply_button, self.clear_button, self.refresh_button):
            button.setEnabled(not busy)
        if busy:
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
        else:
            self._update_pagination()
        if busy:
            self.feedback_label.setText("處理中，正在讀取年度工作總覽…")
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
            self.table_stack.setCurrentWidget(
                self.overview_table if self._rows else self.empty_state
            )
            self._total = metrics.item_count
            self._set_metrics(metrics)
            self.overview_table.clearSelection()
            self._show_selected_detail()
            self.feedback_label.setText(f"已更新，共 {self._total} 筆工作。")
        except Exception as exc:
            self._show_refresh_failure(exc)
        finally:
            self._set_busy(False)
            self._refreshing = False

    def _show_refresh_failure(self, exc: BaseException | None) -> None:
        self._clear_results()
        try:
            self._container.system_log.error(
                "annual_work.overview.ui_load_failed",
                exc=exc,
            )
        except Exception:
            pass
        self.feedback_label.setText("載入失敗，請稍後重新整理。")

    def _clear_results(self) -> None:
        self._rows = []
        self._presentations = []
        self._page = 0
        self._total = 0
        self.overview_table.set_rows((), ())
        self.table_stack.setCurrentWidget(self.empty_state)
        self._set_metrics(AnnualOverviewMetrics())
        self.detail_label.setText("目前沒有可顯示的工作資訊。")
        self._update_pagination()

    def _set_metrics(self, metrics: AnnualOverviewMetrics) -> None:
        values = (
            str(metrics.item_count),
            str(metrics.client_count),
            str(metrics.exception_count),
            str(metrics.document_risk_count),
            format_twd(metrics.collection_shortfall_total),
            format_twd(metrics.unpaid_tax_total),
            format_twd(metrics.outstanding_fee_total),
            str(metrics.overage_count),
        )
        for title, value, label in zip(
            _METRIC_TITLES, values, self.metric_value_labels
        ):
            label.setText(f"{title} {value}")
            label.setToolTip(label.text())

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
        self.next_button.setEnabled(
            (self._page + 1) * _PAGE_SIZE < self._total
        )

    def _show_selected_detail(self) -> None:
        if not self._rows:
            self.detail_label.setText("目前沒有符合篩選條件的年度工作。")
            return
        row_index = self._selected_row_index()
        if row_index is None:
            self.detail_label.setText("請選取表格中的工作項目。")
            return
        row = self._rows[row_index]
        item = row.item
        status = self._presentations[row_index]
        work_type = WORK_TYPE_LABELS.get(item.work_type, "未知工作類型")
        self.detail_label.setText(
            f"客戶：{row.client_name}（{row.client_code}）　作業年度：{row.operation_year}\n"
            f"標題：{item.title}　工作類型：{work_type}　期限：{item.due_date or '—'}\n"
            f"作業：{status.work_status_label}　申報：{status.filing_status_label}　"
            f"憑證：{status.document_status_label}　稅款：{status.tax_status_label}　"
            f"服務費：{status.fee_status_label}\n"
            f"收款短缺：{format_twd(row.balance.collection_shortfall)}　"
            f"未繳稅：{format_twd(row.balance.unpaid_tax)}　"
            f"未收服務費：{format_twd(row.balance.outstanding_fee)}　"
            f"例外原因：{item.exception_reason or '無'}　備註：{item.notes or '無'}"
        )
