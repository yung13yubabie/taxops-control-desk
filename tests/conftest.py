"""Shared pytest fixtures.

Tests must never touch real user data — every fixture below uses pytest's
``tmp_path`` so the SQLite file lives in an isolated directory.

The ``container`` fixture owns its own connection (closed via
``container.close()``). The ``db_conn`` fixture is independent and is for
tests that exercise repositories directly without the service layer.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from taxops.core.paths import AppPaths, resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.services.container import ServiceContainer, build_container


def _ensure_app_dirs(paths: AppPaths) -> None:
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def isolated_tempfile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route tempfile.mkdtemp() into pytest's per-test temp directory.

    Several UI smoke helpers use ``tempfile.mkdtemp()`` directly because they
    are plain helper functions rather than fixtures.  Keeping those directories
    under ``tmp_path`` prevents repeated test runs from accumulating unbounded
    folders in the user's global TEMP directory.
    """
    temp_root = tmp_path / "_tempfile"
    temp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    try:
        yield
    finally:
        tempfile.tempdir = None


@pytest.fixture
def temp_paths(tmp_path: Path) -> AppPaths:
    return resolve_paths(override_root=tmp_path / "TaxOpsControlDeskTest")


@pytest.fixture
def db_conn(temp_paths: AppPaths) -> Iterator[sqlite3.Connection]:
    _ensure_app_dirs(temp_paths)
    conn = open_connection(temp_paths.db_path)
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def container(tmp_path: Path) -> Iterator[ServiceContainer]:
    paths = resolve_paths(override_root=tmp_path / "TaxOpsControlDeskTestContainer")
    _ensure_app_dirs(paths)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    c = build_container(paths, conn)
    try:
        yield c
    finally:
        c.close()
