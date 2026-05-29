"""Work Records page: workflow templates/runs and error reviews."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
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
)
from ...services.container import ServiceContainer
from ...services.work_records import (
    CreateErrorReviewInput,
    WorkRecordValidationError,
)
from ..style import toolbar_icon


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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("工作紀錄")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self._tabs = QTabWidget()
        self._workflow_tab = self._build_workflow_tab()
        self._notes_tab = self._build_notes_tab()
        self._errors_tab = self._build_error_tab()
        self._tabs.addTab(self._workflow_tab, "流程")
        self._tabs.addTab(self._notes_tab, "筆記")
        self._tabs.addTab(self._errors_tab, "錯誤回顧")
        outer.addWidget(self._tabs, stretch=1)

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
        toolbar = QHBoxLayout()
        self._create_standard_btn = QPushButton("建立標準公司設立流程")
        self._instantiate_btn = QPushButton("建立執行清單")
        self._toggle_first_btn = QPushButton("勾選第一步")
        self._overwrite_template_btn = QPushButton("覆蓋回原範本")
        self._save_as_template_btn = QPushButton("另存為新範本")
        for btn, icon in (
            (self._create_standard_btn, "new"),
            (self._instantiate_btn, "new"),
            (self._toggle_first_btn, "complete"),
            (self._overwrite_template_btn, "edit"),
            (self._save_as_template_btn, "new"),
        ):
            btn.setIcon(toolbar_icon(icon))
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._templates_table = QTableWidget(0, 4)
        self._templates_table.setHorizontalHeaderLabels(["編號", "範本名稱", "版本", "進度"])
        layout.addWidget(QLabel("流程範本"))
        layout.addWidget(self._templates_table)

        self._runs_table = QTableWidget(0, 4)
        self._runs_table.setHorizontalHeaderLabels(["編號", "執行名稱", "來源範本", "進度"])
        layout.addWidget(QLabel("執行中流程"))
        layout.addWidget(self._runs_table)

        self._create_standard_btn.clicked.connect(self._on_create_standard_template)
        self._instantiate_btn.clicked.connect(self._on_instantiate_run)
        self._toggle_first_btn.clicked.connect(self._on_toggle_first_run_step)
        self._overwrite_template_btn.clicked.connect(self._on_overwrite_template)
        self._save_as_template_btn.clicked.connect(self._on_save_run_as_template)
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
        splitter.addWidget(self._notes_table)

        self._note_scene = QGraphicsScene()
        self._note_view = _CanvasView(self._note_scene)
        splitter.addWidget(self._note_view)
        splitter.setStretchFactor(1, 1)
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
            pix = QPixmap(str(self._container.canvas_notes.note_assets_dir / str(obj.get("asset_path", ""))))
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
            item.setData(1, obj.get("asset_path"))
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

    def _on_toggle_first_run_step(self) -> None:
        run_id = self._selected_run_id()
        if run_id is None:
            return
        run = next((r for r in self._container.work_records.list_runs() if r.id == run_id), None)
        if run is None:
            return
        stages = self._container.work_records.stages_for_row(run)
        for stage in stages:
            items = stage.get("items", [])
            if items:
                first = items[0]
                self._container.work_records.set_run_step_done(
                    run_id,
                    stage_id=stage["id"],
                    item_id=first["id"],
                    done=not bool(first.get("done")),
                )
                break
        self.refresh_context()

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
            self._container.work_records.create_error_review(
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
