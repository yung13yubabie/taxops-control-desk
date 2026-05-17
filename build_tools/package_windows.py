"""Build the Windows EXE via PyInstaller.

Usage:
    python -m build_tools.package_windows

Output: dist/TaxOpsControlDesk/TaxOpsControlDesk.exe

Requires PyInstaller to be installed:
    pip install pyinstaller
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_SPEC = _PROJECT_ROOT / "TaxOpsControlDesk.spec"
_EXE = _PROJECT_ROOT / "dist" / "TaxOpsControlDesk" / "TaxOpsControlDesk.exe"


def _check_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller not found. Install it with:")
        print("    pip install pyinstaller")
        sys.exit(1)


def build() -> None:
    if not _SPEC.exists():
        print(f"ERROR: Spec file not found: {_SPEC}")
        sys.exit(1)

    _check_pyinstaller()

    print(f"Building from: {_SPEC}")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            str(_SPEC),
            "--noconfirm",
            "--clean",
        ],
        cwd=str(_PROJECT_ROOT),
    )

    if result.returncode != 0:
        print("ERROR: PyInstaller build failed.")
        sys.exit(result.returncode)

    if _EXE.exists():
        size_mb = _EXE.stat().st_size / (1024 * 1024)
        print(f"\nBuild succeeded.")
        print(f"  EXE: {_EXE}")
        print(f"  Size: {size_mb:.1f} MB")
    else:
        print(f"ERROR: Expected EXE not found at: {_EXE}")
        sys.exit(1)


if __name__ == "__main__":
    build()
