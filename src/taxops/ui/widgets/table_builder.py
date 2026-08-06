"""Helpers for the common read-only table pattern used by list pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget

from .. import tokens


def build_standard_table(
    columns: Sequence[str],
    headers: Mapping[str, str],
    *,
    stretch_col: str | None = None,
    fixed_cols: Mapping[str, int] | None = None,
    selection_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    alternating: bool = True,
    row_height: int = tokens.ROW_HEIGHT_TEXT,
) -> QTableWidget:
    """Create the default non-editable row-selection table.

    `row_height` defaults to the text-row token. Tables that host editors must pass
    `tokens.ROW_HEIGHT_EDITOR`, otherwise the editor's own height clips inside the
    row — the defect seen when creating annual work.
    """

    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([headers[c] for c in columns])
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection_mode)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(alternating)
    # Row height and eliding are set here so every list page inherits them instead
    # of patching a single page when text turns out to clip.
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setMinimumSectionSize(row_height)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setWordWrap(False)

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
