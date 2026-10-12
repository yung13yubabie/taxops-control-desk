"""Locate read-only assets in source checkouts and frozen application bundles."""

from __future__ import annotations

import sys
from pathlib import Path


def asset_path(filename: str) -> Path:
    """Return a bundled asset path, independently of the working directory.

    PyInstaller 6 one-dir data lives below ``sys._MEIPASS`` (normally
    ``_internal``), not beside the executable. The executable directory remains
    a fallback for older flat bundles without that bootloader attribute.
    """
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        root = Path(bundle_root) if bundle_root else Path(sys.executable).parent
    else:
        root = Path(__file__).resolve().parents[3]
    return root / "assets" / filename
