from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from taxops.repositories.annual_work import AnnualWorkRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.compliance_profiles import ComplianceProfilesRepository
from taxops.services.annual_work import (
    AnnualWorkError,
    AnnualWorkService,
    AnnualWorkValidationError,
)
from taxops.services.audit import AuditService
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_rules import WorkDraft
from taxops.services.compliance_profiles import ComplianceProfileItemInput


def _client_with_profile(container: object, *, code: str = "C-ANNUAL") -> int:
    client_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code=code, client_name="年度工作測試客戶")
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("vat", "bimonthly"),
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
            ComplianceProfileItemInput(
                "company_annual", "annual", enabled=False, notes="私密草稿"
            ),
        ),
    )
    return client_id


def test_preview_returns_exact_enabled_drafts_without_database_or_audit_mutation(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    conn = getattr(container, "conn")
    audit_count = getattr(container, "audit")._repo.count()
    before_changes = conn.total_changes

    drafts = getattr(container, "annual_work").preview(client_id, 2026)

    assert [
        (
            draft.title,
            draft.operation_year,
            draft.tax_year,
            draft.period_code,
            draft.suggested_due_date,
        )
        for draft in drafts
    ] == [
        ("01-02 營業稅", 2026, 2026, "01-02", "2026-03-15"),
        ("03-04 營業稅", 2026, 2026, "03-04", "2026-05-15"),
        ("05-06 營業稅", 2026, 2026, "05-06", "2026-07-15"),
        ("07-08 營業稅", 2026, 2026, "07-08", "2026-09-15"),
        ("09-10 營業稅", 2026, 2026, "09-10", "2026-11-15"),
        ("11-12 營業稅", 2026, 2026, "11-12", "2027-01-15"),
        ("營利事業所得稅結算申報", 2026, 2025, None, "2026-05-31"),
    ]
    assert conn.total_changes == before_changes
    assert getattr(container, "audit")._repo.count() == audit_count
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0


def test_confirm_preview_is_idempotent_and_never_overwrites_edited_items(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)

    first = service.confirm_preview(client_id, 2026, drafts)
    edited_id = first.items[0].id
    getattr(container, "conn").execute(
        "UPDATE annual_work_items SET title = ?, due_date = ?, notes = ? WHERE id = ?",
        ("使用者自訂標題", "2026-03-20", "使用者私密內容", edited_id),
    )
    getattr(container, "conn").commit()
    second = service.confirm_preview(client_id, 2026, drafts)

    assert first.created_workspace is True
    assert first.inserted_item_count == len(drafts)
    assert first.unchanged is False
    assert second.created_workspace is False
    assert second.inserted_item_count == 0
    assert second.unchanged is True
    assert second.workspace.id == first.workspace.id
    assert [item.id for item in second.items] == [item.id for item in first.items]
    assert second.items[0].id == edited_id
    assert second.items[0].title == "使用者自訂標題"
    assert second.items[0].due_date == "2026-03-20"
    assert second.items[0].notes == "使用者私密內容"


@pytest.mark.parametrize(
    ("client_id", "year", "code"),
    [
        (True, 2026, "annual_work.client_id.invalid"),
        ("1", 2026, "annual_work.client_id.invalid"),
        (1, False, "annual_work.operation_year.invalid"),
        (1, "2026", "annual_work.operation_year.invalid"),
        (1, 1911, "annual_work.operation_year.invalid"),
    ],
)
def test_preview_rejects_mistyped_or_out_of_range_identity_fields(
    container: object, client_id: object, year: object, code: str
) -> None:
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").preview(client_id, year)
    assert caught.value.code == code


def test_preview_reports_missing_deleted_profile_and_all_disabled_with_stable_codes(
    container: object,
) -> None:
    service = getattr(container, "annual_work")
    with pytest.raises(AnnualWorkValidationError) as missing:
        service.preview(999_999, 2026)
    assert missing.value.code == "annual_work.client_not_found"

    no_profile = getattr(container, "clients").create_client(
        CreateClientInput(client_code="C-NO-PROFILE", client_name="尚未設定申報設定")
    )
    with pytest.raises(AnnualWorkValidationError) as profile_missing:
        service.preview(no_profile.id, 2026)
    assert profile_missing.value.code == "annual_work.profile_not_found"

    disabled_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code="C-DISABLED", client_name="全部停用")
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        disabled_id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly", enabled=False),),
    )
    with pytest.raises(AnnualWorkValidationError) as disabled:
        service.preview(disabled_id, 2026)
    assert disabled.value.code == "annual_work.enabled_items.empty"

    deleted_id = _client_with_profile(container, code="C-DELETED")
    getattr(container, "conn").execute(
        "UPDATE clients SET deleted_at = '2026-07-19T00:00:00' WHERE id = ?",
        (deleted_id,),
    )
    getattr(container, "conn").commit()
    with pytest.raises(AnnualWorkValidationError) as deleted:
        service.preview(deleted_id, 2026)
    assert deleted.value.code == "annual_work.client_not_found"


