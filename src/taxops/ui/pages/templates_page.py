"""Message templates page: list, preview, and CRUD actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
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
from ...services.templates import TemplateValidationError, TemplatesService
from ..dialogs.template_form_dialog import TemplateFormDialog
from ..style import DANGER_COLOR, toolbar_icon

_COLUMN_ORDER = ("id", "name", "template_type", "is_builtin", "updated_at")

_SAMPLE_VARS: dict[str, str] = {
    "client_name": "範例客戶股份有限公司",
    "tax_id": "12345678",
    "contact_person": "王小明",
    "period_name": "2024Q4",
    "tax_type_name": "營業稅",
    "engagement_name": "2024年度營業稅申報",
    "missing_items": "- 進項憑證\n- 銷項憑證",
    "invalid_items": "- 不明費用單據",
    "incomplete_items": "- 薪資明細（缺損）",
    "due_date": "2025-01-31",
    "notes": "請盡速提供，謝謝",
}

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
        self._trial_btn = QPushButton("試用模板")
        self._trial_btn.setEnabled(False)
        self._trial_btn.setToolTip("以範例資料預覽此模板的渲染結果")
        self._refresh_btn = QPushButton("重新整理")
        self._new_btn.setIcon(toolbar_icon("new"))
        self._edit_btn.setIcon(toolbar_icon("edit"))
        self._delete_btn.setIcon(toolbar_icon("delete"))
        self._trial_btn.setIcon(toolbar_icon("trial"))
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._edit_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addWidget(self._trial_btn)
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

        self._error_label = QLabel("載入模板失敗，請重新整理或重新啟動程式")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setObjectName("ErrorState")
        self._error_label.setStyleSheet(f"color: {DANGER_COLOR};")
        self._error_label.hide()
        left_layout.addWidget(self._error_label)

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
        self._trial_btn.clicked.connect(self._on_trial_template)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._refresh()

    # ------------------------------------------------------------------
    # Private helpers

    def _refresh(self) -> None:
        try:
            templates = self._container.templates.list_all()
            load_error = False
        except Exception as err:
            self._container.system_log.warn(
                "templates_page: failed to load templates",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            templates = []
            load_error = True

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

        self._error_label.setVisible(load_error)
        if not load_error:
            has_rows = len(templates) > 0
            self._table.setVisible(has_rows)
            self._empty_label.setVisible(not has_rows)
        else:
            self._table.setVisible(False)
            self._empty_label.setVisible(False)
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
        self._trial_btn.setEnabled(has_sel)
        body = self._body_cache.get(tmpl_id, "") if has_sel else ""
        self._preview.setPlainText(TemplatesService.body_for_edit(body))

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

    def _on_trial_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        try:
            rendered = self._container.templates.render_template(tmpl_id, _SAMPLE_VARS)
        except TemplateValidationError as err:
            QMessageBox.warning(self, "試用失敗", error_message(err.code))
            return
        except Exception as err:
            self._container.system_log.warn(
                "templates_page: render failed",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            QMessageBox.warning(self, "試用失敗", error_message("template.render.failed"))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("試用模板（範例資料）")
        dlg.setMinimumWidth(500)
        dlg.setMinimumHeight(350)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("以下為範例資料渲染結果（未儲存）："))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(rendered)
        layout.addWidget(preview, stretch=1)
        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton("複製", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton("關閉", QDialogButtonBox.ButtonRole.RejectRole)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(rendered))
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()
