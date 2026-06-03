"""Regression tests for empty-state layout height drift."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.services.clients import CreateClientInput
from taxops.services.tasks import CreateTaskInput
from taxops.ui.pages.clients_page import ClientsPage
from taxops.ui.pages.tasks_page import TasksPage


def _show_and_process(widget) -> None:
    widget.resize(1366, 768)
    widget.show()
    QApplication.processEvents()


@pytest.mark.usefixtures("qapp")
def test_clients_empty_state_keeps_header_rows_compact(container):
    page = ClientsPage(container)
    _show_and_process(page)

    assert page._empty_label.isVisible()
    assert not page._table.isVisible()
    assert page._count_label.height() <= 40
    assert page._page_label.height() <= 40

    container.clients.create_client(
        CreateClientInput(client_code="LAYOUT-C001", client_name="Layout Client")
    )
    page.refresh_context()
    QApplication.processEvents()

    assert not page._empty_label.isVisible()
    assert page._table.isVisible()
    assert page._count_label.height() <= 40
    assert page._page_label.height() <= 40


@pytest.mark.usefixtures("qapp")
def test_tasks_empty_state_hides_table_until_rows_exist(container):
    page = TasksPage(container)
    _show_and_process(page)

    assert page._empty_label.isVisible()
    assert not page._table.isVisible()

    client = container.clients.create_client(
        CreateClientInput(client_code="LAYOUT-C002", client_name="Task Client")
    )
    container.tasks.create_task(
        CreateTaskInput(
            engagement_id=None,
            client_id=client.id,
            title="Layout Task",
        )
    )
    page.refresh_context()
    QApplication.processEvents()

    assert not page._empty_label.isVisible()
    assert page._table.isVisible()


@pytest.mark.usefixtures("qapp")
def test_tasks_list_is_table_first_with_client_and_status(container):
    from taxops.ui.pages.tasks_page import _COLUMN_ORDER, _STATUS_COL_WIDTH

    client = container.clients.create_client(
        CreateClientInput(client_code="LAYOUT-C003", client_name="表格客戶")
    )
    container.tasks.create_task(
        CreateTaskInput(engagement_id=None, client_id=client.id, title="表格待辦")
    )
    page = TasksPage(container)
    _show_and_process(page)

    client_col = _COLUMN_ORDER.index("client_label")
    status_col = _COLUMN_ORDER.index("status")
    # client + status are always-visible core columns
    assert not page._table.isColumnHidden(client_col)
    assert not page._table.isColumnHidden(status_col)
    assert page._table.item(0, client_col).text() == "表格客戶"

    # table is no longer capped at 520/560, and the status column keeps its width
    assert page._table.maximumWidth() > 1000
    assert page._table.columnWidth(status_col) >= _STATUS_COL_WIDTH - 1
