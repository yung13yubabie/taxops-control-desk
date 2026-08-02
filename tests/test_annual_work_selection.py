from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

import pytest

from taxops.repositories import annual_work as annual_work_repository
from taxops.services.annual_work import AnnualWorkValidationError
from taxops.services.annual_work import AnnualWorkError
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.compliance_rules import WorkDraft


def _client_with_profile(container: object, *, code: str = "C-SELECT") -> int:
    client_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code=code, client_name="年度工作測試客戶 🧾")
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("vat", "bimonthly"),
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
        ),
    )
    return client_id


def _custom_drafts(
    count: int, *, operation_year: int = 2026, start: int = 1
) -> tuple[WorkDraft, ...]:
    return tuple(
        WorkDraft(
            item_key=f"custom:{UUID(int=index)}",
            operation_year=operation_year,
            work_type="vat",
            title=f"批次自訂工作 {index}",
            tax_year=operation_year,
            period_code="全年",
            suggested_due_date="2027-12-31",
        )
        for index in range(start, start + count)
    )


class _OversizedDraftSequence(Sequence[WorkDraft]):
    def __len__(self) -> int:
        return annual_work_repository.MAX_WORKSPACE_ITEMS + 1

    def __getitem__(self, index: int) -> WorkDraft:
        raise AssertionError(f"oversized sequence must not be read: {index}")


class _BrokenLengthDraftSequence(Sequence[WorkDraft]):
    def __len__(self) -> int:
        raise RuntimeError("raw invalid sequence length")

    def __getitem__(self, index: int) -> WorkDraft:
        raise AssertionError(f"broken sequence must not be read: {index}")


class _ConnectionFaultProxy:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        fail_begin: bool = False,
        fail_commit: bool = False,
        fail_rollback: bool = False,
    ) -> None:
        self.connection = connection
        self.fail_begin = fail_begin
        self.fail_commit = fail_commit
        self.fail_rollback = fail_rollback
        self.rollback_calls = 0
        self.closed = False

    @property
    def in_transaction(self) -> bool:
        return self.connection.in_transaction

    def execute(self, statement: str, parameters: object = ()) -> object:
        if statement.strip().upper() == "BEGIN" and self.fail_begin:
            raise sqlite3.OperationalError("raw begin transaction failure")
        return self.connection.execute(statement, parameters)

    def commit(self) -> None:
        if self.fail_commit:
            raise sqlite3.OperationalError("raw commit transaction failure")
        self.connection.commit()

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.fail_rollback:
            raise sqlite3.OperationalError("raw rollback transaction failure")
        self.connection.rollback()

    def close(self) -> None:
        self.closed = True
        self.connection.close()


def test_workspace_item_limit_is_one_shared_product_contract() -> None:
    assert annual_work_repository.MAX_WORKSPACE_ITEMS == 500


@pytest.mark.parametrize("oversized_field", ("expected_drafts", "selected_drafts"))
def test_oversized_drafts_fail_before_begin_or_iteration(
    container: object, oversized_field: str
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    changes_before = conn.total_changes
    audit_before = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0]
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        with pytest.raises(AnnualWorkValidationError) as caught:
            arguments = {
                "expected_drafts": expected,
                "selected_drafts": expected[:1],
            }
            arguments[oversized_field] = _OversizedDraftSequence()
            service.confirm_preview_selection(client_id, 2026, **arguments)
    finally:
        conn.set_trace_callback(None)

    assert caught.value.code == "annual_work.drafts.too_many"
    assert conn.total_changes == changes_before
    assert not any(statement == "BEGIN IMMEDIATE" for statement in statements)
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == audit_before


