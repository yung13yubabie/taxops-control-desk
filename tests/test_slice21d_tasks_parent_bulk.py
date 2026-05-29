"""Slice 21D: workflow_tasks parent_task_id + bulk CRUD."""

from __future__ import annotations

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture()
def two_clients(container):
    from taxops.services.clients import CreateClientInput
    c1 = container.clients.create_client(CreateClientInput(client_code="C21D1", client_name="客戶甲"))
    c2 = container.clients.create_client(CreateClientInput(client_code="C21D2", client_name="客戶乙"))
    return c1, c2


def test_workflow_tasks_has_parent_task_id(db_conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(workflow_tasks)").fetchall()}
    assert "parent_task_id" in cols


def test_workflow_tasks_has_parent_index(db_conn: sqlite3.Connection) -> None:
    rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='workflow_tasks'"
    ).fetchall()
    assert "idx_workflow_tasks_parent" in {r["name"] for r in rows}


def test_convert_to_child_links_two_tasks(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="父任務",
    ))
    child = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="子任務",
    ))
    updated = container.tasks.convert_to_child(child.id, parent.id)
    assert updated.parent_task_id == parent.id


def test_create_child_task_inherits_parent_context(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=c1.id,
        title="父待辦",
        assignee="Alice",
        priority="high",
        next_step="補附件",
    ))

    child = container.tasks.create_child_task(parent.id, "補附件")

    assert child.parent_task_id == parent.id
    assert child.client_id == c1.id
    assert child.engagement_id is None
    assert child.assignee == "Alice"
    assert child.priority == "high"
    assert child.title == "補附件"


def test_create_child_task_rejects_child_as_parent(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="父",
    ))
    child = container.tasks.create_child_task(parent.id, "子")

    with pytest.raises(TaskValidationError) as ei:
        container.tasks.create_child_task(child.id, "孫")
    assert ei.value.code == "task.parent.depth_exceeded"


def test_create_child_task_records_audit(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, *_ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="父",
    ))
    container.tasks.create_child_task(parent.id, "下一步")
    row = container.conn.execute(
        "SELECT id FROM audit_logs WHERE action='task.create_child'"
    ).fetchone()
    assert row is not None


def test_convert_to_child_rejects_grandchild(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    grandparent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="阿公",
    ))
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="爸爸",
    ))
    child = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="兒子",
    ))
    container.tasks.convert_to_child(parent.id, grandparent.id)
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.convert_to_child(child.id, parent.id)
    assert ei.value.code == "task.parent.depth_exceeded"


def test_convert_to_child_rejects_self(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    t = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="自婚",
    ))
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.convert_to_child(t.id, t.id)
    assert ei.value.code == "task.parent.self_reference"


def test_convert_to_child_rejects_cross_client_link(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, c2 = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="甲的父任務",
    ))
    child = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c2.id, title="乙的子任務",
    ))
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.convert_to_child(child.id, parent.id)
    assert ei.value.code == "task.parent.context_mismatch"


def test_delete_task_with_children_is_blocked(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="父",
    ))
    child = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="子",
    ))
    container.tasks.convert_to_child(child.id, parent.id)
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.delete_task(parent.id)
    assert ei.value.code == "task.delete.has_children"


def test_delete_task_with_no_children_succeeds(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    t = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="獨子",
    ))
    container.tasks.delete_task(t.id)
    assert container.tasks.get_task(t.id) is None


def test_create_tasks_bulk_creates_one_per_client(container, two_clients):
    from taxops.services.tasks import BulkTaskTemplate
    c1, c2 = two_clients
    created = container.tasks.create_tasks_bulk(
        client_ids=[c1.id, c2.id],
        template=BulkTaskTemplate(title="批量任務", priority="normal"),
    )
    assert len(created) == 2
    titles = {t.title for t in created}
    assert titles == {"批量任務"}
    client_ids = {t.client_id for t in created}
    assert client_ids == {c1.id, c2.id}


def test_create_tasks_bulk_audit_records_count(container, two_clients):
    from taxops.services.tasks import BulkTaskTemplate
    c1, c2 = two_clients
    container.tasks.create_tasks_bulk(
        client_ids=[c1.id, c2.id],
        template=BulkTaskTemplate(title="批量"),
    )
    rows = container.conn.execute(
        "SELECT detail_json FROM audit_logs WHERE action='task.bulk_create'"
    ).fetchall()
    assert len(rows) == 1
    assert '"task_count": 2' in rows[0]["detail_json"]


def test_create_tasks_bulk_skips_invalid_client(container, two_clients):
    from taxops.services.tasks import BulkTaskTemplate
    c1, _ = two_clients
    created = container.tasks.create_tasks_bulk(
        client_ids=[c1.id, 99999],
        template=BulkTaskTemplate(title="部分有效"),
    )
    assert len(created) == 1


def test_update_tasks_bulk_changes_only_specified_fields(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    t1 = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="T1", priority="low"))
    t2 = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="T2", priority="low"))
    n = container.tasks.update_tasks_bulk([t1.id, t2.id], {"priority": "high"})
    assert n == 2
    assert container.tasks.get_task(t1.id).priority == "high"
    assert container.tasks.get_task(t2.id).priority == "high"
    assert container.tasks.get_task(t1.id).title == "T1"


def test_update_tasks_bulk_rejects_unknown_field_without_audit(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    t = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="T",
    ))
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.update_tasks_bulk([t.id], {"bogus": "value"})
    assert ei.value.code == "task.bulk.update.invalid_field"
    assert container.tasks.get_task(t.id).title == "T"
    rows = container.conn.execute(
        "SELECT id FROM audit_logs WHERE action='task.bulk_update'"
    ).fetchall()
    assert rows == []


def test_update_tasks_bulk_rejects_invalid_due_date(container, two_clients):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    c1, _ = two_clients
    t = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="T", due_date="2026-05-26",
    ))
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.update_tasks_bulk([t.id], {"due_date": "1752-99-99"})
    assert ei.value.code == "task.due_date.invalid"
    assert container.tasks.get_task(t.id).due_date == "2026-05-26"


def test_delete_tasks_bulk_soft_deletes_all(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    ids = []
    for i in range(3):
        t = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title=f"BD{i}"))
        ids.append(t.id)
    n = container.tasks.delete_tasks_bulk(ids)
    assert n == 3
    for i in ids:
        assert container.tasks.get_task(i) is None


def test_delete_tasks_bulk_skips_parent_with_children(container, two_clients):
    from taxops.services.tasks import CreateTaskInput
    c1, _ = two_clients
    parent = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="P"))
    child = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="C"))
    container.tasks.convert_to_child(child.id, parent.id)
    other = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="O"))
    n = container.tasks.delete_tasks_bulk([parent.id, other.id])
    assert n == 1
    assert container.tasks.get_task(parent.id) is not None
    assert container.tasks.get_task(other.id) is None
