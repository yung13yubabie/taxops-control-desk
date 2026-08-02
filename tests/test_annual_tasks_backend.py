from __future__ import annotations

import pytest

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.tasks import CreateTaskInput, TaskValidationError


def _annual_items(container: object, *, client_code: str):
    client = getattr(container, "clients").create_client(
        CreateClientInput(client_code=client_code, client_name="年度任務測試客戶")
    )
    getattr(container, "compliance_profiles").upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )
    annual = getattr(container, "annual_work")
    confirmed = annual.confirm_preview(
        client.id, 2026, annual.preview(client.id, 2026)
    )
    return client, confirmed.items


def _annual_item(container: object, *, client_code: str):
    client, items = _annual_items(container, client_code=client_code)
    return client, items[0]


def test_create_child_task_inherits_annual_item_and_remains_listable(
    container: object,
) -> None:
    _client, item = _annual_item(container, client_code="ANNUAL-TASK-CHILD")
    tasks = getattr(container, "tasks")
    parent = getattr(container, "annual_work").create_linked_task(
        item.id, title="營業稅申報"
    )

    child = tasks.create_child_task(parent.id, "覆核申報資料")

    assert child.parent_task_id == parent.id
    assert child.annual_work_item_id == item.id
    assert {
        row.id for row in tasks.list_by_annual_work_item(item.id)
    } == {parent.id, child.id}


def test_convert_to_child_rejects_different_annual_items_without_writes(
    container: object,
) -> None:
    _client, items = _annual_items(
        container, client_code="ANNUAL-TASK-CONTEXT"
    )
    annual = getattr(container, "annual_work")
    tasks = getattr(container, "tasks")
    parent = annual.create_linked_task(items[0].id, title="一月營業稅")
    annual.link_existing_engagement(items[1].id, parent.engagement_id)
    child = annual.create_linked_task(items[1].id, title="三月營業稅")
    before_child = tasks.get_task(child.id)
    before_audit_count = getattr(container, "audit")._repo.count()

    with pytest.raises(TaskValidationError) as caught:
        tasks.convert_to_child(child.id, parent.id)

    assert caught.value.code == "task.parent.annual_context_mismatch"
    assert tasks.get_task(child.id) == before_child
    assert getattr(container, "audit")._repo.count() == before_audit_count


@pytest.mark.parametrize("annual_task_is_child", [True, False])
def test_convert_to_child_rejects_annual_and_nonannual_pair_without_writes(
    container: object,
    annual_task_is_child: bool,
) -> None:
    _client, item = _annual_item(
        container, client_code=f"ANNUAL-TASK-NONE-{annual_task_is_child}"
    )
    tasks = getattr(container, "tasks")
    annual_task = getattr(container, "annual_work").create_linked_task(
        item.id, title="年度任務"
    )
    plain_task = tasks.create_task(
        CreateTaskInput(
            engagement_id=annual_task.engagement_id,
            title="一般案件任務",
        )
    )
    child, parent = (
        (annual_task, plain_task)
        if annual_task_is_child
        else (plain_task, annual_task)
    )
    before_child = tasks.get_task(child.id)
    before_audit_count = getattr(container, "audit")._repo.count()

    with pytest.raises(TaskValidationError) as caught:
        tasks.convert_to_child(child.id, parent.id)

    assert caught.value.code == "task.parent.annual_context_mismatch"
    assert tasks.get_task(child.id) == before_child
    assert getattr(container, "audit")._repo.count() == before_audit_count


def test_convert_to_child_allows_exact_same_annual_item_context(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-SAME-CONTEXT"
    )
    annual = getattr(container, "annual_work")
    tasks = getattr(container, "tasks")
    parent = annual.create_linked_task(item.id, title="年度申報")
    child = annual.create_linked_task(item.id, title="年度申報覆核")

    converted = tasks.convert_to_child(child.id, parent.id)

    assert converted.parent_task_id == parent.id
    assert converted.annual_work_item_id == item.id


