"""Resource limits for user-provided raster images."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QImageReader

MAX_IMAGE_FILE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 40_000_000


class ImageGuardError(ValueError):
    pass


def validate_image_file(path: Path) -> tuple[int, int]:
    source = Path(path)
    if source.stat().st_size > MAX_IMAGE_FILE_BYTES:
        raise ImageGuardError("image.file_too_large")
    reader = QImageReader(str(source))
    if not reader.canRead():
        raise ImageGuardError("image.invalid")
    size = reader.size()
    _validate_dimensions(size.width(), size.height())
    return size.width(), size.height()


def validate_image_data(image: QImage) -> tuple[int, int]:
    if image.isNull():
        raise ImageGuardError("image.invalid")
    _validate_dimensions(image.width(), image.height())
    return image.width(), image.height()


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ImageGuardError("image.invalid")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ImageGuardError("image.dimensions_too_large")
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageGuardError("image.pixel_count_too_large")
