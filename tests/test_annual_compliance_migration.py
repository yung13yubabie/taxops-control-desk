"""Regression coverage for the v0.30 annual-compliance schema migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from taxops.db import migrate
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.db.migrations import MIGRATIONS


@pytest.fixture
def pre_annual_conn(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sqlite3.Connection]:
    """Create the exact schema immediately before migration 0028."""
    assert MIGRATIONS[26][0] == "0027_client_master_expansion"
    conn = open_connection(tmp_path / "pre-annual.sqlite")
    monkeypatch.setattr(migrate, "MIGRATIONS", MIGRATIONS[:27])
    apply_migrations(conn)
    monkeypatch.setattr(migrate, "MIGRATIONS", MIGRATIONS)
    try:
        yield conn
    finally:
        conn.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _insert_client(conn: sqlite3.Connection, code: str = "ANNUAL") -> int:
    return int(
        conn.execute(
            "INSERT INTO clients(client_code, client_name, created_at, updated_at) "
            "VALUES (?, ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (code, f"{code} 測試客戶"),
        ).lastrowid
    )


def _insert_workspace(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    operation_year: int = 2026,
) -> int:
    return int(
        conn.execute(
            "INSERT INTO annual_workspaces("
            "client_id, operation_year, fiscal_year_start_month_snapshot, "
            "created_at, updated_at"
            ") VALUES (?, ?, 1, '2026-01-01', '2026-01-01')",
            (client_id, operation_year),
        ).lastrowid
    )


def _insert_item(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    item_key: str = "vat:2026:01-02",
) -> int:
    return int(
        conn.execute(
            "INSERT INTO annual_work_items("
            "workspace_id, item_key, work_type, title, tax_year, period_code, "
            "created_at, updated_at"
            ") VALUES (?, ?, 'vat', '營業稅 01-02 月', 2026, '01-02', "
            "'2026-01-01', '2026-01-01')",
            (workspace_id, item_key),
        ).lastrowid
    )


def test_annual_compliance_migration_creates_all_required_tables(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    assert "annual_workspaces" not in _table_names(pre_annual_conn)

    assert apply_migrations(pre_annual_conn) == ["0028_annual_compliance"]

    assert {
        "compliance_profiles",
        "compliance_profile_items",
        "annual_workspaces",
        "annual_work_items",
        "annual_work_transactions",
    } <= _table_names(pre_annual_conn)


def test_annual_compliance_schema_has_exact_columns_and_required_indexes(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)

    expected_columns = {
        "compliance_profiles": {
            "id",
            "client_id",
            "fiscal_year_start_month",
            "created_at",
            "updated_at",
        },
        "compliance_profile_items": {
            "id",
            "profile_id",
            "work_type",
            "frequency",
            "enabled",
            "notes",
            "created_at",
            "updated_at",
        },
        "annual_workspaces": {
            "id",
            "client_id",
            "operation_year",
            "fiscal_year_start_month_snapshot",
            "status",
            "created_at",
            "updated_at",
            "deleted_at",
        },
        "annual_work_items": {
            "id",
            "workspace_id",
            "item_key",
            "work_type",
            "title",
            "tax_year",
            "period_code",
            "suggested_due_date",
            "due_date",
            "work_status",
            "filing_status",
            "document_status",
            "tax_status",
            "fee_status",
            "engagement_id",
            "exception_reason",
            "notes",
            "completed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            "deleted_at",
        },
        "annual_work_transactions": {
            "id",
            "work_item_id",
            "category",
            "amount",
            "transaction_date",
            "reference",
            "notes",
            "created_at",
            "updated_at",
            "deleted_at",
        },
    }
    for table, expected in expected_columns.items():
        actual = {
            row["name"]
            for row in pre_annual_conn.execute(f"PRAGMA table_info({table})")
        }
        assert actual == expected, table

    task_columns = {
        row["name"]
        for row in pre_annual_conn.execute("PRAGMA table_info(workflow_tasks)")
    }
    assert "annual_work_item_id" in task_columns

    indexes = {
        row["name"]: row["sql"]
        for row in pre_annual_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index'"
        )
    }
    required_indexes = {
        "idx_annual_workspaces_client_year",
        "ux_annual_workspaces_active",
        "idx_annual_work_items_workspace",
        "idx_annual_work_items_due_date",
        "idx_annual_work_items_engagement",
        "ux_annual_work_items_active",
        "idx_annual_transactions_work_item",
        "idx_workflow_tasks_annual_item",
    }
    assert required_indexes <= indexes.keys()
    assert "idx_compliance_profile_items_profile" not in indexes
    assert "WHERE deleted_at IS NULL" in indexes["ux_annual_workspaces_active"]
    assert "WHERE deleted_at IS NULL" in indexes["ux_annual_work_items_active"]
    profile_plan = [
        row["detail"]
        for row in pre_annual_conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT notes FROM compliance_profile_items WHERE profile_id = ?",
            (1,),
        )
    ]
    assert any(
        "sqlite_autoindex_compliance_profile_items_1" in detail
        and "profile_id=?" in detail
        for detail in profile_plan
    ), profile_plan


def test_active_workspace_and_item_keys_are_unique_but_soft_delete_can_recreate(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn)
    first_workspace = _insert_workspace(pre_annual_conn, client_id)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_workspace(pre_annual_conn, client_id)

    first_item = _insert_item(pre_annual_conn, first_workspace)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_item(pre_annual_conn, first_workspace)

    pre_annual_conn.execute(
        "UPDATE annual_work_items SET deleted_at = '2026-02-01' WHERE id = ?",
        (first_item,),
    )
    replacement_item = _insert_item(pre_annual_conn, first_workspace)
    assert replacement_item != first_item

    pre_annual_conn.execute(
        "UPDATE annual_workspaces SET deleted_at = '2026-02-01' WHERE id = ?",
        (first_workspace,),
    )
    replacement_workspace = _insert_workspace(pre_annual_conn, client_id)
    assert replacement_workspace != first_workspace


@pytest.mark.parametrize(
    "invalid_year",
    [1911, 10_000, 2026.5, "民國一一五年"],
)
def test_workspace_rejects_operation_year_outside_supported_range(
    pre_annual_conn: sqlite3.Connection,
    invalid_year: object,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, f"YEAR-{invalid_year}")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_workspace(
            pre_annual_conn,
            client_id,
            operation_year=invalid_year,
        )


@pytest.mark.parametrize("invalid_month", [0, 13, 1.5, "一月"])
def test_fiscal_start_month_constraints_reject_invalid_values(
    pre_annual_conn: sqlite3.Connection,
    invalid_month: object,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, f"MONTH-{invalid_month}")
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(
            "INSERT INTO compliance_profiles("
            "client_id, fiscal_year_start_month, created_at, updated_at"
            ") VALUES (?, ?, '2026-01-01', '2026-01-01')",
            (client_id, invalid_month),
        )
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(
            "INSERT INTO annual_workspaces("
            "client_id, operation_year, fiscal_year_start_month_snapshot, "
            "created_at, updated_at"
            ") VALUES (?, 2026, ?, '2026-01-01', '2026-01-01')",
            (client_id, invalid_month),
        )


def test_profile_item_boolean_and_duplicate_work_type_are_constrained(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, "PROFILE")
    profile_id = pre_annual_conn.execute(
        "INSERT INTO compliance_profiles(client_id, created_at, updated_at) "
        "VALUES (?, '2026-01-01', '2026-01-01')",
        (client_id,),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(
            "INSERT INTO compliance_profiles(client_id, created_at, updated_at) "
            "VALUES (?, '2026-01-02', '2026-01-02')",
            (client_id,),
        )
    insert = (
        "INSERT INTO compliance_profile_items("
        "profile_id, work_type, frequency, enabled, created_at, updated_at"
        ") VALUES (?, ?, 'bimonthly', ?, '2026-01-01', '2026-01-01')"
    )
    pre_annual_conn.execute(insert, (profile_id, "vat", 1))
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(insert, (profile_id, "vat", 1))
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(insert, (profile_id, "withholding", 2))
    for invalid_enabled in (1.5, "yes"):
        with pytest.raises(sqlite3.IntegrityError):
            pre_annual_conn.execute(
                insert,
                (profile_id, f"enabled-{invalid_enabled}", invalid_enabled),
            )


@pytest.mark.parametrize(
    ("column", "future_value"),
    [
        ("work_status", "pretend_success"),
        ("filing_status", "silently_filed"),
        ("document_status", "probably_complete"),
        ("tax_status", "unknown_paid"),
        ("fee_status", "maybe_received"),
    ],
)
def test_annual_item_preserves_unknown_independent_statuses_for_forward_compatibility(
    pre_annual_conn: sqlite3.Connection,
    column: str,
    future_value: str,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, f"STATUS-{column}")
    item_id = _insert_item(
        pre_annual_conn,
        _insert_workspace(pre_annual_conn, client_id),
    )
    defaults = pre_annual_conn.execute(
        "SELECT work_status, filing_status, document_status, tax_status, fee_status "
        "FROM annual_work_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    assert tuple(defaults) == (
        "not_started",
        "not_filed",
        "not_requested",
        "unconfirmed",
        "not_billed",
    )
    inserted_item_id = pre_annual_conn.execute(
        "INSERT INTO annual_work_items("
        f"workspace_id, item_key, work_type, title, {column}, created_at, updated_at"
        ") VALUES (?, ?, 'custom', '未來狀態工作', ?, '2026-01-01', '2026-01-01')",
        (
            pre_annual_conn.execute(
                "SELECT workspace_id FROM annual_work_items WHERE id = ?",
                (item_id,),
            ).fetchone()[0],
            f"future:{column}",
            future_value,
        ),
    ).lastrowid
    assert pre_annual_conn.execute(
        f"SELECT {column} FROM annual_work_items WHERE id = ?",
        (inserted_item_id,),
    ).fetchone()[0] == future_value
    pre_annual_conn.execute(
        f"UPDATE annual_work_items SET {column} = ? WHERE id = ?",
        (future_value, item_id),
    )
    assert pre_annual_conn.execute(
        f"SELECT {column} FROM annual_work_items WHERE id = ?",
        (item_id,),
    ).fetchone()[0] == future_value


def test_workspace_preserves_unknown_status_for_forward_compatibility(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, "WORKSPACE-STATUS")
    workspace_id = pre_annual_conn.execute(
        "INSERT INTO annual_workspaces("
        "client_id, operation_year, fiscal_year_start_month_snapshot, status, "
        "created_at, updated_at"
        ") VALUES (?, 2026, 1, 'future_review', '2026-01-01', '2026-01-01')",
        (client_id,),
    ).lastrowid
    assert pre_annual_conn.execute(
        "SELECT status FROM annual_workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()[0] == "future_review"
    pre_annual_conn.execute(
        "UPDATE annual_workspaces SET status = 'future_reopened' WHERE id = ?",
        (workspace_id,),
    )
    assert pre_annual_conn.execute(
        "SELECT status FROM annual_workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()[0] == "future_reopened"

    default_client_id = _insert_client(pre_annual_conn, "WORKSPACE-DEFAULT")
    default_workspace_id = _insert_workspace(pre_annual_conn, default_client_id)
    assert pre_annual_conn.execute(
        "SELECT status FROM annual_workspaces WHERE id = ?",
        (default_workspace_id,),
    ).fetchone()[0] == "active"


def test_supported_year_month_tax_year_and_status_boundaries_are_accepted(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_1912 = _insert_client(pre_annual_conn, "BOUNDARY-1912")
    workspace_1912 = pre_annual_conn.execute(
        "INSERT INTO annual_workspaces("
        "client_id, operation_year, fiscal_year_start_month_snapshot, status, "
        "created_at, updated_at"
        ") VALUES (?, 1912, 1, 'archived', '2026-01-01', '2026-01-01')",
        (client_1912,),
    ).lastrowid
    client_9999 = _insert_client(pre_annual_conn, "BOUNDARY-9999")
    workspace_9999 = pre_annual_conn.execute(
        "INSERT INTO annual_workspaces("
        "client_id, operation_year, fiscal_year_start_month_snapshot, "
        "created_at, updated_at"
        ") VALUES (?, 9999, 12, '2026-01-01', '2026-01-01')",
        (client_9999,),
    ).lastrowid
    pre_annual_conn.execute(
        "INSERT INTO compliance_profiles("
        "client_id, fiscal_year_start_month, created_at, updated_at"
        ") VALUES (?, 1, '2026-01-01', '2026-01-01')",
        (client_1912,),
    )
    pre_annual_conn.execute(
        "INSERT INTO compliance_profiles("
        "client_id, fiscal_year_start_month, created_at, updated_at"
        ") VALUES (?, 12, '2026-01-01', '2026-01-01')",
        (client_9999,),
    )
    pre_annual_conn.executemany(
        "INSERT INTO annual_work_items("
        "workspace_id, item_key, work_type, title, tax_year, created_at, updated_at"
        ") VALUES (?, ?, 'custom', '邊界工作', ?, '2026-01-01', '2026-01-01')",
        (
            (workspace_1912, "boundary:1912", 1912),
            (workspace_9999, "boundary:9999", 9999),
            (workspace_9999, "boundary:null", None),
        ),
    )
    workspace_storage = [
        tuple(row)
        for row in pre_annual_conn.execute(
            "SELECT operation_year, typeof(operation_year), "
            "fiscal_year_start_month_snapshot, "
            "typeof(fiscal_year_start_month_snapshot) "
            "FROM annual_workspaces ORDER BY operation_year"
        )
    ]
    assert workspace_storage == [
        (1912, "integer", 1, "integer"),
        (9999, "integer", 12, "integer"),
    ]
    profile_storage = [
        tuple(row)
        for row in pre_annual_conn.execute(
            "SELECT fiscal_year_start_month, typeof(fiscal_year_start_month) "
            "FROM compliance_profiles ORDER BY fiscal_year_start_month"
        )
    ]
    assert profile_storage == [(1, "integer"), (12, "integer")]
    tax_year_storage = [
        tuple(row)
        for row in pre_annual_conn.execute(
            "SELECT tax_year, typeof(tax_year) FROM annual_work_items "
            "ORDER BY item_key"
        )
    ]
    assert tax_year_storage == [
        (1912, "integer"),
        (9999, "integer"),
        (None, "null"),
    ]

    item_id = pre_annual_conn.execute(
        "SELECT id FROM annual_work_items WHERE item_key = 'boundary:9999'"
    ).fetchone()[0]
    valid_values = {
        "work_status": (
            "not_started",
            "in_progress",
            "completed",
            "completed_with_exception",
            "exception",
            "not_applicable",
            "cancelled",
        ),
        "filing_status": (
            "not_filed",
            "filed",
            "filing_failed",
            "correction_required",
        ),
        "document_status": (
            "not_requested",
            "missing",
            "partially_received",
            "complete",
            "not_applicable",
        ),
        "tax_status": (
            "unconfirmed",
            "awaiting_collection",
            "partially_collected",
            "collected",
            "paid",
            "unpaid",
            "refund",
            "not_applicable",
        ),
        "fee_status": (
            "not_billed",
            "awaiting_payment",
            "partially_paid",
            "paid",
            "not_applicable",
        ),
    }
    for column, values in valid_values.items():
        for value in values:
            pre_annual_conn.execute(
                f"UPDATE annual_work_items SET {column} = ? WHERE id = ?",
                (value, item_id),
            )


@pytest.mark.parametrize(
    "invalid_tax_year",
    [1911, 10_000, 2026.5, "民國一一五年"],
)
def test_annual_item_rejects_tax_year_outside_supported_range(
    pre_annual_conn: sqlite3.Connection,
    invalid_tax_year: object,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, f"TAX-YEAR-{invalid_tax_year}")
    workspace_id = _insert_workspace(pre_annual_conn, client_id)
    with pytest.raises(sqlite3.IntegrityError):
        pre_annual_conn.execute(
            "INSERT INTO annual_work_items("
            "workspace_id, item_key, work_type, title, tax_year, created_at, updated_at"
            ") VALUES (?, 'invalid-tax-year', 'custom', '錯誤課稅年度', ?, "
            "'2026-01-01', '2026-01-01')",
            (workspace_id, invalid_tax_year),
        )


def test_transaction_category_and_amount_constraints_include_both_boundaries(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, "MONEY")
    item_id = _insert_item(
        pre_annual_conn,
        _insert_workspace(pre_annual_conn, client_id),
    )
    insert = (
        "INSERT INTO annual_work_transactions("
        "work_item_id, category, amount, transaction_date, created_at, updated_at"
        ") VALUES (?, ?, ?, '2026-05-10', '2026-05-10', '2026-05-10')"
    )
    pre_annual_conn.execute(insert, (item_id, "tax_liability", 0))
    pre_annual_conn.execute(
        insert,
        (item_id, "fee_receipt", 9_000_000_000_000),
    )
    for category, amount in (
        ("tax_liability", -1),
        ("tax_liability", 9_000_000_000_001),
        ("untracked_total", 100),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            pre_annual_conn.execute(insert, (item_id, category, amount))


def test_transaction_amount_requires_integer_sqlite_storage_class(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    client_id = _insert_client(pre_annual_conn, "MONEY-TYPE")
    item_id = _insert_item(
        pre_annual_conn,
        _insert_workspace(pre_annual_conn, client_id),
    )
    insert = (
        "INSERT INTO annual_work_transactions("
        "work_item_id, category, amount, transaction_date, created_at, updated_at"
        ") VALUES (?, 'fee_receipt', ?, '2026-05-10', '2026-05-10', '2026-05-10')"
    )
    for invalid_amount in (1.5, "一百元"):
        with pytest.raises(sqlite3.IntegrityError):
            pre_annual_conn.execute(insert, (item_id, invalid_amount))

    bool_row_id = pre_annual_conn.execute(insert, (item_id, True)).lastrowid
    bool_row = pre_annual_conn.execute(
        "SELECT amount, typeof(amount) FROM annual_work_transactions WHERE id = ?",
        (bool_row_id,),
    ).fetchone()
    # sqlite3 binds Python bool as integer 0/1; schema cannot distinguish it.
    assert tuple(bool_row) == (1, "integer")


def test_profile_children_cascade_but_evidence_links_restrict_deletion(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    profile_client = _insert_client(pre_annual_conn, "CASCADE")
    profile_id = pre_annual_conn.execute(
        "INSERT INTO compliance_profiles(client_id, created_at, updated_at) "
        "VALUES (?, '2026-01-01', '2026-01-01')",
        (profile_client,),
    ).lastrowid
    pre_annual_conn.execute(
        "INSERT INTO compliance_profile_items("
        "profile_id, work_type, frequency, created_at, updated_at"
        ") VALUES (?, 'vat', 'bimonthly', '2026-01-01', '2026-01-01')",
        (profile_id,),
    )
    pre_annual_conn.execute(
        "DELETE FROM compliance_profiles WHERE id = ?",
        (profile_id,),
    )
    assert pre_annual_conn.execute(
        "SELECT COUNT(*) FROM compliance_profile_items WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()[0] == 0

    evidence_client = _insert_client(pre_annual_conn, "RESTRICT")
    workspace_id = _insert_workspace(pre_annual_conn, evidence_client)
    item_id = _insert_item(pre_annual_conn, workspace_id)
    pre_annual_conn.execute(
        "INSERT INTO annual_work_transactions("
        "work_item_id, category, amount, transaction_date, created_at, updated_at"
        ") VALUES (?, 'tax_liability', 100, '2026-01-01', '2026-01-01', '2026-01-01')",
        (item_id,),
    )
    pre_annual_conn.execute(
        "INSERT INTO workflow_tasks("
        "client_id, annual_work_item_id, title, created_at, updated_at"
        ") VALUES (?, ?, '年度工作待辦', '2026-01-01', '2026-01-01')",
        (evidence_client, item_id),
    )

    for statement, parameter in (
        ("DELETE FROM clients WHERE id = ?", evidence_client),
        ("DELETE FROM annual_workspaces WHERE id = ?", workspace_id),
        ("DELETE FROM annual_work_items WHERE id = ?", item_id),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            pre_annual_conn.execute(statement, (parameter,))


def test_upgrade_preserves_existing_workflow_task_and_sequence_high_water(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    client_id = _insert_client(pre_annual_conn, "LEGACY-TASK")
    pre_annual_conn.execute(
        "INSERT INTO workflow_tasks("
        "id, client_id, title, assignee, due_date, priority, status, next_step, "
        "notes, created_at, updated_at"
        ") VALUES (37, ?, '既有年度前待辦', '林會計師', '2026-08-31', "
        "'high', 'doing', '追憑證', '不可遺失', '2026-01-01', '2026-01-02')",
        (client_id,),
    )
    pre_annual_conn.execute(
        "UPDATE sqlite_sequence SET seq = 900 WHERE name = 'workflow_tasks'"
    )
    sequence_before = {
        row["name"]: row["seq"]
        for row in pre_annual_conn.execute(
            "SELECT name, seq FROM sqlite_sequence"
        ).fetchall()
    }

    assert apply_migrations(pre_annual_conn) == ["0028_annual_compliance"]

    task = pre_annual_conn.execute(
        "SELECT id, client_id, title, assignee, due_date, priority, status, "
        "next_step, notes, created_at, updated_at, annual_work_item_id "
        "FROM workflow_tasks WHERE id = 37"
    ).fetchone()
    assert tuple(task) == (
        37,
        client_id,
        "既有年度前待辦",
        "林會計師",
        "2026-08-31",
        "high",
        "doing",
        "追憑證",
        "不可遺失",
        "2026-01-01",
        "2026-01-02",
        None,
    )
    sequence_after = {
        row["name"]: row["seq"]
        for row in pre_annual_conn.execute(
            "SELECT name, seq FROM sqlite_sequence"
        ).fetchall()
    }
    assert all(
        sequence_after[name] >= high_water
        for name, high_water in sequence_before.items()
    )
    next_task_id = pre_annual_conn.execute(
        "INSERT INTO workflow_tasks(client_id, title, created_at, updated_at) "
        "VALUES (?, '升級後待辦', '2026-01-03', '2026-01-03')",
        (client_id,),
    ).lastrowid
    assert next_task_id > 900


def test_task_link_foreign_key_targets_annual_item(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    apply_migrations(pre_annual_conn)
    task_foreign_keys = {
        (row["from"], row["table"], row["to"], row["on_delete"])
        for row in pre_annual_conn.execute(
            "PRAGMA foreign_key_list(workflow_tasks)"
        )
    }
    assert (
        "annual_work_item_id",
        "annual_work_items",
        "id",
        "NO ACTION",
    ) in task_foreign_keys


def test_annual_compliance_migration_is_idempotent_and_foreign_keys_are_clean(
    pre_annual_conn: sqlite3.Connection,
) -> None:
    assert apply_migrations(pre_annual_conn) == ["0028_annual_compliance"]
    assert apply_migrations(pre_annual_conn) == []
    assert pre_annual_conn.execute(
        "SELECT COUNT(*) FROM schema_migrations "
        "WHERE version = '0028_annual_compliance'"
    ).fetchone()[0] == 1
    assert pre_annual_conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_annual_migration_rolls_back_schema_task_column_and_version(
    pre_annual_conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = _insert_client(pre_annual_conn, "ROLLBACK")
    pre_annual_conn.execute(
        "INSERT INTO workflow_tasks("
        "id, client_id, title, created_at, updated_at"
        ") VALUES (51, ?, '不得遺失', '2026-01-01', '2026-01-01')",
        (client_id,),
    )
    pre_annual_conn.execute(
        "UPDATE sqlite_sequence SET seq = 777 WHERE name = 'workflow_tasks'"
    )
    failing_sql = MIGRATIONS[27][1] + "\nINSERT INTO missing_annual_table(id) VALUES (1);"
    monkeypatch.setattr(
        migrate,
        "MIGRATIONS",
        (("0028_annual_compliance", failing_sql),),
    )

    with pytest.raises(sqlite3.OperationalError, match="missing_annual_table"):
        apply_migrations(pre_annual_conn)

    assert not {
        "compliance_profiles",
        "compliance_profile_items",
        "annual_workspaces",
        "annual_work_items",
        "annual_work_transactions",
    } & _table_names(pre_annual_conn)
    task_columns = {
        row["name"]
        for row in pre_annual_conn.execute("PRAGMA table_info(workflow_tasks)")
    }
    assert "annual_work_item_id" not in task_columns
    assert tuple(
        pre_annual_conn.execute(
            "SELECT id, client_id, title FROM workflow_tasks WHERE id = 51"
        ).fetchone()
    ) == (51, client_id, "不得遺失")
    assert pre_annual_conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'workflow_tasks'"
    ).fetchone()[0] == 777
    assert pre_annual_conn.execute(
        "SELECT version FROM schema_migrations "
        "WHERE version = '0028_annual_compliance'"
    ).fetchone() is None
    assert pre_annual_conn.execute("PRAGMA foreign_key_check").fetchall() == []
