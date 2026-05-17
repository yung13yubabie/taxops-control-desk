"""Remove stale PyInstaller build artifacts.

Usage:
    python -m build_tools.clean_package

Safe to run at any time. Will NOT touch SQLite data, attachments,
cache bundles, test data, source code, or documentation.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

_REMOVE_DIRS = [
    _PROJECT_ROOT / "build",
    _PROJECT_ROOT / "dist" / "TaxOpsControlDesk",
    _PROJECT_ROOT / "__pycache__",
]

_REMOVE_GLOBS = [
    "**/*.pyc",
    "**/*.pyo",
    "*.spec.bak",
]


def clean() -> None:
    removed: list[str] = []

    for target in _REMOVE_DIRS:
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target))

    for pattern in _REMOVE_GLOBS:
        for path in _PROJECT_ROOT.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(str(path))

    if removed:
        print(f"Removed {len(removed)} artifact(s):")
        for r in removed:
            print(f"  {r}")
    else:
        print("Nothing to clean.")


if __name__ == "__main__":
    clean()
    sys.exit(0)
