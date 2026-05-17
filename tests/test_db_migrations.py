"""Migration runner: tables created and idempotent re-runs."""

from __future__ import annotations

import sqlite3

from taxops.db.migrate import apply_migrations

EXPECTED_TABLES = {
    "schema_migrations",
    "app_settings",
    "clients",
    "audit_logs",
    "system_logs",
    "tax_registry_cache",
    "tax_cache_metadata",
    "registry_match_results",
    "engagements",
    "document_requests",
    "document_request_items",
    "workflow_tasks",
    "message_templates",
    "generated_messages",
    "review_notes",
    "late_fee_records",
    "attachments",
    "attachment_versions",
    "backup_records",
    "fts_clients",
    "fts_engagements",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_migrations_create_required_tables(db_conn: sqlite3.Connection) -> None:
    tables = _table_names(db_conn)
    assert EXPECTED_TABLES.issubset(tables), tables


def test_migrations_record_applied_version(db_conn: sqlite3.Connection) -> None:
    rows = db_conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    versions = [row["version"] for row in rows]
    assert versions == ["0001_initial", "0002_tax_cache", "0003_soft_delete", "0004_engagements", "0005_workflow_tasks", "0006_message_templates", "0007_generated_messages", "0008_review_notes", "0009_late_fee", "0010_attachments", "0011_backup", "0012_fts5"]


def test_migrations_are_idempotent(db_conn: sqlite3.Connection) -> None:
    second_pass = apply_migrations(db_conn)
    assert second_pass == []
    rows = db_conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()
    assert rows["c"] == 12


def test_clients_has_deleted_at_column(db_conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in db_conn.execute("PRAGMA table_info(clients)").fetchall()
    }
    assert "deleted_at" in cols
