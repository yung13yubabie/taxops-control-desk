"""Work Records page: workflow templates/runs and error reviews."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.canvas_notes import (
    A4_HEIGHT,
    A4_WIDTH,
    GRID_SIZE,
    CanvasNoteValidationError,
    CreateCanvasNoteInput,
    default_scene_json,
    safe_asset_path,
)
from ...services.container import ServiceContainer
from ...services.work_records import (
    CreateErrorReviewInput,
    WorkRecordValidationError,
)
from ..dialogs.work_records_dialogs import (
    WorkflowTemplateDialog,
    format_stages_for_editor,
)
from ..style import BORDER_COLOR, TEXT_MUTED, toolbar_icon
from ..widgets.empty_state import EmptyState
from ..widgets.flow_layout import FlowLayout

_TREE_KIND_ROLE = Qt.ItemDataRole.UserRole
_TREE_STAGE_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_TREE_ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 2
_TREE_DONE_ROLE = Qt.ItemDataRole.UserRole + 3
_TREE_RUN_ID_ROLE = Qt.ItemDataRole.UserRole + 4


def _snap(value: float) -> float:
    return round(value / GRID_SIZE) * GRID_SIZE


class _SnapRectItem(QGraphicsRectItem):
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            return QPointF(_snap(value.x()), _snap(value.y()))
        return super().itemChange(change, value)


class _SnapTextItem(QGraphicsTextItem):
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            return QPointF(_snap(value.x()), _snap(value.y()))
        return super().itemChange(change, value)


class _CanvasView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self._drawing = False
        self._active_path: QGraphicsPathItem | None = None
        self._active_points: list[list[float]] = []
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def set_drawing(self, enabled: bool) -> None:
        self._drawing = enabled
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag
        )

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._drawing or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = self.mapToScene(event.position().toPoint())
        self._active_points = [[point.x(), point.y()]]
        path = QPainterPath(point)
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor("#DC2626"), 3))
        item.setData(0, "freehand")
        item.setData(2, self._active_points)
        self.scene().addItem(item)
        self._active_path = item

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._active_path is None:
            return super().mouseMoveEvent(event)
        point = self.mapToScene(event.position().toPoint())
        path = self._active_path.path()
        path.lineTo(point)
        self._active_path.setPath(path)
        self._active_points.append([point.x(), point.y()])
        self._active_path.setData(2, self._active_points)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._active_path = None
        self._active_points = []
        return super().mouseReleaseEvent(event)


class WorkRecordsPage(QWidget):
    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._current_note_id: int | None = None
        self._current_workflow_image_path: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("工作紀錄")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self._workflow_tab = self._build_workflow_tab()
        outer.addWidget(self._workflow_tab, stretch=1)

        # Keep the canvas/error widgets alive for existing tests and internal
        # handlers, but do not expose them as first-level tabs in this module.
        self._notes_tab = self._build_notes_tab()
        self._errors_tab = self._build_error_tab()
        self._notes_tab.hide()
        self._errors_tab.hide()

        self.refresh_context()

    def refresh_context(self) -> None:
        self._refresh_workflows()
        self._refresh_notes()
        self._refresh_error_reviews()

    def clear_filter(self) -> None:
        return

    def _build_workflow_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar_widget = QWidget()
        toolbar = FlowLayout(toolbar_widget, h_spacing=6, v_spacing=6)
        self._create_template_btn = QPushButton("新增流程")
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
        left_layout.addWidget(QLabel("流程範本"))
        left_layout.addWidget(self._templates_table)
        self._workflow_empty_state = EmptyState(
            "尚無流程範本",
            detail="新增範本後，可建立執行清單並逐步勾選完成狀態。",
            action_text="新增範本",
        )
        self._workflow_empty_state.hide()
        left_layout.addWidget(self._workflow_empty_state)

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
        left_layout.addWidget(QLabel("執行中流程"))
        left_layout.addWidget(self._runs_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self._workflow_detail = QTreeWidget()
        self._workflow_detail.setHeaderLabels(["流程步驟", "狀態"])
        self._workflow_image = QLabel("尚未選擇流程圖片")
        self._workflow_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._workflow_image.setMinimumHeight(260)
        self._workflow_image.setStyleSheet(
            f"border: 1px solid {BORDER_COLOR}; color: {TEXT_MUTED};"
        )
        self._workflow_image.mousePressEvent = lambda _event: self._on_preview_workflow_image()
        right_layout.addWidget(QLabel("流程說明"))
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

    def _build_notes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        self._create_note_btn = QPushButton("新增筆記")
        self._save_note_btn = QPushButton("儲存畫布")
        self._add_text_btn = QPushButton("文字")
        self._insert_image_btn = QPushButton("插入圖片")
        self._freehand_btn = QPushButton("手繪")
        self._freehand_btn.setCheckable(True)
        self._red_box_btn = QPushButton("紅框")
        self._highlight_btn = QPushButton("螢光筆")
        self._export_pdf_btn = QPushButton("匯出 PDF")
        for btn, icon in (
            (self._create_note_btn, "new"),
            (self._save_note_btn, "save"),
            (self._add_text_btn, "edit"),
            (self._insert_image_btn, "upload"),
            (self._freehand_btn, "edit"),
            (self._red_box_btn, "edit"),
            (self._highlight_btn, "edit"),
            (self._export_pdf_btn, "export"),
        ):
            btn.setIcon(toolbar_icon(icon))
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._notes_table = QTableWidget(0, 2)
        self._notes_table.setHorizontalHeaderLabels(["ID", "筆記"])
        self._notes_table.setMaximumWidth(240)
        self._notes_table.setColumnHidden(0, True)
        self._notes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self._notes_table)

        self._note_scene = QGraphicsScene()
        self._note_view = _CanvasView(self._note_scene)
        splitter.addWidget(self._note_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 620])
        layout.addWidget(splitter, stretch=1)

        self._create_note_btn.clicked.connect(self._on_create_note)
        self._save_note_btn.clicked.connect(self._on_save_note)
        self._add_text_btn.clicked.connect(self._on_add_text_box)
        self._insert_image_btn.clicked.connect(self._on_insert_image)
        self._freehand_btn.clicked.connect(self._on_toggle_freehand)
        self._red_box_btn.clicked.connect(lambda: self._add_shape("red_box"))
        self._highlight_btn.clicked.connect(lambda: self._add_shape("yellow_highlight"))
        self._export_pdf_btn.clicked.connect(self._on_export_note_pdf)
        self._notes_table.itemSelectionChanged.connect(self._on_note_selection_changed)
        self._load_scene(default_scene_json())
        return page

    def _build_error_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self._error_title = QLineEdit()
        self._phenomenon = QTextEdit()
        self._root_cause = QTextEdit()
        self._short_fix = QTextEdit()
        self._long_guard = QTextEdit()
        self._severity = QComboBox()
        self._severity.addItems(["low", "medium", "high"])
        self._template_combo = QComboBox()
        self._guard_step = QLineEdit()
        form.addRow("標題", self._error_title)
        form.addRow("失誤現象", self._phenomenon)
        form.addRow("根本原因", self._root_cause)
        form.addRow("短期補救", self._short_fix)
        form.addRow("長期防呆", self._long_guard)
        form.addRow("嚴重程度", self._severity)
        form.addRow("關聯流程範本", self._template_combo)
        form.addRow("追加防呆步驟", self._guard_step)
        layout.addLayout(form)
        self._create_error_btn = QPushButton("新增錯誤回顧並追加防呆")
        self._create_error_btn.setIcon(toolbar_icon("new"))
        layout.addWidget(self._create_error_btn)
        self._errors_table = QTableWidget(0, 4)
        self._errors_table.setHorizontalHeaderLabels(["編號", "標題", "嚴重程度", "關聯範本"])
        layout.addWidget(self._errors_table)
        self._create_error_btn.clicked.connect(self._on_create_error_review)
        return page

    def _refresh_workflows(self) -> None:
        templates = self._container.work_records.list_templates()
        self._templates_table.setRowCount(len(templates))
        has_templates = len(templates) > 0
        self._templates_table.setVisible(has_templates)
        self._workflow_empty_state.setVisible(not has_templates)
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        self._template_combo.addItem("不關聯", userData=None)
        for row_idx, template in enumerate(templates):
            done, total, percent = self._container.work_records.progress_for_stages_json(
                template.stages_json
            )
            values = [str(template.id), template.name, str(template.version), f"{done}/{total} ({percent}%)"]
            for col, value in enumerate(values):
                self._templates_table.setItem(row_idx, col, QTableWidgetItem(value))
            self._template_combo.addItem(template.name, userData=template.id)
        self._template_combo.blockSignals(False)

        runs = self._container.work_records.list_runs()
        self._runs_table.setRowCount(len(runs))
        for row_idx, run in enumerate(runs):
            done, total, percent = self._container.work_records.progress_for_stages_json(
                run.stages_json
            )
            values = [str(run.id), run.name, str(run.template_id or ""), f"{done}/{total} ({percent}%)"]
            for col, value in enumerate(values):
                self._runs_table.setItem(row_idx, col, QTableWidgetItem(value))
        self._update_workflow_detail()

    def _refresh_notes(self) -> None:
        notes = self._container.canvas_notes.list_notes()
        self._notes_table.setRowCount(len(notes))
        for row_idx, note in enumerate(notes):
            for col, value in enumerate((str(note.id), note.title)):
                self._notes_table.setItem(row_idx, col, QTableWidgetItem(value))
        if self._current_note_id is None and notes:
            self._notes_table.selectRow(0)

    def _selected_note_id(self) -> int | None:
        row = self._notes_table.currentRow()
        if row < 0:
            return None
        item = self._notes_table.item(row, 0)
        return int(item.text()) if item else None

    def _on_note_selection_changed(self) -> None:
        note_id = self._selected_note_id()
        if note_id is None:
            return
        note = self._container.canvas_notes.get_note(note_id)
        if note is None:
            return
        self._current_note_id = note.id
        self._load_scene(note.scene_json)

    def _load_scene(self, scene_json: str) -> None:
        try:
            scene = json.loads(scene_json)
        except json.JSONDecodeError:
            scene = json.loads(default_scene_json())
        self._note_scene.clear()
        self._note_scene.setSceneRect(-400, -300, A4_WIDTH + 800, A4_HEIGHT + 600)
        page_item = self._note_scene.addRect(
            QRectF(0, 0, A4_WIDTH, A4_HEIGHT),
            QPen(QColor("#CBD5E1"), 2),
            QBrush(QColor("white")),
        )
        page_item.setData(0, "page")
        page_item.setZValue(-10)
        for obj in scene.get("objects", []):
            self._add_object_from_json(obj)

    def _serialize_scene(self) -> str:
        objects: list[dict] = []
        for item in self._note_scene.items():
            kind = item.data(0)
            if kind == "text_box" and isinstance(item, QGraphicsTextItem):
                pos = item.pos()
                objects.append({
                    "id": str(item.data(1) or "text_box"),
                    "type": "text_box",
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": item.textWidth(),
                    "height": item.boundingRect().height(),
                    "html": item.toHtml(),
                })
            elif kind == "image" and isinstance(item, QGraphicsPixmapItem):
                pos = item.pos()
                rect = item.boundingRect()
                objects.append({
                    "id": str(item.data(2) or "image"),
                    "type": "image",
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": rect.width(),
                    "height": rect.height(),
                    "asset_path": str(item.data(1) or ""),
                })
            elif kind == "shape" and isinstance(item, QGraphicsRectItem):
                pos = item.pos()
                rect = item.rect()
                objects.append({
                    "id": str(item.data(2) or "shape"),
                    "type": "shape",
                    "shape": str(item.data(1) or "red_box"),
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": rect.width(),
                    "height": rect.height(),
                })
            elif kind == "freehand" and isinstance(item, QGraphicsPathItem):
                objects.append({
                    "id": str(item.data(1) or "freehand"),
                    "type": "freehand",
                    "points": item.data(2) or [],
                    "color": "#DC2626",
                    "width_px": 3,
                })
        return json.dumps(
            {
                "version": 1,
                "grid_size": GRID_SIZE,
                "pages": [{"id": "page_1", "x": 0, "y": 0, "width": A4_WIDTH, "height": A4_HEIGHT}],
                "objects": objects,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _add_object_from_json(self, obj: dict) -> None:
        kind = obj.get("type")
        if kind == "text_box":
            item = _SnapTextItem()
            item.setHtml(str(obj.get("html") or "<p>文字</p>"))
            item.setTextWidth(float(obj.get("width", 180)))
            item.setPos(float(obj.get("x", 40)), float(obj.get("y", 40)))
            item.setData(0, "text_box")
            item.setData(1, obj.get("id") or "text_box")
            item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._note_scene.addItem(item)
        elif kind == "image":
            try:
                asset_path = safe_asset_path(str(obj.get("asset_path") or ""))
            except CanvasNoteValidationError:
                return
            pix = QPixmap(str(self._container.canvas_notes.note_assets_dir / asset_path))
            if pix.isNull():
                return
            item = QGraphicsPixmapItem(pix.scaled(
                int(float(obj.get("width", 240))),
                int(float(obj.get("height", 160))),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            item.setPos(float(obj.get("x", 56)), float(obj.get("y", 56)))
            item.setData(0, "image")
            item.setData(1, asset_path)
            item.setData(2, obj.get("id") or "image")
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._note_scene.addItem(item)
        elif kind == "shape":
            self._add_shape(
                str(obj.get("shape") or "red_box"),
                x=float(obj.get("x", 80)),
                y=float(obj.get("y", 80)),
                width=float(obj.get("width", 160)),
                height=float(obj.get("height", 80)),
            )
        elif kind == "freehand":
            points = obj.get("points") or []
            if not points:
                return
            path = QPainterPath(QPointF(float(points[0][0]), float(points[0][1])))
            for point in points[1:]:
                path.lineTo(float(point[0]), float(point[1]))
            item = QGraphicsPathItem(path)
            item.setPen(QPen(QColor(str(obj.get("color") or "#DC2626")), float(obj.get("width_px", 3))))
            item.setData(0, "freehand")
            item.setData(1, obj.get("id") or "freehand")
            item.setData(2, points)
            self._note_scene.addItem(item)

    def _on_create_note(self) -> None:
        title, ok = QInputDialog.getText(self, "新增筆記", "筆記標題")
        if not ok:
            return
        try:
            note = self._container.canvas_notes.create_note(CreateCanvasNoteInput(title=title))
        except CanvasNoteValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
            return
        self._current_note_id = note.id
        self.refresh_context()

    def _on_save_note(self) -> None:
        note_id = self._current_note_id or self._selected_note_id()
        if note_id is None:
            return
        note = self._container.canvas_notes.get_note(note_id)
        if note is None:
            return
        try:
            self._container.canvas_notes.update_note(
                note_id,
                title=note.title,
                scene_json=self._serialize_scene(),
            )
        except CanvasNoteValidationError as err:
            QMessageBox.warning(self, "儲存失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_add_text_box(self) -> None:
        self._add_object_from_json({
            "id": "text_box",
            "type": "text_box",
            "x": 40,
            "y": 40,
            "width": 220,
            "html": "<p><b>文字</b></p>",
        })

    def _on_insert_image(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "插入圖片",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if not file_name:
            return
        try:
            asset_path = self._container.canvas_notes.import_image_asset(Path(file_name))
        except CanvasNoteValidationError as err:
            QMessageBox.warning(self, "插入失敗", error_message(err.code))
            return
        self._add_object_from_json({
            "id": "image",
            "type": "image",
            "asset_path": asset_path,
            "x": 64,
            "y": 64,
            "width": 240,
            "height": 160,
        })

    def _on_toggle_freehand(self) -> None:
        self._note_view.set_drawing(self._freehand_btn.isChecked())

    def _add_shape(
        self,
        shape: str,
        *,
        x: float = 80,
        y: float = 80,
        width: float = 160,
        height: float = 80,
    ) -> None:
        item = _SnapRectItem(QRectF(0, 0, width, height))
        item.setPos(x, y)
        item.setData(0, "shape")
        item.setData(1, shape)
        item.setData(2, "shape")
        if shape == "yellow_highlight":
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QBrush(QColor(255, 242, 128, 110)))
            item.setZValue(-1)
        else:
            item.setPen(QPen(QColor("#DC2626"), 3))
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self._note_scene.addItem(item)

    def _on_export_note_pdf(self) -> None:
        note_id = self._current_note_id or self._selected_note_id()
        if note_id is None:
            return
        self._on_save_note()
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "匯出 PDF",
            "canvas-note.pdf",
            "PDF (*.pdf)",
        )
        if not file_name:
            return
        try:
            self._container.canvas_notes.export_pdf(note_id, Path(file_name))
        except CanvasNoteValidationError as err:
            QMessageBox.warning(self, "匯出失敗", error_message(err.code))

    def _refresh_error_reviews(self) -> None:
        reviews = self._container.work_records.list_error_reviews()
        self._errors_table.setRowCount(len(reviews))
        for row_idx, review in enumerate(reviews):
            values = [
                str(review.id),
                review.title,
                review.severity,
                str(review.workflow_template_id or ""),
            ]
            for col, value in enumerate(values):
                self._errors_table.setItem(row_idx, col, QTableWidgetItem(value))

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

    def _selected_error_review_id(self) -> int | None:
        row = self._errors_table.currentRow()
        if row < 0:
            return None
        item = self._errors_table.item(row, 0)
        return int(item.text()) if item else None

    def _select_error_review(self, review_id: int) -> None:
        for row in range(self._errors_table.rowCount()):
            item = self._errors_table.item(row, 0)
            if item and item.text() == str(review_id):
                self._errors_table.selectRow(row)
                self._errors_table.scrollToItem(item)
                self._errors_table.setFocus()
                return

    def _selected_image_template_id(self) -> int | None:
        template_id = self._selected_template_id()
        if template_id is not None:
            return template_id
        run_id = self._selected_run_id()
        if run_id is None:
            return None
        run = next((r for r in self._container.work_records.list_runs() if r.id == run_id), None)
        return run.template_id if run else None

    def _selected_workflow_step(self) -> tuple[int, str, str, bool] | None:
        item = self._workflow_detail.currentItem()
        if item is None or item.data(0, _TREE_KIND_ROLE) != "step":
            return None
        run_id = item.data(0, _TREE_RUN_ID_ROLE)
        stage_id = item.data(0, _TREE_STAGE_ID_ROLE)
        item_id = item.data(0, _TREE_ITEM_ID_ROLE)
        if run_id is None or not stage_id or not item_id:
            return None
        return int(run_id), str(stage_id), str(item_id), bool(item.data(0, _TREE_DONE_ROLE))

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
        selected = self._selected_workflow_step()
        if selected is None:
            return None
        run_id, stage_id, item_id, _done = selected
        run = next((r for r in self._container.work_records.list_runs() if r.id == run_id), None)
        if run is None:
            return None
        for stage in self._container.work_records.stages_for_row(run):
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
        stages = self._container.work_records.stages_for_row(row)
        summary = QTreeWidgetItem([f"{row_kind}：{row.name}", f"{done}/{total} ({percent}%)"])
        summary.setData(0, _TREE_KIND_ROLE, "summary")
        self._workflow_detail.addTopLevelItem(summary)
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

    def _on_create_template(self) -> None:
        dlg = WorkflowTemplateDialog(title="新增流程", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._container.work_records.create_template(dlg.payload())
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
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
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._container.work_records.update_template(template_id, dlg.payload())
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "編輯失敗", error_message(err.code))
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
        selected_step = self._selected_workflow_step()
        template_id = self._selected_image_template_id()
        if selected_step is None and template_id is None:
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
            if selected_step is not None:
                run_id, stage_id, item_id, _done = selected_step
                self._container.work_records.set_run_step_image_path(
                    run_id,
                    stage_id=stage_id,
                    item_id=item_id,
                    image_path=file_name,
                )
            else:
                assert template_id is not None
                self._container.work_records.set_template_image_path(template_id, file_name)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "圖片更新失敗", error_message(err.code))
            return
        self.refresh_context()

    def _on_paste_template_image(self) -> None:
        selected_step = self._selected_workflow_step()
        template_id = self._selected_image_template_id()
        if selected_step is None and template_id is None:
            return
        pix = QApplication.clipboard().pixmap()
        if pix.isNull():
            QMessageBox.warning(self, "貼上失敗", "剪貼簿沒有可用圖片")
            return
        rel = Path("images") / f"{uuid4().hex}.png"
        try:
            dest = self._container.work_records.workflow_assets_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not pix.save(str(dest), "PNG"):
                raise WorkRecordValidationError("work_record.asset.image_invalid")
            if selected_step is not None:
                run_id, stage_id, item_id, _done = selected_step
                self._container.work_records.set_run_step_image_asset(
                    run_id,
                    stage_id=stage_id,
                    item_id=item_id,
                    rel_path=rel.as_posix(),
                    width=pix.width(),
                    height=pix.height(),
                )
            else:
                assert template_id is not None
                self._container.work_records.set_template_image_asset(
                    template_id,
                    rel.as_posix(),
                    width=pix.width(),
                    height=pix.height(),
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
        self.refresh_context()

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

    def _on_create_error_review(self) -> None:
        template_id = self._template_combo.currentData()
        try:
            review = self._container.work_records.create_error_review(
                CreateErrorReviewInput(
                    title=self._error_title.text(),
                    phenomenon=self._phenomenon.toPlainText(),
                    root_cause=self._root_cause.toPlainText(),
                    short_term_fix=self._short_fix.toPlainText(),
                    long_term_guard=self._long_guard.toPlainText(),
                    severity=self._severity.currentText(),
                    workflow_template_id=template_id,
                    guard_stage_id=None,
                    guard_step_text=self._guard_step.text(),
                )
            )
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "新增失敗", error_message(err.code))
            return
        self._error_title.clear()
        self._phenomenon.clear()
        self._root_cause.clear()
        self._short_fix.clear()
        self._long_guard.clear()
        self._guard_step.clear()
        self.refresh_context()
        self._select_error_review(review.id)
