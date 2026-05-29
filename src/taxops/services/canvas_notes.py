"""Canvas-note service and A4 PDF renderer."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPageSize, QPdfWriter, QPen, QPixmap, QTextDocument

from ..core.text import sanitize_user_text
from ..repositories.canvas_notes import CanvasNoteRow, CanvasNotesRepository
from .audit import AuditService

A4_WIDTH = 595.0
A4_HEIGHT = 842.0
GRID_SIZE = 8
VALID_OBJECT_TYPES = frozenset({"text_box", "image", "freehand", "shape"})
VALID_SHAPES = frozenset({"red_box", "yellow_highlight"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


class CanvasNoteValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateCanvasNoteInput:
    title: str
    client_id: int | None = None
    engagement_id: int | None = None


def default_scene_json() -> str:
    return json.dumps(
        {
            "version": 1,
            "grid_size": GRID_SIZE,
            "pages": [{"id": "page_1", "x": 0, "y": 0, "width": A4_WIDTH, "height": A4_HEIGHT}],
            "objects": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class _ControlledHtmlParser(HTMLParser):
    _ALLOWED_TAGS = frozenset({"p", "b", "strong", "i", "em", "u", "span", "br", "div"})
    _ALLOWED_STYLES = frozenset({"color", "background-color", "font-weight"})
    _DROP_WITH_CONTENT = frozenset({"script", "style", "iframe", "object"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROP_WITH_CONTENT:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag not in self._ALLOWED_TAGS:
            return
        if tag == "span":
            style = self._clean_style(dict(attrs).get("style"))
            if style:
                self.parts.append(f'<span style="{html.escape(style, quote=True)}">')
                return
        self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROP_WITH_CONTENT and self._drop_depth:
            self._drop_depth -= 1
            return
        if self._drop_depth:
            return
        if tag in self._ALLOWED_TAGS and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        self.parts.append(html.escape(data))

    def _clean_style(self, raw: str | None) -> str:
        if not raw:
            return ""
        safe: list[str] = []
        for declaration in raw.split(";"):
            if ":" not in declaration:
                continue
            key, value = declaration.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key not in self._ALLOWED_STYLES:
                continue
            if any(token in value.lower() for token in ("url(", "expression", "javascript:")):
                continue
            safe.append(f"{key}: {value}")
        return "; ".join(safe)


def sanitize_controlled_html(raw: str) -> str:
    parser = _ControlledHtmlParser()
    parser.feed(raw or "")
    cleaned = "".join(parser.parts).strip()
    return cleaned or "<p></p>"


def _load_scene(scene_json: str) -> dict:
    try:
        scene = json.loads(scene_json)
    except json.JSONDecodeError as err:
        raise CanvasNoteValidationError("canvas_note.scene.invalid") from err
    if not isinstance(scene, dict):
        raise CanvasNoteValidationError("canvas_note.scene.invalid")
    pages = scene.get("pages")
    objects = scene.get("objects")
    if not isinstance(pages, list) or not pages:
        raise CanvasNoteValidationError("canvas_note.scene.invalid")
    if not isinstance(objects, list):
        raise CanvasNoteValidationError("canvas_note.scene.invalid")
    return scene


def _normalized_scene_json(scene_json: str) -> str:
    scene = _load_scene(scene_json)
    normalized_objects: list[dict] = []
    for obj in scene["objects"]:
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        if kind not in VALID_OBJECT_TYPES:
            continue
        clean = dict(obj)
        clean["id"] = sanitize_user_text(str(clean.get("id") or f"obj_{uuid4().hex[:10]}"), max_length=80)
        if kind == "text_box":
            clean["html"] = sanitize_controlled_html(str(clean.get("html") or ""))
        if kind == "image":
            clean["asset_path"] = _safe_asset_path(str(clean.get("asset_path") or ""))
        if kind == "shape" and clean.get("shape") not in VALID_SHAPES:
            continue
        normalized_objects.append(clean)
    scene["objects"] = normalized_objects
    scene["grid_size"] = GRID_SIZE
    return json.dumps(scene, ensure_ascii=False, separators=(",", ":"))


def _safe_asset_path(raw: str) -> str:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or not raw:
        raise CanvasNoteValidationError("canvas_note.asset.path_invalid")
    return path.as_posix()


class CanvasNotesService:
    def __init__(
        self,
        repo: CanvasNotesRepository,
        audit: AuditService,
        note_assets_dir: Path,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._note_assets_dir = note_assets_dir

    @property
    def note_assets_dir(self) -> Path:
        return self._note_assets_dir

    def create_note(self, payload: CreateCanvasNoteInput) -> CanvasNoteRow:
        title = sanitize_user_text(payload.title, max_length=200)
        if not title:
            raise CanvasNoteValidationError("canvas_note.title.required")
        row = self._repo.insert(
            title=title,
            scene_json=default_scene_json(),
            client_id=payload.client_id,
            engagement_id=payload.engagement_id,
            context_snapshot=None,
        )
        self._audit.record(
            action="canvas_note.create",
            target_type="canvas_note",
            target_id=str(row.id),
            detail={"title": row.title},
        )
        return row

    def update_note(self, note_id: int, *, title: str, scene_json: str) -> CanvasNoteRow:
        clean_title = sanitize_user_text(title, max_length=200)
        if not clean_title:
            raise CanvasNoteValidationError("canvas_note.title.required")
        normalized = _normalized_scene_json(scene_json)
        row = self._repo.update(note_id, title=clean_title, scene_json=normalized)
        if row is None:
            raise CanvasNoteValidationError("canvas_note.not_found")
        self._audit.record(
            action="canvas_note.update",
            target_type="canvas_note",
            target_id=str(row.id),
            detail={"title": row.title},
        )
        return row

    def import_image_asset(self, source_path: Path) -> str:
        source = Path(source_path)
        ext = source.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            raise CanvasNoteValidationError("canvas_note.asset.extension_invalid")
        if not source.is_file():
            raise CanvasNoteValidationError("canvas_note.asset.not_found")
        rel = Path("images") / f"{uuid4().hex}{ext}"
        dest = self._note_assets_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return rel.as_posix()

    def list_notes(self) -> list[CanvasNoteRow]:
        return self._repo.list_all()

    def get_note(self, note_id: int) -> CanvasNoteRow | None:
        return self._repo.get(note_id)

    def export_pdf(self, note_id: int, output_path: Path) -> Path:
        note = self._repo.get(note_id)
        if note is None:
            raise CanvasNoteValidationError("canvas_note.not_found")
        scene = _load_scene(note.scene_json)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        _render_scene_to_pdf(scene, output, self._note_assets_dir)
        self._audit.record(
            action="canvas_note.export_pdf",
            target_type="canvas_note",
            target_id=str(note.id),
            detail={"output_path": str(output)},
        )
        return output


def _render_scene_to_pdf(scene: dict, output_path: Path, assets_dir: Path) -> None:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(72)
    writer.setTitle("TaxOps Canvas Note")
    painter = QPainter(writer)
    try:
        pages = scene["pages"]
        for idx, page in enumerate(pages):
            if idx:
                writer.newPage()
            page_rect = QRectF(0, 0, float(page["width"]), float(page["height"]))
            painter.fillRect(page_rect, QColor("white"))
            for obj in scene["objects"]:
                _paint_object(painter, obj, page_rect, assets_dir)
    finally:
        painter.end()


def _paint_object(painter: QPainter, obj: dict, page_rect: QRectF, assets_dir: Path) -> None:
    x = float(obj.get("x", 0))
    y = float(obj.get("y", 0))
    width = float(obj.get("width", 120))
    height = float(obj.get("height", 40))
    if not page_rect.intersects(QRectF(x, y, width, height)):
        return
    kind = obj.get("type")
    if kind == "text_box":
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Microsoft JhengHei", 10))
        doc.setHtml(str(obj.get("html") or ""))
        doc.setTextWidth(width)
        painter.save()
        painter.translate(x, y)
        doc.drawContents(painter, QRectF(0, 0, width, height))
        painter.restore()
    elif kind == "image":
        try:
            asset_path = _safe_asset_path(str(obj.get("asset_path") or ""))
        except CanvasNoteValidationError:
            return
        pix = QPixmap(str(assets_dir / asset_path))
        if not pix.isNull():
            painter.drawPixmap(QRectF(x, y, width, height).toRect(), pix)
    elif kind == "shape":
        if obj.get("shape") == "yellow_highlight":
            painter.fillRect(QRectF(x, y, width, height), QColor(255, 242, 128, 110))
        else:
            pen = QPen(QColor("#DC2626"), 3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(x, y, width, height))
    elif kind == "freehand":
        points = obj.get("points") or []
        if len(points) < 2:
            return
        pen = QPen(QColor(str(obj.get("color") or "#DC2626")), float(obj.get("width_px", 3)))
        painter.setPen(pen)
        last = points[0]
        for point in points[1:]:
            painter.drawLine(float(last[0]), float(last[1]), float(point[0]), float(point[1]))
            last = point
