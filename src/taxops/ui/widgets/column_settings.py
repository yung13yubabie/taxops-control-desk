"""ColumnSettings: right-click header menu + persistence for QTableWidget.

Slice 21C addresses the historical SLOP in our table headers:
1. There was no way to hide columns the user doesn't care about.
2. Resized widths reset on every app restart.
3. The drag handles for resizing are tiny and easy to miss.

ColumnSettings installs a right-click context menu on the header showing a
checkbox per column (core columns are disabled — they always show), plus a
「自動調整所有欄寬」 and 「重設預設」 actions. Hidden columns and resized
widths persist to ``app_settings`` per table_id so they survive restarts.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QTableWidget

_log = logging.getLogger(__name__)


class ColumnSettings:
    def __init__(
        self,
        table: QTableWidget,
        table_id: str,
        all_cols: tuple[str, ...],
        core_cols: frozenset[str],
        headers: dict[str, str],
        settings,
    ) -> None:
        self._table = table
        self._table_id = table_id
        self._all_cols = all_cols
        self._core_cols = core_cols
        self._headers = headers
        self._settings = settings
        self._suspend_save = False

    @property
    def hidden_key(self) -> str:
        return f"ui.{self._table_id}.columns_hidden"

    @property
    def widths_key(self) -> str:
        return f"ui.{self._table_id}.column_widths"

    def install(self) -> None:
        header = self._table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_menu)
        header.sectionResized.connect(self._on_section_resized)
        self._restore()

    def _restore(self) -> None:
        self._suspend_save = True
        try:
            self._restore_hidden()
            self._restore_widths()
        finally:
            self._suspend_save = False

    def _restore_hidden(self) -> None:
        raw = self._settings.get(self.hidden_key) or ""
        hidden = {col for col in raw.split(",") if col}
        for col_idx, col_key in enumerate(self._all_cols):
            if col_key in self._core_cols:
                self._table.setColumnHidden(col_idx, False)
                continue
            self._table.setColumnHidden(col_idx, col_key in hidden)

    def _restore_widths(self) -> None:
        raw = self._settings.get(self.widths_key) or ""
        if not raw:
            return
        try:
            widths = json.loads(raw)
            if not isinstance(widths, dict):
                return
        except (ValueError, TypeError):
            _log.warning(
                "column_settings: invalid widths JSON for %s", self._table_id
            )
            return
        for col_idx, col_key in enumerate(self._all_cols):
            if col_key not in widths:
                continue
            try:
                px = int(widths[col_key])
            except (ValueError, TypeError):
                continue
            if px > 0:
                self._table.setColumnWidth(col_idx, px)

    def _save_hidden(self) -> None:
        if self._suspend_save:
            return
        hidden = [
            col_key
            for col_idx, col_key in enumerate(self._all_cols)
            if self._table.isColumnHidden(col_idx) and col_key not in self._core_cols
        ]
        try:
            self._settings.set_setting(self.hidden_key, ",".join(hidden))
        except Exception:
            _log.warning(
                "column_settings: failed to persist hidden cols for %s",
                self._table_id,
                exc_info=True,
            )

    def _save_widths(self) -> None:
        if self._suspend_save:
            return
        widths: dict[str, int] = {}
        for col_idx, col_key in enumerate(self._all_cols):
            if self._table.isColumnHidden(col_idx):
                continue
            px = int(self._table.columnWidth(col_idx))
            if px > 0:
                widths[col_key] = px
        data = json.dumps(widths, ensure_ascii=False)
        if len(data) > 480:
            _log.warning(
                "column_settings: widths JSON too long for %s (%d chars), skipping",
                self._table_id,
                len(data),
            )
            return
        try:
            self._settings.set_setting(self.widths_key, data)
        except Exception:
            _log.warning(
                "column_settings: failed to persist widths for %s",
                self._table_id,
                exc_info=True,
            )

    def _on_section_resized(self, _idx: int, _old: int, _new: int) -> None:
        self._save_widths()

    def _show_menu(self, pos) -> None:
        menu = QMenu(self._table)
        for col_idx, col_key in enumerate(self._all_cols):
            label = self._headers.get(col_key, col_key)
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col_idx))
            if col_key in self._core_cols:
                action.setEnabled(False)
                action.setToolTip("此欄為必要欄位，不可隱藏")
            action.toggled.connect(
                lambda checked, idx=col_idx: self._on_toggle_col(idx, checked)
            )
            menu.addAction(action)
        menu.addSeparator()
        auto_action = QAction("自動調整所有欄寬", menu)
        auto_action.triggered.connect(self._on_auto_resize_all)
        menu.addAction(auto_action)
        reset_action = QAction("重設預設", menu)
        reset_action.triggered.connect(self._on_reset)
        menu.addAction(reset_action)
        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    def _on_toggle_col(self, col_idx: int, visible: bool) -> None:
        self._table.setColumnHidden(col_idx, not visible)
        self._save_hidden()
        self._save_widths()

    def _on_auto_resize_all(self) -> None:
        for i in range(self._table.columnCount()):
            self._table.resizeColumnToContents(i)
        self._save_widths()

    def _on_reset(self) -> None:
        self._suspend_save = True
        try:
            for col_idx in range(self._table.columnCount()):
                self._table.setColumnHidden(col_idx, False)
                self._table.resizeColumnToContents(col_idx)
        finally:
            self._suspend_save = False
        try:
            self._settings.set_setting(self.hidden_key, "")
            self._settings.set_setting(self.widths_key, "")
        except Exception:
            _log.warning(
                "column_settings: failed to clear presets for %s",
                self._table_id,
                exc_info=True,
            )
