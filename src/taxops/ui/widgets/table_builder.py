"""Helpers for the common read-only table pattern used by list pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import QHeaderView, QTableWidget


def build_standard_table(
    columns: Sequence[str],
    headers: Mapping[str, str],
    *,
    stretch_col: str | None = None,
    fixed_cols: Mapping[str, int] | None = None,
    selection_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    alternating: bool = True,
) -> QTableWidget:
    """Create the default non-editable row-selection table."""

    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([headers[c] for c in columns])
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection_mode)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(alternating)

    header = table.horizontalHeader()
    if stretch_col is not None:
        header.setSectionResizeMode(
            columns.index(stretch_col),
            QHeaderView.ResizeMode.Stretch,
        )
    for col, width in (fixed_cols or {}).items():
        col_idx = columns.index(col)
        header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(col_idx, width)
    return table
