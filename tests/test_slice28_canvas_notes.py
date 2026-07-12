"""v0.20.0 Work Records A4 canvas notes."""

from __future__ import annotations

import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsTextItem
from PySide6.QtWidgets import QApplication, QInputDialog

from taxops.services.canvas_notes import (
    A4_HEIGHT,
    A4_WIDTH,
    CreateCanvasNoteInput,
    CanvasNoteValidationError,
)
from taxops.ui.action_registry import PAGE_WORK_RECORDS, actions_for_page


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


def test_create_canvas_note_rejects_mismatched_client_and_engagement(container) -> None:
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput

    client_a = container.clients.create_client(CreateClientInput(
        client_code="NOTE-CTX-A",
        client_name="Note context A",
    ))
    client_b = container.clients.create_client(CreateClientInput(
        client_code="NOTE-CTX-B",
        client_name="Note context B",
    ))
    engagement_b = container.engagements.create_engagement(CreateEngagementInput(
        client_id=client_b.id,
        engagement_name="Note engagement B",
        tax_type="vat",
        period_name="2026-07",
    ))

    with pytest.raises(CanvasNoteValidationError) as exc:
        container.canvas_notes.create_note(CreateCanvasNoteInput(
            title="Cross-client canvas note",
            client_id=client_a.id,
            engagement_id=engagement_b.id,
        ))

    assert exc.value.code == "canvas_note.context_mismatch"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM canvas_notes"
        " WHERE title = 'Cross-client canvas note'"
    ).fetchone()[0] == 0


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


def test_export_canvas_note_pdf_rejects_unsafe_db_asset_path(container, tmp_path) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="DB 注入圖片"))
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
    container.canvas_notes._repo.update(
        note.id,
        title=note.title,
        scene_json=json.dumps(scene),
    )

    with pytest.raises(CanvasNoteValidationError) as ei:
        container.canvas_notes.export_pdf(note.id, tmp_path / "blocked.pdf")
    assert ei.value.code == "canvas_note.asset.path_invalid"


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


def test_controlled_html_sanitizer_drops_active_content_and_unsafe_styles() -> None:
    from taxops.services.canvas_notes import sanitize_controlled_html

    cleaned = sanitize_controlled_html(
        '<div>Hello & <script>alert(1)</script>'
        '<span style="color: red; background-image: url(x); '
        'font-weight: bold; bad-declaration">World</span>'
        '<iframe>secret</iframe><br></div>'
    )

    assert "Hello &amp;" in cleaned
    assert "World" in cleaned
    assert "color: red" in cleaned
    assert "font-weight: bold" in cleaned
    assert "script" not in cleaned
    assert "alert" not in cleaned
    assert "iframe" not in cleaned
    assert "secret" not in cleaned
    assert "url(" not in cleaned


@pytest.mark.parametrize(
    "scene",
    [
        "not json",
        "[]",
        json.dumps({"pages": [], "objects": []}),
        json.dumps({"pages": [{}], "objects": []}),
        json.dumps({"pages": [{"width": 1, "height": 1}], "objects": {}}),
    ],
)
def test_scene_loader_rejects_invalid_shapes(scene) -> None:
    from taxops.services.canvas_notes import CanvasNoteValidationError, _load_scene

    with pytest.raises(CanvasNoteValidationError) as exc:
        _load_scene(scene)
    assert exc.value.code == "canvas_note.scene.invalid"


@pytest.mark.parametrize(
    "points",
    ["not-a-list", [[0]], [["not-a-number", 1]]],
)
def test_scene_normalizer_rejects_malformed_freehand_points(points) -> None:
    from taxops.services.canvas_notes import (
        CanvasNoteValidationError,
        _normalized_scene_json,
    )

    scene = {
        "pages": [{"width": 794, "height": 1123}],
        "objects": [{"type": "freehand", "points": points}],
    }
    with pytest.raises(CanvasNoteValidationError) as exc:
        _normalized_scene_json(json.dumps(scene))
    assert exc.value.code == "canvas_note.scene.invalid"


def test_scene_normalizer_skips_unknown_objects_and_invalid_shapes() -> None:
    from taxops.services.canvas_notes import _normalized_scene_json

    scene = {
        "pages": [{"width": 794, "height": 1123}],
        "objects": [
            "not-an-object",
            {"type": "unknown"},
            {"type": "shape", "shape": "triangle"},
            {"type": "text_box", "html": "<b>kept</b>"},
        ],
    }

    normalized = json.loads(_normalized_scene_json(json.dumps(scene)))

    assert len(normalized["objects"]) == 1
    assert normalized["objects"][0]["type"] == "text_box"
    assert normalized["grid_size"] > 0


@pytest.mark.parametrize("raw", ["", "../escape.png", "/absolute.png"])
def test_safe_asset_path_rejects_empty_absolute_and_traversal(raw) -> None:
    from taxops.services.canvas_notes import CanvasNoteValidationError, safe_asset_path

    with pytest.raises(CanvasNoteValidationError) as exc:
        safe_asset_path(raw)
    assert exc.value.code == "canvas_note.asset.path_invalid"


