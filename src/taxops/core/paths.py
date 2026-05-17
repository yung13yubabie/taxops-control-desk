"""Resolve OS paths for data, attachments, and backups.

Implements the path policy from ``docs/implementation_spec.md`` "Data And User Mode".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROD_APP_DIR_NAME = "TaxOpsControlDesk"
DEV_APP_DIR_NAME = "TaxOpsControlDeskDev"
BACKUPS_DIR_NAME = "TaxOpsBackups"
DB_FILENAME = "taxops.sqlite"
ATTACHMENTS_DIR_NAME = "attachments"


@dataclass(frozen=True)
class AppPaths:
    """Resolved paths used by the running application."""

    data_root: Path
    db_path: Path
    attachments_dir: Path
    backups_dir: Path


def _local_appdata() -> Path:
    """Return ``%LOCALAPPDATA%`` on Windows; fall back to home for non-Windows dev."""
    env = os.environ.get("LOCALAPPDATA")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share"


def _user_documents() -> Path:
    env = os.environ.get("USERPROFILE")
    base = Path(env) if env else Path.home()
    return base / "Documents"


def resolve_paths(
    *,
    is_dev: bool = False,
    override_root: Path | None = None,
) -> AppPaths:
    """Return :class:`AppPaths` for the current execution mode.

    ``override_root`` is honoured for tests so they never touch real user data.
    """

    if override_root is not None:
        data_root = Path(override_root)
        backups = data_root / BACKUPS_DIR_NAME
    else:
        app_dir = DEV_APP_DIR_NAME if is_dev else PROD_APP_DIR_NAME
        data_root = _local_appdata() / app_dir
        backups = _user_documents() / BACKUPS_DIR_NAME

    return AppPaths(
        data_root=data_root,
        db_path=data_root / DB_FILENAME,
        attachments_dir=data_root / ATTACHMENTS_DIR_NAME,
        backups_dir=backups,
    )


def ensure_paths(paths: AppPaths) -> None:
    """Create data and attachment directories if missing.

    Backups directory is created lazily by the backup feature, not here.
    """

    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