def test_count_by_annual_work_item_matches_visible_tasks(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-COUNT"
    )
    tasks = getattr(container, "tasks")
    parent = getattr(container, "annual_work").create_linked_task(
        item.id, title="年度任務"
    )
    tasks.create_child_task(parent.id, "年度任務覆核")

    assert tasks.count_by_annual_work_item(item.id) == 2


def test_list_by_annual_work_item_rejects_limit_above_200(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-LIMIT"
    )

    with pytest.raises(TaskValidationError) as caught:
        getattr(container, "tasks").list_by_annual_work_item(
            item.id, limit=201
        )

    assert caught.value.code == "task.list.invalid_pagination"


def test_annual_task_pages_reach_201_without_duplicates_with_stable_ties(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-PAGE-201"
    )
    tasks = getattr(container, "tasks")
    first = getattr(container, "annual_work").create_linked_task(
        item.id, title="年度任務 000"
    )
    created = [first]
    created.extend(
        tasks.create_task(
            CreateTaskInput(
                engagement_id=first.engagement_id,
                annual_work_item_id=item.id,
                title=f"年度任務 {index:03d}",
            )
        )
        for index in range(1, 205)
    )
    getattr(container, "conn").execute(
        "UPDATE workflow_tasks SET updated_at = ?"
        " WHERE annual_work_item_id = ?",
        ("2026-07-28T12:00:00Z", item.id),
    )
    getattr(container, "conn").commit()
    expected_ids = sorted(row.id for row in created)

    first_page = tasks.list_by_annual_work_item(
        item.id, limit=200, offset=0
    )
    second_page = tasks.list_by_annual_work_item(
        item.id, limit=5, offset=200
    )
    paged_ids = [row.id for row in (*first_page, *second_page)]

    assert tasks.count_by_annual_work_item(item.id) == 205
    assert paged_ids == expected_ids
    assert second_page[0].id == expected_ids[200]
    assert len(paged_ids) == len(set(paged_ids)) == 205


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (True, 0),
        ("1", 0),
        (0, 0),
        (201, 0),
        (1, True),
        (1, "0"),
        (1, -1),
        (1, 1_000_001),
    ],
)
def test_annual_task_pagination_rejects_unbounded_or_mistyped_values(
    container: object,
    limit: object,
    offset: object,
) -> None:
    _client, item = _annual_item(
        container,
        client_code=(
            f"ANNUAL-TASK-INVALID-{type(limit).__name__}-"
            f"{type(offset).__name__}-{limit}-{offset}"
        ),
    )

    with pytest.raises(TaskValidationError) as caught:
        getattr(container, "tasks").list_by_annual_work_item(
            item.id, limit=limit, offset=offset
        )

    assert caught.value.code == "task.list.invalid_pagination"


def test_annual_task_lists_are_isolated_by_exact_annual_owner(
    container: object,
) -> None:
    _first_client, first_item = _annual_item(
        container, client_code="ANNUAL-TASK-OWNER-A"
    )
    _second_client, second_item = _annual_item(
        container, client_code="ANNUAL-TASK-OWNER-B"
    )
    annual = getattr(container, "annual_work")
    tasks = getattr(container, "tasks")
    first = annual.create_linked_task(first_item.id, title="甲客戶年度任務")
    second = annual.create_linked_task(second_item.id, title="乙客戶年度任務")

    assert tasks.list_by_annual_work_item(first_item.id) == [first]
    assert tasks.list_by_annual_work_item(second_item.id) == [second]
    assert tasks.count_by_annual_work_item(first_item.id) == 1
    assert tasks.count_by_annual_work_item(second_item.id) == 1


