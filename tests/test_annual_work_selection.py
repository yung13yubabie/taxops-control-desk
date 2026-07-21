from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

import pytest

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


def test_workspace_snapshot_rejects_more_than_500_items_without_truncation(
    container: object,
) -> None:
    client_id = _client_with_profile(container)
    service = getattr(container, "annual_work")
    expected = service.preview(client_id, 2026)
    selected = tuple(
        WorkDraft(
            item_key=f"custom:{UUID(int=index + 1)}",
            operation_year=2026,
            work_type="vat",
            title=f"批次自訂工作 {index + 1}",
            tax_year=2026,
            period_code="全年",
            suggested_due_date="2027-12-31",
        )
        for index in range(501)
    )
    service.confirm_preview_selection(
        client_id, 2026, expected_drafts=expected, selected_drafts=selected
    )

    with pytest.raises(AnnualWorkError) as caught:
        service.get_workspace_snapshot(client_id, 2026)

    assert caught.value.code == "annual_work.snapshot.too_many_items"


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
