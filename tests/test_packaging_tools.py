from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_uses_absolute_import_entrypoint() -> None:
    spec = (ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")

    assert "build_tools/pyinstaller_entry.py" in spec
    assert "src/taxops/__main__.py" not in spec


def test_pyinstaller_entrypoint_uses_absolute_import() -> None:
    entry = (ROOT / "build_tools" / "pyinstaller_entry.py").read_text(encoding="utf-8")

    assert "from taxops.ui.app import run" in entry
    assert "from .ui.app import run" not in entry


def test_smoke_test_waits_after_force_kill() -> None:
    smoke = (ROOT / "build_tools" / "smoke_test_exe.py").read_text(encoding="utf-8")

    assert "proc.kill()" in smoke
    assert "proc.wait(timeout=5)" in smoke