def test_canvas_note_action_registry_contracts() -> None:
    labels = {contract.button_label: contract for contract in actions_for_page(PAGE_WORK_RECORDS)}

    for label in ("新增筆記", "儲存畫布", "插入圖片", "匯出 PDF"):
        assert labels[label].enabled is False
        assert labels[label].service is None


def test_canvas_note_context_and_title_guards_reject_missing_targets(container) -> None:
    for payload, code in (
        (CreateCanvasNoteInput(title=""), "canvas_note.title.required"),
        (
            CreateCanvasNoteInput(title="不存在客戶", client_id=999999),
            "canvas_note.context_not_found",
        ),
        (
            CreateCanvasNoteInput(title="不存在案件", engagement_id=999999),
            "canvas_note.context_not_found",
        ),
    ):
        with pytest.raises(CanvasNoteValidationError) as exc:
            container.canvas_notes.create_note(payload)
        assert exc.value.code == code


def test_canvas_note_update_and_export_missing_targets_are_rejected(container, tmp_path) -> None:
    with pytest.raises(CanvasNoteValidationError) as update_exc:
        container.canvas_notes.update_note(
            999999,
            title="不存在筆記",
            scene_json=json.dumps(
                {"pages": [{"width": A4_WIDTH, "height": A4_HEIGHT}], "objects": []}
            ),
        )
    assert update_exc.value.code == "canvas_note.not_found"

    with pytest.raises(CanvasNoteValidationError) as export_exc:
        container.canvas_notes.export_pdf(999999, tmp_path / "missing.pdf")
    assert export_exc.value.code == "canvas_note.not_found"


def test_scene_normalizer_rejects_object_and_freehand_resource_exhaustion(monkeypatch) -> None:
    import taxops.services.canvas_notes as module

    monkeypatch.setattr(module, "_MAX_SCENE_OBJECTS", 1)
    scene = {
        "pages": [{"width": A4_WIDTH, "height": A4_HEIGHT}],
        "objects": [{"type": "text_box"}, {"type": "text_box"}],
    }
    with pytest.raises(CanvasNoteValidationError) as objects_exc:
        module._normalized_scene_json(json.dumps(scene))
    assert objects_exc.value.code == "canvas_note.scene.invalid"

    monkeypatch.setattr(module, "_MAX_SCENE_OBJECTS", 10)
    monkeypatch.setattr(module, "_MAX_FREEHAND_POINTS", 1)
    scene["objects"] = [{"type": "freehand", "points": [[0, 0], [1, 1]]}]
    with pytest.raises(CanvasNoteValidationError) as points_exc:
        module._normalized_scene_json(json.dumps(scene))
    assert points_exc.value.code == "canvas_note.scene.invalid"


def test_html_sanitizer_handles_nested_dropped_and_unsupported_markup() -> None:
    from taxops.services.canvas_notes import sanitize_controlled_html

    cleaned = sanitize_controlled_html(
        '<script><b>drop nested</b></script><unknown>保留文字</unknown>'
        '<span>無 style</span><span style="color: blue; broken; font-weight:bold">安全</span>'
    )

    assert "drop nested" not in cleaned
    assert "unknown" not in cleaned
    assert "保留文字" in cleaned
    assert "<span>無 style</span>" in cleaned
    assert "color: blue" in cleaned
    assert "font-weight: bold" in cleaned


def test_export_pdf_renders_multiple_pages_and_all_supported_objects(
    qapp, container, tmp_path
) -> None:
    note = container.canvas_notes.create_note(CreateCanvasNoteInput(title="完整 PDF 場景"))
    scene = {
        "version": 1,
        "pages": [
            {"id": "page_1", "width": A4_WIDTH, "height": A4_HEIGHT},
            {"id": "page_2", "width": A4_WIDTH, "height": A4_HEIGHT},
        ],
        "objects": [
            {"type": "text_box", "x": 10, "y": 10, "width": 180, "height": 60, "html": "<b>中文字</b>"},
            {"type": "image", "x": 10, "y": 90, "width": 50, "height": 50, "asset_path": "images/missing.png"},
            {"type": "shape", "shape": "yellow_highlight", "x": 10, "y": 160, "width": 100, "height": 20},
            {"type": "shape", "shape": "red_box", "x": 10, "y": 200, "width": 100, "height": 40},
            {"type": "freehand", "x": 0, "y": 0, "width": 50, "height": 50, "points": [[10, 270], [20, 280], [30, 275]]},
            {"type": "freehand", "x": 0, "y": 0, "width": 20, "height": 20, "points": [[1, 1]]},
            {"type": "shape", "shape": "red_box", "x": 99999, "y": 99999, "width": 10, "height": 10},
        ],
    }
    container.canvas_notes.update_note(
        note.id, title=note.title, scene_json=json.dumps(scene)
    )

    output = container.canvas_notes.export_pdf(note.id, tmp_path / "complete-scene.pdf")

    assert output.is_file()
    assert output.stat().st_size > 100
    audit = container.conn.execute(
        "SELECT action FROM audit_logs WHERE target_type = 'canvas_note' AND target_id = ? ORDER BY id DESC LIMIT 1",
        (str(note.id),),
    ).fetchone()
    assert audit[0] == "canvas_note.export_pdf"
