"""Synthetic cache verification transaction and return-value contracts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from taxops.repositories.app_settings import AppSettingsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.services.registry.status import CacheVerification, verify_cache


def _verify(container):
    return verify_cache(
        container.tax_registry_repo,
        container.tax_cache_metadata_repo,
        container.audit,
    )


def _fresh_connection(container):
    conn = sqlite3.connect(container.paths.db_path, timeout=0.05)
    conn.row_factory = sqlite3.Row
    return closing(conn)


def _assert_other_writer_can_commit(container) -> None:
    with _fresh_connection(container) as other:
        AppSettingsRepository(other).upsert("synthetic.other_writer", "saved")
        other.commit()
    with _fresh_connection(container) as reader:
        assert AppSettingsRepository(reader).get("synthetic.other_writer") == "saved"


def _begin_outer_change(container) -> None:
    AppSettingsRepository(container.conn).upsert("synthetic.outer", "pending")
    assert container.conn.in_transaction


def test_verify_cache_empty_result_persists_without_leaving_write_lock(container):
    assert not container.conn.in_transaction

    result = _verify(container)

    assert result == CacheVerification(None, None, 0, False, None, None, None, None)
    assert not container.conn.in_transaction
    with _fresh_connection(container) as reader:
        rows = AuditLogRepository(reader).list_recent()
        assert len(rows) == 1
        assert rows[0].action == "tax_cache.verify"
        assert rows[0].actor == container.audit.actor
        assert rows[0].target_type == "tax_cache"
        assert rows[0].target_id is None
        assert json.loads(rows[0].detail_json) == {
            "metadata_row_count": None,
            "actual_row_count": 0,
            "row_count_matches": False,
            "cache_version": None,
        }
    _assert_other_writer_can_commit(container)
    # Closing the verifier must not silently discard its successful audit.
    container.conn.close()
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == 1


@pytest.mark.parametrize(
    ("metadata_count", "expected_count", "matches"),
    [("1", 1, True), ("2", 2, False), ("", None, False), ("bad", None, False)],
)
def test_verify_cache_preserves_result_and_audit_semantics(
    container, metadata_count, expected_count, matches
):
    container.conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, cache_version, imported_at) "
        "VALUES (?, ?, ?)",
        ("12345678", "synthetic-version", "2026-01-01T00:00:00Z"),
    )
    metadata = {
        "cache_version": "synthetic-version",
        "row_count": metadata_count,
        "last_import_source": "bundle",
        "data_freshness_iso": "2026-01-01",
        "source_sha256": "a" * 64,
        "bundle_sha256_of_data": "b" * 64,
    }
    container.tax_cache_metadata_repo.upsert_many(metadata)

    result = _verify(container)

    assert result == CacheVerification(
        "synthetic-version", expected_count, 1, matches, "bundle",
        "2026-01-01", "a" * 64, "b" * 64,
    )
    assert not container.conn.in_transaction
    with _fresh_connection(container) as reader:
        rows = AuditLogRepository(reader).list_recent()
        assert len(rows) == 1
        assert rows[0].target_id == "synthetic-version"
        assert json.loads(rows[0].detail_json) == {
            "metadata_row_count": expected_count,
            "actual_row_count": 1,
            "row_count_matches": matches,
            "cache_version": "synthetic-version",
        }
        assert dict(reader.execute("SELECT key, value FROM tax_cache_metadata")) == metadata
        assert reader.execute("SELECT COUNT(*) FROM tax_registry_cache").fetchone()[0] == 1


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_verify_cache_owned_audit_failure_rolls_back_and_releases_lock(
    container, monkeypatch, failure
):
    record = container.audit.record
    error = failure("synthetic audit failure after insert")

    def fail_after_insert(**kwargs):
        record(**kwargs)
        raise error

    monkeypatch.setattr(container.audit, "record", fail_after_insert)
    with pytest.raises(failure) as caught:
        _verify(container)

    assert caught.value is error
    assert not container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 0
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == 0
    _assert_other_writer_can_commit(container)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_verify_cache_preserves_callers_pending_transaction(container, finish):
    _begin_outer_change(container)

    result = _verify(container)

    assert result.actual_row_count == 0
    assert not result.row_count_matches
    assert container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 1
    assert AppSettingsRepository(container.conn).get("synthetic.outer") == "pending"
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == 0
        assert AppSettingsRepository(reader).get("synthetic.outer") is None

    getattr(container.conn, finish)()

    assert not container.conn.in_transaction
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == (1 if finish == "commit" else 0)
        assert AppSettingsRepository(reader).get("synthetic.outer") == (
            "pending" if finish == "commit" else None
        )
    _assert_other_writer_can_commit(container)


def test_verify_cache_preserves_explicit_read_only_outer_transaction(container):
    container.conn.execute("BEGIN")

    _verify(container)

    assert container.conn.in_transaction
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == 0
    container.conn.rollback()
    assert AuditLogRepository(container.conn).count() == 0
    _assert_other_writer_can_commit(container)


def test_verify_cache_preserves_callers_same_named_savepoint(container):
    container.conn.execute("SAVEPOINT taxops_verify_cache")
    _begin_outer_change(container)

    _verify(container)

    assert container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 1
    container.conn.execute("ROLLBACK TO SAVEPOINT taxops_verify_cache")
    container.conn.execute("RELEASE SAVEPOINT taxops_verify_cache")
    assert not container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 0
    assert AppSettingsRepository(container.conn).get("synthetic.outer") is None
    _assert_other_writer_can_commit(container)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_verify_cache_nested_audit_failure_keeps_outer_changes(
    container, monkeypatch, failure
):
    _begin_outer_change(container)
    container.audit.record(action="synthetic.outer", target_type="synthetic")
    record = container.audit.record
    error = failure("synthetic nested audit failure after insert")

    def fail_after_insert(**kwargs):
        record(**kwargs)
        raise error

    monkeypatch.setattr(container.audit, "record", fail_after_insert)
    with pytest.raises(failure) as caught:
        _verify(container)

    assert caught.value is error
    assert container.conn.in_transaction
    assert AppSettingsRepository(container.conn).get("synthetic.outer") == "pending"
    assert [row.action for row in AuditLogRepository(container.conn).list_recent()] == [
        "synthetic.outer"
    ]
    with _fresh_connection(container) as reader:
        assert AppSettingsRepository(reader).get("synthetic.outer") is None
        assert AuditLogRepository(reader).count() == 0
    container.conn.commit()
    with _fresh_connection(container) as reader:
        assert AppSettingsRepository(reader).get("synthetic.outer") == "pending"
        assert [row.action for row in AuditLogRepository(reader).list_recent()] == [
            "synthetic.outer"
        ]
    _assert_other_writer_can_commit(container)


@pytest.mark.parametrize("outer_transaction", [False, True])
def test_verify_cache_read_failure_cleans_only_its_transaction(
    container, monkeypatch, outer_transaction
):
    if outer_transaction:
        _begin_outer_change(container)

    def fail_count():
        raise sqlite3.OperationalError("synthetic count failure")

    monkeypatch.setattr(container.tax_registry_repo, "count", fail_count)
    with pytest.raises(sqlite3.OperationalError, match="synthetic count failure"):
        _verify(container)

    assert container.conn.in_transaction is outer_transaction
    assert AuditLogRepository(container.conn).count() == 0
    if outer_transaction:
        assert AppSettingsRepository(container.conn).get("synthetic.outer") == "pending"
        container.conn.rollback()
    _assert_other_writer_can_commit(container)


def test_verify_cache_owned_transaction_covers_reads_and_audit(container, monkeypatch):
    get_all = container.tax_cache_metadata_repo.get_all
    observations = []

    def observe_metadata_read():
        assert container.conn.in_transaction
        metadata = get_all()
        with _fresh_connection(container) as other:
            # A competing importer cannot change metadata/cache after the
            # metadata read and before the count/audit on the owned transaction.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            observations.append(AuditLogRepository(other).count())
        return metadata

    monkeypatch.setattr(container.tax_cache_metadata_repo, "get_all", observe_metadata_read)
    _verify(container)

    assert observations == [0]
    assert not container.conn.in_transaction
    _assert_other_writer_can_commit(container)


def test_verify_cache_begin_failure_leaves_connection_idle(container):
    container.conn.execute("PRAGMA busy_timeout = 50")
    with _fresh_connection(container) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _verify(container)
        assert not container.conn.in_transaction
        assert writer.in_transaction
        assert AuditLogRepository(container.conn).count() == 0
        writer.rollback()
    _assert_other_writer_can_commit(container)


def test_verify_cache_commit_failure_rolls_back_owned_transaction(container):
    def deny_commit(action, first, _second, _database, _source):
        if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    container.conn.set_authorizer(deny_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            _verify(container)
    finally:
        container.conn.set_authorizer(None)
    assert not container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 0
    _assert_other_writer_can_commit(container)


@pytest.mark.parametrize("denied_operation", ["BEGIN", "RELEASE"])
def test_verify_cache_savepoint_failure_preserves_outer_transaction(
    container, denied_operation
):
    _begin_outer_change(container)
    denied = []

    def deny_once(action, first, _second, _database, _source):
        if action == sqlite3.SQLITE_SAVEPOINT and first == denied_operation and not denied:
            denied.append(first)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    container.conn.set_authorizer(deny_once)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            _verify(container)
    finally:
        container.conn.set_authorizer(None)
    assert denied == [denied_operation]
    assert container.conn.in_transaction
    assert AuditLogRepository(container.conn).count() == 0
    assert AppSettingsRepository(container.conn).get("synthetic.outer") == "pending"
    container.conn.commit()
    with _fresh_connection(container) as reader:
        assert AuditLogRepository(reader).count() == 0
        assert AppSettingsRepository(reader).get("synthetic.outer") == "pending"
    _assert_other_writer_can_commit(container)


@pytest.mark.parametrize("outer_transaction", [False, True])
def test_verify_cache_cleanup_failure_preserves_original_error(
    container, monkeypatch, outer_transaction
):
    if outer_transaction:
        _begin_outer_change(container)
    record = container.audit.record
    error = RuntimeError("synthetic original audit failure")

    def fail_after_insert(**kwargs):
        record(**kwargs)
        raise error

    def deny_rollback(action, first, _second, _database, _source):
        if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT) and first == "ROLLBACK":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    monkeypatch.setattr(container.audit, "record", fail_after_insert)
    container.conn.set_authorizer(deny_rollback)
    try:
        with pytest.raises(RuntimeError) as caught:
            _verify(container)
        assert caught.value is error
        assert "Cache verification rollback also failed" in error.__notes__[0]
        assert "not authorized" in error.__notes__[0]
        assert container.conn.in_transaction
    finally:
        container.conn.set_authorizer(None)
        container.conn.rollback()
    _assert_other_writer_can_commit(container)