def test_abnormal_sequence_length_is_stable_invalid_without_begin(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    changes_before = conn.total_changes
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        with pytest.raises(AnnualWorkValidationError) as caught:
            service.confirm_preview_selection(
                client_id,
                2026,
                expected_drafts=expected,
                selected_drafts=_BrokenLengthDraftSequence(),
            )
    finally:
        conn.set_trace_callback(None)

    assert caught.value.code == "annual_work.drafts.invalid"
    assert "raw invalid sequence length" not in str(caught.value)
    assert conn.total_changes == changes_before
    assert not any(statement == "BEGIN IMMEDIATE" for statement in statements)
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0


def test_confirm_selection_inserts_only_selected_subset(container: object) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)

    result = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:2]
    )

    assert result.inserted_item_count == 2
    assert [item.item_key for item in result.items] == [
        expected[0].item_key,
        expected[1].item_key,
    ]


def test_confirm_selection_persists_allowed_edits_including_date_boundary(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    edited = replace(
        expected[0],
        title="跨年申報追蹤 ✨",
        tax_year=2025,
        period_code="12-01",
        suggested_due_date="2027-01-01",
    )

    result = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=(edited,)
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert (item.title, item.tax_year, item.period_code) == (
        "跨年申報追蹤 ✨",
        2025,
        "12-01",
    )
    assert item.suggested_due_date == "2027-01-01"
    assert item.due_date == "2027-01-01"


def test_confirm_selection_accepts_canonical_custom_uuid(container: object) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    custom = WorkDraft(
        item_key="custom:123e4567-e89b-42d3-a456-426614174000",
        operation_year=2026,
        work_type="vat",
        title="客製跨年盤點 🧩",
        tax_year=2026,
        period_code="全年",
        suggested_due_date="2027-12-31",
    )

    result = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=(custom,)
    )

    assert result.inserted_item_count == 1
    assert result.items[0].item_key == custom.item_key
    assert result.items[0].title == "客製跨年盤點 🧩"
    assert result.items[0].due_date == "2027-12-31"


def test_confirm_selection_stale_expected_rolls_back_everything(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=2,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(expected[0],),
        )

    assert caught.value.code == "annual_work.drafts.profile_mismatch"
    conn = getattr(container, "conn")
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "item_key",
    (
        "custom:not-a-uuid",
        "custom:123E4567-E89B-42D3-A456-426614174000",
        "custom:{123e4567-e89b-42d3-a456-426614174000}",
    ),
)
def test_confirm_selection_rejects_noncanonical_custom_keys(
    container: object, item_key: str
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    invalid = replace(expected[0], item_key=item_key)

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id, 2026, expected_drafts=expected, selected_drafts=(invalid,)
        )

    assert caught.value.code == "annual_work.draft.custom_key.invalid"


def test_confirm_selection_rejects_fabricated_duplicate_and_empty_inputs(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)

    with pytest.raises(AnnualWorkValidationError) as fabricated:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(replace(expected[0], item_key="fabricated:key"),),
        )
    assert fabricated.value.code == "annual_work.draft.item_key.fabricated"

    with pytest.raises(AnnualWorkValidationError) as duplicate:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(expected[0], expected[0]),
        )
    assert duplicate.value.code == "annual_work.draft.item_key.duplicate"

    with pytest.raises(AnnualWorkValidationError) as empty:
        service.confirm_preview_selection(
            client_id, 2026, expected_drafts=expected, selected_drafts=()
        )
    assert empty.value.code == "annual_work.drafts.empty"
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


def test_confirm_selection_rejects_standard_work_type_tampering(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    tampered = replace(expected[0], work_type="corporate_income_tax")

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(tampered,),
        )

    assert caught.value.code == "annual_work.draft.standard_mismatch"


def test_confirm_selection_retry_is_idempotent_and_does_not_overwrite_later_edits(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    selected = (replace(expected[0], title="首次建立標題 📝"),)
    first = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=selected
    )
    conn = getattr(container, "conn")
    conn.execute(
        "UPDATE annual_work_items SET title = ?, due_date = ? WHERE id = ?",
        ("使用者後續編輯 🔒", "2027-01-02", first.items[0].id),
    )
    conn.commit()

    second = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=selected
    )

    assert second.inserted_item_count == 0
    assert second.unchanged is True
    assert second.items[0].title == "使用者後續編輯 🔒"
    assert second.items[0].due_date == "2027-01-02"


