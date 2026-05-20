from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_uses_absolute_import_entrypoint() -> None:
    spec = (ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")

    assert "build_tools/pyinstaller_entry.py" in spec
    assert "src/taxops/__main__.py" not in spec


def test_pyinstaller_spec_embeds_windows_icon() -> None:
    spec = (ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")

    assert "assets/app_icon.ico" in spec
    assert "icon=" in spec
    assert '("assets/app_icon.ico", "assets")' in spec
    assert (ROOT / "assets" / "app_icon.ico").exists()


def test_app_sets_windows_app_user_model_id() -> None:
    app_py = (ROOT / "src" / "taxops" / "ui" / "app.py").read_text(encoding="utf-8")

    assert "SetCurrentProcessExplicitAppUserModelID" in app_py


def test_style_prefers_packaged_icon_asset() -> None:
    style_py = (ROOT / "src" / "taxops" / "ui" / "style.py").read_text(encoding="utf-8")

    assert "app_icon.ico" in style_py
    assert "setWindowIcon(QIcon(str(icon_path)))" in style_py


def test_pyinstaller_entrypoint_uses_absolute_import() -> None:
    entry = (ROOT / "build_tools" / "pyinstaller_entry.py").read_text(encoding="utf-8")

    assert "from taxops.ui.app import run" in entry
    assert "from .ui.app import run" not in entry


def test_smoke_test_waits_after_force_kill() -> None:
    smoke = (ROOT / "build_tools" / "smoke_test_exe.py").read_text(encoding="utf-8")

    assert "proc.kill()" in smoke
    assert "proc.wait(timeout=5)" in smoke
