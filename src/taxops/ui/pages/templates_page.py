"""Message templates page: list, preview, and CRUD actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...i18n.status_labels import TEMPLATE_TYPE_LABELS
from ...services.container import ServiceContainer
from ...services.templates import TemplateValidationError
from ..dialogs.template_form_dialog import TemplateFormDialog

_COLUMN_ORDER = ("id", "name", "template_type", "is_builtin", "updated_at")

_TABLE_HEADERS = {
    "id": "編號",
    "name": "名稱",
    "template_type": "類型",
    "is_builtin": "內建",
    "updated_at": "更新時間",
}


class TemplatesPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._body_cache: dict[int, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title_label = QLabel("訊息模板")
        title_label.setObjectName("PageTitle")
        outer.addWidget(title_label)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._new_btn = QPushButton("新增模板")
        self._edit_btn = QPushButton("編輯模板")
        self._edit_btn.setEnabled(False)
        self._delete_btn = QPushButton("刪除模板")
        self._delete_btn.setEnabled(False)
        self._refresh_btn = QPushButton("重新整理")
        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._edit_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._refresh_btn)
        outer.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        self._table.setHorizontalHeaderLabels([_TABLE_HEADERS[c] for c in _COLUMN_ORDER])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            _COLUMN_ORDER.index("name"), QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        left_layout.addWidget(self._table)

        self._empty_label = QLabel("目前沒有模板")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.hide()
        left_layout.addWidget(self._empty_label)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        preview_label = QLabel("模板預覽")
        preview_label.setObjectName("SectionLabel")
        right_layout.addWidget(preview_label)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("選擇一個模板以預覽內容")
        right_layout.addWidget(self._preview)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter)

        self._new_btn.clicked.connect(self._on_new_template)
        self._edit_btn.clicked.connect(self._on_edit_template)
        self._delete_btn.clicked.connect(self._on_delete_template)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._refresh()

    # ------------------------------------------------------------------
    # Private helpers

    def _refresh(self) -> None:
        try:
            templates = self._container.templates.list_all()
        except Exception:
            templates = []

        self._body_cache = {tmpl.id: tmpl.body for tmpl in templates}
        self._table.setRowCount(len(templates))
        for row_idx, tmpl in enumerate(templates):
            values = {
                "id": str(tmpl.id),
                "name": tmpl.name,
                "template_type": TEMPLATE_TYPE_LABELS.get(tmpl.template_type, tmpl.template_type),
                "is_builtin": "是" if tmpl.is_builtin else "",
                "updated_at": tmpl.updated_at[:16] if tmpl.updated_at else "",
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_idx, col_idx, item)

        has_rows = len(templates) > 0
        self._table.setVisible(has_rows)
        self._empty_label.setVisible(not has_rows)
        self._on_selection_changed()

    def _selected_template_id(self) -> int | None:
        if not self._table.selectedItems():
            return None
        row = self._table.currentRow()
        id_item = self._table.item(row, 0)
        if id_item is None:
            return None
        try:
            return int(id_item.text())
        except ValueError:
            return None

    def _on_selection_changed(self) -> None:
        tmpl_id = self._selected_template_id()
        has_sel = tmpl_id is not None
        self._edit_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._preview.setPlainText(self._body_cache.get(tmpl_id, "") if has_sel else "")

    # ------------------------------------------------------------------
    # Action handlers

    def _on_new_template(self) -> None:
        dlg = TemplateFormDialog(self._container.templates, parent=self)
        if dlg.exec() == TemplateFormDialog.DialogCode.Accepted:
            self._refresh()

    def _on_edit_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        try:
            tmpl = self._container.templates.get_template(tmpl_id)
        except Exception:
            tmpl = None
        if tmpl is None:
            QMessageBox.warning(self, "找不到模板", error_message("template.not_found"))
            self._refresh()
            return
        dlg = TemplateFormDialog(self._container.templates, existing=tmpl, parent=self)
        if dlg.exec() == TemplateFormDialog.DialogCode.Accepted:
            self._refresh()

    def _on_delete_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        reply = QMessageBox.question(
            self,
            "刪除模板",
            "確定要刪除此模板？此操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.templates.delete_template(tmpl_id)
        except TemplateValidationError as err:
            QMessageBox.warning(self, "刪除失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.warning(self, "刪除失敗", error_message("template.delete.failed"))
            return
        self._refresh()