def test_confirm_selection_never_deletes_previously_created_unselected_items(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    first = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:2]
    )

    second = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=(expected[0],)
    )

    assert second.inserted_item_count == 0
    assert second.unchanged is True
    assert [item.id for item in second.items] == [item.id for item in first.items]


def test_confirm_selection_fault_rolls_back_workspace_items_and_audit(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_selection_audit BEFORE INSERT ON audit_logs "
        "BEGIN SELECT RAISE(ABORT, 'private database detail'); END"
    )
    conn.commit()

    with pytest.raises(AnnualWorkError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=expected[:2],
        )

    assert caught.value.code == "annual_work.confirm.failed"
    assert "private database detail" not in str(caught.value)
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == 0


def test_confirm_selection_audit_has_counts_without_private_titles(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    private_title = "不可進入 audit 的私人標題 🔐"
    custom = WorkDraft(
        item_key="custom:123e4567-e89b-42d3-a456-426614174000",
        operation_year=2026,
        work_type="vat",
        title=private_title,
        tax_year=2026,
        period_code="年底",
        suggested_due_date="2027-01-01",
    )

    result = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=(expected[0], custom),
    )
    row = getattr(container, "conn").execute(
        "SELECT detail_json FROM audit_logs "
        "WHERE action = 'annual_workspace.confirm' AND target_id = ?",
        (str(result.workspace.id),),
    ).fetchone()
    detail = json.loads(row["detail_json"])

    assert detail["selected_count"] == 2
    assert detail["custom_count"] == 1
    assert detail["unchanged"] is False
    assert private_title not in row["detail_json"]


def test_confirm_selection_exactly_500_items_returns_and_audits_every_item(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)

    result = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=_custom_drafts(annual_work_repository.MAX_WORKSPACE_ITEMS),
    )

    assert result.inserted_item_count == annual_work_repository.MAX_WORKSPACE_ITEMS
    assert len(result.items) == annual_work_repository.MAX_WORKSPACE_ITEMS
    row = getattr(container, "conn").execute(
        "SELECT detail_json FROM audit_logs "
        "WHERE action = 'annual_workspace.confirm' AND target_id = ?",
        (str(result.workspace.id),),
    ).fetchone()
    detail = json.loads(row["detail_json"])
    assert detail["item_count"] == annual_work_repository.MAX_WORKSPACE_ITEMS
    assert detail["selected_count"] == annual_work_repository.MAX_WORKSPACE_ITEMS
    snapshot = service.get_workspace_snapshot(client_id, 2026)
    assert snapshot is not None
    assert len(snapshot.items) == annual_work_repository.MAX_WORKSPACE_ITEMS


def test_confirm_selection_oversized_tuple_fails_before_workspace_and_audit(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    conn = getattr(container, "conn")
    changes_before = conn.total_changes
    audit_before = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0]
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))

    try:
        with pytest.raises(AnnualWorkValidationError) as caught:
            service.confirm_preview_selection(
                client_id,
                2026,
                expected_drafts=expected,
                selected_drafts=_custom_drafts(
                    annual_work_repository.MAX_WORKSPACE_ITEMS + 1
                ),
            )
    finally:
        conn.set_trace_callback(None)

    assert caught.value.code == "annual_work.drafts.too_many"
    assert conn.in_transaction is False
    assert conn.total_changes == changes_before
    assert not any(statement == "BEGIN IMMEDIATE" for statement in statements)
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == audit_before


