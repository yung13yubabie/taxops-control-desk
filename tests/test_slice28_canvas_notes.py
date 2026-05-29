"""v0.20.0 Work Records A4 canvas notes."""

from __future__ import annotations

import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QInputDialog

from taxops.services.canvas_notes import (
    A4_HEIGHT,
    A4_WIDTH,
    CreateCanvasNoteInput,
    CanvasNoteValidationError,
)
from taxops.ui.action_registry import PAGE_WORK_RECORDS, actions_for_page
from taxops.ui.pages.work_records_page import WorkRecordsPage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_canvas_notes_table_exists(db_conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in db_conn.execute("PRAGMA table_info(canvas_notes)").fetchall()
    }
    assert {"title", "scene_json", "client_id", "engagement_id", "context_snapshot"}.issubset(cols)


def test_create_canvas_note_has_a4_page_and_grid(container) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="客戶會議筆記"))
    scene = json.loads(note.scene_json)

    assert scene["grid_size"] == 8
    assert scene["pages"][0]["width"] == A4_WIDTH
    assert scene["pages"][0]["height"] == A4_HEIGHT
    assert scene["objects"] == []


def test_update_canvas_note_sanitizes_controlled_html(container) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="HTML 筆記"))
    scene = json.loads(note.scene_json)
    scene["objects"].append(
        {
            "id": "t1",
            "type": "text_box",
            "x": 16,
            "y": 16,
            "width": 200,
            "height": 80,
            "html": '<p><b>保留</b><script>alert(1)</script><span style="color: red; background-image: url(x)">紅字</span></p>',
        }
    )

    updated = container.canvas_notes.update_note(
        note.id,
        title=note.title,
        scene_json=json.dumps(scene),
    )

    assert "<script>" not in updated.scene_json
    assert "alert(1)" not in updated.scene_json
    assert "background-image" not in updated.scene_json
    assert "<b>保留</b>" in updated.scene_json
    assert "color: red" in updated.scene_json


def test_import_image_asset_copies_to_note_assets(container, tmp_path) -> None:
    image_path = tmp_path / "source.png"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(image_path))

    rel = container.canvas_notes.import_image_asset(image_path)

    assert rel.startswith("images/")
    assert (container.canvas_notes.note_assets_dir / rel).is_file()


def test_export_canvas_note_pdf_writes_file(qapp, container, tmp_path) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="PDF 筆記"))
    scene = json.loads(note.scene_json)
    scene["objects"].append(
        {
            "id": "t1",
            "type": "text_box",
            "x": 48,
            "y": 48,
            "width": 240,
            "height": 80,
            "html": "<p><b>PDF 內容</b></p>",
        }
    )
    container.canvas_notes.update_note(note.id, title=note.title, scene_json=json.dumps(scene))

    output = container.canvas_notes.export_pdf(note.id, tmp_path / "note.pdf")

    assert output.is_file()
    assert output.stat().st_size > 0


def test_import_image_rejects_non_image(container, tmp_path) -> None:
    source = tmp_path / "bad.txt"
    source.write_text("no", encoding="utf-8")

    with pytest.raises(CanvasNoteValidationError) as ei:
        container.canvas_notes.import_image_asset(source)
    assert ei.value.code == "canvas_note.asset.extension_invalid"


def test_update_canvas_note_rejects_asset_path_traversal(container) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="圖片路徑"))
    scene = json.loads(note.scene_json)
    scene["objects"].append(
        {
            "id": "img",
            "type": "image",
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
            "asset_path": "../outside.png",
        }
    )

    with pytest.raises(CanvasNoteValidationError) as ei:
        container.canvas_notes.update_note(
            note.id,
            title=note.title,
            scene_json=json.dumps(scene),
        )
    assert ei.value.code == "canvas_note.asset.path_invalid"


def test_work_records_canvas_note_ui_creates_and_saves_scene(qapp, container, monkeypatch) -> None:
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("畫布筆記", True),
    )
    page = WorkRecordsPage(container)
    page._on_create_note()
    page._on_add_text_box()
    page._add_shape("red_box")
    page._add_shape("yellow_highlight")
    page._on_save_note()

    notes = container.canvas_notes.list_notes()
    assert len(notes) == 1
    scene = json.loads(notes[0].scene_json)
    types = {obj["type"] for obj in scene["objects"]}
    shapes = {obj.get("shape") for obj in scene["objects"] if obj["type"] == "shape"}
    assert "text_box" in types
    assert shapes == {"red_box", "yellow_highlight"}


def test_canvas_note_action_registry_contracts() -> None:
    labels = {contract.button_label: contract for contract in actions_for_page(PAGE_WORK_RECORDS)}

    assert labels["新增筆記"].service == "CanvasNotesService.create_note"
    assert labels["儲存畫布"].repository == "CanvasNotesRepository.update"
    assert labels["插入圖片"].service == "CanvasNotesService.import_image_asset"
    assert labels["匯出 PDF"].audit_action == "canvas_note.export_pdf"
