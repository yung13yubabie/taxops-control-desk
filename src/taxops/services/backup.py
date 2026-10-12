"""Backup and restore service.

Backup uses sqlite3.Connection.backup() for a consistent copy. Restore
validates and migrates a staging copy before replacing the live database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from ..core.paths import AppPaths
from ..db.migrate import apply_migrations
from ..db.migrations import MIGRATIONS
from ..repositories.audit_logs import AuditLogRepository
from ..repositories.backup import BackupRepository, BackupRow
from .audit import AuditService
from .backup_bundle import (
    ASSET_NAMES, DATABASE_NAME, FULL_BACKUP_SUFFIX, BackupBundleError,
    install_assets, read_bundle, references, rewrite_references,
    validate_references, write_bundle, write_restore_history,
)

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
        self._cleanup_warnings: list[Path] = []

    @property
    def cleanup_warnings(self) -> tuple[Path, ...]:
        """Owned temporary paths that could not be removed in the last operation."""
        return tuple(self._cleanup_warnings)

    def _cleanup_warning(self, path: Path) -> None:
        self._cleanup_warnings.append(path)
        _log.warning("Temporary backup path may remain after cleanup failure: %s", path,
                     exc_info=True)

    @contextmanager
    def _staging_directory(self, *, prefix: str, directory: Path):
        temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=directory)
        try:
            yield Path(temporary.name)
        finally:
            # Cleanup is not the business operation. In particular it must not
            # turn an already committed backup/restore into a reported failure.
            try:
                temporary.cleanup()
            except OSError:
                self._cleanup_warning(Path(temporary.name))

    def _cleanup_sqlite_best_effort(self, path: Path) -> None:
        try:
            self._remove_sqlite_files(path)
        except OSError:
            self._cleanup_warning(path)

    def create_backup(self, paths: AppPaths, *, notes: str | None = None) -> BackupRow:
        """Create a verified portable database-and-assets backup."""
        self._cleanup_warnings.clear()
        self._require_idle_connection()
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        filename = f"office_desk_{datetime.now():%Y%m%d_%H%M%S_%f}{FULL_BACKUP_SUFFIX}"
        destination = paths.backups_dir / filename
        try:
            with self._staging_directory(prefix=".backup_stage_", directory=paths.backups_dir) as stage:
                database = stage / DATABASE_NAME
                with closing(sqlite3.connect(database)) as snapshot:
                    self._conn.backup(snapshot)
                archive = stage / filename
                manifest = write_bundle(database, paths, archive)
                archive.replace(destination)
                with self._conn:
                    row = self._repo.insert(
                        filename=filename, backup_path=str(destination),
                        file_size=destination.stat().st_size, notes=notes,
                    )
                    self._audit.record(
                        action="backup.create", target_type="backup", target_id=str(row.id),
                        detail={"filename": filename, "format": "full-v1",
                                "file_count": len(manifest["files"]), "file_size": row.file_size},
                    )
            return row
        except Exception as exc:
            destination.unlink(missing_ok=True)
            code = str(exc) if isinstance(exc, BackupBundleError) else "backup.create.failed"
            raise BackupError(code) from exc

    def create_database_snapshot(self, paths: AppPaths, *, notes: str | None = None) -> BackupRow:
        """Explicit legacy DB-only snapshot; it does not include file assets."""
        self._cleanup_warnings.clear()
        self._require_idle_connection()
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
                action="backup.create.database_only",
                target_type="backup",
                target_id=str(row.id),
                detail={"filename": filename, "file_size": file_size},
            )
        return row

    def restore_backup(self, backup_path: Path, paths: AppPaths) -> None:
        """Validate and migrate staging before replacing the live database."""
        self._cleanup_warnings.clear()
        self._require_idle_connection()
        self._validate_backup_file(backup_path)
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        if backup_path.name.lower().endswith(FULL_BACKUP_SUFFIX):
            try:
                with self._staging_directory(prefix=".restore_bundle_", directory=paths.backups_dir) as directory:
                    manifest = read_bundle(backup_path, directory)
                    self._restore_from_stage(
                        directory / DATABASE_NAME, backup_path, paths,
                        full_bundle=(directory, manifest),
                    )
            except BackupError:
                raise
            except BackupBundleError as exc:
                raise BackupError(str(exc)) from exc
            except Exception as exc:
                raise BackupError("backup.restore.failed") from exc
            return
        stage_path = self._create_stage_copy(backup_path, paths.backups_dir)
        try:
            self._restore_from_stage(stage_path, backup_path, paths)
        finally:
            self._cleanup_sqlite_best_effort(stage_path)

    def _restore_from_stage(
        self,
        stage_path: Path,
        backup_path: Path,
        paths: AppPaths,
        *,
        full_bundle: tuple[Path, dict] | None = None,
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
            if full_bundle is not None:
                validate_references(
                    stage_conn, {entry["path"]: entry for entry in full_bundle[1]["files"]}
                )
        except BackupBundleError as exc:
            stage_conn.close()
            raise BackupError(str(exc)) from exc
        except BackupError:
            stage_conn.close()
            raise
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
                self._cleanup_sqlite_best_effort(before_path)
            raise BackupError("backup.before_restore.failed") from exc

        history: dict | None = None
        restore_id = uuid4().hex
        try:
            if full_bundle is not None:
                directory, manifest = full_bundle
                history = {
                    "version": 1, "restore_id": restore_id,
                    "created_at": datetime.now().astimezone().isoformat(),
                    "state": "prepared", "source_backup": backup_path.name,
                    "manifest_sha256": manifest["manifest_sha256"],
                    "before_restore_database": before_filename,
                    "policy": "retain_previous_assets_and_restore_namespaces",
                    "namespaces": [f"{name}/restored_{restore_id}" for name in ASSET_NAMES],
                    "source_files": manifest["files"],
                    "planned_mapping": {
                        entry["path"]: (
                            f"{entry['path'].split('/', 1)[0]}/restored_{restore_id}/"
                            f"{index}{Path(entry['path']).suffix}"
                        )
                        for index, entry in enumerate(manifest["files"])
                        if entry["path"] != DATABASE_NAME
                    },
                    "references": [
                        {"path": f"{root}/{relative}", "required": required}
                        for root, relative, required in references(stage_conn)
                    ],
                }
                write_restore_history(paths, restore_id, history)
                mapping = install_assets(directory, manifest, paths, restore_id)
                rewrite_references(stage_conn, mapping, restore_id)
                history["mapping"] = {
                    f"{root}/{old}": f"{root}/{new}" for (root, old), new in mapping.items()
                }
                history["state"] = "assets_ready"
                write_restore_history(paths, restore_id, history)
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
                        "restore_id": restore_id,
                        "format": "full-v1" if full_bundle is not None else "database-only",
                    },
                )
            self._assert_integrity(stage_conn)
            stage_conn.backup(self._conn)
        except Exception as exc:
            if history is not None:
                history["state"] = "failed_before_commit"
                self._write_history_best_effort(paths, restore_id, history)
            code = str(exc) if isinstance(exc, BackupBundleError) else "backup.restore.failed"
            raise BackupError(code) from exc
        finally:
            stage_conn.close()
        if history is not None:
            history["state"] = "committed"
            self._write_history_best_effort(paths, restore_id, history)

    def _require_idle_connection(self) -> None:
        if self._conn.in_transaction:
            raise BackupError("backup.pending_changes")

    @staticmethod
    def _write_history_best_effort(paths: AppPaths, restore_id: str, history: dict) -> None:
        try:
            write_restore_history(paths, restore_id, history)
        except Exception:
            # The prepared journal plus the DB audit restore_id remain the
            # recovery authority if disk failure interrupts this final update.
            _log.exception("Could not update restore retention history %s", restore_id)

    @staticmethod
    def _validate_backup_file(backup_path: Path) -> None:
        if not backup_path.exists():
            raise BackupError("backup.file_not_found")
        if not backup_path.is_file() or not (
            backup_path.suffix.lower() == ".sqlite"
            or backup_path.name.lower().endswith(FULL_BACKUP_SUFFIX)
        ):
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


def _schema_objects(
    conn: sqlite3.Connection,
) -> frozenset[tuple[str, str, str | None]]:
    placeholders = ",".join("?" for _ in _SCHEMA_OBJECT_TYPES)
    rows = conn.execute(
        f"SELECT type, name, sql FROM sqlite_master WHERE type IN ({placeholders})"
        " AND name NOT LIKE 'sqlite_%'",
        _SCHEMA_OBJECT_TYPES,
    ).fetchall()
    return frozenset((row[0], row[1], row[2]) for row in rows)


@lru_cache(maxsize=1)
def _expected_schema_objects() -> frozenset[tuple[str, str, str | None]]:
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        reference.execute("PRAGMA foreign_keys = ON")
        apply_migrations(reference)
        return _schema_objects(reference)
    finally:
        reference.close()
