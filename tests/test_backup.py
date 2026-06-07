"""Tests for BackupService, BackupRepository, and backup action contracts."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from taxops.core.paths import resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.backup import BackupRepository
from taxops.services.audit import AuditService
from taxops.services.backup import BackupError, BackupService
from taxops.ui.action_registry import PAGE_SETTINGS, actions_for_page


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def conn(tmp_path):
    paths = resolve_paths(override_root=tmp_path / "data")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    c = open_connection(paths.db_path)
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def paths(tmp_path):
    p = resolve_paths(override_root=tmp_path / "data")
    p.data_root.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def repo(conn):
    return BackupRepository(conn)


@pytest.fixture
def audit(conn):
    return AuditService(AuditLogRepository(conn), actor="test")


@pytest.fixture
def svc(conn, repo, audit):
    return BackupService(conn=conn, repo=repo, audit=audit)


# ── create_backup ────────────────────────────────────────────────────────────


def test_backup_creates_sqlite_file(svc, paths):
    row = svc.create_backup(paths)
    assert Path(row.backup_path).exists()


def test_backup_filename_format(svc, paths):
    row = svc.create_backup(paths)
    assert row.filename.startswith("office_desk_")
    assert row.filename.endswith(".sqlite")


def test_backups_created_in_same_second_have_unique_names(svc, paths):
    first = svc.create_backup(paths)
    second = svc.create_backup(paths)

    assert first.filename != second.filename
    assert Path(first.backup_path).exists()
    assert Path(second.backup_path).exists()


def test_backup_file_is_readable_sqlite(svc, paths):
    row = svc.create_backup(paths)
    with sqlite3.connect(row.backup_path) as c:
        tables = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert len(tables) > 0


def test_backup_writes_record(svc, repo, paths):
    row = svc.create_backup(paths)
    records = repo.list_all()
    assert any(r.id == row.id for r in records)


def test_backup_record_has_positive_file_size(svc, paths):
    row = svc.create_backup(paths)
    assert row.file_size > 0


def test_backup_records_audit(conn, svc, paths):
    svc.create_backup(paths)
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'backup.create'"
    ).fetchone()
    assert log is not None


def test_backup_creates_in_backups_dir(svc, paths):
    row = svc.create_backup(paths)
    assert Path(row.backup_path).parent == paths.backups_dir


# ── restore_backup ───────────────────────────────────────────────────────────


def test_restore_creates_before_restore_backup(svc, paths):
    # After restore the live DB is replaced, so backup_records reverts to the
    # backup's state.  Check the before_restore FILE on disk instead.
    backup_row = svc.create_backup(paths)
    svc.restore_backup(Path(backup_row.backup_path), paths)

    before_files = list(paths.backups_dir.glob("before_restore_*.sqlite"))
    assert len(before_files) >= 1


def test_restore_before_restore_is_readable_sqlite(svc, paths):
    backup_row = svc.create_backup(paths)
    svc.restore_backup(Path(backup_row.backup_path), paths)

    before_files = list(paths.backups_dir.glob("before_restore_*.sqlite"))
    assert len(before_files) >= 1
    with sqlite3.connect(str(before_files[0])) as c:
        tables = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert len(tables) > 0


def test_restore_records_audit(conn, svc, paths):
    backup_row = svc.create_backup(paths)
    svc.restore_backup(Path(backup_row.backup_path), paths)
    log = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'backup.restore'"
    ).fetchone()
    assert log is not None


def test_restore_preserves_before_restore_record(repo, svc, paths):
    backup_row = svc.create_backup(paths)
    svc.restore_backup(Path(backup_row.backup_path), paths)

    records = repo.list_all()
    assert any(row.notes == "before_restore" for row in records)


def test_restore_nonexistent_file_rejected(svc, paths):
    missing = paths.backups_dir / "nonexistent.sqlite"
    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(missing, paths)
    assert exc_info.value.code == "backup.file_not_found"


def test_restore_wrong_extension_rejected(svc, paths, tmp_path):
    wrong = tmp_path / "backup.txt"
    wrong.write_text("not a sqlite file")
    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(wrong, paths)
    assert exc_info.value.code == "backup.invalid_file"


def test_restore_invalid_sqlite_rejected(svc, paths, tmp_path):
    bad = tmp_path / "corrupt.sqlite"
    bad.write_bytes(b"This is not a valid SQLite database file")
    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(bad, paths)
    assert exc_info.value.code == "backup.invalid_file"


def test_restore_rejects_non_taxops_sqlite_without_touching_live_db(
    conn, svc, paths, tmp_path
):
    foreign_db = tmp_path / "foreign.sqlite"
    with sqlite3.connect(foreign_db) as foreign_conn:
        foreign_conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before_hash = hashlib.sha256(paths.db_path.read_bytes()).hexdigest()

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(foreign_db, paths)

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    after_hash = hashlib.sha256(paths.db_path.read_bytes()).hexdigest()
    assert exc_info.value.code == "backup.invalid_file"
    assert after_hash == before_hash


def test_restore_rejects_unknown_migration_version(svc, paths):
    backup_row = svc.create_backup(paths)
    forged = Path(backup_row.backup_path)
    with sqlite3.connect(forged) as forged_conn:
        forged_conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            ("9999_attacker", "2026-06-07T00:00:00"),
        )

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(forged, paths)

    assert exc_info.value.code == "backup.invalid_file"


def test_restore_rejects_unknown_trigger_before_migration(svc, paths):
    backup_row = svc.create_backup(paths)
    forged = Path(backup_row.backup_path)
    with sqlite3.connect(forged) as forged_conn:
        forged_conn.execute(
            "CREATE TRIGGER attacker_trigger AFTER INSERT ON schema_migrations"
            " BEGIN DELETE FROM clients; END"
        )

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(forged, paths)

    assert exc_info.value.code == "backup.invalid_file"


def test_restore_rejects_foreign_key_corruption(svc, paths):
    backup_row = svc.create_backup(paths)
    forged = Path(backup_row.backup_path)
    with sqlite3.connect(forged) as forged_conn:
        forged_conn.execute("PRAGMA foreign_keys = OFF")
        forged_conn.execute(
            "INSERT INTO engagements("
            " client_id, engagement_name, tax_type, period_name, status,"
            " created_at, updated_at"
            ") VALUES (999999, 'orphan', 'vat', '2026', 'draft', ?, ?)",
            ("2026-06-07T00:00:00", "2026-06-07T00:00:00"),
        )

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(forged, paths)

    assert exc_info.value.code == "backup.invalid_file"


def test_restore_migration_failure_leaves_live_db_hash_unchanged(
    conn, svc, paths, monkeypatch
):
    backup_row = svc.create_backup(paths)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before_hash = hashlib.sha256(paths.db_path.read_bytes()).hexdigest()

    def fail_migration(_conn):
        raise sqlite3.OperationalError("simulated migration failure")

    monkeypatch.setattr("taxops.services.backup.apply_migrations", fail_migration)

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(Path(backup_row.backup_path), paths)

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    after_hash = hashlib.sha256(paths.db_path.read_bytes()).hexdigest()
    assert exc_info.value.code == "backup.restore_migrate_failed"
    assert after_hash == before_hash


def test_before_restore_failure_prevents_restore(conn, svc, repo, paths, monkeypatch):
    """If the before_restore backup fails, the live DB must not be touched."""
    # Seed a sentinel row that is NOT in the backup
    backup_row = svc.create_backup(paths)

    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at)"
        " VALUES ('SENTINEL', '哨兵', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()

    original_connect = sqlite3.connect

    def patched_connect(path_str, *args, **kwargs):
        if Path(path_str).name.startswith("before_restore_"):
            raise OSError("simulated disk failure")
        return original_connect(path_str, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", patched_connect)

    with pytest.raises(BackupError) as exc_info:
        svc.restore_backup(Path(backup_row.backup_path), paths)
    assert exc_info.value.code == "backup.before_restore.failed"

    # Sentinel must still exist — restore was not performed
    row = conn.execute(
        "SELECT * FROM clients WHERE client_code = 'SENTINEL'"
    ).fetchone()
    assert row is not None, "Sentinel was deleted — restore ran despite before_restore failure"


# ── action registry contracts ────────────────────────────────────────────────


def test_backup_contracts_in_registry():
    contracts = actions_for_page(PAGE_SETTINGS)
    labels = {c.button_label for c in contracts}
    assert "立即備份" in labels
    assert "還原備份" in labels


def test_backup_contract_has_required_fields():
    for c in actions_for_page(PAGE_SETTINGS):
        if c.button_label == "立即備份":
            assert c.audit_action == "backup.create"
            assert c.service is not None
            assert c.repository is not None
            assert c.enabled is True
            return
    pytest.fail("立即備份 contract not found")


def test_restore_contract_has_required_fields():
    for c in actions_for_page(PAGE_SETTINGS):
        if c.button_label == "還原備份":
            assert c.audit_action == "backup.restore"
            assert c.service is not None
            assert c.repository is not None
            assert c.enabled is True
            return
    pytest.fail("還原備份 contract not found")
