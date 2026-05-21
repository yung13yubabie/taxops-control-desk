"""Shared constants for dialogs."""

from __future__ import annotations

TAX_TYPE_CHOICES: list[tuple[str, str]] = [
    ("vat", "營業稅"),
    ("cit", "營利事業所得稅"),
    ("iit", "綜合所得稅"),
    ("stamp", "印花稅"),
    ("inheritance", "遺產稅"),
    ("other", "其他"),
]