def test_mismatched_annual_client_engagement_tuple_is_fail_closed(
    container: object,
) -> None:
    first_client, first_item = _annual_item(
        container, client_code="ANNUAL-TASK-CORRUPT-A"
    )
    second_client, second_item = _annual_item(
        container, client_code="ANNUAL-TASK-CORRUPT-B"
    )
    annual = getattr(container, "annual_work")
    tasks = getattr(container, "tasks")
    first = annual.create_linked_task(first_item.id, title="甲客戶年度任務")
    second = annual.create_linked_task(second_item.id, title="乙客戶年度任務")
    getattr(container, "conn").execute(
        "UPDATE workflow_tasks SET client_id = ?, engagement_id = ?"
        " WHERE id = ?",
        (second_client.id, second.engagement_id, first.id),
    )
    getattr(container, "conn").commit()
    audit_before = getattr(container, "audit")._repo.count()

    assert first_client.id != second_client.id
    assert tasks.get_task(first.id) is None
    assert tasks.list_by_annual_work_item(first_item.id) == []
    assert tasks.count_by_annual_work_item(first_item.id) == 0
    assert tasks.list_by_annual_work_item(second_item.id) == [second]
    with pytest.raises(TaskValidationError) as child:
        tasks.create_child_task(first.id, "不得繼承污染 ownership")
    assert child.value.code == "task.parent.not_found"
    assert getattr(container, "audit")._repo.count() == audit_before


def test_deleted_annual_task_is_excluded_from_count_and_pages(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-DELETED"
    )
    tasks = getattr(container, "tasks")
    task = getattr(container, "annual_work").create_linked_task(
        item.id, title="待刪除年度任務"
    )

    tasks.delete_task(task.id)

    assert tasks.list_by_annual_work_item(item.id) == []
    assert tasks.count_by_annual_work_item(item.id) == 0


@pytest.mark.parametrize(
    ("owner_table", "owner_column"),
    [
        ("annual_work_items", "id"),
        ("annual_workspaces", "id"),
        ("clients", "id"),
    ],
)
def test_deleted_annual_owners_are_not_addressable(
    container: object,
    owner_table: str,
    owner_column: str,
) -> None:
    client, item = _annual_item(
        container, client_code=f"ANNUAL-TASK-DELETED-{owner_table}"
    )
    task = getattr(container, "annual_work").create_linked_task(
        item.id, title="年度任務"
    )
    workspace_id = getattr(container, "conn").execute(
        "SELECT workspace_id FROM annual_work_items WHERE id = ?",
        (item.id,),
    ).fetchone()[0]
    owner_id = {
        "annual_work_items": item.id,
        "annual_workspaces": workspace_id,
        "clients": client.id,
    }[owner_table]
    getattr(container, "conn").execute(
        f"UPDATE {owner_table} SET deleted_at = ? WHERE {owner_column} = ?",
        ("2026-07-28T12:30:00Z", owner_id),
    )
    getattr(container, "conn").commit()
    tasks = getattr(container, "tasks")

    with pytest.raises(TaskValidationError) as listed:
        tasks.list_by_annual_work_item(item.id)
    assert listed.value.code == "task.annual_work_item_not_found"
    with pytest.raises(TaskValidationError) as counted:
        tasks.count_by_annual_work_item(item.id)
    assert counted.value.code == "task.annual_work_item_not_found"
    assert tasks.get_task(task.id) is None


def test_deleted_engagement_hides_annual_task_without_cross_owner_leak(
    container: object,
) -> None:
    _client, item = _annual_item(
        container, client_code="ANNUAL-TASK-DELETED-ENGAGEMENT"
    )
    tasks = getattr(container, "tasks")
    task = getattr(container, "annual_work").create_linked_task(
        item.id, title="案件已刪除的年度任務"
    )
    getattr(container, "conn").execute(
        "UPDATE engagements SET deleted_at = ? WHERE id = ?",
        ("2026-07-28T12:30:00Z", task.engagement_id),
    )
    getattr(container, "conn").commit()

    assert tasks.list_by_annual_work_item(item.id) == []
    assert tasks.count_by_annual_work_item(item.id) == 0
    assert tasks.get_task(task.id) is None
