"""Slice 21E: TasksPage parent/child + bulk UI wiring."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.app_settings import AppSettingsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.system_logs import SystemLogRepository
from taxops.repositories.tasks import TasksRepository
from taxops.services.audit import AuditService
from taxops.services.clients import ClientsService, CreateClientInput
from taxops.services.engagements import EngagementsService
from taxops.services.settings import SettingsService
from taxops.services.system_log import SystemLogService
from taxops.services.tasks import BulkTaskTemplate, CreateTaskInput, TasksService
from taxops.ui.action_registry import PAGE_TASKS, actions_for_page
from taxops.ui.pages.tasks_page import TasksPage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeContainer:
    def __init__(self, conn):
        self._conn = conn
        audit_repo = AuditLogRepository(conn)
        self.audit_repo = audit_repo
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.system_log = SystemLogService(SystemLogRepository(conn))
        self.clients = ClientsService(ClientsRepository(conn), self._audit)
        self.engagements = EngagementsService(EngagementsRepository(conn), self._audit)
        settings_repo = AppSettingsRepository(conn)
        settings_repo.seed_defaults()
        self.settings = SettingsService(settings_repo, self._audit)
        self.tasks = TasksService(TasksRepository(conn), self._audit)


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "slice21e.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


@pytest.fixture()
def clients(container):
    c1 = container.clients.create_client(CreateClientInput(client_code="T21E1", client_name="客戶一"))
    c2 = container.clients.create_client(CreateClientInput(client_code="T21E2", client_name="客戶二"))
    return c1, c2


def _select_row(page: TasksPage, row: int) -> None:
    idx = page._table.model().index(row, 0)
    page._table.selectionModel().select(
        idx,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )


def test_tasks_page_has_slice21e_buttons(qapp, container):
    page = TasksPage(container)
    assert page._bulk_new_btn.text() == "批量新增"
    assert page._bulk_edit_btn.text() == "批量編輯"
    assert page._bulk_delete_btn.text() == "批量刪除"
    assert page._make_child_btn.text() == "設為子待辦"


def test_multi_selection_enables_bulk_buttons(qapp, container, clients):
    c1, _ = clients
    for i in range(2):
        container.tasks.create_task(CreateTaskInput(
            engagement_id=None, client_id=c1.id, title=f"T{i}",
        ))
    page = TasksPage(container)
    page._refresh()
    _select_row(page, 0)
    _select_row(page, 1)
    page._on_selection_changed()
    assert page._bulk_edit_btn.isEnabled()
    assert page._bulk_delete_btn.isEnabled()
    assert not page._complete_btn.isEnabled()
    assert not page._make_child_btn.isEnabled()


def test_bulk_create_button_writes_db_and_audit(qapp, monkeypatch, container, clients):
    c1, c2 = clients

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

        def exec(self):
            return self.DialogCode.Accepted

        def selected_client_ids(self):
            return [c1.id, c2.id]

        def template(self):
            return BulkTaskTemplate(title="批量 UI")

    monkeypatch.setattr("taxops.ui.pages.tasks_page.BulkCreateTasksDialog", _Dialog)
    page = TasksPage(container)
    page._on_bulk_new_tasks()
    assert page._table.rowCount() == 2
    logs = container.audit_repo.list_recent(limit=20)
    assert any(log.action == "task.bulk_create" for log in logs)


def test_bulk_edit_button_updates_selected_tasks(qapp, monkeypatch, container, clients):
    c1, _ = clients
    for i in range(2):
        container.tasks.create_task(CreateTaskInput(
            engagement_id=None, client_id=c1.id, title=f"T{i}", priority="low",
        ))

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

        def exec(self):
            return self.DialogCode.Accepted

        def fields(self):
            return {"priority": "high"}

    monkeypatch.setattr("taxops.ui.pages.tasks_page.BulkEditTasksDialog", _Dialog)
    page = TasksPage(container)
    page._refresh()
    _select_row(page, 0)
    _select_row(page, 1)
    page._on_bulk_edit_tasks()
    rows = container._conn.execute(
        "SELECT priority FROM workflow_tasks ORDER BY id"
    ).fetchall()
    assert [r["priority"] for r in rows] == ["high", "high"]


def test_bulk_delete_button_deletes_selected_tasks(qapp, monkeypatch, container, clients):
    c1, _ = clients
    for i in range(2):
        container.tasks.create_task(CreateTaskInput(
            engagement_id=None, client_id=c1.id, title=f"T{i}",
        ))
    monkeypatch.setattr(
        "taxops.ui.pages.tasks_page.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    page = TasksPage(container)
    page._refresh()
    _select_row(page, 0)
    _select_row(page, 1)
    page._on_bulk_delete_tasks()
    assert page._table.rowCount() == 0


def test_make_child_button_uses_parent_dialog_and_indents_child(qapp, monkeypatch, container, clients):
    c1, _ = clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="父",
    ))
    child = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="子",
    ))

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

        def exec(self):
            return self.DialogCode.Accepted

        def selected_parent_id(self):
            return parent.id

    monkeypatch.setattr("taxops.ui.pages.tasks_page.ParentTaskDialog", _Dialog)
    page = TasksPage(container)
    page._refresh()
    child_row = 1 if page._table.item(1, 0).text() == str(child.id) else 0
    page._table.selectRow(child_row)
    page._on_make_child_task()
    assert container.tasks.get_task(child.id).parent_task_id == parent.id
    page._refresh()
    titles = [page._table.item(r, 1).text() for r in range(page._table.rowCount())]
    assert any(t.startswith("　└ ") for t in titles)


def test_task_action_registry_includes_slice21e_contracts():
    labels = {c.button_label: c for c in actions_for_page(PAGE_TASKS)}
    assert labels["批量新增"].service == "TasksService.create_tasks_bulk"
    assert labels["批量編輯"].audit_action == "task.bulk_update"
    assert labels["批量刪除"].service == "TasksService.delete_tasks_bulk"
    assert labels["設為子待辦"].repository == "TasksRepository.update_parent"
