"""Backup and restore service.

Backup uses sqlite3.Connection.backup() for a consistent copy. Restore
validates and migrates a staging copy before replacing the live database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from ..core.paths import AppPaths
from ..db.migrate import apply_migrations
from ..db.migrations import MIGRATIONS
from ..repositories.audit_logs import AuditLogRepository
from ..repositories.backup import BackupRepository, BackupRow
from .audit import AuditService

_log = logging.getLogger(__name__)
_SCHEMA_OBJECT_TYPES = ("table", "index", "trigger", "view")


class BackupError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BackupService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repo: BackupRepository,
        audit: AuditService,
    ) -> None:
        self._conn = conn
        self._repo = repo
        self._audit = audit

    def create_backup(self, paths: AppPaths, *, notes: str | None = None) -> BackupRow:
        """Backup the live DB and record the operation."""
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"office_desk_{ts}.sqlite"
        dest_path = paths.backups_dir / filename

        try:
            with closing(sqlite3.connect(str(dest_path))) as dest_conn:
                self._conn.backup(dest_conn)
        except Exception as exc:
            dest_path.unlink(missing_ok=True)
            raise BackupError("backup.create.failed") from exc

        file_size = dest_path.stat().st_size
        with self._conn:
            row = self._repo.insert(
                filename=filename,
                backup_path=str(dest_path),
                file_size=file_size,
                notes=notes,
            )
            self._audit.record(
                action="backup.create",
                target_type="backup",
                target_id=str(row.id),
                detail={"filename": filename, "file_size": file_size},
            )
        return row

    def restore_backup(self, backup_path: Path, paths: AppPaths) -> None:
        """Validate and migrate staging before replacing the live database."""
        self._validate_backup_file(backup_path)
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        stage_path = self._create_stage_copy(backup_path, paths.backups_dir)
        try:
            self._restore_from_stage(stage_path, backup_path, paths)
        finally:
            self._remove_sqlite_files(stage_path)

    def _restore_from_stage(
        self,
        stage_path: Path,
        backup_path: Path,
        paths: AppPaths,
    ) -> None:
        stage_conn: sqlite3.Connection | None = None
        try:
            stage_conn = sqlite3.connect(str(stage_path))
            stage_conn.row_factory = sqlite3.Row
            stage_conn.execute("PRAGMA foreign_keys = ON")
            self._assert_integrity(stage_conn)
            self._assert_taxops_database(stage_conn)
        except BackupError:
            if stage_conn is not None:
                stage_conn.close()
            raise
        except Exception as exc:
            if stage_conn is not None:
                stage_conn.close()
            raise BackupError("backup.invalid_file") from exc

        try:
            apply_migrations(stage_conn)
            self._assert_integrity(stage_conn)
            self._assert_taxops_database(stage_conn, require_current=True)
        except Exception as exc:
            _log.error("backup.restore: staging migration failed", exc_info=True)
            stage_conn.close()
            raise BackupError("backup.restore_migrate_failed") from exc

        before_path: Path | None = None
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            before_filename = f"before_restore_{ts}.sqlite"
            before_path = paths.backups_dir / before_filename
            with closing(sqlite3.connect(str(before_path))) as dest_conn:
                self._conn.backup(dest_conn)
            before_size = before_path.stat().st_size
        except Exception as exc:
            stage_conn.close()
            if before_path is not None:
                self._remove_sqlite_files(before_path)
            raise BackupError("backup.before_restore.failed") from exc

        try:
            stage_repo = BackupRepository(stage_conn)
            stage_audit = AuditService(
                AuditLogRepository(stage_conn),
                actor=self._audit.actor,
            )
            with stage_conn:
                stage_repo.insert(
                    filename=before_filename,
                    backup_path=str(before_path),
                    file_size=before_size,
                    notes="before_restore",
                )
                stage_audit.record(
                    action="backup.restore",
                    target_type="backup",
                    detail={
                        "restored_from": str(backup_path),
                        "before_restore_snapshot": str(before_path),
                    },
                )
            self._assert_integrity(stage_conn)
            stage_conn.backup(self._conn)
        except Exception as exc:
            raise BackupError("backup.restore.failed") from exc
        finally:
            stage_conn.close()

    @staticmethod
    def _validate_backup_file(backup_path: Path) -> None:
        if not backup_path.exists():
            raise BackupError("backup.file_not_found")
        if backup_path.suffix.lower() != ".sqlite" or not backup_path.is_file():
            raise BackupError("backup.invalid_file")

    @staticmethod
    def _create_stage_copy(backup_path: Path, directory: Path) -> Path:
        fd, stage_name = tempfile.mkstemp(
            prefix=".restore_stage_",
            suffix=".sqlite",
            dir=directory,
        )
        os.close(fd)
        stage_path = Path(stage_name)
        try:
            with (
                closing(sqlite3.connect(str(backup_path))) as source_conn,
                closing(sqlite3.connect(str(stage_path))) as stage_conn,
            ):
                source_conn.backup(stage_conn)
        except Exception as exc:
            BackupService._remove_sqlite_files(stage_path)
            raise BackupError("backup.invalid_file") from exc
        return stage_path

    @staticmethod
    def _assert_integrity(conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        if len(rows) != 1 or rows[0][0] != "ok":
            raise BackupError("backup.invalid_file")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("backup.invalid_file")

    @staticmethod
    def _assert_taxops_database(
        conn: sqlite3.Connection,
        *,
        require_current: bool = False,
    ) -> None:
        required_tables = {
            "schema_migrations",
            "app_settings",
            "clients",
            "audit_logs",
        }
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {row[0] for row in rows}
        if not required_tables.issubset(tables):
            raise BackupError("backup.invalid_file")
        initial = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            ("0001_initial",),
        ).fetchone()
        if initial is None:
            raise BackupError("backup.invalid_file")
        known_versions = {version for version, _sql in MIGRATIONS}
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        if not applied.issubset(known_versions):
            raise BackupError("backup.invalid_file")

        dangerous_objects = conn.execute(
            "SELECT type, name FROM sqlite_master"
            " WHERE type IN ('trigger', 'view') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if dangerous_objects:
            raise BackupError("backup.invalid_file")

        if require_current:
            if applied != known_versions:
                raise BackupError("backup.invalid_file")
            if _schema_objects(conn) != _expected_schema_objects():
                raise BackupError("backup.invalid_file")

    @staticmethod
    def _remove_sqlite_files(db_path: Path) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _schema_objects(conn: sqlite3.Connection) -> frozenset[tuple[str, str]]:
    placeholders = ",".join("?" for _ in _SCHEMA_OBJECT_TYPES)
    rows = conn.execute(
        f"SELECT type, name FROM sqlite_master WHERE type IN ({placeholders})"
        " AND name NOT LIKE 'sqlite_%'",
        _SCHEMA_OBJECT_TYPES,
    ).fetchall()
    return frozenset((row[0], row[1]) for row in rows)


@lru_cache(maxsize=1)
def _expected_schema_objects() -> frozenset[tuple[str, str]]:
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        reference.execute("PRAGMA foreign_keys = ON")
        apply_migrations(reference)
        return _schema_objects(reference)
    finally:
        reference.close()
