"""Editable annual-work preview table with stable row identities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

from ...core.compliance import WORK_TYPE_LABELS, WORK_TYPE_ORDER
from ...services.compliance_rules import WorkDraft


@dataclass
class _RowWidgets:
    item_key: str
    work_type_code: str
    standard: bool
    selected: QCheckBox
    work_type: QComboBox | None
    title: QLineEdit
    tax_year: QLineEdit
    period_code: QLineEdit
    due_date: QLineEdit


class AnnualPreviewTable(QTableWidget):
    selection_changed = Signal()

    def __init__(self) -> None:
        super().__init__(0, 6)
        self._rows: list[_RowWidgets] = []
        self.setObjectName("AnnualPreviewTable")
        self.setHorizontalHeaderLabels(
            ("選取", "工作類型", "標題", "稅務年度", "期間", "到期日")
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setMinimumHeight(220)
        font = self.font()
        font.setPixelSize(13)
        self.setFont(font)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 58)
        header.resizeSection(1, 160)
        header.resizeSection(2, 260)
        header.resizeSection(3, 90)
        header.resizeSection(4, 125)
        header.resizeSection(5, 115)

    def clear_drafts(self) -> None:
        self._rows.clear()
        self.setRowCount(0)
        self.selection_changed.emit()

    def set_standard_drafts(self, drafts: tuple[WorkDraft, ...]) -> None:
        self.clear_drafts()
        for draft in drafts:
            self._append(draft, standard=True)

    def add_custom_draft(self, operation_year: int) -> str:
        key = f"custom:{uuid.uuid4()}"
        self._append(
            WorkDraft(
                item_key=key,
                operation_year=operation_year,
                work_type=WORK_TYPE_ORDER[0],
                title="",
                tax_year=operation_year,
                period_code=None,
                suggested_due_date=None,
            ),
            standard=False,
        )
        return key

    @staticmethod
    def _line(value: object, max_length: int) -> QLineEdit:
        line = QLineEdit("" if value is None else str(value))
        line.setMaxLength(max_length)
        line.setToolTip(line.text())
        line.textChanged.connect(line.setToolTip)
        return line

    def _append(self, draft: WorkDraft, *, standard: bool) -> None:
        row = self.rowCount()
        self.insertRow(row)
        selected = QCheckBox()
        selected.setChecked(True)
        selected.setToolTip("包含此年度工作")
        selected.stateChanged.connect(lambda _state: self.selection_changed.emit())
        self.setCellWidget(row, 0, selected)

        work_type_combo: QComboBox | None = None
        if standard:
            item = QTableWidgetItem(
                WORK_TYPE_LABELS.get(draft.work_type, "未知工作類型")
            )
            item.setToolTip(item.text())
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 1, item)
        else:
            work_type_combo = QComboBox()
            for work_type in WORK_TYPE_ORDER:
                work_type_combo.addItem(WORK_TYPE_LABELS[work_type], work_type)
            work_type_combo.setCurrentIndex(
                max(0, work_type_combo.findData(draft.work_type))
            )
            work_type_combo.setToolTip(work_type_combo.currentText())
            work_type_combo.currentTextChanged.connect(work_type_combo.setToolTip)
            self.setCellWidget(row, 1, work_type_combo)

        title = self._line(draft.title, 500)
        tax_year = self._line(draft.tax_year, 4)
        period = self._line(draft.period_code, 50)
        due = self._line(draft.suggested_due_date, 10)
        for column, widget in enumerate((title, tax_year, period, due), start=2):
            self.setCellWidget(row, column, widget)
        self._rows.append(
            _RowWidgets(
                item_key=draft.item_key,
                work_type_code=draft.work_type,
                standard=standard,
                selected=selected,
                work_type=work_type_combo,
                title=title,
                tax_year=tax_year,
                period_code=period,
                due_date=due,
            )
        )

    def item_key(self, row: int) -> str:
        return self._rows[row].item_key

    def set_checked(self, row: int, checked: bool) -> None:
        self._rows[row].selected.setChecked(checked)

    def is_checked(self, row: int) -> bool:
        return self._rows[row].selected.isChecked()

    def set_work_type(self, row: int, work_type: str) -> None:
        combo = self._rows[row].work_type
        if combo is None:
            raise ValueError("standard work type is immutable")
        index = combo.findData(work_type)
        if index < 0:
            raise ValueError("work type is not allowlisted")
        combo.setCurrentIndex(index)

    def set_title(self, row: int, value: str) -> None:
        self._rows[row].title.setText(value)

    def set_tax_year(self, row: int, value: int | None) -> None:
        self._rows[row].tax_year.setText("" if value is None else str(value))

    def set_period_code(self, row: int, value: str | None) -> None:
        self._rows[row].period_code.setText(value or "")

    def set_due_date(self, row: int, value: str | None) -> None:
        self._rows[row].due_date.setText(value or "")

    def row_widgets(self, row: int) -> _RowWidgets:
        return self._rows[row]

    def draft_for_row(self, row: int, operation_year: int) -> WorkDraft:
        widgets = self._rows[row]
        raw_year = widgets.tax_year.text().strip()
        work_type = (
            str(widgets.work_type.currentData())
            if widgets.work_type is not None
            else widgets.work_type_code
        )
        return WorkDraft(
            item_key=widgets.item_key,
            operation_year=operation_year,
            work_type=work_type,
            title=widgets.title.text().strip(),
            tax_year=int(raw_year) if raw_year else None,
            period_code=widgets.period_code.text().strip() or None,
            suggested_due_date=widgets.due_date.text().strip() or None,
        )

    def set_payload_enabled(self, enabled: bool) -> None:
        for row in self._rows:
            row.selected.setEnabled(enabled)
            if row.work_type is not None:
                row.work_type.setEnabled(enabled)
            row.title.setEnabled(enabled)
            row.tax_year.setEnabled(enabled)
            row.period_code.setEnabled(enabled)
            row.due_date.setEnabled(enabled)