@pytest.mark.parametrize(
    ("drafts", "code"),
    [
        ("not-a-sequence-of-drafts", "annual_work.drafts.invalid"),
        (b"not-a-sequence-of-drafts", "annual_work.drafts.invalid"),
        ((), "annual_work.drafts.empty"),
        ((object(),), "annual_work.draft.invalid"),
    ],
)
def test_confirm_rejects_invalid_draft_containers_without_writes(
    container: object, drafts: object, code: str
) -> None:
    service = getattr(container, "annual_work")
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview(1, 2026, drafts)
    assert caught.value.code == code
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: replace(d, operation_year=2025), "annual_work.draft.operation_year.mismatch"),
        (lambda d: replace(d, item_key=""), "annual_work.draft.invalid"),
        (lambda d: replace(d, work_type="unknown"), "annual_work.draft.invalid"),
        (lambda d: replace(d, title=""), "annual_work.draft.invalid"),
        (lambda d: replace(d, tax_year=True), "annual_work.draft.invalid"),
        (lambda d: replace(d, period_code=1), "annual_work.draft.invalid"),
        (lambda d: replace(d, period_code=""), "annual_work.draft.invalid"),
        (lambda d: replace(d, suggested_due_date="2026-02-30"), "annual_work.draft.invalid"),
    ],
)
def test_confirm_rejects_invalid_draft_fields(
    container: object, mutate: object, code: str
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    original = service.preview(client_id, 2026)[0]
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview(client_id, 2026, (mutate(original),))
    assert caught.value.code == code


def test_confirm_rejects_duplicate_keys_and_stale_or_fabricated_preview(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    with pytest.raises(AnnualWorkValidationError) as duplicate:
        service.confirm_preview(client_id, 2026, (drafts[0], drafts[0]))
    assert duplicate.value.code == "annual_work.draft.item_key.duplicate"

    fabricated = (replace(drafts[0], title="外造標題"),) + drafts[1:]
    with pytest.raises(AnnualWorkValidationError) as external:
        service.confirm_preview(client_id, 2026, fabricated)
    assert external.value.code == "annual_work.drafts.profile_mismatch"

    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=2,
        items=(
            ComplianceProfileItemInput("vat", "bimonthly"),
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
        ),
    )
    with pytest.raises(AnnualWorkValidationError) as stale:
        service.confirm_preview(client_id, 2026, drafts)
    assert stale.value.code == "annual_work.drafts.profile_mismatch"
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("client_id", "year", "code"),
    [
        (True, 2026, "annual_work.client_id.invalid"),
        ("1", 2026, "annual_work.client_id.invalid"),
        (1, False, "annual_work.operation_year.invalid"),
        (1, "2026", "annual_work.operation_year.invalid"),
    ],
)
def test_confirm_rejects_mistyped_identity_fields_before_writing(
    container: object, client_id: object, year: object, code: str
) -> None:
    valid_client_id = _client_with_profile(container)
    drafts = getattr(container, "annual_work").preview(valid_client_id, 2026)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").confirm_preview(client_id, year, drafts)
    assert caught.value.code == code
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


