"""Original candidate assets are deterministic and do not select a new brand."""
from __future__ import annotations

import hashlib
import struct
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtWidgets import QApplication

from build_tools import generate_app_icons as icons


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("candidate", icons.CANDIDATES)
def test_candidates_are_original_geometry_with_no_external_inputs(candidate):
    allowed = {"svg", "title", "rect", "path"}
    for name in ("mark.svg", "mark-small.svg"):
        root = ET.parse(icons.SOURCE / candidate / name).getroot()
        for element in root.iter():
            assert element.tag.rsplit("}", 1)[-1] in allowed
            assert not any("href" in key for key in element.attrib)
            assert not any("url(" in value for value in element.attrib.values())
        assert root.attrib["viewBox"] == ("0 0 16 16" if "small" in name else "0 0 256 256")


@pytest.mark.parametrize("candidate", icons.CANDIDATES)
def test_candidate_ico_contains_all_frames_and_matches_pinned_generation(candidate, qapp):
    source = icons.SOURCE / candidate / "app_icon.ico"
    data = source.read_bytes()
    assert data == icons.encode_ico(icons.candidate_images(candidate))
    assert struct.unpack_from("<HHH", data) == (0, 1, 7)
    offset = 6 + 7 * 16
    for index, size in enumerate(icons.SIZES):
        width, height, colors, reserved, planes, bpp, length, position = struct.unpack_from(
            "<BBBBHHII", data, 6 + index * 16,
        )
        assert (width or 256, height or 256) == (size, size)
        assert (colors, reserved, planes, bpp) == (0, 0, 1, 32)
        assert position == offset
        chunk = data[position:position + length]
        if size == 256:
            assert chunk.startswith(b"\x89PNG\r\n\x1a\n")
            decoded = QImage.fromData(chunk, "PNG")
            assert decoded.size() == QSize(size, size)
        else:
            assert struct.unpack_from("<IiiHH", chunk) == (40, size, size * 2, 1, 32)
        offset += length
    assert offset == len(data)
    icon = QIcon(str(source))
    assert {item.width() for item in icon.availableSizes()} == set(icons.SIZES)
    for size in icons.SIZES:
        pixmap = icon.pixmap(QSize(size, size))
        assert not pixmap.isNull()
        assert pixmap.size() == QSize(size, size)
        assert pixmap.toImage().pixelColor(0, 0).alpha() == 0
        assert pixmap.toImage().pixelColor(size // 2, size // 2).alpha() == 255


def test_dib_preserves_bgra_orientation_and_transparency_mask():
    image = QImage(3, 3, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(0, 0, QColor(1, 2, 3, 255))
    image.setPixelColor(2, 2, QColor(4, 5, 6, 128))
    data = icons._dib(image)
    assert data[40:52] == bytes((0, 0, 0, 0, 0, 0, 0, 0, 6, 5, 4, 128))
    assert data[64:76] == bytes((3, 2, 1, 255, 0, 0, 0, 0, 0, 0, 0, 0))
    assert data[76:] == bytes((0xC0, 0, 0, 0, 0xE0, 0, 0, 0, 0x60, 0, 0, 0))


@pytest.mark.parametrize("sizes", [(), ((16, 16), (16, 16)), ((16, 15),), ((257, 257),), ((0, 0),)])
def test_ico_rejects_invalid_frame_sets(sizes):
    frames = tuple(QImage(width, height, QImage.Format.Format_RGBA8888) for width, height in sizes)
    with pytest.raises(ValueError):
        icons.encode_ico(frames)


def test_invalid_svg_and_candidate_fail_loudly(tmp_path):
    invalid = tmp_path / "invalid.svg"
    invalid.write_text("<svg><rect></svg>", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid SVG"):
        icons.render_svg(invalid, 16)
    with pytest.raises(ValueError, match="Unknown"):
        icons.candidate_images("unselected")


def test_generation_is_cwd_independent_and_preserves_shipping_icon(tmp_path, monkeypatch, qapp):
    shipping = icons.ROOT / "assets" / "app_icon.ico"
    original = hashlib.sha256(shipping.read_bytes()).hexdigest()
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "候選圖示 輸出"
    preview = tmp_path / "圖示預覽.png"
    assert icons.main(["--output-directory", str(output), "--preview", str(preview)]) == 0
    for candidate in icons.CANDIDATES:
        assert (output / candidate / "app_icon.ico").read_bytes() == (
            icons.SOURCE / candidate / "app_icon.ico"
        ).read_bytes()
    assert QImage(str(preview)).size() == QSize(1440, 900)
    assert hashlib.sha256(shipping.read_bytes()).hexdigest() == original


def test_shipping_icon_is_selected_ledger_and_has_all_sizes(tmp_path, qapp):
    for selected, candidate in (("app_icon.svg", "mark.svg"),
                                ("app_icon-small.svg", "mark-small.svg")):
        assert (icons.ROOT / "assets" / selected).read_bytes() == (
            icons.SOURCE / "ledger" / candidate
        ).read_bytes()
    rebuilt = tmp_path / "shipping.ico"
    icons.build_shipping_icon(rebuilt)
    assert rebuilt.read_bytes() == (icons.ROOT / "assets" / "app_icon.ico").read_bytes()
    assert rebuilt.read_bytes() == (icons.SOURCE / "ledger" / "app_icon.ico").read_bytes()
    icon = QIcon(str(rebuilt))
    assert {size.width() for size in icon.availableSizes()} == set(icons.SIZES)


def test_application_and_top_level_windows_use_selected_icon(qapp):
    from PySide6.QtWidgets import QWidget
    from taxops.ui.app import _set_app_icon

    original = qapp.windowIcon()
    window = None
    try:
        _set_app_icon(qapp)
        assert {size.width() for size in qapp.windowIcon().availableSizes()} == set(icons.SIZES)
        window = QWidget()
        assert window.windowIcon().cacheKey() == qapp.windowIcon().cacheKey()
        expected = QIcon(str(icons.ROOT / "assets" / "app_icon.ico"))
        for size in icons.SIZES:
            assert window.windowIcon().pixmap(size).toImage() == expected.pixmap(size).toImage()
    finally:
        if window is not None:
            window.close()
        qapp.setWindowIcon(original)
