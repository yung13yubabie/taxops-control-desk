"""Work Records page: workflow templates and runs."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDialog,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.container import ServiceContainer
from ...services.work_records import WorkRecordValidationError
from ..dialogs.work_records_dialogs import (
    WorkflowTemplateDialog,
    format_stages_for_editor,
)
from ..style import BORDER_COLOR, TEXT_MUTED, toolbar_icon
from ..widgets.buttons import set_button_role
from ..widgets.empty_state import EmptyState
from ..widgets.flow_layout import FlowLayout

_TREE_KIND_ROLE = Qt.ItemDataRole.UserRole
_TREE_STAGE_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_TREE_ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 2
_TREE_DONE_ROLE = Qt.ItemDataRole.UserRole + 3
_TREE_RUN_ID_ROLE = Qt.ItemDataRole.UserRole + 4
_TREE_ROW_KIND_ROLE = Qt.ItemDataRole.UserRole + 5
_TREE_ROW_ID_ROLE = Qt.ItemDataRole.UserRole + 6


class _WorkflowImageLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class WorkRecordsPage(QWidget):
    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._current_workflow_image_path: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("工作紀錄")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self._workflow_tab = self._build_workflow_tab()
        outer.addWidget(self._workflow_tab, stretch=1)

        self.refresh_context()

    def refresh_context(self) -> None:
        self._refresh_workflows()

    def clear_filter(self) -> None:
        return

    def _build_workflow_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        self._create_template_btn = QPushButton("新增流程")
        set_button_role(self._create_template_btn, "primary")
        self._edit_template_btn = QPushButton("編輯流程")
        self._delete_template_btn = QPushButton("刪除流程")
        self._edit_run_btn = QPushButton("編輯執行")
        self._delete_run_btn = QPushButton("刪除執行")
        self._set_template_image_btn = QPushButton("匯入流程圖片")
        self._paste_template_image_btn = QPushButton("貼上截圖")
        self._create_standard_btn = QPushButton("建立標準公司設立流程")
        self._instantiate_btn = QPushButton("建立執行清單")
        self._toggle_first_btn = QPushButton("完成/取消完成選取步驟")
        self._overwrite_template_btn = QPushButton("覆蓋回原範本")
        self._save_as_template_btn = QPushButton("另存為新範本")
        for btn, icon in (
            (self._create_template_btn, "new"),
            (self._edit_template_btn, "edit"),
            (self._delete_template_btn, "delete"),
            (self._edit_run_btn, "edit"),
            (self._delete_run_btn, "delete"),
            (self._set_template_image_btn, "upload"),
            (self._paste_template_image_btn, "paste"),
            (self._create_standard_btn, "new"),
            (self._instantiate_btn, "new"),
            (self._toggle_first_btn, "complete"),
            (self._overwrite_template_btn, "edit"),
            (self._save_as_template_btn, "new"),
        ):
            btn.setIcon(toolbar_icon(icon))
            toolbar.addWidget(btn)
        layout.addWidget(toolbar_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left.setMinimumWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self._template_group = QGroupBox("流程範本與說明")
        template_layout = QVBoxLayout(self._template_group)
        template_layout.setContentsMargins(8, 8, 8, 8)
        self._templates_table = QTableWidget(0, 4)
        self._templates_table.setHorizontalHeaderLabels(["編號", "範本名稱", "版本", "進度"])
        self._templates_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._templates_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._templates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        templates_header = self._templates_table.horizontalHeader()
        templates_header.setMinimumSectionSize(56)
        templates_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._templates_table.setColumnWidth(0, 56)
        self._templates_table.setColumnWidth(2, 72)
        self._templates_table.setColumnWidth(3, 96)
        template_layout.addWidget(self._templates_table)
        self._workflow_empty_state = EmptyState(
            "尚無流程範本",
            detail="新增範本後，可建立執行清單並逐步勾選完成狀態。",
            action_text="新增範本",
        )
        self._workflow_empty_state.hide()
        template_layout.addWidget(self._workflow_empty_state)
        left_layout.addWidget(self._template_group)

        self._run_group = QGroupBox("執行中流程")
        run_layout = QVBoxLayout(self._run_group)
        run_layout.setContentsMargins(8, 8, 8, 8)
        self._runs_table = QTableWidget(0, 4)
        self._runs_table.setHorizontalHeaderLabels(["編號", "執行名稱", "來源範本", "進度"])
        self._runs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._runs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._runs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        runs_header = self._runs_table.horizontalHeader()
        runs_header.setMinimumSectionSize(56)
        runs_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._runs_table.setColumnWidth(0, 56)
        self._runs_table.setColumnWidth(2, 96)
        self._runs_table.setColumnWidth(3, 96)
        run_layout.addWidget(self._runs_table)
        left_layout.addWidget(self._run_group)
        splitter.addWidget(left)

        right = QGroupBox("流程說明與圖片（雙擊圖片放大）")
        self._detail_group = right
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        self._workflow_detail = QTreeWidget()
        self._workflow_detail.setHeaderLabels(["流程步驟", "狀態"])
        self._workflow_image = _WorkflowImageLabel("尚未選擇流程圖片")
        self._workflow_image.setObjectName("WorkflowImagePreview")
        self._workflow_image.setToolTip("圖片會直接顯示在此；雙擊可放大查看")
        self._workflow_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._workflow_image.setMinimumHeight(260)
        self._workflow_image.setStyleSheet(
            f"border: 1px solid {BORDER_COLOR}; color: {TEXT_MUTED};"
        )
        self._workflow_image.double_clicked.connect(
            lambda: self._on_preview_workflow_image()
        )
        right_layout.addWidget(QLabel("流程步驟與說明"))
        right_layout.addWidget(self._workflow_detail, stretch=4)
        right_layout.addWidget(QLabel("搭配圖片"))
        right_layout.addWidget(self._workflow_image, stretch=2)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])
        layout.addWidget(splitter, stretch=1)

        self._create_template_btn.clicked.connect(self._on_create_template)
        if self._workflow_empty_state.action_button is not None:
            self._workflow_empty_state.action_button.clicked.connect(self._on_create_template)
        self._edit_template_btn.clicked.connect(self._on_edit_template)
        self._delete_template_btn.clicked.connect(self._on_delete_template)
        self._edit_run_btn.clicked.connect(self._on_edit_run)
        self._delete_run_btn.clicked.connect(self._on_delete_run)
        self._set_template_image_btn.clicked.connect(self._on_set_template_image)
        self._paste_template_image_btn.clicked.connect(self._on_paste_template_image)
        self._create_standard_btn.clicked.connect(self._on_create_standard_template)
        self._instantiate_btn.clicked.connect(self._on_instantiate_run)
        self._toggle_first_btn.clicked.connect(self._on_toggle_selected_run_step)
        self._overwrite_template_btn.clicked.connect(self._on_overwrite_template)
        self._save_as_template_btn.clicked.connect(self._on_save_run_as_template)
        self._templates_table.itemSelectionChanged.connect(self._on_template_selection_changed)
        self._runs_table.itemSelectionChanged.connect(self._on_run_selection_changed)
        self._workflow_detail.currentItemChanged.connect(lambda *_args: self._refresh_workflow_image())
        return page

    def _refresh_workflows(self) -> None:
        templates = self._container.work_records.list_templates()
        self._templates_table.blockSignals(True)
        self._templates_table.setRowCount(len(templates))
        has_templates = len(templates) > 0
        self._templates_table.setVisible(has_templates)
        self._workflow_empty_state.setVisible(not has_templates)
        for row_idx, template in enumerate(templates):
            done, total, percent = self._container.work_records.progress_for_stages_json(
                template.stages_json
            )
            values = [str(template.id), template.name, str(template.version), f"{done}/{total} ({percent}%)"]
            for col, value in enumerate(values):
                self._templates_table.setItem(row_idx, col, QTableWidgetItem(value))
        self._templates_table.blockSignals(False)

        runs = self._container.work_records.list_runs()
        self._runs_table.blockSignals(True)
        self._runs_table.setRowCount(len(runs))
        for row_idx, run in enumerate(runs):
            done, total, percent = self._container.work_records.progress_for_stages_json(
                run.stages_json
            )
            values = [str(run.id), run.name, str(run.template_id or ""), f"{done}/{total} ({percent}%)"]
            for col, value in enumerate(values):
                self._runs_table.setItem(row_idx, col, QTableWidgetItem(value))
        self._runs_table.blockSignals(False)
        self._update_workflow_detail()

    def _selected_template_id(self) -> int | None:
        row = self._templates_table.currentRow()
        if row < 0:
            return None
        item = self._templates_table.item(row, 0)
        return int(item.text()) if item else None

    def _selected_run_id(self) -> int | None:
        row = self._runs_table.currentRow()
        if row < 0:
            return None
        item = self._runs_table.item(row, 0)
        return int(item.text()) if item else None

    def _on_template_selection_changed(self) -> None:
        if self._templates_table.currentRow() >= 0:
            self._runs_table.blockSignals(True)
            self._runs_table.clearSelection()
            self._runs_table.setCurrentCell(-1, -1)
            self._runs_table.blockSignals(False)
        self._update_workflow_detail()

    def _on_run_selection_changed(self) -> None:
        if self._runs_table.currentRow() >= 0:
            self._templates_table.blockSignals(True)
            self._templates_table.clearSelection()
            self._templates_table.setCurrentCell(-1, -1)
            self._templates_table.blockSignals(False)
        self._update_workflow_detail()

    def _selected_image_template_id(self) -> int | None:
        template_id = self._selected_template_id()
        if template_id is not None:
            return template_id
        run_id = self._selected_run_id()
        if run_id is None:
            return None
        run = next((r for r in self._container.work_records.list_runs() if r.id == run_id), None)
        return run.template_id if run else None

    def _selected_workflow_step_ref(self) -> tuple[str, int, str, str, bool] | None:
        item = self._workflow_detail.currentItem()
        if item is None or item.data(0, _TREE_KIND_ROLE) != "step":
            return None
        row_kind = item.data(0, _TREE_ROW_KIND_ROLE)
        row_id = item.data(0, _TREE_ROW_ID_ROLE)
        stage_id = item.data(0, _TREE_STAGE_ID_ROLE)
        item_id = item.data(0, _TREE_ITEM_ID_ROLE)
        if row_kind not in {"template", "run"} or row_id is None or not stage_id or not item_id:
            return None
        return str(row_kind), int(row_id), str(stage_id), str(item_id), bool(item.data(0, _TREE_DONE_ROLE))

    def _selected_workflow_step(self) -> tuple[int, str, str, bool] | None:
        selected = self._selected_workflow_step_ref()
        if selected is None:
            return None
        row_kind, row_id, stage_id, item_id, done = selected
        if row_kind != "run":
            return None
        return row_id, stage_id, item_id, done

    def _template_image_path(self, context_snapshot: str | None) -> Path | None:
        if not context_snapshot:
            return None
        try:
            data = json.loads(context_snapshot)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        rel = str(data.get("image_path") or "")
        if not rel:
            return None
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        try:
            return self._container.work_records.workflow_assets_dir / rel_path
        except WorkRecordValidationError:
            return None

    def _workflow_asset_path(self, rel: str | None) -> Path | None:
        rel = str(rel or "")
        if not rel:
            return None
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        try:
            return self._container.work_records.workflow_assets_dir / rel_path
        except WorkRecordValidationError:
            return None

    def _selected_step_image_path(self) -> Path | None:
        selected = self._selected_workflow_step_ref()
        if selected is None:
            return None
        row_kind, row_id, stage_id, item_id, _done = selected
        if row_kind == "run":
            row = next((r for r in self._container.work_records.list_runs() if r.id == row_id), None)
        else:
            row = next((t for t in self._container.work_records.list_templates() if t.id == row_id), None)
        if row is None:
            self._detail_group.setTitle("流程說明與圖片（雙擊圖片放大）")
            return None
        for stage in self._container.work_records.stages_for_row(row):
            if str(stage.get("id") or "") != stage_id:
                continue
            for item in stage.get("items", []):
                if str(item.get("id") or "") == item_id:
                    return self._workflow_asset_path(item.get("image_path"))
        return None

    def _set_workflow_image_path(self, image_path: Path | None) -> None:
        self._current_workflow_image_path = image_path
        pix = QPixmap(str(image_path)) if image_path else QPixmap()
        if pix.isNull():
            self._workflow_image.setPixmap(QPixmap())
            self._workflow_image.setText("尚未選擇流程圖片")
            return
        self._workflow_image.setText("")
        self._workflow_image.setPixmap(
            pix.scaled(
                self._workflow_image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _refresh_workflow_image(self) -> None:
        selected_run = self._selected_run_id()
        selected_template = self._selected_template_id()
        row = None
        if selected_run is not None:
            row = next((r for r in self._container.work_records.list_runs() if r.id == selected_run), None)
        if row is None and selected_template is not None:
            row = next((t for t in self._container.work_records.list_templates() if t.id == selected_template), None)
        self._set_workflow_image_path(
            self._selected_step_image_path()
            or self._template_image_path(row.context_snapshot if row else None)
        )

    def _on_preview_workflow_image(self) -> None:
        if self._current_workflow_image_path is None:
            return
        pix = QPixmap(str(self._current_workflow_image_path))
        if pix.isNull():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("圖片預覽")
        w = self.window().width()
        h = self.window().height()
        dlg.resize(int(w * 0.7), int(h * 0.75))
        layout = QVBoxLayout(dlg)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(
            pix.scaled(
                dlg.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(label)
        dlg.exec()

    def _update_workflow_detail(self) -> None:
        self._workflow_detail.clear()
        selected_template = self._selected_template_id()
        selected_run = self._selected_run_id()
        row = None
        row_kind = ""
        if selected_run is not None:
            row = next((r for r in self._container.work_records.list_runs() if r.id == selected_run), None)
            row_kind = "執行清單"
        if row is None and selected_template is not None:
            row = next((t for t in self._container.work_records.list_templates() if t.id == selected_template), None)
            row_kind = "流程範本"
        if row is None:
            empty = QTreeWidgetItem(["請先從左側選擇流程範本或執行清單。", ""])
            empty.setData(0, _TREE_KIND_ROLE, "empty")
            self._workflow_detail.addTopLevelItem(empty)
            self._set_workflow_image_path(None)
            self._toggle_first_btn.setEnabled(False)
            return
        done, total, percent = self._container.work_records.progress_for_stages_json(row.stages_json)
        self._detail_group.setTitle(
            "執行中流程與圖片（雙擊圖片放大）"
            if selected_run is not None
            else "流程範本與說明（圖片雙擊放大）"
        )
        stages = self._container.work_records.stages_for_row(row)
        summary = QTreeWidgetItem([f"{row_kind}：{row.name}", f"{done}/{total} ({percent}%)"])
        summary.setData(0, _TREE_KIND_ROLE, "summary")
        self._workflow_detail.addTopLevelItem(summary)
        tree_row_kind = "run" if selected_run is not None else "template"
        tree_row_id = row.id
        tree_run_id = row.id if selected_run is not None else None
        for stage in stages:
            stage_item = QTreeWidgetItem([str(stage.get("title") or "未命名階段"), ""])
            stage_item.setData(0, _TREE_KIND_ROLE, "stage")
            stage_item.setData(0, _TREE_STAGE_ID_ROLE, str(stage.get("id") or ""))
            for item in stage.get("items", []):
                done_flag = bool(item.get("done"))
                text = str(item.get("text") or "")
                step_item = QTreeWidgetItem([text, "完成" if done_flag else "未完成"])
                step_item.setData(0, _TREE_KIND_ROLE, "step")
                step_item.setData(0, _TREE_STAGE_ID_ROLE, str(stage.get("id") or ""))
                step_item.setData(0, _TREE_ITEM_ID_ROLE, str(item.get("id") or ""))
                step_item.setData(0, _TREE_DONE_ROLE, done_flag)
                step_item.setData(0, _TREE_RUN_ID_ROLE, tree_run_id)
                step_item.setData(0, _TREE_ROW_KIND_ROLE, tree_row_kind)
                step_item.setData(0, _TREE_ROW_ID_ROLE, tree_row_id)
                if done_flag:
                    font = step_item.font(0)
                    font.setStrikeOut(True)
                    step_item.setFont(0, font)
                stage_item.addChild(step_item)
            self._workflow_detail.addTopLevelItem(stage_item)
            stage_item.setExpanded(True)
        self._workflow_detail.resizeColumnToContents(0)
        self._toggle_first_btn.setEnabled(selected_run is not None)
        self._refresh_workflow_image()

    def _select_run_step(self, run_id: int, stage_id: str, item_id: str) -> None:
        for row in range(self._runs_table.rowCount()):
            id_item = self._runs_table.item(row, 0)
            if id_item is not None and id_item.text() == str(run_id):
                self._runs_table.selectRow(row)
                break
        for top_idx in range(self._workflow_detail.topLevelItemCount()):
            stage_item = self._workflow_detail.topLevelItem(top_idx)
            if stage_item.data(0, _TREE_STAGE_ID_ROLE) != stage_id:
                continue
            for child_idx in range(stage_item.childCount()):
                step_item = stage_item.child(child_idx)
                if step_item.data(0, _TREE_ITEM_ID_ROLE) == item_id:
                    self._workflow_detail.setCurrentItem(step_item)
                    return

    def _on_create_template(self) -> None:
        dlg = WorkflowTemplateDialog(
            title="新增流程",
            on_submit=self._container.work_records.create_template,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.refresh_context()

    def _on_edit_template(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            return
        template = next((t for t in self._container.work_records.list_templates() if t.id == template_id), None)
        if template is None:
            return
        stages_text = format_stages_for_editor(self._container.work_records.stages_for_row(template))
        dlg = WorkflowTemplateDialog(
            title="編輯流程",
            name=template.name,
            stages_text=stages_text,
            on_submit=lambda payload: self._container.work_records.update_template(
                template_id, payload
            ),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.refresh_context()

    def _on_delete_template(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            return
        reply = QMessageBox.question(
            self,
            "刪除流程",
            "確定要刪除這個流程範本？已建立的執行清單不會被刪除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.work_records.delete_template(template_id)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "刪除失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_edit_run(self) -> None:
        run_id = self._selected_run_id()
        if run_id is None:
            return
        run = next((r for r in self._container.work_records.list_runs() if r.id == run_id), None)
        if run is None:
            return
        name, ok = QInputDialog.getText(
            self,
            "編輯執行名稱",
            "執行名稱",
            text=run.name,
        )
        if not ok:
            return
        try:
            self._container.work_records.rename_run(run_id, name)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "編輯失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_delete_run(self) -> None:
        run_id = self._selected_run_id()
        if run_id is None:
            return
        reply = QMessageBox.question(
            self,
            "刪除執行清單",
            "確定要刪除這個執行清單？流程範本不會被刪除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._container.work_records.delete_run(run_id)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "刪除失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_set_template_image(self) -> None:
        selected_ref = self._selected_workflow_step_ref()
        template_id = self._selected_image_template_id()
        if selected_ref is None and template_id is None:
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "選擇流程圖片",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if not file_name:
            return
        try:
            if selected_ref is not None:
                row_kind, row_id, stage_id, item_id, _done = selected_ref
                if row_kind == "run":
                    self._container.work_records.set_run_step_image_path(
                        row_id,
                        stage_id=stage_id,
                        item_id=item_id,
                        image_path=file_name,
                    )
                else:
                    self._container.work_records.set_template_step_image_path(
                        row_id,
                        stage_id=stage_id,
                        item_id=item_id,
                        image_path=file_name,
                    )
            else:
                if template_id is None:
                    return
                self._container.work_records.set_template_image_path(template_id, file_name)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "圖片更新失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_paste_template_image(self) -> None:
        selected_ref = self._selected_workflow_step_ref()
        template_id = self._selected_image_template_id()
        if selected_ref is None and template_id is None:
            return
        pix = QApplication.clipboard().pixmap()
        if pix.isNull():
            QMessageBox.warning(self, "貼上失敗", "剪貼簿沒有可用圖片")
            return
        try:
            image = pix.toImage()
            if selected_ref is not None:
                row_kind, row_id, stage_id, item_id, _done = selected_ref
                if row_kind == "run":
                    self._container.work_records.set_run_step_image_data(
                        row_id,
                        stage_id=stage_id,
                        item_id=item_id,
                        image=image,
                    )
                else:
                    self._container.work_records.set_template_step_image_data(
                        row_id,
                        stage_id=stage_id,
                        item_id=item_id,
                        image=image,
                    )
            else:
                if template_id is None:
                    return
                self._container.work_records.set_template_image_data(
                    template_id,
                    image,
                )
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "貼上失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_create_standard_template(self) -> None:
        try:
            self._container.work_records.create_standard_company_setup_template()
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "建立失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_instantiate_run(self) -> None:
        template_id = self._selected_template_id()
        if template_id is None:
            return
        try:
            self._container.work_records.instantiate_run(template_id)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "建立失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_toggle_selected_run_step(self) -> None:
        selected = self._selected_workflow_step()
        if selected is None:
            QMessageBox.warning(self, "更新失敗", "請先選取執行清單中的流程步驟")
            return
        run_id, stage_id, item_id, done = selected
        try:
            self._container.work_records.set_run_step_done(
                run_id,
                stage_id=stage_id,
                item_id=item_id,
                done=not done,
            )
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "更新失敗", error_message(err.code))
            return
        self._refresh_workflows()
        self._select_run_step(run_id, stage_id, item_id)

    def _on_toggle_first_run_step(self) -> None:
        self._on_toggle_selected_run_step()

    def _on_overwrite_template(self) -> None:
        run_id = self._selected_run_id()
        if run_id is None:
            return
        try:
            self._container.work_records.overwrite_template_from_run(run_id)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "覆蓋失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_save_run_as_template(self) -> None:
        run_id = self._selected_run_id()
        if run_id is None:
            return
        name, ok = QInputDialog.getText(self, "另存為新範本", "範本名稱")
        if not ok:
            return
        try:
            self._container.work_records.save_run_as_template(run_id, name)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "另存失敗", error_message(err.code))
            return
        self.refresh_context()