def test_confirm_fails_fast_without_committing_or_rolling_back_caller_transaction(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) "
        "VALUES ('INFO', 'caller-owned transaction', '2026-07-19T00:00:00')"
    )
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview(client_id, 2026, drafts)
    assert caught.value.code == "annual_work.transaction.already_active"
    assert conn.in_transaction is True
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller-owned transaction'"
    ).fetchone()[0] == 1
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller-owned transaction'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("trigger_table", "trigger_timing"),
    [
        ("annual_workspaces", "BEFORE INSERT"),
        ("annual_work_items", "BEFORE INSERT"),
        ("audit_logs", "BEFORE INSERT"),
    ],
)
def test_confirm_rolls_back_every_row_and_hides_raw_database_errors(
    container: object, trigger_table: str, trigger_timing: str
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    conn.execute(
        f"CREATE TRIGGER fail_annual_confirm {trigger_timing} ON {trigger_table} "
        "BEGIN SELECT RAISE(ABORT, 'raw SQL secret'); END"
    )
    conn.commit()
    with pytest.raises(AnnualWorkError) as caught:
        service.confirm_preview(client_id, 2026, drafts)
    assert caught.value.code == "annual_work.confirm.failed"
    assert "raw SQL secret" not in str(caught.value)
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == 0


def test_confirm_audit_truthfully_describes_created_then_noop_and_fresh_connection_reads(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    first = service.confirm_preview(client_id, 2026, drafts)
    second = service.confirm_preview(client_id, 2026, drafts)
    rows = getattr(container, "conn").execute(
        "SELECT target_id, detail_json FROM audit_logs "
        "WHERE action = 'annual_workspace.confirm' ORDER BY id"
    ).fetchall()
    details = [json.loads(row["detail_json"]) for row in rows]
    assert [row["target_id"] for row in rows] == [str(first.workspace.id)] * 2
    assert details == [
        {
            "client_id": client_id,
            "operation_year": 2026,
            "created_workspace": True,
            "inserted_item_count": len(drafts),
            "item_count": len(drafts),
            "unchanged": False,
        },
        {
            "client_id": client_id,
            "operation_year": 2026,
            "created_workspace": False,
            "inserted_item_count": 0,
            "item_count": len(drafts),
            "unchanged": True,
        },
    ]
    assert second.unchanged is True

    db_path = getattr(container, "conn").execute("PRAGMA database_list").fetchone()[2]
    fresh = sqlite3.connect(db_path)
    try:
        assert fresh.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 1
        assert fresh.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == len(drafts)
        assert fresh.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
        ).fetchone()[0] == 2
    finally:
        fresh.close()


def test_service_requires_same_connection_for_all_collaborators(db_conn: sqlite3.Connection) -> None:
    other = sqlite3.connect(":memory:")
    try:
        repository = AnnualWorkRepository(db_conn)
        profiles = ComplianceProfilesRepository(db_conn)
        audit = AuditService(AuditLogRepository(other))
        with pytest.raises(ValueError, match="annual_work.connection.mismatch"):
            AnnualWorkService(db_conn, repository, profiles, audit)
    finally:
        other.close()


def test_empty_rule_preview_has_stable_code_and_no_writes(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    monkeypatch.setattr("taxops.services.annual_work.build_standard_drafts", lambda *_a, **_kw: ())
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").preview(client_id, 2026)
    assert caught.value.code == "annual_work.preview.empty"
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


def test_confirm_uses_begin_immediate(container: object) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    statements: list[str] = []
    getattr(container, "conn").set_trace_callback(statements.append)
    try:
        service.confirm_preview(client_id, 2026, drafts)
    finally:
        getattr(container, "conn").set_trace_callback(None)
    assert any(statement.strip().upper() == "BEGIN IMMEDIATE" for statement in statements)


def test_confirm_reports_writer_contention_with_stable_error(container: object) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    locker = sqlite3.connect(db_path)
    locker.execute("PRAGMA busy_timeout = 1")
    conn.execute("PRAGMA busy_timeout = 1")
    locker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(AnnualWorkError) as caught:
            service.confirm_preview(client_id, 2026, drafts)
        assert caught.value.code == "annual_work.transaction.busy"
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    finally:
        locker.rollback()
        locker.close()


def test_item_failure_after_prior_insert_rolls_back_prior_item_and_workspace(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_late_item BEFORE INSERT ON annual_work_items "
        "WHEN NEW.work_type = 'corporate_income_tax' "
        "BEGIN SELECT RAISE(ABORT, 'late raw SQL secret'); END"
    )
    conn.commit()
    with pytest.raises(AnnualWorkError) as caught:
        service.confirm_preview(client_id, 2026, drafts)
    assert caught.value.code == "annual_work.confirm.failed"
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("method_name", ["list_workspaces", "search_overview"])
@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (True, 0),
        ("10", 0),
        (0, 0),
        (501, 0),
        (10, False),
        (10, "0"),
        (10, -1),
        (10, 1_000_001),
    ],
)
def test_repository_collection_queries_require_bounded_exact_int_pagination(
    container: object, method_name: str, limit: object, offset: object
) -> None:
    repository = getattr(container, "annual_work").repository
    with pytest.raises(ValueError, match="^annual_work.pagination.invalid$"):
        getattr(repository, method_name)(limit=limit, offset=offset)


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(True, 0), ("10", 0), (0, 0), (501, 0), (10, False), (10, -1)],
)
def test_repository_list_items_requires_bounded_pagination_and_valid_workspace_id(
    container: object, limit: object, offset: object
) -> None:
    repository = getattr(container, "annual_work").repository
    with pytest.raises(ValueError, match="^annual_work.pagination.invalid$"):
        repository.list_items(1, limit=limit, offset=offset)
    with pytest.raises(ValueError, match="^annual_work.workspace_id.invalid$"):
        repository.list_items(True)


