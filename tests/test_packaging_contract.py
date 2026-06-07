"""Packaging must include every registered database migration."""

from __future__ import annotations

from pathlib import Path


def test_pyinstaller_spec_collects_all_migration_submodules() -> None:
    spec = Path("TaxOpsControlDesk.spec").read_text(encoding="utf-8")

    assert 'collect_submodules("taxops.db.migrations")' in spec


def test_release_requirements_pin_runtime_and_packaging_dependencies() -> None:
    lines = {
        line.strip()
        for line in Path("requirements-release.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    for package in ("PySide6", "Jinja2", "openpyxl", "PyInstaller", "setuptools"):
        assert any(line.startswith(f"{package}==") for line in lines), package
    assert all("==" in line for line in lines)
