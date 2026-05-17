"""Path resolution + ensure_paths."""

from __future__ import annotations

from pathlib import Path

from taxops.core.paths import (
    ATTACHMENTS_DIR_NAME,
    DB_FILENAME,
    DEV_APP_DIR_NAME,
    PROD_APP_DIR_NAME,
    ensure_paths,
    resolve_paths,
)


def test_override_root_keeps_paths_under_root(tmp_path: Path) -> None:
    paths = resolve_paths(override_root=tmp_path / "case1")
    assert paths.data_root == tmp_path / "case1"
    assert paths.db_path == tmp_path / "case1" / DB_FILENAME
    assert paths.attachments_dir == tmp_path / "case1" / ATTACHMENTS_DIR_NAME
    assert paths.backups_dir == tmp_path / "case1" / "TaxOpsBackups"


def test_dev_mode_uses_dev_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    prod = resolve_paths(is_dev=False)
    dev = resolve_paths(is_dev=True)
    assert PROD_APP_DIR_NAME in str(prod.data_root)
    assert DEV_APP_DIR_NAME in str(dev.data_root)
    assert prod.data_root != dev.data_root


def test_ensure_paths_creates_directories(tmp_path: Path) -> None:
    paths = resolve_paths(override_root=tmp_path / "case2")
    assert not paths.data_root.exists()
    ensure_paths(paths)
    assert paths.data_root.is_dir()
    assert paths.attachments_dir.is_dir()
