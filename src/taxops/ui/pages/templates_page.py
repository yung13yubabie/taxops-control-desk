"""Message templates page: master-detail list, inspector detail, and preview.

Follows `clients_page.py`. 新增模板 is the header's single primary; 編輯模板 and
試用模板 appear in the inspector only while a row is selected, and 刪除模板 sits
behind 更多. 重新整理 is a quiet icon and the page also reloads on entry through
`refresh_context`, so the reload is no longer a labelled button competing with the
create action.

The table carries the name and a fixed-width type column. 編號, 內建 and 更新時間
were three of five columns, which left the name — the only thing anyone scans a
template list for — the least room; they moved into the inspector. With nothing
selected the right-hand panel explains what a selection will show instead of
presenting an empty text box.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import NAV_LABELS, error_message
from ...i18n.status_labels import TEMPLATE_TYPE_LABELS, UNKNOWN_STATUS_TEXT
from ...services.container import ServiceContainer
from ...services.templates import TemplateValidationError, TemplatesService
from .. import tokens
from ..dialogs.template_form_dialog import TemplateFormDialog
from ..style import toolbar_icon
from ..widgets.buttons import make_icon_button, set_button_role
from ..widgets.empty_state import EmptyState
from ..widgets.inspector import Inspector
from ..widgets.page_shell import ActionBar, PageHeader, build_page_layout
from ..widgets.table_builder import build_standard_table

_COLUMN_ORDER = ("id", "name", "template_type", "is_builtin", "updated_at")

_TABLE_HEADERS = {
    "id": "編號",
    "name": "名稱",
    "template_type": "類型",
    "is_builtin": "內建",
    "updated_at": "更新時間",
}

# Metadata columns. Every one of these is a single short value that says nothing
# while scanning a list of names, and together they took three of five columns.
# The inspector shows all three for the selected template instead.
_HIDDEN_COLUMNS = frozenset({"id", "is_builtin", "updated_at"})

# The type stays visible because it is how templates are grouped, but at a fixed
# width so it cannot take a proportional share of the name column.
_TYPE_COL_WIDTH = 120

_BUILTIN_READONLY_CODE = "template.builtin.readonly"

_PLACEHOLDER = (
    "選取左側模板後，可在此查看類型、是否為內建模板、能否編輯或刪除，"
    "以及完整的模板內容預覽。"
)


class TemplatesPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._body_cache: dict[int, str] = {}
        self._name_cache: dict[int, str] = {}
        self._builtin_cache: dict[int, bool] = {}

        # ── Header: the page's only primary action ──────────────────
        self._header = PageHeader(NAV_LABELS["templates"])
        self._new_btn = QPushButton("新增模板")
        self._new_btn.setIcon(toolbar_icon("new"))
        self._header.add_action(self._new_btn, role=tokens.ROLE_PRIMARY)

        # ── Action bar: reload only, as a quiet icon ────────────────
        self._action_bar = ActionBar()
        self._refresh_btn = self._action_bar.add_tool_icon(
            "refresh",
            tooltip="重新整理模板清單",
            accessible_name="重新整理模板清單",
        )

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(tokens.SPACING_MD)

        # The load error and the empty state each replace the whole master-detail
        # body rather than sitting above an empty framed table.
        self._error_label = QLabel("載入模板失敗，請重新整理或重新啟動程式")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setObjectName("ErrorText")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        body_layout.addWidget(self._error_label)

        self._empty_state = EmptyState(
            "目前沒有模板",
            detail="新增模板後可用客戶或案件資料套版產生訊息。",
            action_text="新增模板",
        )
        self._empty_label = self._empty_state.title_label
        self._empty_state.hide()
        body_layout.addWidget(self._empty_state, stretch=1)

        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setChildrenCollapsible(False)

        self._table = build_standard_table(
            _COLUMN_ORDER,
            _TABLE_HEADERS,
            stretch_col="name",
            fixed_cols={"template_type": _TYPE_COL_WIDTH},
        )
        for col_idx, col in enumerate(_COLUMN_ORDER):
            self._table.setColumnHidden(col_idx, col in _HIDDEN_COLUMNS)
        self._split.addWidget(self._table)

        # ── Right column: inspector, then the content preview ───────
        detail_column = QWidget()
        detail_layout = QVBoxLayout(detail_column)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(tokens.SPACING_MD)

        self._inspector = Inspector(placeholder=_PLACEHOLDER, min_width=320)
        self._edit_btn = QPushButton("編輯模板")
        self._edit_btn.setIcon(toolbar_icon("edit"))
        set_button_role(self._edit_btn, tokens.ROLE_SECONDARY)
        self._inspector.add_action(self._edit_btn)

        self._trial_btn = QPushButton("試用模板")
        self._trial_btn.setIcon(toolbar_icon("trial"))
        self._trial_btn.setToolTip("選擇真實客戶預覽此模板的渲染結果")
        set_button_role(self._trial_btn, tokens.ROLE_QUIET)
        self._inspector.add_action(self._trial_btn)

        # 刪除 is destructive and rare, so it lives behind 更多. The button stays the
        # single place the behaviour is wired; the menu entry clicks it, so menu use
        # and programmatic use follow one path with one enabled state.
        self._more_btn = make_icon_button(
            "overflow", tooltip="更多模板操作", accessible_name="更多模板操作"
        )
        self._more_menu = QMenu(self)
        self._delete_btn = QPushButton("刪除模板")
        set_button_role(self._delete_btn, tokens.ROLE_DANGER)
        self._delete_action = self._more_menu.addAction("刪除模板")
        self._more_btn.setMenu(self._more_menu)
        self._inspector.add_action(self._more_btn)

        detail_layout.addWidget(self._inspector, stretch=1)

        # Hidden entirely until a template is selected: the empty box this replaces
        # was the largest thing on the page and said nothing.
        self._preview_panel = QWidget()
        preview_layout = QVBoxLayout(self._preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(tokens.SPACING_XS)
        preview_title = QLabel("模板內容")
        preview_title.setObjectName("SectionTitle")
        preview_layout.addWidget(preview_title)
        preview_hint = QLabel("欄位標記以【】顯示，產生訊息時才會套入真實資料。")
        preview_hint.setObjectName("HintText")
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(140)
        preview_layout.addWidget(self._preview, stretch=1)
        self._preview_panel.setVisible(False)
        detail_layout.addWidget(self._preview_panel, stretch=1)

        self._split.addWidget(detail_column)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 2)
        body_layout.addWidget(self._split, stretch=1)

        self.setLayout(
            build_page_layout(self._header, action_bar=self._action_bar, body=body)
        )

        self._new_btn.clicked.connect(self._on_new_template)
        if self._empty_state.action_button is not None:
            self._empty_state.action_button.clicked.connect(self._on_new_template)
        self._edit_btn.clicked.connect(self._on_edit_template)
        self._delete_btn.clicked.connect(self._on_delete_template)
        self._delete_action.triggered.connect(lambda _=False: self._delete_btn.click())
        self._trial_btn.clicked.connect(self._on_trial_template)
        self._refresh_btn.clicked.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(lambda _index: self._on_edit_template())

        self._refresh()

    # ------------------------------------------------------------------
    # Private helpers

    def refresh_context(self) -> None:
        """Reload templates when the page becomes active.

        `MainWindow._activate_page` calls this, which is why 重新整理 no longer needs
        to be a labelled action.
        """
        self._refresh()

    def _type_label(self, template_type: str) -> str:
        """The Chinese label for a template type.

        An unmapped value is not shown raw: it renders the unknown-status sentence
        and writes a log line, so a new type added without a label is visible as a
        defect instead of leaking a database value into the list.
        """
        label = TEMPLATE_TYPE_LABELS.get(template_type)
        if label is not None:
            return label
        self._container.system_log.warn(
            "templates_page: unknown template type",
            detail={"template_type": template_type},
        )
        return UNKNOWN_STATUS_TEXT

    def _refresh(self) -> None:
        selected_id = self._selected_template_id()
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
        self._name_cache = {tmpl.id: tmpl.name for tmpl in templates}
        self._builtin_cache = {tmpl.id: bool(tmpl.is_builtin) for tmpl in templates}
        self._table.setRowCount(len(templates))
        for row_idx, tmpl in enumerate(templates):
            values = {
                "id": str(tmpl.id),
                "name": tmpl.name,
                "template_type": self._type_label(tmpl.template_type),
                "is_builtin": "內建" if tmpl.is_builtin else "自訂",
                "updated_at": tmpl.updated_at[:16] if tmpl.updated_at else "",
            }
            for col_idx, col in enumerate(_COLUMN_ORDER):
                item = QTableWidgetItem(values[col])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(values[col])
                self._table.setItem(row_idx, col_idx, item)

        self._restore_selection(selected_id)
        self._error_label.setVisible(load_error)
        has_rows = len(templates) > 0 and not load_error
        self._table.setVisible(has_rows)
        self._split.setVisible(has_rows)
        self._empty_state.setVisible(not has_rows and not load_error)
        self._on_selection_changed()

    def _restore_selection(self, template_id: int | None) -> None:
        self._table.clearSelection()
        if template_id is None:
            return
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.text() == str(template_id):
                self._table.selectRow(row)
                return

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
        if tmpl_id is None:
            self._edit_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._trial_btn.setEnabled(False)
            self._sync_more_menu()
            self._inspector.clear()
            self._preview.setPlainText("")
            self._preview_panel.setVisible(False)
            return

        is_builtin = self._builtin_cache.get(tmpl_id, False)
        readonly_reason = error_message(_BUILTIN_READONLY_CODE)
        self._edit_btn.setEnabled(not is_builtin)
        self._delete_btn.setEnabled(not is_builtin)
        self._trial_btn.setEnabled(True)
        self._edit_btn.setToolTip(readonly_reason if is_builtin else "")
        self._delete_btn.setToolTip(readonly_reason if is_builtin else "")
        self._sync_more_menu()

        body = self._body_cache.get(tmpl_id, "")
        self._preview.setPlainText(TemplatesService.body_for_edit(body))
        self._preview_panel.setVisible(True)
        self._populate_inspector(tmpl_id, is_builtin=is_builtin)

    def _sync_more_menu(self) -> None:
        """Keep the 更多 entry in step with the button that owns the behaviour."""
        self._delete_action.setEnabled(self._delete_btn.isEnabled())

    def _populate_inspector(self, template_id: int, *, is_builtin: bool) -> None:
        row_idx = self._row_for_template(template_id)
        self._inspector.begin_update()
        name = self._name_cache.get(template_id, "")
        type_label = self._cell_text(row_idx, "template_type")
        self._inspector.set_title(name, subtitle=type_label)

        self._inspector.add_section("模板資訊")
        self._inspector.add_field("類型", type_label)
        self._inspector.add_field("來源", "內建模板" if is_builtin else "自訂模板")
        self._inspector.add_field("編號", str(template_id))
        self._inspector.add_field("更新時間", self._cell_text(row_idx, "updated_at"))

        # Stated in words for both cases. A built-in template used to differ from a
        # custom one only by a 是 in a narrow column, which explained nothing about
        # why 編輯 and 刪除 would refuse.
        self._inspector.add_section("可否修改")
        self._inspector.add_field(
            "編輯", "不可編輯（內建模板）" if is_builtin else "可以編輯"
        )
        self._inspector.add_field(
            "刪除", "不可刪除（內建模板）" if is_builtin else "可以刪除"
        )
        if is_builtin:
            self._inspector.add_note(error_message(_BUILTIN_READONLY_CODE))

    def _row_for_template(self, template_id: int) -> int:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.text() == str(template_id):
                return row
        return -1

    def _cell_text(self, row_idx: int, col: str) -> str:
        if row_idx < 0:
            return ""
        item = self._table.item(row_idx, _COLUMN_ORDER.index(col))
        return item.text() if item is not None else ""

    # ------------------------------------------------------------------
    # Action handlers

    def _on_new_template(self) -> None:
        dlg = TemplateFormDialog(
            self._container.templates,
            parent=self,
            container=self._container,
        )
        if dlg.exec() == TemplateFormDialog.DialogCode.Accepted:
            self._refresh()

    def _on_edit_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        if self._builtin_cache.get(tmpl_id, False):
            # Reached by double-clicking a built-in row; 編輯模板 is already disabled.
            # Saying why beats opening a form that cannot be saved, and beats doing
            # nothing at all.
            QMessageBox.information(
                self, "內建模板", error_message(_BUILTIN_READONLY_CODE)
            )
            return
        try:
            tmpl = self._container.templates.get_template(tmpl_id)
        except Exception as err:
            self._container.system_log.warn(
                "templates_page: failed to load template for edit",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            tmpl = None
        if tmpl is None:
            QMessageBox.warning(self, "找不到模板", error_message("template.not_found"))
            self._refresh()
            return
        dlg = TemplateFormDialog(
            self._container.templates,
            existing=tmpl,
            parent=self,
            container=self._container,
        )
        if dlg.exec() == TemplateFormDialog.DialogCode.Accepted:
            self._refresh()

    def _on_delete_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        name = self._name_cache.get(tmpl_id, "")
        reply = QMessageBox.question(
            self,
            "刪除模板",
            f"確定要刪除模板「{name}」？此操作無法復原。",
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
        except Exception as err:
            self._container.system_log.warn(
                "templates_page: delete failed",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            QMessageBox.warning(self, "刪除失敗", error_message("template.delete.failed"))
            return
        self._refresh()

    def _on_trial_template(self) -> None:
        tmpl_id = self._selected_template_id()
        if tmpl_id is None:
            return
        try:
            clients = self._container.clients.search_clients("", limit=500)
        except Exception as err:
            self._container.system_log.warn(
                "templates_page: failed to load clients for trial",
                detail={"exc": type(err).__name__, "msg": str(err)},
            )
            clients = []
        if not clients:
            QMessageBox.warning(
                self,
                "沒有範例客戶",
                "請先在客戶管理建立客戶，才能用真實資料試用模板。",
            )
            return
        if len(clients) == 1:
            client = clients[0]
        else:
            labels = [
                f"{client.client_code}  {client.client_name}" for client in clients
            ]
            selected, accepted = QInputDialog.getItem(
                self,
                "選擇真實客戶",
                "模板預覽將使用此客戶的真實資料：",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            client = clients[labels.index(selected)]
        try:
            variables = self._container.gen_messages.build_client_example_variables(
                client.id
            )
            rendered = self._container.templates.render_template(tmpl_id, variables)
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
        self._show_trial_result(client.client_name, rendered)

    def _show_trial_result(self, client_name: str, rendered: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"試用模板（{client_name}）")
        dlg.setMinimumWidth(500)
        dlg.setMinimumHeight(350)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(
            tokens.SPACING_XL, tokens.SPACING_XL, tokens.SPACING_XL, tokens.SPACING_XL
        )
        layout.setSpacing(tokens.SPACING_MD)
        layout.addWidget(QLabel("以下為真實客戶資料渲染結果（未儲存）："))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(rendered)
        layout.addWidget(preview, stretch=1)
        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton("複製", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = buttons.addButton("關閉", QDialogButtonBox.ButtonRole.RejectRole)
        set_button_role(copy_btn, tokens.ROLE_PRIMARY)
        set_button_role(close_btn, tokens.ROLE_SECONDARY)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(rendered))
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()
