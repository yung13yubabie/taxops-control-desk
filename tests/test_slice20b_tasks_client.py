"""Slice 20B regression tests: workflow_tasks.client_id + UI cascade.

Covers:
- Schema: workflow_tasks.client_id column + index
- Migration backfill: existing tasks with engagement_id get client_id filled
- Service: create_task with engagement auto-syncs client_id from engagement
- Service: create_task with client_id only (no engagement) supported
- Service: list_by_client returns engagement-bound + client-only tasks
- Service: client_not_found validation
- TasksPage: 客戶 combo + dependent 案件 combo cascade
- NewTaskDialog: 客戶 combo + dependent 案件 combo cascade
- refresh_context picks up newly created clients
"""

from __future__ import annotations

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def client_and_engagement(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    c = container.clients.create_client(CreateClientInput(
        client_code="CB01", client_name="客戶丙",
    ))
    e = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c.id, engagement_name="案件丙", tax_type="cit", period_name="2024",
    ))
    return c, e


@pytest.fixture()
def two_clients_with_engagements(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    c1 = container.clients.create_client(CreateClientInput(
        client_code="CB10", client_name="客戶甲",
    ))
    c2 = container.clients.create_client(CreateClientInput(
        client_code="CB20", client_name="客戶乙",
    ))
    e1 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c1.id, engagement_name="案件甲A", tax_type="cit", period_name="2024",
    ))
    e2 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c1.id, engagement_name="案件甲B", tax_type="vat", period_name="2024-Q1",
    ))
    e3 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c2.id, engagement_name="案件乙A", tax_type="cit", period_name="2024",
    ))
    return c1, c2, e1, e2, e3


# ── schema ────────────────────────────────────────────────────────────────


def test_workflow_tasks_has_client_id_column(db_conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in db_conn.execute("PRAGMA table_info(workflow_tasks)").fetchall()
    }
    assert "client_id" in cols


def test_workflow_tasks_has_client_id_index(db_conn: sqlite3.Connection) -> None:
    rows = db_conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'index' AND tbl_name = 'workflow_tasks'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert "idx_workflow_tasks_client" in names


def test_migration_backfill_fills_client_id_from_engagement(db_conn: sqlite3.Connection) -> None:
    """After 0017, a row with engagement_id but client_id=NULL gets backfilled.

    Simulates a pre-migration row by inserting with NULL client_id, then runs
    the migration's UPDATE statement (idempotent) and confirms backfill.
    """
    db_conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES ('BF01', '回填客戶', '2024-01-01', '2024-01-01')"
    )
    client_id = db_conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    db_conn.execute(
        "INSERT INTO engagements(client_id, engagement_name, tax_type, period_name,"
        " status, created_at, updated_at)"
        " VALUES (?, '回填案件', 'cit', '2024', 'draft', '2024-01-01', '2024-01-01')",
        (client_id,),
    )
    eng_id = db_conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    db_conn.execute(
        "INSERT INTO workflow_tasks(engagement_id, client_id, title, priority,"
        " status, created_at, updated_at)"
        " VALUES (?, NULL, '舊任務', 'normal', 'todo', '2024-01-01', '2024-01-01')",
        (eng_id,),
    )
    task_id = db_conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    db_conn.commit()
    # Re-run the migration's UPDATE statement (idempotent). The ALTER TABLE
    # portion already ran at fixture init and can't run twice.
    db_conn.executescript(
        """
        UPDATE workflow_tasks
           SET client_id = (
                   SELECT engagements.client_id
                     FROM engagements
                    WHERE engagements.id = workflow_tasks.engagement_id
               )
         WHERE engagement_id IS NOT NULL
           AND client_id IS NULL;
        """
    )
    row = db_conn.execute(
        "SELECT client_id FROM workflow_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    assert row["client_id"] == client_id


# ── service: create_task client_id derivation ─────────────────────────────


def test_create_task_with_engagement_auto_syncs_client_id(container, client_and_engagement):
    from taxops.services.tasks import CreateTaskInput
    c, e = client_and_engagement
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=e.id,
        title="同步 client_id",
    ))
    assert task.engagement_id == e.id
    assert task.client_id == c.id


def test_create_task_with_client_only_creates_unbound_task(container, client_and_engagement):
    """A task can have client_id without engagement_id (client-level task)."""
    from taxops.services.tasks import CreateTaskInput
    c, _ = client_and_engagement
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=c.id,
        title="客戶層級任務（無案件）",
    ))
    assert task.engagement_id is None
    assert task.client_id == c.id


