"""Paginated annual transaction ledger and service-derived balances."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n.errors import error_message
from ...i18n.labels import ANNUAL_TRANSACTION_CATEGORY_LABELS
from ...services.container import ServiceContainer
from .annual_overview_table import format_twd


class AnnualTransactionPanel(QWidget):
    """Read model that refreshes only through ``page`` and ``balance``."""

    mutation_committed = Signal()

    DATE_COLUMN = 0
    CATEGORY_COLUMN = 1
    AMOUNT_COLUMN = 2
    REFERENCE_COLUMN = 3

    def __init__(
        self,
        container: ServiceContainer,
        work_item_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AnnualTransactionPanel")
        self._container = container
        self._service = container.annual_transactions
        self.work_item_id = work_item_id
        self.page_size = 50
        self.offset = 0
        self.total = 0
        self._load_valid = False
        self._dialog_open = False

        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        action_row = QHBoxLayout()
        self.add_button = QPushButton("新增交易")
        self.edit_button = QPushButton("編輯交易")
        self.delete_button = QPushButton("刪除交易")
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.edit_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("AnnualTransactionTable")
        self.table.setHorizontalHeaderLabels(
            ("日期", "分類", "金額", "參考資訊")
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            self.DATE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.CATEGORY_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.AMOUNT_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.REFERENCE_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

        pagination_row = QHBoxLayout()
        self.previous_button = QPushButton("交易上一頁")
        self.next_button = QPushButton("交易下一頁")
        self.page_label = QLabel("第 1 / 1 頁，共 0 筆")
        pagination_row.addWidget(self.previous_button)
        pagination_row.addWidget(self.next_button)
        pagination_row.addStretch(1)
        pagination_row.addWidget(self.page_label)
        layout.addLayout(pagination_row)

        balance_group = QGroupBox("帳務核對")
        balance_grid = QGridLayout(balance_group)
        balance_grid.setHorizontalSpacing(10)
        balance_grid.setVerticalSpacing(4)
        for index, (attr, label) in enumerate((
            ("tax_liability_label", "應納稅額"),
            ("client_tax_collection_label", "客戶稅款代收"),
            ("tax_payment_label", "已繳稅款"),
            ("tax_credit_or_refund_label", "退抵稅額"),
            ("fee_receivable_label", "應收服務費"),
            ("fee_receipt_label", "已收服務費"),
            ("collection_shortfall_label", "代收不足"),
            ("unpaid_tax_label", "欠繳稅款"),
            ("outstanding_fee_label", "未收服務費"),
            ("excess_client_collection_label", "代收溢收"),
            ("tax_overpayment_label", "稅款溢繳"),
            ("fee_overpayment_label", "服務費溢收"),
        )):
            value = QLabel("NT$ 0")
            value.setObjectName(attr)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            setattr(self, attr, value)
            row = index // 3
            column = (index % 3) * 2
            balance_grid.addWidget(QLabel(label), row, column)
            balance_grid.addWidget(value, row, column + 1)
            balance_grid.setColumnStretch(column + 1, 1)
        layout.addWidget(balance_group)

        self.retry_button = QPushButton("重新讀取交易")
        self.retry_button.hide()
        self.retry_button.clicked.connect(lambda: self.reload())
        layout.addWidget(self.retry_button)
        self.add_button.clicked.connect(self._open_add)
        self.edit_button.clicked.connect(self._open_edit)
        self.delete_button.clicked.connect(self._delete_selected)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.table.cellDoubleClicked.connect(self._open_edit_row)
        self.reload()

    def reload(self, *, after_commit: bool = False) -> None:
        try:
            page = self._service.page(
                self.work_item_id,
                limit=self.page_size,
                offset=self.offset,
                order_by="transaction_date",
                order_dir="ASC",
            )
            balance = self._service.balance(self.work_item_id)
            if page.total and self.offset >= page.total:
                self.offset = (
                    (page.total - 1) // self.page_size
                ) * self.page_size
                page = self._service.page(
                    self.work_item_id,
                    limit=self.page_size,
                    offset=self.offset,
                    order_by="transaction_date",
                    order_dir="ASC",
                )
            self.total = page.total
            self._show_rows(page.rows)
            self._show_balance(balance)
            self._show_pagination()
            self._load_valid = True
            if after_commit:
                self.feedback_label.setText(
                    "交易紀錄已儲存並重新核對帳務。"
                )
            else:
                self.feedback_label.clear()
        except Exception as exc:
            self._load_valid = False
            code = getattr(exc, "code", "")
            if after_commit:
                self.feedback_label.setText(
                    "資料已寫入但重新讀取失敗；為避免依舊資料繼續操作，"
                    "交易異動已停用，請重新讀取或關閉視窗。"
                )
            else:
                self.feedback_label.setText(
                    error_message(code)
                    if code
                    else "讀取交易帳本失敗，請稍後再試。"
                )
        self._apply_control_state()

    def _apply_control_state(self) -> None:
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
        ):
            button.setEnabled(self._load_valid)
        self.previous_button.setEnabled(
            self._load_valid and self.offset > 0
        )
        self.next_button.setEnabled(
            self._load_valid and self.offset + self.page_size < self.total
        )
        self.retry_button.setVisible(not self._load_valid)
        self.retry_button.setEnabled(not self._load_valid)

    def _show_pagination(self) -> None:
        page_count = max(1, (self.total + self.page_size - 1) // self.page_size)
        page_number = min(page_count, self.offset // self.page_size + 1)
        self.page_label.setText(
            f"第 {page_number} / {page_count} 頁，共 {self.total} 筆"
        )

    def _show_rows(self, rows) -> None:
        self.table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.table.insertRow(row_index)
            values = (
                row.transaction_date,
                ANNUAL_TRANSACTION_CATEGORY_LABELS.get(
                    row.category, "未知交易類別"
                ),
                format_twd(row.amount),
                row.reference or "",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if column == self.DATE_COLUMN:
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                self.table.setItem(row_index, column, item)

    def _show_balance(self, balance) -> None:
        for name in (
            "tax_liability",
            "client_tax_collection",
            "tax_payment",
            "tax_credit_or_refund",
            "fee_receivable",
            "fee_receipt",
            "collection_shortfall",
            "unpaid_tax",
            "outstanding_fee",
            "excess_client_collection",
            "tax_overpayment",
            "fee_overpayment",
        ):
            getattr(self, f"{name}_label").setText(
                format_twd(getattr(balance, name))
            )

    def transaction_id_at(self, row: int) -> int | None:
        item = self.table.item(row, self.DATE_COLUMN)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if type(value) is int else None

    def selected_transaction_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        return self.transaction_id_at(rows[0].row())

    def _require_selected(self, action: str) -> int | None:
        transaction_id = self.selected_transaction_id()
        if transaction_id is None:
            self.feedback_label.setText(
                f"請先選取要{action}的交易紀錄。"
            )
            QTimer.singleShot(
                0,
                lambda: self.table.setFocus(
                    Qt.FocusReason.OtherFocusReason
                ),
            )
        return transaction_id

    def _open_add(self) -> None:
        from ..dialogs.annual_transaction_dialog import AnnualTransactionDialog

        dialog = AnnualTransactionDialog(
            self._service, self.work_item_id, parent=self
        )
        dialog.committed.connect(self._on_mutation_committed)
        dialog.exec()

    def _open_edit(self) -> None:
        transaction_id = self._require_selected("編輯")
        if transaction_id is None:
            return
        self._open_edit_transaction(transaction_id)

    def _open_edit_transaction(self, transaction_id: int) -> None:
        if self._dialog_open:
            return
        from ..dialogs.annual_transaction_dialog import AnnualTransactionDialog

        dialog = AnnualTransactionDialog(
            self._service,
            self.work_item_id,
            transaction_id=transaction_id,
            parent=self,
        )
        dialog.committed.connect(self._on_mutation_committed)
        self._dialog_open = True
        try:
            dialog.exec()
        finally:
            self._dialog_open = False

    def _open_edit_row(self, row: int, _column: int) -> None:
        transaction_id = self.transaction_id_at(row)
        if transaction_id is not None:
            self._open_edit_transaction(transaction_id)

    def _delete_selected(self) -> None:
        transaction_id = self._require_selected("刪除")
        if transaction_id is None or self._dialog_open:
            return
        from ..dialogs.annual_transaction_dialog import (
            AnnualTransactionDeleteDialog,
        )

        dialog = AnnualTransactionDeleteDialog(
            self._service,
            transaction_id,
            parent=self,
        )
        dialog.committed.connect(self._on_mutation_committed)
        self._dialog_open = True
        try:
            dialog.exec()
        finally:
            self._dialog_open = False

    def _on_mutation_committed(self) -> None:
        self.mutation_committed.emit()
        self.reload(after_commit=True)

    def _previous_page(self) -> None:
        if not self._load_valid or self.offset <= 0:
            return
        self.offset = max(0, self.offset - self.page_size)
        self.reload()

    def _next_page(self) -> None:
        if (
            not self._load_valid
            or self.offset + self.page_size >= self.total
        ):
            return
        self.offset += self.page_size
        self.reload()
