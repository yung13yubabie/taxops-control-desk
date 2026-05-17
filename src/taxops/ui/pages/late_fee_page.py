"""Late fee calculator page: compute and record penalty amounts per document request."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...i18n.status_labels import status_to_label
from ...services.container import ServiceContainer
from ...services.late_fee import CalculateLateFeeInput, LateFeeValidationError

_HISTORY_COLUMNS = ("id", "overdue_days", "penalty_percent", "base_amount", "penalty_amount", "calc_at")
_HISTORY_HEADERS = {
    "id": "編號",
    "overdue_days": "逾期天數",
    "penalty_percent": "滯納金率(%)",
    "base_amount": "稅額",
    "penalty_amount": "滯納金",
    "calc_at": "試算時間",
}

_ALL = -1


class LateFeePage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._history: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("滯納金試算")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        # -- Filter row --
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("案件："))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(200)
        filter_row.addWidget(self._eng_combo)

        filter_row.addWidget(QLabel("索件批次："))
        self._req_combo = QComboBox()
        self._req_combo.setMinimumWidth(200)
        filter_row.addWidget(self._req_combo)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        # -- Input form --
        form_box = QGroupBox("試算參數")
        form_layout = QFormLayout(form_box)
        form_layout.setSpacing(10)

        self._days_spin = QSpinBox()
        self._days_spin.setRange(0, 3650)
        self._days_spin.setSuffix(" 天")
        form_layout.addRow("逾期天數：", self._days_spin)

        self._base_spin = QDoubleSpinBox()
        self._base_spin.setRange(0, 999_999_999)
        self._base_spin.setDecimals(2)
        self._base_spin.setSuffix(" 元")
        form_layout.addRow("申報稅額：", self._base_spin)

        self._calc_btn = QPushButton("開始試算")
        self._calc_btn.clicked.connect(self._on_calculate)
        form_layout.addRow("", self._calc_btn)

        outer.addWidget(form_box)

        # -- Result display --
        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        outer.addWidget(self._result_label)

        # -- History table --
        history_label = QLabel("試算記錄")
        history_label.setObjectName("SectionTitle")
        outer.addWidget(history_label)

        self._table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self._table.setHorizontalHeaderLabels(
            [_HISTORY_HEADERS[c] for c in _HISTORY_COLUMNS]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        outer.addWidget(self._table)

        self._eng_combo.currentIndexChanged.connect(self._on_engagement_changed)
        self._req_combo.currentIndexChanged.connect(self._load_history)
        self._load_engagements()

    def _load_engagements(self) -> None:
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("（請選擇案件）", _ALL)
        try:
            for eng in self._container.engagements.list_all():
                self._eng_combo.addItem(eng.engagement_name, eng.id)
        except Exception:
            pass
        self._eng_combo.blockSignals(False)
        self._on_engagement_changed()

    def _on_engagement_changed(self) -> None:
        eng_id = self._eng_combo.currentData()
        self._req_combo.blockSignals(True)
        self._req_combo.clear()
        self._req_combo.addItem("（請選擇索件批次）", _ALL)
        if eng_id != _ALL:
            try:
                for req in self._container.doc_requests.list_by_engagement(eng_id):
                    label = f"{req.period_name} ({status_to_label(req.tax_type)})"
                    self._req_combo.addItem(label, req.id)
            except Exception:
                pass
        self._req_combo.blockSignals(False)
        self._load_history()

    def _load_history(self) -> None:
        req_id = self._req_combo.currentData()
        self._history = []
        if req_id and req_id != _ALL:
            try:
                self._history = self._container.late_fee.list_by_request(req_id)
            except Exception:
                pass
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(0)
        for rec in self._history:
            row = self._table.rowCount()
            self._table.insertRow(row)
            vals = {
                "id": str(rec.id),
                "overdue_days": str(rec.overdue_days),
                "penalty_percent": f"{rec.penalty_percent:.1f}%",
                "base_amount": f"{rec.base_amount:,.2f}",
                "penalty_amount": f"{rec.penalty_amount:,.2f}",
                "calc_at": rec.calc_at,
            }
            for col, key in enumerate(_HISTORY_COLUMNS):
                self._table.setItem(row, col, QTableWidgetItem(vals[key]))

    def _on_calculate(self) -> None:
        req_id = self._req_combo.currentData()
        if not req_id or req_id == _ALL:
            QMessageBox.warning(self, "提示", "請先選擇索件批次")
            return

        try:
            row = self._container.late_fee.calculate_and_save(
                CalculateLateFeeInput(
                    request_id=req_id,
                    overdue_days=self._days_spin.value(),
                    base_amount=self._base_spin.value(),
                )
            )
        except LateFeeValidationError as err:
            QMessageBox.critical(self, "試算失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "試算失敗", error_message("late_fee.calculate.failed"))
            return

        if row.needs_manual_review:
            self._result_label.setText(
                "⚠ 勞健保稅種需人工確認，無法自動計算滯納金。請聯絡主管確認滯納金金額。"
            )
        else:
            self._result_label.setText(
                f"試算結果：滯納金率 {row.penalty_percent:.1f}%，"
                f"滯納金 {row.penalty_amount:,.2f} 元"
                f"（稅額 {row.base_amount:,.2f} 元，逾期 {row.overdue_days} 天）"
            )
        self._load_history()
