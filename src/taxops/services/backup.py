"""Backup and restore service.

Backup uses the sqlite3.Connection.backup() API for an atomic, consistent
copy of the live database.  Restore creates a before_restore safety snapshot
first; only if that succeeds does it overwrite the live connection's data.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

_log = logging.getLogger(__name__)

from ..core.paths import AppPaths
from ..db.migrate import apply_migrations
from ..repositories.backup import BackupRepository, BackupRow
from .audit import AuditService


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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self, paths: AppPaths, *, notes: str | None = None) -> BackupRow:
        """Backup the live DB to paths.backups_dir and record it.

        Raises BackupError("backup.create.failed") on any failure.
        """
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"office_desk_{ts}.sqlite"
        dest_path = paths.backups_dir / filename

        try:
            with sqlite3.connect(str(dest_path)) as dest_conn:
                self._conn.backup(dest_conn)
        except Exception as exc:
            dest_path.unlink(missing_ok=True)
            raise BackupError("backup.create.failed") from exc

        file_size = dest_path.stat().st_size
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
        """Restore the live DB from *backup_path*.

        Safety protocol:
        1. Validate the file (exists, .sqlite extension, readable as SQLite).
        2. Create a before_restore snapshot — if this fails, abort.
        3. Restore from backup_path into the live connection.
        4. Re-apply migrations (idempotent).
        5. Write audit log.

        Raises BackupError on validation or before_restore failure.
        Never corrupts the live DB if step 1 or 2 fails.
        """
        self._validate_backup_file(backup_path)

        # Step 2: create safety snapshot before overwriting anything
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            paths.backups_dir.mkdir(parents=True, exist_ok=True)
            before_filename = f"before_restore_{ts}.sqlite"
            before_path = paths.backups_dir / before_filename
            with sqlite3.connect(str(before_path)) as dest_conn:
                self._conn.backup(dest_conn)
            before_size = before_path.stat().st_size
            self._repo.insert(
                filename=before_filename,
                backup_path=str(before_path),
                file_size=before_size,
                notes="before_restore",
            )
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError("backup.before_restore.failed") from exc

        # Step 3: restore
        try:
            with sqlite3.connect(str(backup_path)) as src_conn:
                src_conn.backup(self._conn)
        except Exception as exc:
            raise BackupError("backup.restore.failed") from exc

        # Step 4: re-apply migrations (idempotent — ensures schema is current)
        try:
            apply_migrations(self._conn)
        except Exception:
            _log.error("backup.restore: apply_migrations failed — restart recommended", exc_info=True)

        self._audit.record(
            action="backup.restore",
            target_type="backup",
            detail={
                "restored_from": str(backup_path),
                "before_restore_snapshot": str(before_path),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_backup_file(self, backup_path: Path) -> None:
        if not backup_path.exists():
            raise BackupError("backup.file_not_found")
        if backup_path.suffix.lower() != ".sqlite":
            raise BackupError("backup.invalid_file")
        try:
            with sqlite3.connect(str(backup_path)) as c:
                c.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        except Exception as exc:
            raise BackupError("backup.invalid_file") from exc
