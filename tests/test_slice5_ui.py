"""Slice 5 UI integration tests: TasksPage handler → service → DB → audit."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.tasks import TasksRepository
from taxops.services.audit import AuditService
from taxops.services.engagements import EngagementsService, CreateEngagementInput
from taxops.services.tasks import CreateTaskInput, TasksService
from taxops.ui.pages.tasks_page import TasksPage


# ── QApplication singleton ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── DB + services fixture ─────────────────────────────────────────────────────

class _FakeContainer:
    """Minimal stand-in for ServiceContainer used by TasksPage."""

    def __init__(self, conn):
        self._conn = conn
        audit_repo = AuditLogRepository(conn)
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.audit_repo = audit_repo
        self.engagements = EngagementsService(EngagementsRepository(conn), self._audit)
        tasks_repo = TasksRepository(conn)
        self.tasks = TasksService(tasks_repo, self._audit)


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "ui_test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


@pytest.fixture()
def eng_id(conn, container):
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("CL001", "UI測試客戶"),
    )
    conn.commit()
    client_id = cur.lastrowid
    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="UI測試案件",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    return eng.id


@pytest.fixture()
def page(qapp, container):
    w = TasksPage(container)
    w.show()
    return w


# ── widget smoke ──────────────────────────────────────────────────────────────

def test_tasks_page_instantiates(page):
    assert page is not None


def test_buttons_disabled_with_no_selection(page):
    assert not page._complete_btn.isEnabled()
    assert not page._status_btn.isEnabled()
    assert not page._delete_btn.isEnabled()


def test_new_btn_always_enabled(page):
    assert page._new_btn.isEnabled()


def test_refresh_btn_always_enabled(page):
    assert page._refresh_btn.isEnabled()


# ── empty state ───────────────────────────────────────────────────────────────

def test_empty_state_shown_when_no_tasks(page):
    assert page._empty_label.isVisible()
    assert not page._table.isVisible()


# ── table populates after create ──────────────────────────────────────────────

def test_table_shows_task_after_service_create(page, container, eng_id):
    container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="顯示測試")
    )
    page._refresh()
    assert page._table.rowCount() == 1
    assert page._table.item(0, 1).text() == "顯示測試"


def test_empty_state_hidden_when_tasks_exist(page, container, eng_id):
    container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="有資料")
    )
    page._refresh()
    assert not page._empty_label.isVisible()
    assert page._table.isVisible()


# ── complete_task → DB → audit ────────────────────────────────────────────────

def test_complete_task_updates_db_and_audit(page, container, eng_id):
    row = container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="完成測試")
    )
    container.tasks.set_status(row.id, "doing")
    page._refresh()
    page._table.selectRow(0)
    assert page._complete_btn.isEnabled()

    container.tasks.complete_task(row.id)
    page._refresh()

    updated = container.tasks.get_task(row.id)
    assert updated.status == "done"
    assert updated.completed_at is not None

    logs = container.audit_repo.list_recent(limit=20)
    assert any(log.action == "task.complete" and log.target_id == str(row.id) for log in logs)


# ── delete_task → DB → audit ──────────────────────────────────────────────────

def test_delete_task_soft_deletes_and_audit(page, container, eng_id):
    row = container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="刪除測試")
    )
    page._refresh()
    page._table.selectRow(0)

    container.tasks.delete_task(row.id)
    page._refresh()

    assert container.tasks.get_task(row.id) is None
    assert page._table.rowCount() == 0

    logs = container.audit_repo.list_recent(limit=20)
    assert any(log.action == "task.delete" and log.target_id == str(row.id) for log in logs)


# ── _selected_task_id ─────────────────────────────────────────────────────────

def test_selected_task_id_returns_none_without_selection(page):
    assert page._selected_task_id() is None


def test_selected_task_id_returns_correct_id(page, container, eng_id):
    row = container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="選取測試")
    )
    page._refresh()
    page._table.selectRow(0)
    assert page._selected_task_id() == row.id


# ── engagement filter combo ───────────────────────────────────────────────────

def test_engagement_combo_has_all_option(page):
    assert page._eng_combo.count() >= 1
    assert page._eng_combo.itemText(0) == "（全部案件）"


# ── set_status via service → audit ───────────────────────────────────────────

def test_set_status_via_service_writes_audit(page, container, eng_id):
    row = container.tasks.create_task(
        CreateTaskInput(engagement_id=eng_id, title="狀態測試")
    )
    container.tasks.set_status(row.id, "doing")

    logs = container.audit_repo.list_recent(limit=20)
    assert any(
        log.action == "task.status_change" and log.target_id == str(row.id)
        for log in logs
    )

    updated = container.tasks.get_task(row.id)
    assert updated.status == "doing"
