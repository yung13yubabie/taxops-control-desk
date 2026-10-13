"""Render original SVG candidates to Windows multi-size ICOs using pinned Qt.

This is a development tool. It uses PySide6, already in requirements-release.txt,
and Python's standard library. No converter, font, network, or target-PC setup is
required. Rendering candidates never changes the shipping app_icon.ico; the
explicit --shipping option regenerates it from the selected SVG masters.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "application_icon_candidates"
SIZES = (16, 24, 32, 48, 64, 128, 256)
CANDIDATES = ("ledger", "workbench", "monogram")


def render_svg(source: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {source.name}")
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    return image


def _dib(image: QImage) -> bytes:
    """Encode a 32-bit bottom-up ICO DIB and its DWORD-aligned transparency mask."""
    size = image.width()
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(rgba.constBits())
    stride = rgba.bytesPerLine()
    xor = bytearray()
    mask = bytearray()
    mask_stride = ((size + 31) // 32) * 4
    for y in range(size - 1, -1, -1):
        row_mask = bytearray(mask_stride)
        for x in range(size):
            offset = y * stride + x * 4
            red, green, blue, alpha = pixels[offset:offset + 4]
            xor.extend((blue, green, red, alpha))
            if alpha == 0:
                row_mask[x // 8] |= 0x80 >> (x % 8)
        mask.extend(row_mask)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32,
                         0, len(xor), 0, 0, 0, 0)
    return header + xor + mask


def _png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Could not open PNG buffer")
    try:
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not encode PNG")
    finally:
        buffer.close()
    return bytes(data)


def encode_ico(images: tuple[QImage, ...]) -> bytes:
    if not images:
        raise ValueError("ICO requires at least one image")
    sizes = [image.width() for image in images]
    if (len(set(sizes)) != len(sizes)
            or any(image.isNull() or image.height() != size or not 1 <= size <= 256
                   for image, size in zip(images, sizes))):
        raise ValueError("ICO images must be unique square sizes from 1 to 256")
    chunks = [_png(image) if image.width() == 256 else _dib(image) for image in images]
    offset = 6 + len(images) * 16
    entries = bytearray()
    for size, chunk in zip(sizes, chunks):
        entries.extend(struct.pack("<BBBBHHII", size % 256, size % 256,
                                   0, 0, 1, 32, len(chunk), offset))
        offset += len(chunk)
    return struct.pack("<HHH", 0, 1, len(images)) + entries + b"".join(chunks)


def candidate_images(candidate: str) -> tuple[QImage, ...]:
    if candidate not in CANDIDATES:
        raise ValueError("Unknown application icon candidate")
    return tuple(render_svg(SOURCE / candidate / (
        "mark-small.svg" if size <= 32 else "mark.svg"), size) for size in SIZES)


def build_candidates(destination: Path) -> None:
    for candidate in CANDIDATES:
        target = destination / candidate / "app_icon.ico"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode_ico(candidate_images(candidate)))


def build_shipping_icon(destination: Path) -> None:
    images = tuple(render_svg(ROOT / "assets" / (
        "app_icon-small.svg" if size <= 32 else "app_icon.svg"), size) for size in SIZES)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encode_ico(images))


def render_preview(destination: Path) -> None:
    """Create a design review sheet, not a screenshot of Windows or the app."""
    image = QImage(1440, 900, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#F5F7FA"))
    painter = QPainter(image)
    try:
        def text(x: int, y: int, value: str, size: int, color: str = "#1E293B",
                 bold: bool = False) -> None:
            font = QFont("Noto Sans CJK TC", size)
            font.setPixelSize(size)
            font.setBold(bold)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(x, y, value)

        text(60, 64, "TaxOps · 專屬應用程式圖示", 32, bold=True)
        text(60, 103, "同一識別，桌面、視窗與工作列共用；小尺寸另外做清晰化調整。", 20, "#64748B")
        captions = (
            ("A · 帳冊", "會計辨識最直接，安靜而專業"),
            ("B · 工作檯", "把左側導覽與工作區變成圖形"),
            ("C · TO 印記", "延續藍底，以 TaxOps 字母建立識別"),
        )
        for column, (candidate, (title, description)) in enumerate(zip(CANDIDATES, captions)):
            x = 60 + column * 450
            painter.fillRect(x, 143, 420, 693, QColor("#FFFFFF"))
            painter.drawImage(x + 130, 173, render_svg(SOURCE / candidate / "mark.svg", 160))
            text(x + 28, 383, title, 27, bold=True)
            text(x + 28, 421, description, 19, "#64748B")
            text(x + 28, 480, "淺色環境 · 下列圖示為實際像素大小", 17, "#64748B")
            frames = candidate_images(candidate)
            for row, (background, foreground, y) in enumerate((
                    ("#F1F5F9", "#64748B", 505), ("#1E293B", "#CBD5E1", 647))):
                painter.fillRect(x + 20, y, 380, 112, QColor(background))
                offset = x + 42
                for size, frame in zip(SIZES[:5], frames[:5]):
                    painter.drawImage(offset, y + (76 - size) // 2, frame)
                    text(offset, y + 99, str(size), 14, foreground)
                    offset += size + 25
                if row == 1:
                    text(x + 28, y - 18, "深色環境 · 16 / 24 / 32 / 48 / 64 px", 17, "#64748B")
            text(x + 28, 802, "ICO 內含 16–256 px，共 7 個尺寸", 17, "#64748B")
        text(60, 875, "設計預覽；尚未代表 Windows 桌面／釘選實機驗收。無漸層、無字型依賴、SVG 可維護。", 18, "#64748B")
    finally:
        painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(destination), "PNG"):
        raise RuntimeError("Could not write application icon preview")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=SOURCE)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--shipping", action="store_true",
                        help="Regenerate assets/app_icon.ico from the selected SVG masters")
    args = parser.parse_args(argv)
    app = QGuiApplication.instance() or QGuiApplication([])
    build_candidates(args.output_directory)
    if args.shipping:
        build_shipping_icon(ROOT / "assets" / "app_icon.ico")
    if args.preview:
        render_preview(args.preview)
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
