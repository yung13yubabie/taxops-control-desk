"""Late fee calculator page: compute and record penalty amounts per document request."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.clock import today_iso
from ...i18n import error_message
from ...i18n.status_labels import status_to_label
from ...services.container import ServiceContainer
from ..style import STATUS_PENDING_BG, STATUS_PENDING_FG, toolbar_icon
from ..widgets.date_field import DateField
from ...services.late_fee import (
    PERIOD_CODES,
    CalculateLateFeeInput,
    LateFeeValidationError,
    build_penalty_schedule,
    calculate_overdue_days,
    calculate_penalty_percent,
    last_payment_date_for_period,
)

_HISTORY_COLUMNS = (
    "id",
    "period_code",
    "last_payment_date",
    "actual_payment_date",
    "overdue_days",
    "penalty_percent",
    "base_amount",
    "penalty_amount",
    "calc_at",
)
_HISTORY_HEADERS = {
    "id": "編號",
    "period_code": "期別",
    "last_payment_date": "最後繳款日",
    "actual_payment_date": "實際繳款日",
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
        self._calculating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        root.addWidget(self._scroll)

        self._scroll_body = QWidget()
        outer = QVBoxLayout(self._scroll_body)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)
        self._scroll.setWidget(self._scroll_body)

        title = QLabel("滯納金試算")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self._manual_check = QCheckBox("手動試算模式（不連結案件，結果不儲存）")
        outer.addWidget(self._manual_check)

        # -- Filter row (hidden in manual mode) --
        self._filter_widget = QWidget()
        filter_row = QHBoxLayout(self._filter_widget)
        filter_row.setContentsMargins(0, 0, 0, 0)
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
        outer.addWidget(self._filter_widget)

        # -- Input form --
        form_box = QGroupBox("試算參數")
        self._form_layout = QGridLayout(form_box)
        self._form_layout.setHorizontalSpacing(16)
        self._form_layout.setVerticalSpacing(10)
        self._form_layout.setColumnStretch(1, 1)
        self._form_layout.setColumnStretch(3, 1)

        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, 2100)
        self._year_spin.setValue(datetime.date.fromisoformat(today_iso()).year)
        self._form_layout.addWidget(QLabel("年份："), 0, 0)
        self._form_layout.addWidget(self._year_spin, 0, 1)

        self._period_combo = QComboBox()
        self._period_combo.addItem("（不指定期別）", "")
        for code in PERIOD_CODES:
            self._period_combo.addItem(f"{code} 月", code)
        self._form_layout.addWidget(QLabel("期別："), 0, 2)
        self._form_layout.addWidget(self._period_combo, 0, 3)

        self._last_payment_date = DateField(required=False)
        self._actual_payment_date = DateField(required=False)
        self._form_layout.addWidget(QLabel("最後繳款日："), 1, 0)
        self._form_layout.addWidget(self._last_payment_date, 1, 1)
        self._form_layout.addWidget(QLabel("實際繳款日："), 1, 2)
        self._form_layout.addWidget(self._actual_payment_date, 1, 3)

        self._unlock_check = QCheckBox("自行輸入最後繳款日（解除期別自動帶入）")
        self._form_layout.addWidget(self._unlock_check, 2, 1, 1, 3)
        self._manual_date_hint = QLabel("")
        self._manual_date_hint.setWordWrap(True)
        self._manual_date_hint.setStyleSheet(f"color: {STATUS_PENDING_FG}; font-size: 12px;")
        self._form_layout.addWidget(self._manual_date_hint, 3, 1, 1, 3)

        self._base_spin = QDoubleSpinBox()
        self._base_spin.setRange(0, 999_999_999)
        self._base_spin.setDecimals(2)
        self._base_spin.setSuffix(" 元")
        self._form_layout.addWidget(QLabel("申報稅額："), 4, 0)
        self._form_layout.addWidget(self._base_spin, 4, 1)

        self._calc_btn = QPushButton("開始試算")
        self._calc_btn.setIcon(toolbar_icon("trial"))
        self._calc_btn.clicked.connect(self._on_calculate)
        self._form_layout.addWidget(self._calc_btn, 4, 3)

        outer.addWidget(form_box)

        # -- Result display --
        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        outer.addWidget(self._result_label)

        # -- Penalty-rate date-range schedule --
        sched_label = QLabel("滯納金率日期區間")
        sched_label.setObjectName("SectionTitle")
        outer.addWidget(sched_label)
        self._schedule_table = QTableWidget(0, 3)
        self._schedule_table.setHorizontalHeaderLabels(["滯納金率", "起始日", "結束日"])
        self._schedule_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._schedule_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._schedule_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._schedule_table.setMinimumHeight(160)
        self._schedule_table.setMaximumHeight(240)
        outer.addWidget(self._schedule_table)
        self._schedule_note = QLabel("")
        self._schedule_note.setWordWrap(True)
        self._schedule_note.setStyleSheet(f"color: {STATUS_PENDING_FG};")
        outer.addWidget(self._schedule_note)

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
        self._table.setMinimumHeight(180)
        outer.addWidget(self._table)

        self._manual_check.toggled.connect(self._on_mode_changed)
        self._eng_combo.currentIndexChanged.connect(self._on_engagement_changed)
        self._req_combo.currentIndexChanged.connect(self._load_history)
        self._year_spin.valueChanged.connect(self._on_period_inputs_changed)
        self._period_combo.currentIndexChanged.connect(self._on_period_inputs_changed)
        self._unlock_check.toggled.connect(self._on_unlock_toggled)
        self._last_payment_date.value_changed.connect(self._refresh_schedule_display)
        self._actual_payment_date.value_changed.connect(self._refresh_schedule_display)
        self._load_engagements()
        self._apply_period_lock()

    def _on_mode_changed(self, manual: bool) -> None:
        self._filter_widget.setVisible(not manual)
        self._result_label.setText("")
        if manual:
            self._table.setRowCount(0)
        else:
            self._load_history()

    def refresh_context(self) -> None:
        """Reload engagement/request choices when the page becomes active."""
        self._load_engagements()

    def _load_engagements(self) -> None:
        selected_id = self._eng_combo.currentData()
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("（請選擇案件）", _ALL)
        try:
            for eng in self._container.engagements.list_all():
                self._eng_combo.addItem(eng.engagement_name, eng.id)
        except Exception as err:
            self._container.system_log.warn(
                "late_fee_page: failed to load engagements",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            self._eng_combo.addItem("（載入案件失敗，請重新整理）", _ALL)
        if selected_id is not None:
            for i in range(self._eng_combo.count()):
                if self._eng_combo.itemData(i) == selected_id:
                    self._eng_combo.setCurrentIndex(i)
                    break
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
            except Exception as err:
                self._container.system_log.warn(
                    "late_fee_page: failed to load requests",
                    detail={"eng_id": eng_id, "exc": type(err).__name__, "msg": str(err)},
                )
                self._req_combo.addItem("（載入批次失敗，請重新整理）", _ALL)
        self._req_combo.blockSignals(False)
        self._load_history()

    def _load_history(self) -> None:
        req_id = self._req_combo.currentData()
        self._history = []
        if req_id and req_id != _ALL:
            try:
                self._history = self._container.late_fee.list_by_request(req_id)
            except Exception as err:
                self._container.system_log.warn(
                    "late_fee_page: failed to load history",
                    detail={"req_id": req_id, "exc": type(err).__name__, "msg": str(err)},
                )
                self._result_label.setText("試算記錄載入失敗，請重新整理頁面")
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(0)
        for row, rec in enumerate(self._history):
            self._table.insertRow(row)
            vals = {
                "id": str(rec.id),
                "period_code": rec.period_code or "",
                "last_payment_date": rec.last_payment_date or "",
                "actual_payment_date": rec.actual_payment_date or "",
                "overdue_days": str(rec.overdue_days),
                "penalty_percent": f"{rec.penalty_percent:.1f}%",
                "base_amount": f"{rec.base_amount:,.2f}",
                "penalty_amount": f"{rec.penalty_amount:,.2f}",
                "calc_at": rec.calc_at,
            }
            for col, key in enumerate(_HISTORY_COLUMNS):
                self._table.setItem(row, col, QTableWidgetItem(vals[key]))

    # ------------------------------------------------------------------
    # Period half-lock + penalty-rate schedule
    # ------------------------------------------------------------------

    def _compute_period_last_payment(self) -> str | None:
        code = self._period_combo.currentData()
        if not code:
            return None
        try:
            return last_payment_date_for_period(self._year_spin.value(), code)
        except LateFeeValidationError:
            return None

    def _on_period_inputs_changed(self, *_args) -> None:
        self._apply_period_lock()

    def _on_unlock_toggled(self, *_args) -> None:
        self._apply_period_lock()

    def _apply_period_lock(self) -> None:
        """Half-lock: period auto-fills 最後繳款日 unless the user unlocks it."""
        has_period = bool(self._period_combo.currentData())
        self._unlock_check.setEnabled(has_period)
        locked = has_period and not self._unlock_check.isChecked()
        self._last_payment_date.setEnabled(not locked)
        if locked:
            iso = self._compute_period_last_payment()
            if iso:
                self._last_payment_date.set_value(iso)
            self._manual_date_hint.setText(
                "最後繳款日已依期別自動帶入；勾選「自行輸入最後繳款日」可手動調整。"
            )
        elif has_period and self._unlock_check.isChecked():
            self._manual_date_hint.setText("已手動調整最後繳款日。")
        else:
            self._manual_date_hint.setText("")
        self._refresh_schedule_display()

    def _refresh_schedule_display(self, *_args) -> None:
        self._schedule_table.setRowCount(0)
        self._schedule_note.setText("")
        last = self._last_payment_date.value()
        if not last:
            return
        try:
            bands = build_penalty_schedule(last)
        except LateFeeValidationError:
            return
        overdue: int | None = None
        actual = self._actual_payment_date.value()
        if actual:
            try:
                overdue = calculate_overdue_days(last, actual)
            except LateFeeValidationError:
                overdue = None
        hit_percent = (
            calculate_penalty_percent(overdue)
            if overdue is not None and overdue >= 1
            else None
        )
        self._schedule_table.setRowCount(len(bands))
        for row, band in enumerate(bands):
            end = band["end_date"] or "（之後）"
            for col, text in enumerate((f"{band['percent']}%", band["start_date"], end)):
                cell = QTableWidgetItem(text)
                if hit_percent is not None and float(band["percent"]) == hit_percent:
                    cell.setBackground(QColor(STATUS_PENDING_BG))
                self._schedule_table.setItem(row, col, cell)
        if overdue is not None and overdue > 30:
            self._schedule_note.setText(
                "[!] 已逾 30 日，可能涉及滯納利息／移送執行；本工具目前僅計算滯納金，需人工確認。"
            )

    def _on_calculate(self) -> None:
        if self._calculating:
            return
        self._calculating = True
        self._calc_btn.setEnabled(False)
        try:
            self._calculate()
        finally:
            self._calculating = False
            self._calc_btn.setEnabled(True)

    def _calculate(self) -> None:
        try:
            last_payment_date = self._last_payment_date.validated_value()
            actual_payment_date = self._actual_payment_date.validated_value()
        except DateField.InvalidInput:
            return
        if last_payment_date is None or actual_payment_date is None:
            QMessageBox.warning(self, "提示", "請輸入最後繳款日與實際繳款日")
            return
        base_amount = self._base_spin.value()

        if self._manual_check.isChecked():
            try:
                overdue_days = calculate_overdue_days(last_payment_date, actual_payment_date)
                penalty_percent = calculate_penalty_percent(overdue_days)
            except LateFeeValidationError as err:
                QMessageBox.critical(self, "試算失敗", error_message(err.code))
                return
            penalty_amount = round(base_amount * penalty_percent / 100, 2)
            self._result_label.setText(
                f"試算結果（未儲存）：滯納金率 {penalty_percent:.1f}%，"
                f"滯納金 {penalty_amount:,.2f} 元"
                f"（稅額 {base_amount:,.2f} 元，逾期 {overdue_days} 天）"
            )
            return

        req_id = self._req_combo.currentData()
        if not req_id or req_id == _ALL:
            QMessageBox.warning(self, "提示", "請先選擇索件批次，或切換為手動試算模式")
            return

        period_code = self._period_combo.currentData() or None
        period_year = self._year_spin.value() if period_code else None
        try:
            row = self._container.late_fee.calculate_and_save(
                CalculateLateFeeInput(
                    request_id=req_id,
                    overdue_days=0,
                    base_amount=base_amount,
                    last_payment_date=last_payment_date,
                    actual_payment_date=actual_payment_date,
                    period_year=period_year,
                    period_code=period_code,
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
                "[!] 勞健保稅種需人工確認，無法自動計算滯納金。請聯絡主管確認滯納金金額。"
            )
        else:
            self._result_label.setText(
                f"試算結果：滯納金率 {row.penalty_percent:.1f}%，"
                f"滯納金 {row.penalty_amount:,.2f} 元"
                f"（稅額 {row.base_amount:,.2f} 元，逾期 {row.overdue_days} 天）"
            )
        self._load_history()
