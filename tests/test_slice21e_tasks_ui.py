"""Slice 21E: TasksPage parent/child + bulk UI wiring."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
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
    assert page._next_step_btn.text() == "新增下一步"
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
    assert not page._next_step_btn.isEnabled()
    assert not page._make_child_btn.isEnabled()


def test_single_selection_enables_next_step_and_shows_client(qapp, container, clients):
    c1, _ = clients
    container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=c1.id,
        title="整理資料",
        next_step="聯絡客戶",
    ))
    page = TasksPage(container)
    page._refresh()
    page._table.selectRow(0)
    assert page._next_step_btn.isEnabled()
    # The client name is now shown directly in the list (no detail panel).
    from taxops.ui.pages.tasks_page import _COLUMN_ORDER

    client_col = _COLUMN_ORDER.index("client_label")
    assert page._table.item(0, client_col).text() == "客戶一"


def test_refresh_after_sort_preserves_selection_by_task_id(
    qapp, container, clients
):
    c1, _ = clients
    target = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="Alpha",
    ))
    container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="Zulu",
    ))
    page = TasksPage(container)
    from taxops.ui.pages.tasks_page import _COLUMN_ORDER

    title_col = _COLUMN_ORDER.index("title")
    id_col = _COLUMN_ORDER.index("id")
    page._table.setSortingEnabled(True)
    page._table.sortItems(title_col, Qt.SortOrder.AscendingOrder)
    target_row = next(
        row for row in range(page._table.rowCount())
        if int(page._table.item(row, id_col).text()) == target.id
    )
    page._table.selectRow(target_row)

    container._conn.execute(
        "UPDATE workflow_tasks SET title = ? WHERE id = ?",
        ("Zzz", target.id),
    )
    container._conn.commit()
    page._refresh()

    assert page._selected_task_id() == target.id
    visible = {
        int(page._table.item(row, id_col).text()):
        page._table.item(row, title_col).text()
        for row in range(page._table.rowCount())
    }
    assert visible[target.id] == "Zzz"


def test_status_action_offers_only_legal_non_duplicate_transitions(
    qapp, monkeypatch, container, clients
):
    from taxops.i18n.status_labels import status_to_label

    c1, _ = clients
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="Status choices",
    ))
    captured_choices: list[str] = []

    def choose_doing(_parent, _title, _prompt, choices, **_kwargs):
        captured_choices.extend(choices)
        return status_to_label("doing"), True

    monkeypatch.setattr(
        "taxops.ui.pages.tasks_page.QInputDialog.getItem", choose_doing
    )
    page = TasksPage(container)
    row = next(
        row for row in range(page._table.rowCount())
        if int(page._table.item(row, 0).text()) == task.id
    )
    page._table.selectRow(row)

    page._on_set_status()

    assert set(captured_choices) == {
        status_to_label("doing"),
        status_to_label("waiting_client"),
        status_to_label("waiting_internal_review"),
        status_to_label("cancelled"),
    }
    assert container.tasks.get_task(task.id).status == "doing"


@pytest.mark.parametrize("terminal_status", ["done", "cancelled"])
def test_terminal_task_disables_invalid_status_operations(
    qapp, container, clients, terminal_status
):
    c1, _ = clients
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title=terminal_status,
    ))
    if terminal_status == "done":
        container.tasks.complete_task(task.id)
    else:
        container.tasks.set_status(task.id, terminal_status)
    page = TasksPage(container)
    row = next(
        row for row in range(page._table.rowCount())
        if int(page._table.item(row, 0).text()) == task.id
    )
    page._table.selectRow(row)

    assert not page._complete_btn.isEnabled()
    assert not page._status_btn.isEnabled()


def test_status_action_does_not_submit_current_status(
    qapp, monkeypatch, container, clients
):
    from taxops.i18n.status_labels import status_to_label

    c1, _ = clients
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="No duplicate",
    ))
    submissions: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.tasks_page.QInputDialog.getItem",
        lambda *_args, **_kwargs: (status_to_label("todo"), True),
    )
    monkeypatch.setattr(
        container.tasks,
        "set_status",
        lambda task_id, status: submissions.append((task_id, status)),
    )
    page = TasksPage(container)
    row = next(
        row for row in range(page._table.rowCount())
        if int(page._table.item(row, 0).text()) == task.id
    )
    page._table.selectRow(row)

    page._on_set_status()

    assert submissions == []


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


def test_bulk_create_real_dialog_widgets_reach_page_handler(
    qapp, monkeypatch, container, clients
):
    from taxops.ui.dialogs.task_bulk_dialogs import BulkCreateTasksDialog as RealDialog

    class _Dialog(RealDialog):
        def exec(self):
            self._clients.item(0).setCheckState(Qt.CheckState.Checked)
            self._title.setText("真實批量對話框")
            self._due_date.set_value("2026-06-30")
            self.accept()
            return self.result()

    monkeypatch.setattr("taxops.ui.pages.tasks_page.BulkCreateTasksDialog", _Dialog)
    page = TasksPage(container)
    page._on_bulk_new_tasks()

    rows = container._conn.execute(
        "SELECT client_id, title, due_date FROM workflow_tasks"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (clients[0].id, "真實批量對話框", "2026-06-30")
    ]


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


def test_bulk_edit_real_dialog_fields_survive_until_page_handler(
    qapp, monkeypatch, container, clients
):
    c1, _ = clients
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c1.id, title="Real dialog", priority="low",
    ))

    from taxops.ui.dialogs.task_bulk_dialogs import BulkEditTasksDialog as RealDialog

    class _Dialog(RealDialog):
        def exec(self):
            self._priority_enabled.setChecked(True)
            self._priority.setCurrentIndex(self._priority.findData("high"))
            return self.DialogCode.Accepted

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr("taxops.ui.pages.tasks_page.BulkEditTasksDialog", _Dialog)
    monkeypatch.setattr(
        "taxops.ui.pages.tasks_page.QMessageBox.warning",
        lambda _parent, title, body: warnings.append((title, body)),
    )
    page = TasksPage(container)
    page._refresh()
    page._table.selectRow(0)

    page._on_bulk_edit_tasks()

    row = container._conn.execute(
        "SELECT priority FROM workflow_tasks WHERE id = ?", (task.id,)
    ).fetchone()
    assert row["priority"] == "high"
    assert warnings == []


def test_bulk_edit_button_updates_real_dialog_field_set(qapp, monkeypatch, container, clients):
    c1, _ = clients
    for i in range(2):
        container.tasks.create_task(CreateTaskInput(
            engagement_id=None, client_id=c1.id, title=f"Full{i}", priority="low",
        ))

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

        def exec(self):
            return self.DialogCode.Accepted

        def fields(self):
            return {
                "status": "doing",
                "priority": "urgent",
                "assignee": "Alice",
                "due_date": "2026-06-20",
                "next_step": "電話確認",
                "notes": "批量備註",
            }

    monkeypatch.setattr("taxops.ui.pages.tasks_page.BulkEditTasksDialog", _Dialog)
    page = TasksPage(container)
    page._refresh()
    _select_row(page, 0)
    _select_row(page, 1)
    page._on_bulk_edit_tasks()

    rows = container._conn.execute(
        "SELECT status, priority, assignee, due_date, next_step, notes"
        " FROM workflow_tasks ORDER BY id"
    ).fetchall()
    assert [
        tuple(row)
        for row in rows
    ] == [
        ("doing", "urgent", "Alice", "2026-06-20", "電話確認", "批量備註"),
        ("doing", "urgent", "Alice", "2026-06-20", "電話確認", "批量備註"),
    ]


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
    from taxops.ui.pages.tasks_page import _COLUMN_ORDER

    title_col = _COLUMN_ORDER.index("title")
    titles = [page._table.item(r, title_col).text() for r in range(page._table.rowCount())]
    assert any(t.startswith("　└ ") for t in titles)


def test_make_child_real_parent_dialog_selection_reaches_page_handler(
    qapp, monkeypatch, container, clients
):
    from taxops.ui.dialogs.task_bulk_dialogs import ParentTaskDialog as RealDialog

    c1, _ = clients
    parent = container.tasks.create_task(
        CreateTaskInput(engagement_id=None, client_id=c1.id, title="真父待辦")
    )
    child = container.tasks.create_task(
        CreateTaskInput(engagement_id=None, client_id=c1.id, title="真子待辦")
    )

    class _Dialog(RealDialog):
        def exec(self):
            for row in range(self._list.count()):
                if self._list.item(row).data(Qt.ItemDataRole.UserRole) == parent.id:
                    self._list.setCurrentRow(row)
                    break
            self.accept()
            return self.result()

    monkeypatch.setattr("taxops.ui.pages.tasks_page.ParentTaskDialog", _Dialog)
    page = TasksPage(container)
    page._refresh()
    for row in range(page._table.rowCount()):
        if int(page._table.item(row, 0).text()) == child.id:
            page._table.selectRow(row)
            break
    page._on_make_child_task()

    assert container.tasks.get_task(child.id).parent_task_id == parent.id


def test_next_step_button_creates_context_inheriting_child(qapp, monkeypatch, container, clients):
    c1, _ = clients
    parent = container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=c1.id,
        title="父",
        assignee="Bob",
        priority="urgent",
        next_step="打電話確認",
    ))
    monkeypatch.setattr(
        "taxops.ui.pages.tasks_page.QInputDialog.getText",
        lambda *args, **kwargs: ("打電話確認", True),
    )
    page = TasksPage(container)
    page._refresh()
    page._table.selectRow(0)
    page._on_create_next_step_task()

    rows = container.tasks.list_by_client(c1.id)
    child = next(t for t in rows if t.id != parent.id)
    assert child.parent_task_id == parent.id
    assert child.client_id == parent.client_id
    assert child.engagement_id == parent.engagement_id
    assert child.assignee == parent.assignee
    assert child.priority == parent.priority


def test_task_action_registry_includes_slice21e_contracts():
    labels = {c.button_label: c for c in actions_for_page(PAGE_TASKS)}
    assert labels["批量新增"].service == "TasksService.create_tasks_bulk"
    assert labels["批量編輯"].audit_action == "task.bulk_update"
    assert labels["批量刪除"].service == "TasksService.delete_tasks_bulk"
    assert labels["設為子待辦"].repository == "TasksRepository.update_parent"
    assert labels["新增下一步"].service == "TasksService.create_child_task"