@pytest.mark.parametrize(
    ("order_by", "order_dir"),
    [
        ("unknown", "ASC"),
        ("operation_year; DROP TABLE clients", "ASC"),
        ("operation_year", "sideways"),
        (1, "ASC"),
        ("operation_year", 1),
    ],
)
def test_list_workspaces_rejects_unknown_or_malicious_sort_values(
    container: object, order_by: object, order_dir: object
) -> None:
    repository = getattr(container, "annual_work").repository
    with pytest.raises(ValueError, match="^annual_work.sort.invalid$"):
        repository.list_workspaces(order_by=order_by, order_dir=order_dir)


@pytest.mark.parametrize(
    ("filters", "code"),
    [
        ("not-a-mapping", "annual_work.filters.invalid"),
        ({"unknown": "x"}, "annual_work.filters.invalid"),
        ({"order_by": "unknown"}, "annual_work.sort.invalid"),
        ({"order_by": "id; DROP TABLE clients"}, "annual_work.sort.invalid"),
        ({"order_dir": "sideways"}, "annual_work.sort.invalid"),
        ({"client_id": True}, "annual_work.filters.invalid"),
        ({"client_id": "1"}, "annual_work.filters.invalid"),
        ({"operation_year": False}, "annual_work.filters.invalid"),
        ({"operation_year": "2026"}, "annual_work.filters.invalid"),
        ({"operation_year": 1911}, "annual_work.filters.invalid"),
        ({"work_type": 1}, "annual_work.filters.invalid"),
        ({"work_type": "unknown"}, "annual_work.filters.invalid"),
        ({"work_status": ""}, "annual_work.filters.invalid"),
        ({"filing_status": 1}, "annual_work.filters.invalid"),
        ({"document_status": 1}, "annual_work.filters.invalid"),
        ({"tax_status": 1}, "annual_work.filters.invalid"),
        ({"fee_status": 1}, "annual_work.filters.invalid"),
        ({"due_from": "2026-02-30"}, "annual_work.filters.invalid"),
        ({"due_to": 20260101}, "annual_work.filters.invalid"),
        (
            {"due_from": "2026-12-31", "due_to": "2026-01-01"},
            "annual_work.filters.invalid",
        ),
        ({"query": 1}, "annual_work.filters.invalid"),
    ],
)
def test_search_overview_rejects_unknown_sort_and_mistyped_filter_values(
    container: object, filters: object, code: str
) -> None:
    repository = getattr(container, "annual_work").repository
    with pytest.raises(ValueError, match=f"^{code}$"):
        repository.search_overview(filters)


