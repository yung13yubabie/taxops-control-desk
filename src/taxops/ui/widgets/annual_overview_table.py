"""Read-only annual overview table with stable desktop columns."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from ...core.compliance import WORK_TYPE_LABELS
from ...repositories.annual_work import AnnualWorkOverviewRow
from ...services.annual_work import AnnualWorkStatusPresentation


def format_twd(amount: int) -> str:
    return f"NT$ {amount:,}"


class AnnualOverviewTable(QTableWidget):
    CLIENT_COLUMN = 0
    YEAR_COLUMN = 1
    TITLE_COLUMN = 2
    WORK_TYPE_COLUMN = 3
    DUE_DATE_COLUMN = 4
    WORK_STATUS_COLUMN = 5
    FILING_STATUS_COLUMN = 6
    DOCUMENT_STATUS_COLUMN = 7
    TAX_STATUS_COLUMN = 8
    FEE_STATUS_COLUMN = 9
    COLLECTION_SHORTFALL_COLUMN = 10
    UNPAID_TAX_COLUMN = 11
    OUTSTANDING_FEE_COLUMN = 12

    HEADERS = (
        "客戶",
        "年度",
        "標題",
        "工作類型",
        "期限",
        "作業狀態",
        "申報狀態",
        "憑證狀態",
        "稅款狀態",
        "服務費狀態",
        "收款短缺",
        "未繳稅",
        "未收服務費",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setObjectName("AnnualOverviewTable")
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.CLIENT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.TITLE_COLUMN, QHeaderView.ResizeMode.Stretch)
        fixed_widths = {
            self.YEAR_COLUMN: 72,
            self.WORK_TYPE_COLUMN: 168,
            self.DUE_DATE_COLUMN: 104,
            self.WORK_STATUS_COLUMN: 112,
            self.FILING_STATUS_COLUMN: 112,
            self.DOCUMENT_STATUS_COLUMN: 112,
            self.TAX_STATUS_COLUMN: 128,
            self.FEE_STATUS_COLUMN: 136,
            self.COLLECTION_SHORTFALL_COLUMN: 126,
            self.UNPAID_TAX_COLUMN: 118,
            self.OUTSTANDING_FEE_COLUMN: 132,
        }
        for column, width in fixed_widths.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)

        font = self.font()
        font.setPixelSize(13)
        self.setFont(font)

    def set_rows(
        self,
        rows: Sequence[AnnualWorkOverviewRow],
        presentations: Sequence[AnnualWorkStatusPresentation],
    ) -> None:
        if len(rows) != len(presentations):
            raise ValueError("annual overview rows and presentations differ")
        self.blockSignals(True)
        try:
            self.clearContents()
            self.setRowCount(len(rows))
            for row_index, (row, status) in enumerate(zip(rows, presentations)):
                item = row.item
                values = (
                    row.client_name,
                    str(row.operation_year),
                    item.title,
                    WORK_TYPE_LABELS.get(item.work_type, "未知工作類型"),
                    item.due_date or "—",
                    status.work_status_label,
                    status.filing_status_label,
                    status.document_status_label,
                    status.tax_status_label,
                    status.fee_status_label,
                    format_twd(row.balance.collection_shortfall),
                    format_twd(row.balance.unpaid_tax),
                    format_twd(row.balance.outstanding_fee),
                )
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(value)
                    if column == self.CLIENT_COLUMN:
                        cell.setData(Qt.ItemDataRole.UserRole, row_index)
                    if column in {
                        self.YEAR_COLUMN,
                        self.DUE_DATE_COLUMN,
                        self.WORK_STATUS_COLUMN,
                        self.FILING_STATUS_COLUMN,
                        self.DOCUMENT_STATUS_COLUMN,
                        self.TAX_STATUS_COLUMN,
                        self.FEE_STATUS_COLUMN,
                    }:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    elif column >= self.COLLECTION_SHORTFALL_COLUMN:
                        cell.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.setItem(row_index, column, cell)
        finally:
            self.blockSignals(False)
