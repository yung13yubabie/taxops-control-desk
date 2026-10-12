"""Exercise resource loading against PyInstaller's actual one-dir layout."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from taxops.core.resources import asset_path
from taxops.ui import app as app_module
from taxops.ui import style


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_source_assets_ignore_working_directory_and_unrelated_meipass(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.chdir(tmp_path)

    assert asset_path("app_icon.ico") == ROOT / "assets" / "app_icon.ico"
    assert asset_path("app_icon.ico").is_file()


class _ApplicationProbe:
    def __init__(self) -> None:
        self.icons: list[object] = []
        self.styles: list[str] = []

    def setWindowIcon(self, icon: object) -> None:
        self.icons.append(icon)

    def setStyleSheet(self, stylesheet: str) -> None:
        self.styles.append(stylesheet)


@pytest.mark.parametrize("layout", ["internal", "custom_internal", "legacy_flat"])
def test_both_icon_loaders_use_frozen_bundle_assets(
    layout, tmp_path, monkeypatch, qapp,
) -> None:
    executable_root = tmp_path / "移動後的程式 資料夾"
    executable_root.mkdir()
    executable = executable_root / "TaxOpsControlDesk.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    if layout == "legacy_flat":
        bundle_root = executable_root
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    else:
        bundle_root = executable_root / (
            "_internal" if layout == "internal" else "bundle_resources"
        )
        monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    icon_path = bundle_root / "assets" / "app_icon.ico"
    icon_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "assets" / "app_icon.ico", icon_path)
    unrelated_cwd = tmp_path / "other_cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    from PySide6 import QtGui
    original_icon = QtGui.QIcon
    loaded_paths: list[str] = []

    def record_icon(source):
        if isinstance(source, str):
            loaded_paths.append(source)
        return original_icon(source)

    monkeypatch.setattr(QtGui, "QIcon", record_icon)
    probe = _ApplicationProbe()
    app_module._set_app_icon(probe)
    style.apply(probe)

    assert loaded_paths == [str(icon_path), str(icon_path)]
    assert len(probe.icons) == 2
    assert all(not icon.isNull() for icon in probe.icons)
    assert probe.styles == [style.APP_STYLESHEET]


def test_missing_frozen_icon_keeps_existing_generated_fallback(
    tmp_path, monkeypatch, qapp,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    probe = _ApplicationProbe()

    app_module._set_app_icon(probe)
    assert probe.icons == []
    style.apply(probe)

    assert len(probe.icons) == 1
    assert not probe.icons[0].isNull()
    assert probe.styles == [style.APP_STYLESHEET]
