"""Regression tests for empty-state layout height drift."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from taxops.services.clients import CreateClientInput
from taxops.services.tasks import CreateTaskInput
from taxops.ui.pages.clients_page import ClientsPage
from taxops.ui.pages.engagements_page import EngagementsPage
from taxops.ui.pages.tasks_page import TasksPage
from taxops.ui.widgets.flow_layout import FlowLayout


def _show_and_process(widget) -> None:
    widget.resize(1366, 768)
    widget.show()
    QApplication.processEvents()


def _visible_child_overflows_page(child, page) -> bool:
    top_left = child.mapTo(page, child.rect().topLeft())
    bottom_right = child.mapTo(page, child.rect().bottomRight())
    return (
        top_left.x() < -2
        or top_left.y() < -2
        or bottom_right.x() > page.width() + 2
        or bottom_right.y() > page.height() + 2
    )


@pytest.mark.usefixtures("qapp")
def test_flow_layout_places_children_without_manual_activate():
    root = QWidget()
    outer = QVBoxLayout(root)
    toolbar = QWidget()
    flow = FlowLayout(toolbar, h_spacing=6, v_spacing=6)
    one = QPushButton("A")
    two = QPushButton("B")
    flow.addWidget(one)
    flow.addWidget(two)
    outer.addWidget(toolbar)

    root.resize(300, 100)
    root.show()
    QApplication.processEvents()

    assert one.geometry().width() < toolbar.width()
    assert two.geometry().x() > one.geometry().x()


@pytest.mark.usefixtures("qapp")
def test_engagements_toolbar_buttons_do_not_overflow_at_narrow_width(container):
    page = EngagementsPage(container)
    page.resize(640, 520)
    page.show()
    QApplication.processEvents()

    buttons = [
        page._new_btn,
        page._edit_btn,
        page._status_btn,
        page._delete_btn,
        page._open_btn,
        page._refresh_btn,
    ]
    assert all(not _visible_child_overflows_page(btn, page) for btn in buttons)


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
