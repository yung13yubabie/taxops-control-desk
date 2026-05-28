"""Folder bookmarks page (Slice 24 / v0.15.1)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import NAV_LABELS, error_message
from ...services.container import ServiceContainer
from ...services.folder_bookmarks import (
    CreateBookmarkInput,
    FolderBookmarkValidationError,
    UpdateBookmarkInput,
)
from ..style import toolbar_icon
from ..widgets.flow_layout import FlowLayout

_log = logging.getLogger(__name__)

_COLUMNS = ("id", "name", "path", "category", "updated_at")
_HEADERS = {
    "id": "編號",
    "name": "名稱",
    "path": "路徑",
    "category": "分類",
    "updated_at": "更新時間",
}


class _BookmarkDialog(QDialog):
    """Reusable dialog for new + edit bookmark entries."""

    def __init__(
        self,
        *,
        title: str,
        name: str = "",
        path: str = "",
        category: str = "",
        sort_order: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(540)

        form = QFormLayout(self)
        form.setSpacing(8)
        form.setContentsMargins(20, 16, 20, 16)

        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("例如：工作底稿 2026")
        self._name_edit.setMaxLength(100)
        form.addRow("名稱：", self._name_edit)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(path)
        self._path_edit.setPlaceholderText(
            r"本機路徑或 UNC（例如 C:\Users\… 或 \\server\share\…）"
        )
        path_row.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("瀏覽…")
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        form.addRow("路徑：", path_row)

        self._category_edit = QLineEdit(category)
        self._category_edit.setPlaceholderText("（選填）例如：工作 / 私人 / 共享")
        self._category_edit.setMaxLength(50)
        form.addRow("分類：", self._category_edit)

        hint = QLabel("可貼上完整路徑；UNC 路徑請以 \\\\ 開頭。")
        hint.setStyleSheet("color: #64748B; font-size: 12px;")
        form.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._sort_order = sort_order

    def _on_browse(self) -> None:
        start = self._path_edit.text().strip() or ""
        chosen = QFileDialog.getExistingDirectory(self, "選擇資料夾", start)
        if chosen:
            self._path_edit.setText(chosen)

    def values(self) -> tuple[str, str, str, int]:
        return (
            self._name_edit.text(),
            self._path_edit.text(),
            self._category_edit.text(),
            self._sort_order,
        )


class FolderBookmarksPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel(NAV_LABELS["folder_bookmarks"])
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        outer.addWidget(title)

        hint = QLabel(
            "管理常用本機資料夾或內網路徑（UNC）的快捷書籤。雙擊或選取後按「開啟資料夾」即可開啟。"
        )
        hint.setStyleSheet("color: #64748B; font-size: 13px;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        self._new_btn = QPushButton("新增資料夾")
        self._edit_btn = QPushButton("編輯資料夾")
        self._delete_btn = QPushButton("刪除資料夾")
        self._open_btn = QPushButton("開啟資料夾")
        self._refresh_btn = QPushButton("重新整理")
        self._new_btn.setIcon(toolbar_icon("new"))
        self._edit_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._open_btn.setIcon(toolbar_icon("export"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        self._edit_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._open_btn.setEnabled(False)
        for btn in (
            self._new_btn,
            self._edit_btn,
            self._delete_btn,
            self._open_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        outer.addWidget(toolbar_widget)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([_HEADERS[c] for c in _COLUMNS])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(
            _COLUMNS.index("path"), QHeaderView.ResizeMode.Stretch
        )
        outer.addWidget(self._table, stretch=1)

        self._new_btn.clicked.connect(self._on_new)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn.clicked.connect(self._on_delete)
        self._open_btn.clicked.connect(self._on_open)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_open)

        self._refresh()

    def refresh_context(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            bookmarks = self._container.folder_bookmarks.list_bookmarks()
        except Exception as err:
            self._container.system_log.error(
                "folder_bookmarks.list failed", exc=err
            )
            QMessageBox.warning(self, "載入失敗", error_message("system.unexpected"))
            return
        self._table.setRowCount(len(bookmarks))
        for row_idx, bm in enumerate(bookmarks):
            values = {
                "id": str(bm.id),
                "name": bm.name,
                "path": bm.path,
                "category": bm.category or "",
                "updated_at": bm.updated_at,
            }
            for col_idx, col in enumerate(_COLUMNS):
                item = QTableWidgetItem(values[col])
                item.setToolTip(values[col])
                self._table.setItem(row_idx, col_idx, item)
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._edit_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._open_btn.setEnabled(has_sel)

    def _selected_id(self) -> int | None:
        items = self._table.selectedItems()
        if not items:
            return None
        row = self._table.row(items[0])
        id_item = self._table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _on_new(self) -> None:
        dialog = _BookmarkDialog(title="新增資料夾", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, path, category, sort_order = dialog.values()
        try:
            self._container.folder_bookmarks.create_bookmark(
                CreateBookmarkInput(
                    name=name, path=path, category=category or None,
                    sort_order=sort_order,
                )
            )
        except FolderBookmarkValidationError as exc:
            QMessageBox.warning(self, "新增失敗", error_message(exc.code))
            return
        except Exception:
            _log.exception("folder_bookmark create failed")
            QMessageBox.warning(self, "新增失敗", error_message("system.unexpected"))
            return
        self._refresh()

    def _on_edit(self, *_args) -> None:
        bookmark_id = self._selected_id()
        if bookmark_id is None:
            return
        bm = self._container.folder_bookmarks.get_bookmark(bookmark_id)
        if bm is None:
            QMessageBox.warning(self, "找不到資料夾", error_message("folder_bookmark.not_found"))
            self._refresh()
            return
        dialog = _BookmarkDialog(
            title="編輯資料夾",
            name=bm.name,
            path=bm.path,
            category=bm.category or "",
            sort_order=bm.sort_order,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, path, category, sort_order = dialog.values()
        try:
            self._container.folder_bookmarks.update_bookmark(
                UpdateBookmarkInput(
                    bookmark_id=bookmark_id, name=name, path=path,
                    category=category or None, sort_order=sort_order,
                )
            )
        except FolderBookmarkValidationError as exc:
            QMessageBox.warning(self, "更新失敗", error_message(exc.code))
            return
        except Exception:
            _log.exception("folder_bookmark update failed")
            QMessageBox.warning(self, "更新失敗", error_message("system.unexpected"))
            return
        self._refresh()

    def _on_delete(self) -> None:
        bookmark_id = self._selected_id()
        if bookmark_id is None:
            return
        bm = self._container.folder_bookmarks.get_bookmark(bookmark_id)
        if bm is None:
            self._refresh()
            return
        reply = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除資料夾書籤「{bm.name}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.folder_bookmarks.delete_bookmark(bookmark_id)
        except FolderBookmarkValidationError as exc:
            QMessageBox.warning(self, "刪除失敗", error_message(exc.code))
            return
        except Exception:
            _log.exception("folder_bookmark delete failed")
            QMessageBox.warning(self, "刪除失敗", error_message("system.unexpected"))
            return
        self._refresh()

    def _on_open(self, *_args) -> None:
        bookmark_id = self._selected_id()
        if bookmark_id is None:
            return
        bm = self._container.folder_bookmarks.get_bookmark(bookmark_id)
        if bm is None:
            return
        url = QUrl.fromLocalFile(bm.path)
        opened = QDesktopServices.openUrl(url)
        if not opened:
            QMessageBox.warning(self, "開啟失敗", error_message("folder_bookmark.open.failed"))
