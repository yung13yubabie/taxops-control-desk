"""Late-fee trial page: compute a penalty, then record it against a document request.

Reading order follows the task: choose where the filing data comes from, see the
statutory deadline, enter the real payment date and the tax amount, read the penalty,
and only then inspect the rate bands behind it.

Three defects this replaces. The primary action sat in the same grid as the date
fields, so the date popup covered the button that consumed those dates. The
eleven-row rate-band table was always the largest thing on screen, calculation or
not. And the answer — an amount someone is about to pay — was a run-on sentence.

The statutory arithmetic stays in `services.late_fee`; this module formats what it
returns.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QRadioButton,
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
from .. import tokens
from ..widgets.buttons import make_button
from ..widgets.date_field import DateField
from ..widgets.empty_state import EmptyState
from ..widgets.page_shell import ActionBar, PageHeader
from ...services.late_fee import (
    PERIOD_CODES,
    CalculateLateFeeInput,
    LateFeeValidationError,
    build_penalty_schedule,
    calculate_overdue_days,
    calculate_penalty_percent,
    last_payment_date_for_period,
)

# ── Trial history table ─────────────────────────────────────────────
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
    "last_payment_date": "法定期限",
    "actual_payment_date": "實際繳款日",
    "overdue_days": "逾期天數",
    "penalty_percent": "滯納金率",
    "base_amount": "申報稅額",
    "penalty_amount": "滯納金",
    "calc_at": "試算時間",
}
# Numbers align on their right edge so digits line up down the column.
_HISTORY_NUMERIC_COLUMNS = frozenset(
    {"overdue_days", "penalty_percent", "base_amount", "penalty_amount"}
)

# ── Rate-band breakdown table ───────────────────────────────────────
SCHEDULE_HEADERS: tuple[str, ...] = (
    "起始日",
    "結束日",
    "逾期天數",
    "適用滯納金率",
    "滯納金",
)
RATE_COLUMN = 3
_SCHEDULE_NUMERIC_FROM = 2

_ALL = -1
_CURRENCY_UNIT = "NT$"
# A present answer for a value that has none yet, per the spec's loud rule.
_NO_VALUE = "—"
_NEEDS_REVIEW = "需人工確認"

_HISTORY_EMPTY_NO_BATCH = "先選擇案件與索件批次，才能查看該批次的試算記錄。"
_HISTORY_EMPTY_NO_RECORDS = "選擇索件批次並按下「開始試算」後，每次試算都會留下一筆記錄。"


def _money(value: float) -> str:
    """Thousands separators always; cents only when the amount has them."""
    if abs(value - round(value)) < 0.005:
        return f"{_CURRENCY_UNIT} {value:,.0f}"
    return f"{_CURRENCY_UNIT} {value:,.2f}"


def _percent(value: float) -> str:
    """1.0 reads as 1%, not 1.0% — there is nothing behind the decimal point."""
    return f"{value:g}%"


def _days(value: int) -> str:
    return f"{value} 天"


def _band_day_range(band: dict) -> str:
    """Which overdue days a rate band covers.

    `build_penalty_schedule` emits ten three-day bands plus one open-ended band,
    so those are the only two shapes.
    """
    start_day = band["start_day"]
    if band["end_day"] is None:
        return f"第 {start_day} 日起"
    return f"第 {start_day}–{band['end_day']} 日"


def _fit_to_contents(table: QTableWidget) -> None:
    """Size a table to its rows so the page owns the only scrollbar.

    Both tables used to scroll inside a page that also scrolled — the double-scroll
    defect recorded against this file.
    """
    height = table.horizontalHeader().sizeHint().height() + 2 * table.frameWidth()
    height += sum(table.rowHeight(row) for row in range(table.rowCount()))
    table.setFixedHeight(height)


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
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(self._scroll)

        self._scroll_body = QWidget()
        body = QVBoxLayout(self._scroll_body)
        body.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        body.setSpacing(tokens.SPACING_LG)
        self._scroll.setWidget(self._scroll_body)

        self._header = PageHeader("滯納金試算")
        body.addWidget(self._header)

        body.addWidget(self._build_action_bar())
        body.addWidget(self._build_case_selectors())
        body.addWidget(self._build_form())
        body.addLayout(self._build_action_row())
        body.addWidget(self._build_result_block())
        body.addWidget(self._build_schedule_block())
        body.addWidget(self._build_history_block())
        body.addStretch(1)

        self._source_manual_radio.toggled.connect(self._on_mode_changed)
        self._eng_combo.currentIndexChanged.connect(self._on_engagement_changed)
        self._req_combo.currentIndexChanged.connect(self._load_history)
        self._year_spin.valueChanged.connect(self._on_period_inputs_changed)
        self._period_combo.currentIndexChanged.connect(self._on_period_inputs_changed)
        self._unlock_check.toggled.connect(self._on_unlock_toggled)
        self._last_payment_date.value_changed.connect(self._on_trial_input_changed)
        self._actual_payment_date.value_changed.connect(self._on_trial_input_changed)
        self._base_spin.valueChanged.connect(self._on_trial_input_changed)
        self._schedule_toggle.toggled.connect(self._on_schedule_toggled)
        self._reset_btn.clicked.connect(self._on_reset)
        self._calc_btn.clicked.connect(self._on_calculate)

        self._load_engagements()
        self._apply_period_lock()
        self._clear_result()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_action_bar(self) -> ActionBar:
        """Data source plus its consequence, and the one view tool this page has."""
        self._action_bar = ActionBar()

        source_widget = QWidget()
        row = QHBoxLayout(source_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACING_MD)

        caption = QLabel("資料來源")
        caption.setObjectName("HintText")
        row.addWidget(caption)

        self._source_case_radio = QRadioButton("從案件帶入")
        self._source_manual_radio = QRadioButton("手動輸入")
        self._source_case_radio.setChecked(True)
        self._source_group = QButtonGroup(self)
        self._source_group.setExclusive(True)
        self._source_group.addButton(self._source_case_radio)
        self._source_group.addButton(self._source_manual_radio)
        row.addWidget(self._source_case_radio)
        row.addWidget(self._source_manual_radio)

        # Surviving name for the manual choice: existing tests drive the mode
        # through `_manual_check`, and that path now clicks the real radio.
        self._manual_check = self._source_manual_radio

        # The caveat belongs where the choice is made, not in the result.
        self._source_note = QLabel("手動輸入的結果不會儲存，也不會寫入試算記錄。")
        self._source_note.setObjectName("HintText")
        self._source_note.setWordWrap(True)
        row.addWidget(self._source_note, 1)

        self._action_bar.add_leading_widget(source_widget, stretch=1)
        self._refresh_btn = self._action_bar.add_tool_icon(
            "refresh",
            tooltip="重新載入案件與索件批次",
            accessible_name="重新載入案件與索件批次",
        )
        self._refresh_btn.clicked.connect(self.refresh_context)
        return self._action_bar

    def _build_case_selectors(self) -> QWidget:
        """Visible only when the filing data comes from a case."""
        self._filter_widget = QWidget()
        row = QHBoxLayout(self._filter_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACING_SM)

        row.addWidget(QLabel("案件"))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(220)
        row.addWidget(self._eng_combo)

        row.addWidget(QLabel("索件批次"))
        self._req_combo = QComboBox()
        self._req_combo.setMinimumWidth(220)
        row.addWidget(self._req_combo)
        row.addStretch(1)
        return self._filter_widget

    def _build_form(self) -> QWidget:
        form = QWidget()
        self._form_layout = QGridLayout(form)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setHorizontalSpacing(tokens.SPACING_MD)
        self._form_layout.setVerticalSpacing(tokens.SPACING_MD)
        # Column 4 absorbs the slack so fields keep a readable width instead of
        # stretching across the page.
        self._form_layout.setColumnStretch(4, 1)

        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, 2100)
        self._year_spin.setValue(datetime.date.fromisoformat(today_iso()).year)
        self._year_spin.setMaximumWidth(140)
        self._year_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._form_layout.addWidget(QLabel("年份"), 0, 0)
        self._form_layout.addWidget(self._year_spin, 0, 1)

        self._period_combo = QComboBox()
        self._period_combo.addItem("（不指定期別）", "")
        for code in PERIOD_CODES:
            self._period_combo.addItem(f"{code} 月", code)
        self._period_combo.setMaximumWidth(220)
        self._form_layout.addWidget(QLabel("期別"), 0, 2)
        self._form_layout.addWidget(self._period_combo, 0, 3)

        self._last_payment_date = DateField(required=False)
        self._form_layout.addWidget(QLabel("法定期限"), 1, 0)
        self._form_layout.addWidget(self._last_payment_date, 1, 1)

        self._unlock_check = QCheckBox("自行輸入法定期限")
        self._form_layout.addWidget(self._unlock_check, 1, 2, 1, 2)

        self._manual_date_hint = QLabel("")
        self._manual_date_hint.setObjectName("HintText")
        self._manual_date_hint.setWordWrap(True)
        self._form_layout.addWidget(self._manual_date_hint, 2, 1, 1, 3)

        self._actual_payment_date = DateField(required=False)
        self._form_layout.addWidget(QLabel("實際繳款日"), 3, 0)
        self._form_layout.addWidget(self._actual_payment_date, 3, 1)

        amount_row = QHBoxLayout()
        amount_row.setContentsMargins(0, 0, 0, 0)
        amount_row.setSpacing(tokens.SPACING_SM)
        # The unit is a label, not part of the editable text: a suffix inside the
        # editor makes the user type and delete around it.
        self._amount_unit_label = QLabel(_CURRENCY_UNIT)
        self._amount_unit_label.setObjectName("HintText")
        amount_row.addWidget(self._amount_unit_label)
        self._base_spin = QDoubleSpinBox()
        self._base_spin.setRange(0, 999_999_999)
        self._base_spin.setDecimals(2)
        self._base_spin.setGroupSeparatorShown(True)
        self._base_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._base_spin.setMaximumWidth(220)
        amount_row.addWidget(self._base_spin)
        amount_row.addStretch(1)
        self._form_layout.addWidget(QLabel("申報稅額"), 4, 0)
        self._form_layout.addLayout(amount_row, 4, 1, 1, 3)
        return form

    def _build_action_row(self) -> QHBoxLayout:
        """The trial action sits under the form it reads, right-aligned.

        Keeping it out of `_form_layout` is what stops the date popup — which drops
        below its own field, on the left — from landing on it.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACING_SM)
        row.addStretch(1)

        self._reset_btn = make_button(
            "清除",
            role=tokens.ROLE_SECONDARY,
            icon_role="clear",
            tooltip="清除試算欄位與結果",
        )
        row.addWidget(self._reset_btn)

        self._calc_btn = make_button(
            "開始試算", role=tokens.ROLE_PRIMARY, icon_role="trial"
        )
        row.addWidget(self._calc_btn)
        return row

    def _build_result_block(self) -> QWidget:
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(tokens.SPACING_SM)

        heading = QLabel("試算結果")
        heading.setObjectName("SectionTitle")
        column.addWidget(heading)

        self._result_card = QFrame()
        self._result_card.setObjectName("ContentSurface")
        self._result_card.setMaximumWidth(480)
        grid = QGridLayout(self._result_card)
        grid.setContentsMargins(
            tokens.SPACING_LG, tokens.SPACING_MD, tokens.SPACING_LG, tokens.SPACING_MD
        )
        grid.setHorizontalSpacing(tokens.SPACING_LG)
        grid.setVerticalSpacing(tokens.SPACING_SM)
        grid.setColumnStretch(1, 1)

        self._result_days_value = self._add_result_row(grid, 0, "逾期天數")
        self._result_rate_value = self._add_result_row(grid, 1, "滯納金率")
        # The two amounts are why the page exists, so they carry the largest type.
        self._result_penalty_value = self._add_result_row(
            grid, 2, "滯納金", emphasis=True
        )
        self._result_total_value = self._add_result_row(
            grid, 3, "應繳總額", emphasis=True
        )
        column.addWidget(self._result_card)

        self._result_label = QLabel("")
        self._result_label.setObjectName("HintText")
        self._result_label.setWordWrap(True)
        column.addWidget(self._result_label)
        return widget

    def _add_result_row(
        self, grid: QGridLayout, row: int, label_text: str, *, emphasis: bool = False
    ) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("HintText")
        grid.addWidget(label, row, 0)

        value = QLabel(_NO_VALUE)
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        font = QFont(value.font())
        if emphasis:
            font.setPixelSize(tokens.FONT_SECTION_TITLE + 2)
            font.setBold(True)
        else:
            font.setPixelSize(tokens.FONT_BODY)
        value.setFont(font)
        grid.addWidget(value, row, 1)
        return value

    def _build_schedule_block(self) -> QWidget:
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(tokens.SPACING_SM)

        self._schedule_toggle = make_button(
            "計算區間明細 ▸",
            role=tokens.ROLE_QUIET,
            tooltip="展開各滯納金率適用的日期區間",
        )
        self._schedule_toggle.setCheckable(True)
        column.addWidget(self._schedule_toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        self._schedule_body = QWidget()
        inner = QVBoxLayout(self._schedule_body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(tokens.SPACING_SM)

        self._schedule_table = self._make_table(SCHEDULE_HEADERS)
        self._schedule_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        inner.addWidget(self._schedule_table)

        self._schedule_note = QLabel("")
        self._schedule_note.setObjectName("HintText")
        self._schedule_note.setWordWrap(True)
        inner.addWidget(self._schedule_note)

        self._schedule_body.setVisible(False)
        column.addWidget(self._schedule_body)
        return widget

    def _build_history_block(self) -> QWidget:
        self._history_block = QWidget()
        column = QVBoxLayout(self._history_block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(tokens.SPACING_SM)

        heading = QLabel("試算記錄")
        heading.setObjectName("SectionTitle")
        column.addWidget(heading)

        # No next step to offer: a record appears as a by-product of a trial.
        self._history_empty = EmptyState(
            "尚無試算記錄", detail=_HISTORY_EMPTY_NO_RECORDS
        )
        column.addWidget(self._history_empty)

        self._table = self._make_table(
            tuple(_HISTORY_HEADERS[c] for c in _HISTORY_COLUMNS)
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setVisible(False)
        column.addWidget(self._table)
        return self._history_block

    def _make_table(self, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # The page is the only scroll region; see `_fit_to_contents`.
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _fit_to_contents(table)
        return table

    # ------------------------------------------------------------------
    # Mode and context
    # ------------------------------------------------------------------

    def _manual_mode(self) -> bool:
        return self._source_manual_radio.isChecked()

    def _on_mode_changed(self, *_args) -> None:
        """Change the data source without discarding what was typed.

        Only case-scoped affordances and the stale result reset: the usual reason to
        switch is that the case did not carry the numbers, so 法定期限, 實際繳款日
        and 申報稅額 survive.
        """
        manual = self._manual_mode()
        self._filter_widget.setVisible(not manual)
        self._history_block.setVisible(not manual)
        self._result_label.setText("")
        self._clear_result()
        if manual:
            self._history = []
            self._render_table()
        else:
            self._load_history()

    def clear_filter(self) -> None:
        self._eng_combo.setCurrentIndex(0)  # 重置為「請選擇案件」；會觸發 _on_engagement_changed 連帶清空 _req_combo

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
                    detail={
                        "eng_id": eng_id,
                        "exc": type(err).__name__,
                        "msg": str(err),
                    },
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
                    detail={
                        "req_id": req_id,
                        "exc": type(err).__name__,
                        "msg": str(err),
                    },
                )
                self._set_message("試算記錄載入失敗，請重新整理頁面", error=True)
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(0)
        for row, rec in enumerate(self._history):
            self._table.insertRow(row)
            vals = {
                "id": str(rec.id),
                "period_code": rec.period_code or _NO_VALUE,
                "last_payment_date": rec.last_payment_date or _NO_VALUE,
                "actual_payment_date": rec.actual_payment_date or _NO_VALUE,
                "overdue_days": _days(rec.overdue_days),
                "penalty_percent": _percent(rec.penalty_percent),
                "base_amount": _money(rec.base_amount),
                "penalty_amount": _money(rec.penalty_amount),
                "calc_at": rec.calc_at,
            }
            for col, key in enumerate(_HISTORY_COLUMNS):
                cell = QTableWidgetItem(vals[key])
                if key in _HISTORY_NUMERIC_COLUMNS:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, col, cell)
        _fit_to_contents(self._table)
        self._render_history_view()

    def _render_history_view(self) -> None:
        """Table or empty state, never an empty framed grid."""
        has_rows = self._table.rowCount() > 0
        self._table.setVisible(has_rows)
        self._history_empty.setVisible(not has_rows)
        if not has_rows:
            req_id = self._req_combo.currentData()
            has_batch = bool(req_id) and req_id != _ALL
            self._history_empty.detail_label.setText(
                _HISTORY_EMPTY_NO_RECORDS if has_batch else _HISTORY_EMPTY_NO_BATCH
            )
            self._history_empty.detail_label.setVisible(True)

    # ------------------------------------------------------------------
    # Result block
    # ------------------------------------------------------------------

    def _set_message(self, text: str, *, error: bool = False) -> None:
        self._result_label.setText(text)
        self._result_label.setObjectName("ErrorText" if error else "HintText")
        # An object name changed after construction only takes effect on repolish.
        style = self._result_label.style()
        if style is not None:
            style.unpolish(self._result_label)
            style.polish(self._result_label)

    def _result_values(self) -> tuple[QLabel, ...]:
        return (
            self._result_days_value,
            self._result_rate_value,
            self._result_penalty_value,
            self._result_total_value,
        )

    def _clear_result(self) -> None:
        for value in self._result_values():
            value.setText(_NO_VALUE)

    def _show_result(
        self,
        *,
        overdue_days: int,
        penalty_percent: float,
        base_amount: float,
        penalty_amount: float,
    ) -> None:
        self._result_days_value.setText(_days(overdue_days))
        self._result_rate_value.setText(_percent(penalty_percent))
        self._result_penalty_value.setText(_money(penalty_amount))
        self._result_total_value.setText(_money(base_amount + penalty_amount))

    def _on_trial_input_changed(self, *_args) -> None:
        """A changed input retires the result it no longer describes."""
        self._clear_result()
        self._refresh_schedule_display()

    def _on_reset(self) -> None:
        self._actual_payment_date.clear()
        self._base_spin.setValue(0)
        period_locked = bool(self._period_combo.currentData()) and not (
            self._unlock_check.isChecked()
        )
        if not period_locked:
            self._last_payment_date.clear()
        self._result_label.setText("")
        self._clear_result()
        self._refresh_schedule_display()

    # ------------------------------------------------------------------
    # Period half-lock and rate-band breakdown
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
        self._clear_result()
        self._apply_period_lock()

    def _on_unlock_toggled(self, *_args) -> None:
        self._apply_period_lock()

    def _apply_period_lock(self) -> None:
        """Half-lock: the period fills 法定期限 unless the user unlocks it."""
        has_period = bool(self._period_combo.currentData())
        self._unlock_check.setEnabled(has_period)
        locked = has_period and not self._unlock_check.isChecked()
        self._last_payment_date.setEnabled(not locked)
        if locked:
            iso = self._compute_period_last_payment()
            if iso:
                self._last_payment_date.set_value(iso)
            self._manual_date_hint.setText(
                "法定期限已依期別自動帶入；勾選「自行輸入法定期限」可手動調整。"
            )
        elif has_period and self._unlock_check.isChecked():
            self._manual_date_hint.setText("已手動調整法定期限。")
        else:
            self._manual_date_hint.setText("")
        self._refresh_schedule_display()

    def _on_schedule_toggled(self, expanded: bool) -> None:
        self._schedule_toggle.setText(
            "計算區間明細 ▾" if expanded else "計算區間明細 ▸"
        )
        self._sync_schedule_visibility()

    def _refresh_schedule_display(self, *_args) -> None:
        self._schedule_table.setRowCount(0)
        self._schedule_note.setText("")
        last = self._last_payment_date.value()
        if not last:
            self._finish_schedule()
            return
        try:
            bands = build_penalty_schedule(last)
        except LateFeeValidationError:
            self._finish_schedule()
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

        base_amount = self._base_spin.value()
        self._schedule_table.setRowCount(len(bands))
        for row, band in enumerate(bands):
            band_percent = float(band["percent"])
            amount = (
                _money(round(base_amount * band_percent / 100, 2))
                if base_amount > 0
                else _NO_VALUE
            )
            texts = (
                band["start_date"],
                band["end_date"] or "（之後）",
                _band_day_range(band),
                _percent(band_percent),
                amount,
            )
            is_hit = hit_percent is not None and band_percent == hit_percent
            for col, text in enumerate(texts):
                cell = QTableWidgetItem(text)
                if col >= _SCHEDULE_NUMERIC_FROM:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if is_hit:
                    cell.setBackground(QColor(tokens.STATUS_PENDING_BG))
                self._schedule_table.setItem(row, col, cell)

        if overdue is not None and overdue > 30:
            self._schedule_note.setText(
                "[!] 已逾 30 日，可能涉及滯納利息／移送執行；"
                "本工具目前僅計算滯納金，需人工確認。"
            )
        self._finish_schedule()

    def _finish_schedule(self) -> None:
        _fit_to_contents(self._schedule_table)
        self._sync_schedule_visibility()

    def _sync_schedule_visibility(self) -> None:
        """Collapsed by default, and absent entirely when there is nothing to show."""
        has_rows = self._schedule_table.rowCount() > 0
        self._schedule_toggle.setVisible(has_rows)
        self._schedule_body.setVisible(has_rows and self._schedule_toggle.isChecked())

    # ------------------------------------------------------------------
    # Calculation
    # ------------------------------------------------------------------

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
            # The field marks itself; a modal on top of it would say less.
            return
        if last_payment_date is None or actual_payment_date is None:
            QMessageBox.warning(self, "提示", "請輸入法定期限與實際繳款日")
            return
        base_amount = self._base_spin.value()

        if self._manual_mode():
            try:
                overdue_days = calculate_overdue_days(
                    last_payment_date, actual_payment_date
                )
                penalty_percent = calculate_penalty_percent(overdue_days)
            except LateFeeValidationError as err:
                QMessageBox.critical(self, "試算失敗", error_message(err.code))
                return
            self._show_result(
                overdue_days=overdue_days,
                penalty_percent=penalty_percent,
                base_amount=base_amount,
                penalty_amount=round(base_amount * penalty_percent / 100, 2),
            )
            self._set_message("手動試算結果未儲存。")
            return

        req_id = self._req_combo.currentData()
        if not req_id or req_id == _ALL:
            QMessageBox.warning(self, "提示", "請先選擇索件批次，或切換為手動輸入")
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
            QMessageBox.critical(
                self, "試算失敗", error_message("late_fee.calculate.failed")
            )
            return

        if row.needs_manual_review:
            # No number is the honest answer here; the service computed none.
            self._result_days_value.setText(_days(row.overdue_days))
            for value in (
                self._result_rate_value,
                self._result_penalty_value,
                self._result_total_value,
            ):
                value.setText(_NEEDS_REVIEW)
            self._set_message(
                "[!] 勞健保稅種需人工確認，無法自動計算滯納金。"
                "請聯絡主管確認滯納金金額。",
                error=True,
            )
        else:
            self._show_result(
                overdue_days=row.overdue_days,
                penalty_percent=row.penalty_percent,
                base_amount=row.base_amount,
                penalty_amount=row.penalty_amount,
            )
            self._result_label.setText("")
        self._load_history()