def test_confirm_selection_501st_cumulative_item_rolls_back_only_that_call(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    first = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=_custom_drafts(annual_work_repository.MAX_WORKSPACE_ITEMS),
    )
    conn = getattr(container, "conn")
    changes_before = conn.total_changes
    audit_before = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0]
    extra = _custom_drafts(
        1, start=annual_work_repository.MAX_WORKSPACE_ITEMS + 1
    )
    insert_calls = 0
    original_insert = service.repository.insert_item_if_missing

    def count_insert(workspace_id: int, draft: WorkDraft) -> object:
        nonlocal insert_calls
        insert_calls += 1
        return original_insert(workspace_id, draft)

    monkeypatch.setattr(service.repository, "insert_item_if_missing", count_insert)

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=extra,
        )

    assert caught.value.code == "annual_work.snapshot.too_many_items"
    assert conn.in_transaction is False
    assert insert_calls == 0
    assert conn.total_changes == changes_before
    assert conn.execute(
        "SELECT COUNT(*) FROM annual_work_items WHERE workspace_id = ?",
        (first.workspace.id,),
    ).fetchone()[0] == annual_work_repository.MAX_WORKSPACE_ITEMS
    assert conn.execute(
        "SELECT COUNT(*) FROM annual_work_items WHERE workspace_id = ? AND item_key = ?",
        (first.workspace.id, extra[0].item_key),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == audit_before


def test_confirm_selection_preflight_rejects_already_oversized_workspace(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    first = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=_custom_drafts(annual_work_repository.MAX_WORKSPACE_ITEMS),
    )
    overflow = _custom_drafts(
        1, start=annual_work_repository.MAX_WORKSPACE_ITEMS + 1
    )[0]
    service.repository.insert_item_if_missing(first.workspace.id, overflow)
    conn = getattr(container, "conn")
    conn.commit()
    changes_before = conn.total_changes
    audit_before = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0]
    insert_calls = 0
    original_insert = service.repository.insert_item_if_missing

    def count_insert(workspace_id: int, draft: WorkDraft) -> object:
        nonlocal insert_calls
        insert_calls += 1
        return original_insert(workspace_id, draft)

    monkeypatch.setattr(service.repository, "insert_item_if_missing", count_insert)
    next_draft = _custom_drafts(
        1, start=annual_work_repository.MAX_WORKSPACE_ITEMS + 2
    )

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=next_draft,
        )

    assert caught.value.code == "annual_work.snapshot.too_many_items"
    assert insert_calls == 0
    assert conn.total_changes == changes_before
    assert conn.execute(
        "SELECT COUNT(*) FROM annual_work_items WHERE workspace_id = ?",
        (first.workspace.id,),
    ).fetchone()[0] == annual_work_repository.MAX_WORKSPACE_ITEMS + 1
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == audit_before


def test_confirm_selection_accepts_exact_text_and_date_boundaries(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    boundary = WorkDraft(
        item_key="custom:123e4567-e89b-42d3-a456-426614174001",
        operation_year=2026,
        work_type="vat",
        title="界" * 500,
        tax_year=9999,
        period_code="期" * 50,
        suggested_due_date="9999-12-31",
    )

    result = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=(boundary,),
    )

    assert result.items[0].title == "界" * 500
    assert result.items[0].period_code == "期" * 50
    assert result.items[0].due_date == "9999-12-31"


@pytest.mark.parametrize(
    "invalid",
    (
        {"title": "界" * 501},
        {"period_code": "期" * 51},
        {"suggested_due_date": "2027-01-01T00:00:00"},
    ),
)
def test_confirm_selection_rejects_values_past_exact_boundaries(
    container: object, invalid: dict[str, object]
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(replace(expected[0], **invalid),),
        )

    assert caught.value.code == "annual_work.draft.invalid"
    conn = getattr(container, "conn")
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM annual_work_items").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_workspace.confirm'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "invalid",
    (
        {"title": "\u200b"},
        {"title": "合法標題\u200b"},
        {"title": "合法標題\n第二行"},
        {"period_code": "01\u200b"},
        {"period_code": "01\n02"},
    ),
)
def test_confirm_selection_rejects_invisible_and_control_draft_text(
    container: object, invalid: dict[str, object]
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.confirm_preview_selection(
            client_id,
            2026,
            expected_drafts=expected,
            selected_drafts=(replace(expected[0], **invalid),),
        )

    assert caught.value.code == "annual_work.draft.invalid"
    conn = getattr(container, "conn")
    assert conn.execute("SELECT COUNT(*) FROM annual_workspaces").fetchone()[0] == 0


def test_workspace_snapshot_returns_exact_items_and_missing_is_none(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    assert service.get_workspace_snapshot(client_id, 2026) is None
    expected = service.preview(client_id, 2026)
    created = service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:2]
    )

    snapshot = service.get_workspace_snapshot(client_id, 2026)

    assert snapshot is not None
    assert snapshot.workspace == created.workspace
    assert snapshot.items == created.items
    assert not hasattr(snapshot, "created_workspace")


