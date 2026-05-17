"""Tests for TasksService + TasksRepository + audit log (Slice 5)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.tasks import TasksRepository
from taxops.services.audit import AuditService
from taxops.services.tasks import (
    CreateTaskInput,
    TaskValidationError,
    TasksService,
    VALID_TASK_STATUSES,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def audit_repo(conn):
    return AuditLogRepository(conn)


@pytest.fixture()
def svc(conn, audit_repo):
    audit = AuditService(audit_repo, actor="test_user")
    repo = TasksRepository(conn)
    return TasksService(repo, audit)


@pytest.fixture()
def eng_id(conn):
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("CL001", "測試客戶"),
    )
    conn.commit()
    client_id = cur.lastrowid
    cur2 = conn.execute(
        "INSERT INTO engagements("
        "client_id, engagement_name, tax_type, period_name, status, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (client_id, "2024 申報", "vat", "2024Q1", "draft"),
    )
    conn.commit()
    return cur2.lastrowid


def _make(eng_id: int, **kwargs) -> CreateTaskInput:
    defaults = dict(engagement_id=eng_id, title="測試待辦", priority="normal")
    defaults.update(kwargs)
    return CreateTaskInput(**defaults)


# ── schema ────────────────────────────────────────────────────────────────────

def test_workflow_tasks_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_tasks'"
    ).fetchone()
    assert row is not None, "workflow_tasks table not found"


def test_workflow_tasks_columns_present(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_tasks)").fetchall()}
    required = {
        "id", "engagement_id", "title", "assignee", "due_date", "priority",
        "status", "next_step", "notes", "completed_at", "created_at", "updated_at", "deleted_at",
    }
    missing = required - cols
    assert not missing, f"Missing columns: {missing}"


# ── create_task ───────────────────────────────────────────────────────────────

def test_create_task_success(svc, eng_id):
    row = svc.create_task(_make(eng_id, title="完成報稅"))
    assert row.id is not None
    assert row.title == "完成報稅"
    assert row.status == "todo"
    assert row.priority == "normal"
    assert row.engagement_id == eng_id


def test_create_task_requires_title(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, title=""))
    assert exc.value.code == "task.title.required"


def test_create_task_whitespace_only_title_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, title="   "))
    assert exc.value.code == "task.title.required"


def test_create_task_invalid_priority_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, priority="super_urgent"))
    assert exc.value.code == "task.priority.invalid"


def test_create_task_invalid_engagement_raises(svc):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(99999))
    assert exc.value.code == "task.engagement_not_found"


def test_create_task_with_due_date(svc, eng_id):
    row = svc.create_task(_make(eng_id, due_date="2024-12-31"))
    assert row.due_date == "2024-12-31"


def test_create_task_with_assignee_and_next_step(svc, eng_id):
    row = svc.create_task(_make(eng_id, assignee="林大明", next_step="寄送確認信"))
    assert row.assignee == "林大明"
    assert row.next_step == "寄送確認信"


def test_create_task_none_due_date_accepted(svc, eng_id):
    row = svc.create_task(_make(eng_id, due_date=None))
    assert row.due_date is None


def test_create_task_malformed_due_date_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, due_date="2024/12/31"))
    assert exc.value.code == "task.due_date.invalid"


def test_create_task_partial_iso_date_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, due_date="2024-12"))
    assert exc.value.code == "task.due_date.invalid"


def test_create_task_leap_day_valid(svc, eng_id):
    row = svc.create_task(_make(eng_id, due_date="2024-02-29"))
    assert row.due_date == "2024-02-29"


def test_create_task_feb31_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, due_date="2024-02-31"))
    assert exc.value.code == "task.due_date.invalid"


def test_create_task_invalid_month_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, due_date="2024-99-99"))
    assert exc.value.code == "task.due_date.invalid"


def test_create_task_zero_date_raises(svc, eng_id):
    with pytest.raises(TaskValidationError) as exc:
        svc.create_task(_make(eng_id, due_date="0000-00-00"))
    assert exc.value.code == "task.due_date.invalid"


def test_create_task_writes_audit(svc, eng_id, audit_repo):
    row = svc.create_task(_make(eng_id, title="稽核作業"))
    logs = audit_repo.list_recent(limit=10)
    assert any(
        log.action == "task.create" and log.target_type == "task" and log.target_id == str(row.id)
        for log in logs
    )


# ── complete_task ─────────────────────────────────────────────────────────────

def test_complete_task_sets_done_and_completed_at(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    completed = svc.complete_task(row.id)
    assert completed.status == "done"
    assert completed.completed_at is not None


def test_complete_task_already_done_raises(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    svc.complete_task(row.id)
    with pytest.raises(TaskValidationError) as exc:
        svc.complete_task(row.id)
    assert exc.value.code == "task.already_done"


def test_complete_task_cancelled_raises(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    svc.set_status(row.id, "cancelled")
    with pytest.raises(TaskValidationError) as exc:
        svc.complete_task(row.id)
    assert exc.value.code == "task.status.transition_invalid"


def test_complete_task_nonexistent_raises(svc):
    with pytest.raises(TaskValidationError) as exc:
        svc.complete_task(99999)
    assert exc.value.code == "task.not_found"


def test_complete_task_writes_audit(svc, eng_id, audit_repo):
    row = svc.create_task(_make(eng_id))
    svc.complete_task(row.id)
    logs = audit_repo.list_recent(limit=10)
    assert any(
        log.action == "task.complete" and log.target_id == str(row.id)
        for log in logs
    )


# ── set_status ────────────────────────────────────────────────────────────────

def test_set_status_todo_to_doing(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    updated = svc.set_status(row.id, "doing")
    assert updated.status == "doing"


def test_set_status_doing_to_done(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    svc.set_status(row.id, "doing")
    updated = svc.set_status(row.id, "done")
    assert updated.status == "done"


def test_set_status_todo_to_done_is_invalid(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    with pytest.raises(TaskValidationError) as exc:
        svc.set_status(row.id, "done")
    assert exc.value.code == "task.status.transition_invalid"


def test_set_status_done_is_terminal(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    svc.complete_task(row.id)
    with pytest.raises(TaskValidationError) as exc:
        svc.set_status(row.id, "todo")
    assert exc.value.code == "task.status.transition_invalid"


def test_set_status_unknown_status_raises(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    with pytest.raises(TaskValidationError) as exc:
        svc.set_status(row.id, "not_a_status")
    assert exc.value.code == "task.status.invalid"


def test_set_status_nonexistent_raises(svc):
    with pytest.raises(TaskValidationError) as exc:
        svc.set_status(99999, "doing")
    assert exc.value.code == "task.not_found"


def test_set_status_writes_audit(svc, eng_id, audit_repo):
    row = svc.create_task(_make(eng_id))
    svc.set_status(row.id, "doing")
    logs = audit_repo.list_recent(limit=10)
    assert any(
        log.action == "task.status_change" and log.target_id == str(row.id)
        for log in logs
    )


# ── delete_task ───────────────────────────────────────────────────────────────

def test_delete_task_soft_deletes(svc, eng_id):
    row = svc.create_task(_make(eng_id))
    svc.delete_task(row.id)
    assert svc.get_task(row.id) is None


def test_delete_task_nonexistent_raises(svc):
    with pytest.raises(TaskValidationError) as exc:
        svc.delete_task(99999)
    assert exc.value.code == "task.not_found"


def test_delete_task_writes_audit(svc, eng_id, audit_repo):
    row = svc.create_task(_make(eng_id))
    svc.delete_task(row.id)
    logs = audit_repo.list_recent(limit=10)
    assert any(
        log.action == "task.delete" and log.target_id == str(row.id)
        for log in logs
    )


# ── list_by_engagement ────────────────────────────────────────────────────────

def test_list_by_engagement_returns_only_matching(svc, conn, eng_id):
    cur = conn.execute(
        "INSERT INTO engagements("
        "client_id, engagement_name, tax_type, period_name, status, created_at, updated_at"
        ") VALUES ((SELECT client_id FROM engagements WHERE id=?), ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (eng_id, "另一案件", "cit", "2024", "draft"),
    )
    conn.commit()
    other_eng_id = cur.lastrowid

    svc.create_task(_make(eng_id, title="案件A任務"))
    svc.create_task(_make(other_eng_id, title="案件B任務"))

    results = svc.list_by_engagement(eng_id)
    assert len(results) == 1
    assert results[0].title == "案件A任務"


def test_list_by_engagement_excludes_deleted(svc, eng_id):
    row = svc.create_task(_make(eng_id, title="待刪除"))
    svc.create_task(_make(eng_id, title="保留"))
    svc.delete_task(row.id)
    results = svc.list_by_engagement(eng_id)
    assert len(results) == 1
    assert results[0].title == "保留"


# ── list_overdue ──────────────────────────────────────────────────────────────

def test_list_overdue_returns_past_due_nondone(svc, eng_id):
    svc.create_task(_make(eng_id, title="逾期", due_date="2020-01-01"))
    results = svc.list_overdue("2024-01-01")
    assert any(t.title == "逾期" for t in results)


def test_list_overdue_excludes_done(svc, eng_id):
    row = svc.create_task(_make(eng_id, title="已完成逾期", due_date="2020-01-01"))
    svc.set_status(row.id, "doing")
    svc.complete_task(row.id)
    results = svc.list_overdue("2024-01-01")
    assert not any(t.id == row.id for t in results)


def test_list_overdue_excludes_cancelled(svc, eng_id):
    row = svc.create_task(_make(eng_id, title="已取消逾期", due_date="2020-01-01"))
    svc.set_status(row.id, "cancelled")
    results = svc.list_overdue("2024-01-01")
    assert not any(t.id == row.id for t in results)


def test_list_overdue_excludes_future(svc, eng_id):
    svc.create_task(_make(eng_id, title="未來任務", due_date="2099-12-31"))
    results = svc.list_overdue("2024-01-01")
    assert not any(t.title == "未來任務" for t in results)


def test_list_overdue_excludes_no_due_date(svc, eng_id):
    svc.create_task(_make(eng_id, title="無期限"))
    results = svc.list_overdue("2024-01-01")
    assert not any(t.title == "無期限" for t in results)


# ── list_all ──────────────────────────────────────────────────────────────────

def test_list_all_returns_all_non_deleted(svc, conn, eng_id):
    cur = conn.execute(
        "INSERT INTO engagements("
        "client_id, engagement_name, tax_type, period_name, status, created_at, updated_at"
        ") VALUES ((SELECT client_id FROM engagements WHERE id=?), ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (eng_id, "案件B", "cit", "2024", "draft"),
    )
    conn.commit()
    eng2 = cur.lastrowid

    svc.create_task(_make(eng_id, title="任務A"))
    row_b = svc.create_task(_make(eng2, title="任務B"))
    svc.delete_task(row_b.id)

    results = svc.list_all()
    titles = [t.title for t in results]
    assert "任務A" in titles
    assert "任務B" not in titles
