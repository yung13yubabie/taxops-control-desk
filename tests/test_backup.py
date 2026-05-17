"""Tests for BackupService, BackupRepository, and backup action contracts."""

from __future__ import annotations

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


def test_before_restore_failure_prevents_restore(conn, svc, repo, paths, monkeypatch):
    """If the before_restore backup fails, the live DB must not be touched."""
    # Seed a sentinel row that is NOT in the backup
    backup_row = svc.create_backup(paths)

    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at)"
        " VALUES ('SENTINEL', '哨兵', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()

    # Monkeypatch sqlite3.connect to raise on the first call inside restore
    # (which is the before_restore step)
    call_count = 0
    original_connect = sqlite3.connect

    def patched_connect(path_str, **kwargs):
        nonlocal call_count
        call_count += 1
        # call 1 = _validate_backup_file (must succeed so validation passes)
        # call 2 = before_restore snapshot write (this is what we want to fail)
        if call_count == 2:
            raise OSError("simulated disk failure")
        return original_connect(path_str, **kwargs)

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
