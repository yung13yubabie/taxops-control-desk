"""The opt-in artifact hook must not hide the original geometry failure."""
import json

from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

import qt_geometry_diagnostics
from qt_geometry_diagnostics import capture_qt_geometry, dump_qt_geometry


def test_no_diagnostics_env_does_not_grab_or_write(qtbot, monkeypatch, tmp_path):
    root = QWidget()
    qtbot.addWidget(root)
    monkeypatch.delenv("TAXOPS_UI_DIAGNOSTICS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(root, "grab", lambda: (_ for _ in ()).throw(AssertionError("must not grab")))
    before = list(tmp_path.iterdir())
    assert dump_qt_geometry(root, "disabled") is None
    assert list(tmp_path.iterdir()) == before


def test_diagnostic_records_named_geometry_font_layout_scroll_and_png(qtbot, qapp, monkeypatch, tmp_path):
    root = QWidget()
    qtbot.addWidget(root)
    layout = QVBoxLayout(root)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QLabel("合成測試內容")
    content.setMinimumWidth(540)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    root.resize(360, 240)
    root.show()
    qapp.processEvents()
    before = capture_qt_geometry(root, phase="before", named_widgets={"active_scroll": scroll})
    size_before = root.size()
    monkeypatch.setenv("TAXOPS_UI_DIAGNOSTICS_DIR", str(tmp_path))
    result = dump_qt_geometry(root, "../tab:0", named_widgets={"active_scroll": scroll},
                              extra={"tab_index": 0, "tab_text": "合成"}, checkpoints=[before])
    assert "diagnostic_error" not in result
    assert result["png_saved"] is True
    assert root.size() == size_before
    document = json.loads((tmp_path / "tab_0.json").read_text(encoding="utf-8"))
    assert (tmp_path / "tab_0.png").read_bytes().startswith(b"\x89PNG")
    assert document["checkpoints"][0]["phase"] == "before"
    assert document["extra"] == {"tab_index": 0, "tab_text": "合成"}
    assert document["layouts"] and document["environment"]["qt"]
    row = next(row for row in document["widgets"] if "active_scroll" in row["aliases"])
    assert row["visible"] is True
    assert row["viewport"] and row["horizontal_scroll"]["maximum"] > 0
    assert row["minimum_size"] and row["minimum_size_hint"]
    info = QFontInfo(scroll.font())
    # An offscreen backend may have no resolved font. Record that fact exactly.
    assert row["font"]["resolved_family"] == info.family()
    assert row["font"]["resolved_point_size"] == info.pointSizeF()
    assert row["font"]["resolved_pixel_size"] == info.pixelSize()
    assert row["font"]["exact_match"] == info.exactMatch()
    assert row["dpi"] == [scroll.logicalDpiX(), scroll.logicalDpiY()]
    assert all(value > 0 for value in row["dpi"])
    assert document["after_grab_size"] == [size_before.width(), size_before.height()]


def test_empty_resolved_font_family_is_preserved(qtbot, monkeypatch):
    root = QWidget()
    qtbot.addWidget(root)
    font = root.font()
    font.setFamily("Synthetic requested family")
    root.setFont(font)

    class EmptyResolvedFamily(QFontInfo):
        def family(self):
            return ""

    # Reproduce the Windows offscreen capability even on hosts with fonts.
    monkeypatch.setattr(qt_geometry_diagnostics, "QFontInfo", EmptyResolvedFamily)
    document = capture_qt_geometry(root)
    row = document["widgets"][0]
    assert row["font"]["family"] == "Synthetic requested family"
    assert row["font"]["resolved_family"] == ""
    info = QFontInfo(root.font())
    assert row["font"]["resolved_point_size"] == info.pointSizeF()
    assert row["font"]["resolved_pixel_size"] == info.pixelSize()
    assert row["font"]["exact_match"] == info.exactMatch()
    assert row["dpi"] == [root.logicalDpiX(), root.logicalDpiY()]


def test_unwritable_diagnostics_reports_error_without_masking_assert(qtbot, monkeypatch, tmp_path):
    root = QWidget()
    qtbot.addWidget(root)
    file = tmp_path / "not-a-directory"
    file.write_text("test", encoding="utf8")
    monkeypatch.setenv("TAXOPS_UI_DIAGNOSTICS_DIR", str(file))
    result = dump_qt_geometry(root, "failure")
    assert "diagnostic_error" in result
