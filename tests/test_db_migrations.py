"""Migration runner: tables created and idempotent re-runs."""

from __future__ import annotations

import sqlite3

import pytest

from taxops.db import migrate
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
    "folder_bookmarks",
    "late_fee_records",
    "attachments",
    "attachment_versions",
    "backup_records",
    "fts_clients",
    "fts_engagements",
    "recurring_billing_plans",
    "recurring_billing_lines",
    "recurring_billing_occurrences",
    "workflow_templates_v2",
    "workflow_runs",
    "error_reviews",
    "canvas_notes",
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
    assert versions == ["0001_initial", "0002_tax_cache", "0003_soft_delete", "0004_engagements", "0005_workflow_tasks", "0006_message_templates", "0007_generated_messages", "0008_review_notes", "0009_late_fee", "0010_attachments", "0011_backup", "0012_fts5", "0013_client_lease", "0014_nullable_engagement", "0015_recurring_billing", "0016_rename_amount_cents", "0017_workflow_tasks_client_id", "0018_task_parent", "0019_drop_review_notes", "0020_folder_bookmarks", "0021_document_request_name", "0022_work_records", "0023_canvas_notes", "0024_payment_follow_up_template", "0025_late_fee_period_breakdown"]


def test_migrations_are_idempotent(db_conn: sqlite3.Connection) -> None:
    second_pass = apply_migrations(db_conn)
    assert second_pass == []
    rows = db_conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()
    assert rows["c"] == 25


def test_document_requests_has_request_name_column(db_conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in db_conn.execute("PRAGMA table_info(document_requests)").fetchall()
    }
    assert "request_name" in cols


def test_clients_has_deleted_at_column(db_conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in db_conn.execute("PRAGMA table_info(clients)").fetchall()
    }
    assert "deleted_at" in cols


def test_failed_migration_rolls_back_schema_and_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(
        migrate,
        "MIGRATIONS",
        (
            (
                "test_failure",
                """
                CREATE TABLE partially_applied (id INTEGER PRIMARY KEY);
                INSERT INTO missing_table(id) VALUES (1);
                """,
            ),
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn)

    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'partially_applied'"
    ).fetchone()
    ledger = conn.execute(
        "SELECT version FROM schema_migrations WHERE version = 'test_failure'"
    ).fetchone()
    assert table is None
    assert ledger is None
    conn.close()