def test_search_overview_treats_percent_and_underscore_as_literal_text(
    container: object,
) -> None:
    percent_client = _client_with_profile(container, code="C-LITERAL-%")
    plain_client = _client_with_profile(container, code="C-LITERAL-PLAIN")
    service = getattr(container, "annual_work")
    service.confirm_preview(percent_client, 2026, service.preview(percent_client, 2026))
    service.confirm_preview(plain_client, 2026, service.preview(plain_client, 2026))

    percent_rows = service.repository.search_overview({"query": "%"})
    underscore_rows = service.repository.search_overview({"query": "C_LITERAL"})
    assert {row.workspace_client_id for row in percent_rows} == {percent_client}
    assert underscore_rows == []


def test_repository_reads_apply_limit_and_offset_to_each_collection(
    container: object,
) -> None:
    first_client = _client_with_profile(container, code="C-BOUND-1")
    second_client = _client_with_profile(container, code="C-BOUND-2")
    service = getattr(container, "annual_work")
    first = service.confirm_preview(first_client, 2026, service.preview(first_client, 2026))
    service.confirm_preview(second_client, 2026, service.preview(second_client, 2026))

    workspace_page = service.repository.list_workspaces(
        limit=1, offset=1, order_by="id", order_dir="ASC"
    )
    item_page = service.repository.list_items(first.workspace.id, limit=1, offset=1)
    overview_page = service.repository.search_overview(
        {"client_id": first_client, "order_by": "id", "order_dir": "ASC"},
        limit=1,
        offset=1,
    )
    assert len(workspace_page) == len(item_page) == len(overview_page) == 1
    assert workspace_page[0].client_id == second_client
    assert item_page[0].id == first.items[1].id
    assert overview_page[0].item.id == first.items[1].id


def test_insert_item_if_missing_surfaces_non_unique_constraint_failures(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    result = service.confirm_preview(client_id, 2026, service.preview(client_id, 2026))
    invalid = WorkDraft(
        item_key="invalid-title-check",
        operation_year=2026,
        work_type="vat",
        title="",
        tax_year=2026,
        period_code="01-02",
        suggested_due_date="2026-03-15",
    )
    with pytest.raises(sqlite3.IntegrityError):
        service.repository.insert_item_if_missing(result.workspace.id, invalid)


def test_insert_item_if_missing_reports_only_target_conflict_as_not_inserted(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    result = service.confirm_preview(client_id, 2026, drafts)
    duplicate = service.repository.insert_item_if_missing(result.workspace.id, drafts[0])
    assert duplicate.inserted is False
    assert duplicate.row.id == result.items[0].id


def test_workspace_unique_race_rereads_existing_without_claiming_created(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    first = service.confirm_preview(client_id, 2026, drafts)
    original_find = service.repository.find_workspace
    calls = 0

    def hide_existing_once(candidate_client_id: int, candidate_year: int) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_find(candidate_client_id, candidate_year)

    monkeypatch.setattr(service.repository, "find_workspace", hide_existing_once)
    raced = service.confirm_preview(client_id, 2026, drafts)

    assert raced.workspace.id == first.workspace.id
    assert raced.created_workspace is False
    assert raced.inserted_item_count == 0
    assert raced.unchanged is True
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces WHERE client_id = ? AND operation_year = ?",
        (client_id, 2026),
    ).fetchone()[0] == 1