def test_workspace_snapshot_owns_one_transaction_across_both_reads(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:2]
    )
    conn = getattr(container, "conn")
    events: list[str] = []
    original_find = service.repository.find_workspace
    original_items = service.repository.list_items_for_snapshot

    def trace(statement: str) -> None:
        events.append(statement.strip().upper())

    def find_workspace(candidate_client_id: int, candidate_year: int) -> object:
        events.append("FIND_ENTER")
        assert conn.in_transaction is True
        result = original_find(candidate_client_id, candidate_year)
        events.append("FIND_DONE")
        return result

    def list_items(workspace_id: int) -> object:
        events.append("ITEMS_ENTER")
        assert conn.in_transaction is True
        result = original_items(workspace_id)
        events.append("ITEMS_DONE")
        return result

    monkeypatch.setattr(service.repository, "find_workspace", find_workspace)
    monkeypatch.setattr(service.repository, "list_items_for_snapshot", list_items)
    conn.set_trace_callback(trace)
    try:
        snapshot = service.get_workspace_snapshot(client_id, 2026)
    finally:
        conn.set_trace_callback(None)

    assert snapshot is not None
    assert conn.in_transaction is False
    assert events.index("BEGIN") < events.index("FIND_ENTER")
    assert events.index("FIND_DONE") < events.index("ITEMS_ENTER")
    assert events.index("ITEMS_DONE") < events.index("COMMIT")


def test_workspace_snapshot_missing_workspace_closes_owned_transaction(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        snapshot = service.get_workspace_snapshot(client_id, 2026)
    finally:
        conn.set_trace_callback(None)

    assert snapshot is None
    assert conn.in_transaction is False
    assert "BEGIN" in statements
    assert "COMMIT" in statements


def test_workspace_snapshot_begin_failure_is_stable_and_never_leaks_raw(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    proxy = _ConnectionFaultProxy(conn, fail_begin=True)
    monkeypatch.setattr(service, "_conn", proxy)

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.transaction_failed"
    assert "raw begin transaction failure" not in str(caught.value)
    assert conn.in_transaction is False
    assert proxy.rollback_calls == 0


def test_workspace_snapshot_commit_failure_rolls_back_owned_transaction(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    proxy = _ConnectionFaultProxy(conn, fail_commit=True)
    monkeypatch.setattr(service, "_conn", proxy)

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.transaction_failed"
    assert "raw commit transaction failure" not in str(caught.value)
    assert proxy.rollback_calls == 1
    assert conn.in_transaction is False


def test_workspace_snapshot_preserves_caller_owned_transaction(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:1]
    )
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) "
        "VALUES ('INFO', 'caller snapshot transaction', '2026-12-31T23:59:59')"
    )
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        snapshot = service.get_workspace_snapshot(client_id, 2026)
    finally:
        conn.set_trace_callback(None)

    assert snapshot is not None
    assert conn.in_transaction is True
    assert not any(
        statement in {"BEGIN", "COMMIT", "ROLLBACK"} for statement in statements
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller snapshot transaction'"
    ).fetchone()[0] == 1
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller snapshot transaction'"
    ).fetchone()[0] == 0


def test_workspace_snapshot_owned_read_error_rolls_back_and_hides_raw_detail(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:1]
    )
    conn = getattr(container, "conn")

    def fail_items(_workspace_id: int) -> object:
        raise sqlite3.DatabaseError("raw private snapshot detail")

    monkeypatch.setattr(service.repository, "list_items_for_snapshot", fail_items)
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        with pytest.raises(AnnualWorkError) as caught:
            service.get_workspace_snapshot(client_id, 2026)
    finally:
        conn.set_trace_callback(None)

    assert caught.value.code == "annual_work.snapshot.failed"
    assert "raw private snapshot detail" not in str(caught.value)
    assert conn.in_transaction is False
    assert "BEGIN" in statements
    assert "ROLLBACK" in statements


