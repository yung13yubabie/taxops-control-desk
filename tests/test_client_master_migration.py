"""Regression coverage for the v0.29 to v0.30 client-master migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from taxops.db import migrate
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.db.migrations import MIGRATIONS


@pytest.fixture
def v029_conn(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sqlite3.Connection]:
    """Create a real v0.29 database, then expose the full migration registry."""
    conn = open_connection(tmp_path / "v029.sqlite")
    monkeypatch.setattr(migrate, "MIGRATIONS", MIGRATIONS[:26])
    apply_migrations(conn)
    monkeypatch.setattr(migrate, "MIGRATIONS", MIGRATIONS)
    try:
        yield conn
    finally:
        conn.close()


_ATTACHMENT_COLUMNS = (
    "id, engagement_id, request_id, original_filename, stored_filename, "
    "file_hash_sha256, file_size, mime_type, extension, uploaded_by, uploaded_at, "
    "source, status, notes, accepted_by, accepted_at"
)


def _seed_v029_attachment_chain(
    conn: sqlite3.Connection,
) -> tuple[int, int, int]:
    client_id = conn.execute(
        "INSERT INTO clients("
        "client_code, client_name, created_at, updated_at"
        ") VALUES ('ATTACH', '附件測試客戶', '2026-01-01T01:00:00', "
        "'2026-01-02T02:00:00')"
    ).lastrowid
    engagement_id = conn.execute(
        "INSERT INTO engagements("
        "client_id, engagement_name, tax_type, period_name, status, created_at, updated_at"
        ") VALUES (?, '營業稅申報', 'vat', '2026-01', 'draft', "
        "'2026-01-03T03:00:00', '2026-01-04T04:00:00')",
        (client_id,),
    ).lastrowid
    request_id = conn.execute(
        "INSERT INTO document_requests("
        "engagement_id, tax_type, period_name, status, due_date, requested_at, "
        "follow_up_count, notes, created_at, updated_at, request_name"
        ") VALUES (?, 'vat', '2026-01', 'requested', '2026-02-10', "
        "'2026-01-05T05:00:00', 2, '請補齊附件', '2026-01-05T05:00:00', "
        "'2026-01-06T06:00:00', '一月憑證')",
        (engagement_id,),
    ).lastrowid

    attachment_rows = (
        (10, "原始.pdf", "2026/01/a.pdf", "a" * 64, 101, "待覆核", "uploaded", None, None),
        (11, "修訂.pdf", "2026/01/b.pdf", "b" * 64, 202, "第二版", "accepted", "王覆核", "2026-01-09T09:00:00"),
        (12, "定稿.pdf", "2026/01/c.pdf", "c" * 64, 303, None, "rejected", None, None),
    )
    for (
        attachment_id,
        original_filename,
        stored_filename,
        digest,
        file_size,
        notes,
        status,
        accepted_by,
        accepted_at,
    ) in attachment_rows:
        conn.execute(
            "INSERT INTO attachments("
            "id, engagement_id, request_id, original_filename, stored_filename, "
            "file_hash_sha256, file_size, mime_type, extension, uploaded_by, "
            "uploaded_at, source, status, notes, accepted_by, accepted_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'application/pdf', '.pdf', "
            "'測試人員', '2026-01-07T07:00:00', 'manual', ?, ?, ?, ?)",
            (
                attachment_id,
                engagement_id,
                request_id,
                original_filename,
                stored_filename,
                digest,
                file_size,
                status,
                notes,
                accepted_by,
                accepted_at,
            ),
        )
    conn.executemany(
        "INSERT INTO attachment_versions(id, attachment_id, supersedes_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (
            (20, 10, None, "2026-01-07T07:00:00"),
            (21, 11, 10, "2026-01-08T08:00:00"),
            (22, 12, 11, "2026-01-09T09:00:00"),
        ),
    )
    return client_id, engagement_id, request_id


def test_client_master_migration_backfills_addresses_and_legacy_lease(
    v029_conn: sqlite3.Connection,
) -> None:
    client_id = v029_conn.execute(
        "INSERT INTO clients("
        "client_code, client_name, address, lease_start, lease_end, created_at, updated_at"
        ") VALUES ('C1', '測試客戶', '臺北市舊址', '2025-01-01', '2026-12-31', "
        "'2024-01-01T08:00:00', '2024-02-01T09:00:00')"
    ).lastrowid

    assert "client_leases" not in {
        row["name"]
        for row in v029_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert apply_migrations(v029_conn) == [
        "0027_client_master_expansion",
        "0028_annual_compliance",
    ]

    client = v029_conn.execute(
        "SELECT registered_address, contact_address, contact_address_same, "
        "address, lease_start, lease_end "
        "FROM clients WHERE id = ?",
        (client_id,),
    ).fetchone()
    assert tuple(client) == (
        "臺北市舊址",
        "臺北市舊址",
        1,
        "臺北市舊址",
        "2025-01-01",
        "2026-12-31",
    )

    leases = v029_conn.execute(
        "SELECT lease_name, start_date, end_date, created_at, updated_at "
        "FROM client_leases WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    assert [tuple(row) for row in leases] == [
        (
            "既有租約",
            "2025-01-01",
            "2026-12-31",
            "2024-01-01T08:00:00",
            "2024-02-01T09:00:00",
        )
    ]
    assert apply_migrations(v029_conn) == []
    assert v029_conn.execute(
        "SELECT COUNT(*) FROM client_leases WHERE client_id = ?", (client_id,)
    ).fetchone()[0] == 1


def test_client_master_migration_handles_partial_lease_dates_and_null_address(
    v029_conn: sqlite3.Connection,
) -> None:
    v029_conn.executemany(
        "INSERT INTO clients("
        "client_code, client_name, address, lease_start, lease_end, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, '2025-01-01T00:00:00', '2025-02-01T00:00:00')",
        (
            ("START", "只有起日", "新北市", "2025-03-01", None),
            ("END", "只有迄日", "臺中市", None, "2027-02-28"),
            ("NULL", "無地址無租約", None, None, None),
        ),
    )

    apply_migrations(v029_conn)

    clients = {
        row["client_code"]: (
            row["registered_address"],
            row["contact_address"],
            row["contact_address_same"],
        )
        for row in v029_conn.execute(
            "SELECT client_code, registered_address, contact_address, "
            "contact_address_same FROM clients"
        )
    }
    assert clients == {
        "START": ("新北市", "新北市", 1),
        "END": ("臺中市", "臺中市", 1),
        "NULL": (None, None, 1),
    }
    leases = [
        tuple(row)
        for row in v029_conn.execute(
            "SELECT c.client_code, l.start_date, l.end_date "
            "FROM client_leases l JOIN clients c ON c.id = l.client_id "
            "ORDER BY c.client_code"
        )
    ]
    assert leases == [
        ("END", None, "2027-02-28"),
        ("START", "2025-03-01", None),
    ]


def test_client_master_migration_upgrades_empty_database_with_required_schema(
    v029_conn: sqlite3.Connection,
) -> None:
    assert apply_migrations(v029_conn) == [
        "0027_client_master_expansion",
        "0028_annual_compliance",
    ]

    tables = {
        row["name"]
        for row in v029_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"client_leases", "client_industries"} <= tables
    assert v029_conn.execute("SELECT COUNT(*) FROM client_leases").fetchone()[0] == 0

    lease_columns = {
        row["name"] for row in v029_conn.execute("PRAGMA table_info(client_leases)")
    }
    assert lease_columns == {
        "id",
        "client_id",
        "lease_name",
        "premises_address",
        "landlord_name",
        "start_date",
        "end_date",
        "monthly_rent",
        "deposit_amount",
        "reminder_days",
        "status",
        "notes",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    industry_columns = {
        row["name"]
        for row in v029_conn.execute("PRAGMA table_info(client_industries)")
    }
    assert industry_columns == {
        "id",
        "client_id",
        "industry_code",
        "industry_name",
        "is_primary",
        "sort_order",
        "source",
        "source_version",
        "applied_at",
    }

    required_indexes = {
        "idx_client_leases_client",
        "idx_client_leases_end_date",
        "idx_client_industries_client",
        "idx_attachments_engagement",
        "idx_attachments_request",
        "idx_attachments_client",
        "idx_attachments_lease",
        "idx_attachments_status",
        "idx_attachment_versions_attachment",
    }
    indexes = {
        row["name"]
        for row in v029_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert required_indexes <= indexes

    residue = v029_conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE name GLOB '*_v030_new' OR name GLOB '_m0027_*' "
        "OR name GLOB '*_legacy' "
        "UNION ALL "
        "SELECT name FROM sqlite_temp_master "
        "WHERE name GLOB '*_v030_new' OR name GLOB '_m0027_*' "
        "OR name GLOB '*_legacy'"
    ).fetchall()
    assert residue == []
    assert v029_conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert apply_migrations(v029_conn) == []


def test_new_client_master_constraints_allow_overlap_and_reject_invalid_values(
    v029_conn: sqlite3.Connection,
) -> None:
    apply_migrations(v029_conn)
    client_id = v029_conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at) "
        "VALUES ('RULES', '契約規則客戶', '2026-01-01', '2026-01-01')"
    ).lastrowid
    lease_sql = (
        "INSERT INTO client_leases("
        "client_id, lease_name, start_date, end_date, monthly_rent, deposit_amount, "
        "reminder_days, created_at, updated_at"
        ") VALUES (?, ?, '2026-01-01', '2026-12-31', ?, ?, ?, '2026-01-01', '2026-01-01')"
    )
    v029_conn.execute(lease_sql, (client_id, "重疊租約一", 1000, 2000, 0))
    v029_conn.execute(lease_sql, (client_id, "重疊租約二", 3000, 4000, 3650))
    overlapping = [
        tuple(row)
        for row in v029_conn.execute(
            "SELECT status, reminder_days FROM client_leases "
            "WHERE client_id = ? ORDER BY id",
            (client_id,),
        )
    ]
    assert overlapping == [("active", 0), ("active", 3650)]

    for invalid_values in (
        ("負租金", -1, 0, 60),
        ("負押金", 0, -1, 60),
        ("提醒過長", 0, 0, 3651),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            v029_conn.execute(lease_sql, (client_id, *invalid_values))

    v029_conn.execute(
        "INSERT INTO client_industries("
        "client_id, industry_code, industry_name, is_primary, sort_order, source, "
        "source_version, applied_at"
        ") VALUES (?, '6920', '會計服務業', 1, 0, 'registry', '202607', '2026-07-16')",
        (client_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        v029_conn.execute(
            "INSERT INTO client_industries("
            "client_id, industry_code, industry_name, source, applied_at"
            ") VALUES (?, '6920', '重複代碼', 'manual', '2026-07-16')",
            (client_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        v029_conn.execute(
            "UPDATE client_industries SET is_primary = 2 WHERE client_id = ?",
            (client_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        v029_conn.execute(
            "UPDATE clients SET contact_address_same = 2 WHERE id = ?", (client_id,)
        )


def test_client_master_migration_preserves_attachment_rows_and_version_chain(
    v029_conn: sqlite3.Connection,
) -> None:
    _seed_v029_attachment_chain(v029_conn)
    attachments_before = [
        tuple(row)
        for row in v029_conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments ORDER BY id"
        )
    ]
    versions_before = [
        tuple(row)
        for row in v029_conn.execute(
            "SELECT id, attachment_id, supersedes_id, created_at "
            "FROM attachment_versions ORDER BY id"
        )
    ]

    apply_migrations(v029_conn)

    attachments_after = [
        tuple(row)
        for row in v029_conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments ORDER BY id"
        )
    ]
    versions_after = [
        tuple(row)
        for row in v029_conn.execute(
            "SELECT id, attachment_id, supersedes_id, created_at "
            "FROM attachment_versions ORDER BY id"
        )
    ]
    assert attachments_after == attachments_before
    assert versions_after == versions_before
    assert {row["name"] for row in v029_conn.execute("PRAGMA table_info(attachments)")} >= {
        "engagement_id",
        "request_id",
        "client_id",
        "lease_id",
    }


def test_client_master_migration_preserves_attachment_sequence_high_water(
    v029_conn: sqlite3.Connection,
) -> None:
    _client_id, engagement_id, request_id = _seed_v029_attachment_chain(v029_conn)
    high_water = {"attachments": 100, "attachment_versions": 200}
    v029_conn.executemany(
        "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
        ((seq, name) for name, seq in high_water.items()),
    )

    apply_migrations(v029_conn)

    restored = {
        row["name"]: row["seq"]
        for row in v029_conn.execute(
            "SELECT name, seq FROM sqlite_sequence "
            "WHERE name IN ('attachments', 'attachment_versions')"
        )
    }
    assert restored == high_water

    attachment_id = v029_conn.execute(
        "INSERT INTO attachments("
        "engagement_id, request_id, original_filename, stored_filename, "
        "file_hash_sha256, file_size, mime_type, extension, uploaded_at"
        ") VALUES (?, ?, '新增.pdf', '2026/01/new.pdf', ?, 404, "
        "'application/pdf', '.pdf', '2026-01-10T10:00:00')",
        (engagement_id, request_id, "d" * 64),
    ).lastrowid
    version_id = v029_conn.execute(
        "INSERT INTO attachment_versions(attachment_id, supersedes_id, created_at) "
        "VALUES (?, 12, '2026-01-10T10:00:00')",
        (attachment_id,),
    ).lastrowid

    assert attachment_id > high_water["attachments"]
    assert version_id > high_water["attachment_versions"]


def test_lease_attachment_owner_is_enforced_by_composite_foreign_key(
    v029_conn: sqlite3.Connection,
) -> None:
    client_a, _engagement_id, _request_id = _seed_v029_attachment_chain(v029_conn)
    client_b = v029_conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at) "
        "VALUES ('CLIENT-B', '客戶乙', '2026-01-01', '2026-01-01')"
    ).lastrowid
    apply_migrations(v029_conn)
    lease_id = v029_conn.execute(
        "INSERT INTO client_leases("
        "client_id, lease_name, premises_address, landlord_name, start_date, end_date, "
        "monthly_rent, deposit_amount, reminder_days, notes, created_at, updated_at"
        ") VALUES (?, '總公司租約', '臺北市信義區', '房東甲', '2026-01-01', "
        "'2026-12-31', 50000, 100000, 45, '完整租約', '2026-01-01', '2026-01-01')",
        (client_a,),
    ).lastrowid

    valid_id = v029_conn.execute(
        "INSERT INTO attachments("
        "client_id, lease_id, original_filename, stored_filename, file_hash_sha256, "
        "file_size, mime_type, extension, uploaded_at"
        ") VALUES (?, ?, '租約.pdf', 'leases/valid.pdf', ?, 808, "
        "'application/pdf', '.pdf', '2026-01-11T11:00:00')",
        (client_a, lease_id, "e" * 64),
    ).lastrowid
    assert valid_id is not None

    with pytest.raises(sqlite3.IntegrityError):
        v029_conn.execute(
            "INSERT INTO attachments("
            "client_id, lease_id, original_filename, stored_filename, file_hash_sha256, "
            "file_size, mime_type, extension, uploaded_at"
            ") VALUES (?, ?, '錯配.pdf', 'leases/mismatch.pdf', ?, 909, "
            "'application/pdf', '.pdf', '2026-01-12T12:00:00')",
            (client_b, lease_id, "f" * 64),
        )

    assert v029_conn.execute(
        "SELECT COUNT(*) FROM attachments WHERE stored_filename = 'leases/mismatch.pdf'"
    ).fetchone()[0] == 0
    assert v029_conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_attachment_owner_check_rejects_ambiguous_and_incomplete_owners(
    v029_conn: sqlite3.Connection,
) -> None:
    client_id, engagement_id, request_id = _seed_v029_attachment_chain(v029_conn)
    apply_migrations(v029_conn)
    lease_id = v029_conn.execute(
        "INSERT INTO client_leases("
        "client_id, lease_name, created_at, updated_at"
        ") VALUES (?, '檢查租約', '2026-01-01', '2026-01-01')",
        (client_id,),
    ).lastrowid
    attachment_sql = (
        "INSERT INTO attachments("
        "engagement_id, request_id, client_id, lease_id, original_filename, "
        "stored_filename, file_hash_sha256, file_size, mime_type, extension, uploaded_at"
        ") VALUES (?, ?, ?, ?, 'owner.pdf', ?, ?, 1, "
        "'application/pdf', '.pdf', '2026-01-01')"
    )
    invalid_owners = (
        (engagement_id, None, client_id, lease_id, "both-owners.pdf"),
        (None, request_id, client_id, lease_id, "lease-with-request.pdf"),
        (None, None, None, None, "no-owner.pdf"),
    )
    for engagement, request, client, lease, stored_filename in invalid_owners:
        with pytest.raises(sqlite3.IntegrityError):
            v029_conn.execute(
                attachment_sql,
                (
                    engagement,
                    request,
                    client,
                    lease,
                    stored_filename,
                    "0" * 64,
                ),
            )