def test_create_task_with_no_client_no_engagement_allowed(container):
    """A standalone task (no client, no engagement) remains supported."""
    from taxops.services.tasks import CreateTaskInput
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=None,
        title="完全獨立的任務",
    ))
    assert task.engagement_id is None
    assert task.client_id is None


def test_create_task_engagement_client_overrides_provided_client(container, two_clients_with_engagements):
    """If both engagement_id and client_id provided, engagement.client_id wins."""
    from taxops.services.tasks import CreateTaskInput
    c1, c2, e1, _, _ = two_clients_with_engagements
    task = container.tasks.create_task(CreateTaskInput(
        engagement_id=e1.id,
        client_id=c2.id,
        title="衝突情境",
    ))
    assert task.client_id == c1.id


def test_create_task_client_not_found_raises(container):
    from taxops.services.tasks import CreateTaskInput, TaskValidationError
    with pytest.raises(TaskValidationError) as ei:
        container.tasks.create_task(CreateTaskInput(
            engagement_id=None,
            client_id=9999,
            title="找不到客戶",
        ))
    assert ei.value.code == "task.client_not_found"


# ── service: list_by_client ───────────────────────────────────────────────


def test_list_by_client_returns_only_that_clients_tasks(container, two_clients_with_engagements):
    from taxops.services.tasks import CreateTaskInput
    c1, c2, e1, _, e3 = two_clients_with_engagements
    t1 = container.tasks.create_task(CreateTaskInput(engagement_id=e1.id, title="客戶1任務1"))
    t2 = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="客戶1任務2"))
    t3 = container.tasks.create_task(CreateTaskInput(engagement_id=e3.id, title="客戶2任務1"))
    c1_tasks = container.tasks.list_by_client(c1.id)
    c1_ids = {t.id for t in c1_tasks}
    assert t1.id in c1_ids
    assert t2.id in c1_ids
    assert t3.id not in c1_ids


def test_list_by_client_includes_engagement_bound_and_client_only_tasks(
    container, client_and_engagement
):
    from taxops.services.tasks import CreateTaskInput
    c, e = client_and_engagement
    t_bound = container.tasks.create_task(CreateTaskInput(
        engagement_id=e.id, title="綁案件",
    ))
    t_unbound = container.tasks.create_task(CreateTaskInput(
        engagement_id=None, client_id=c.id, title="只綁客戶",
    ))
    found = container.tasks.list_by_client(c.id)
    ids = {t.id for t in found}
    assert t_bound.id in ids
    assert t_unbound.id in ids


# ── TasksPage UI cascade ──────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_tasks_page_has_client_combo(container):
    from taxops.ui.pages.tasks_page import TasksPage
    page = TasksPage(container)
    assert hasattr(page, "_client_combo")


@pytest.mark.usefixtures("qapp")
def test_tasks_page_client_combo_first_item_is_all(container):
    from taxops.ui.pages.tasks_page import TasksPage, _ALL_CLIENTS
    page = TasksPage(container)
    assert page._client_combo.itemData(0) == _ALL_CLIENTS


@pytest.mark.usefixtures("qapp")
def test_tasks_page_client_combo_includes_all_clients(container, two_clients_with_engagements):
    from taxops.ui.pages.tasks_page import TasksPage
    c1, c2, *_ = two_clients_with_engagements
    page = TasksPage(container)
    page.refresh_context()
    ids = {page._client_combo.itemData(i) for i in range(page._client_combo.count())}
    assert c1.id in ids
    assert c2.id in ids


@pytest.mark.usefixtures("qapp")
def test_tasks_page_engagement_combo_filtered_by_selected_client(
    container, two_clients_with_engagements
):
    from taxops.ui.pages.tasks_page import TasksPage
    c1, c2, e1, e2, e3 = two_clients_with_engagements
    page = TasksPage(container)
    page.refresh_context()
    idx = page._client_combo.findData(c1.id)
    page._client_combo.setCurrentIndex(idx)
    eng_ids = {
        page._eng_combo.itemData(i)
        for i in range(page._eng_combo.count())
    }
    assert e1.id in eng_ids
    assert e2.id in eng_ids
    assert e3.id not in eng_ids