def test_workspace_snapshot_rollback_failure_invalidates_shared_connection(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:1]
    )
    conn = getattr(container, "conn")
    proxy = _ConnectionFaultProxy(conn, fail_rollback=True)
    monkeypatch.setattr(service, "_conn", proxy)

    def fail_items(_workspace_id: int) -> object:
        raise sqlite3.DatabaseError("raw read failure before rollback")

    monkeypatch.setattr(service.repository, "list_items_for_snapshot", fail_items)

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.transaction_failed"
    assert "raw rollback transaction failure" not in str(caught.value)
    assert proxy.rollback_calls == 1
    assert proxy.closed is True
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with pytest.raises(AnnualWorkError) as reused:
        service.get_workspace_snapshot(client_id, 2026)
    assert reused.value.code == "annual_work.snapshot.transaction_failed"


def test_workspace_snapshot_error_never_rolls_back_caller_transaction(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:1]
    )
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) "
        "VALUES ('INFO', 'caller survives snapshot error', '2027-01-01T00:00:00')"
    )

    def fail_items(_workspace_id: int) -> object:
        raise sqlite3.DatabaseError("raw caller-owned detail")

    monkeypatch.setattr(service.repository, "list_items_for_snapshot", fail_items)
    statements: list[str] = []
    conn.set_trace_callback(lambda statement: statements.append(statement.strip().upper()))
    try:
        with pytest.raises(AnnualWorkError) as caught:
            service.get_workspace_snapshot(client_id, 2026)
    finally:
        conn.set_trace_callback(None)

    assert caught.value.code == "annual_work.snapshot.failed"
    assert conn.in_transaction is True
    assert not any(statement in {"COMMIT", "ROLLBACK"} for statement in statements)
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller survives snapshot error'"
    ).fetchone()[0] == 1
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller survives snapshot error'"
    ).fetchone()[0] == 0


def test_workspace_snapshot_reports_when_caller_transaction_ends_during_read(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=expected[:1]
    )
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) "
        "VALUES ('INFO', 'caller transaction will end', '2027-01-01T00:00:01')"
    )

    def end_caller_transaction(_workspace_id: int) -> object:
        conn.rollback()
        raise sqlite3.DatabaseError("raw read after caller ended")

    monkeypatch.setattr(
        service.repository,
        "list_items_for_snapshot",
        end_caller_transaction,
    )

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.caller_transaction_ended"
    assert "raw read after caller ended" not in str(caught.value)
    assert conn.in_transaction is False
    assert conn.execute(
        "SELECT COUNT(*) FROM system_logs WHERE message = 'caller transaction will end'"
    ).fetchone()[0] == 0


def test_workspace_snapshot_rejects_more_than_500_items_without_truncation(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    created = service.confirm_preview_selection(
        client_id,
        2026,
        expected_drafts=expected,
        selected_drafts=_custom_drafts(annual_work_repository.MAX_WORKSPACE_ITEMS),
    )
    service.repository.insert_item_if_missing(
        created.workspace.id,
        _custom_drafts(
            1, start=annual_work_repository.MAX_WORKSPACE_ITEMS + 1
        )[0],
    )
    getattr(container, "conn").commit()

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.too_many_items"
    assert getattr(container, "conn").in_transaction is False


@pytest.mark.parametrize(
    ("client_id", "operation_year", "code"),
    (
        (True, 2026, "annual_work.client_id.invalid"),
        ("1", 2026, "annual_work.client_id.invalid"),
        (1, False, "annual_work.operation_year.invalid"),
        (1, "2026", "annual_work.operation_year.invalid"),
    ),
)
def test_workspace_snapshot_strictly_validates_identity(
    container: object, client_id: object, operation_year: object, code: str
) -> None:
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").get_workspace_snapshot(
            client_id, operation_year
        )

    assert caught.value.code == code
