from __future__ import annotations

import pytest

from taxops.security.image_guard import ImageGuardError, validate_image_data


class _HugeImage:
    def isNull(self) -> bool:
        return False

    def width(self) -> int:
        return 50_000

    def height(self) -> int:
        return 50_000


def test_image_guard_rejects_excessive_dimensions_before_decode() -> None:
    with pytest.raises(ImageGuardError, match="image.dimensions_too_large"):
        validate_image_data(_HugeImage())  # type: ignore[arg-type]