@pytest.mark.usefixtures("qapp")
def test_tasks_page_filter_by_client_shows_only_that_clients_tasks(
    container, two_clients_with_engagements
):
    from taxops.services.tasks import CreateTaskInput
    from taxops.ui.pages.tasks_page import TasksPage
    c1, c2, e1, _, e3 = two_clients_with_engagements
    t1 = container.tasks.create_task(CreateTaskInput(engagement_id=e1.id, title="客戶1任務"))
    t2 = container.tasks.create_task(CreateTaskInput(engagement_id=None, client_id=c1.id, title="客戶1獨立"))
    t3 = container.tasks.create_task(CreateTaskInput(engagement_id=e3.id, title="客戶2任務"))
    page = TasksPage(container)
    page.refresh_context()
    idx = page._client_combo.findData(c1.id)
    page._client_combo.setCurrentIndex(idx)
    visible_ids = {
        int(page._table.item(r, 0).text())
        for r in range(page._table.rowCount())
    }
    assert t1.id in visible_ids
    assert t2.id in visible_ids
    assert t3.id not in visible_ids


@pytest.mark.usefixtures("qapp")
def test_tasks_page_refresh_context_picks_up_new_client(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.tasks_page import TasksPage
    page = TasksPage(container)
    initial_count = page._client_combo.count()
    new_client = container.clients.create_client(CreateClientInput(
        client_code="NEW9", client_name="新客戶",
    ))
    page.refresh_context()
    new_count = page._client_combo.count()
    assert new_count == initial_count + 1
    ids = {page._client_combo.itemData(i) for i in range(new_count)}
    assert new_client.id in ids


# ── NewTaskDialog cascade ──────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_new_task_dialog_has_client_combo(container, client_and_engagement):
    from taxops.ui.dialogs.new_task_dialog import NewTaskDialog
    dlg = NewTaskDialog(
        container.tasks,
        parent=None,
        engagements_service=container.engagements,
        clients_service=container.clients,
    )
    assert hasattr(dlg, "_client_combo")


@pytest.mark.usefixtures("qapp")
def test_new_task_dialog_engagement_combo_filtered_by_client(
    container, two_clients_with_engagements
):
    from taxops.ui.dialogs.new_task_dialog import NewTaskDialog
    c1, c2, e1, e2, e3 = two_clients_with_engagements
    dlg = NewTaskDialog(
        container.tasks,
        parent=None,
        engagements_service=container.engagements,
        clients_service=container.clients,
    )
    idx = dlg._client_combo.findData(c1.id)
    dlg._client_combo.setCurrentIndex(idx)
    eng_ids = {
        dlg._eng_combo.itemData(i) for i in range(dlg._eng_combo.count())
    }
    assert e1.id in eng_ids
    assert e2.id in eng_ids
    assert e3.id not in eng_ids


@pytest.mark.usefixtures("qapp")
def test_new_task_dialog_save_with_client_only(container, client_and_engagement):
    """Picking a client + '不綁案件' creates a client-only task."""
    from taxops.ui.dialogs.new_task_dialog import (
        NewTaskDialog,
        _NO_ENGAGEMENT,
    )
    c, _ = client_and_engagement
    dlg = NewTaskDialog(
        container.tasks,
        parent=None,
        engagements_service=container.engagements,
        clients_service=container.clients,
    )
    idx = dlg._client_combo.findData(c.id)
    dlg._client_combo.setCurrentIndex(idx)
    assert dlg._eng_combo.itemData(0) == _NO_ENGAGEMENT
    dlg._eng_combo.setCurrentIndex(0)
    dlg._title.setText("只綁客戶的任務")
    dlg.on_save()
    tasks = container.tasks.list_by_client(c.id)
    assert any(t.title == "只綁客戶的任務" and t.engagement_id is None for t in tasks)


@pytest.mark.usefixtures("qapp")
def test_new_task_dialog_save_with_engagement_syncs_client(
    container, client_and_engagement
):
    """Picking an engagement implicitly sets the correct client_id."""
    from taxops.ui.dialogs.new_task_dialog import NewTaskDialog
    c, e = client_and_engagement
    dlg = NewTaskDialog(
        container.tasks,
        parent=None,
        engagements_service=container.engagements,
        clients_service=container.clients,
    )
    idx_c = dlg._client_combo.findData(c.id)
    dlg._client_combo.setCurrentIndex(idx_c)
    idx_e = dlg._eng_combo.findData(e.id)
    dlg._eng_combo.setCurrentIndex(idx_e)
    dlg._title.setText("綁案件的任務")
    dlg.on_save()
    found = [
        t for t in container.tasks.list_by_engagement(e.id)
        if t.title == "綁案件的任務"
    ]
    assert len(found) == 1
    assert found[0].client_id == c.id
