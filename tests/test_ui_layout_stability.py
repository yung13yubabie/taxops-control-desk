"""Regression tests for empty-state layout height drift."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from taxops.services.clients import CreateClientInput
from taxops.services.tasks import CreateTaskInput
from taxops.ui.pages.attachments_page import AttachmentsPage
from taxops.ui.pages.clients_page import ClientsPage
from taxops.ui.pages.engagements_page import EngagementsPage
from taxops.ui.main_window import _initial_window_size, _minimum_window_size
from taxops.ui.pages.late_fee_page import LateFeePage
from taxops.ui.pages.settings_page import SettingsPage
from taxops.ui.style import APP_STYLESHEET
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
def test_flow_layout_can_be_destroyed_after_wrapped_children():
    root = QWidget()
    outer = QVBoxLayout(root)
    toolbar = QWidget()
    flow = FlowLayout(toolbar, h_spacing=6, v_spacing=6)
    for label in ("One", "Two", "Three", "Four"):
        flow.addWidget(QPushButton(label))
    outer.addWidget(toolbar)

    root.resize(120, 100)
    root.show()
    QApplication.processEvents()
    root.close()
    root.deleteLater()
    QApplication.processEvents()


def test_main_window_initial_size_tracks_available_geometry():
    from taxops.ui.main_window import _initial_window_size

    compact = _initial_window_size(QSize(1093, 614))
    large = _initial_window_size(QSize(1920, 1080))

    assert compact.width() <= 1093
    assert compact.height() <= 614
    assert large != compact
    assert large.width() <= 1280
    assert large.height() <= 720


@pytest.mark.usefixtures("qapp")
def test_main_window_can_resize_to_supported_compact_geometry(container):
    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    window.resize(1093, 614)

    assert window.minimumWidth() <= 1093
    assert window.minimumHeight() <= 614
    assert window.size() == QSize(1093, 614)


def test_global_stylesheet_has_visible_focus_and_title_tokens():
    for selector in (
        "QPushButton:focus",
        "QLineEdit:focus",
        "QComboBox:focus",
        "QTableWidget:focus",
        "QListWidget#MainNav:focus",
        "QLabel#PageTitle",
        "QLabel#SectionTitle",
    ):
        assert selector in APP_STYLESHEET


@pytest.mark.usefixtures("qapp")
def test_attachments_toolbar_wraps_at_compact_width(container):
    page = AttachmentsPage(container)
    page.resize(640, 614)
    page.show()
    QApplication.processEvents()

    assert isinstance(page._toolbar_layout, FlowLayout)
    assert page._toolbar_widget.height() > page._upload_btn.height()
    assert all(
        not _visible_child_overflows_page(button, page)
        for button in (
            page._upload_btn,
            page._accept_btn,
            page._reject_btn,
            page._delete_btn,
            page._info_btn,
            page._open_btn,
            page._location_btn,
        )
    )


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("height", [614, 720])
def test_late_fee_content_remains_reachable_without_collapsing_tables(
    container, height
):
    page = LateFeePage(container)
    page.resize(853, height)
    page.show()
    QApplication.processEvents()

    assert page._scroll.verticalScrollBar().maximum() > 0
    assert page._schedule_table.height() >= 140
    assert page._table.height() >= 140


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("width", [640, 800, 1040])
def test_settings_content_has_no_horizontal_overflow(container, width):
    page = SettingsPage(container)
    page.resize(width, 614)
    page.show()
    QApplication.processEvents()

    viewport_width = page._scroll.viewport().width()
    assert page._settings_body.width() <= viewport_width
    assert (
        page._scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )


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
def test_window_sizes_fit_1366x768_at_150_percent_dpi() -> None:
    logical_available = QSize(911, 512)

    assert _minimum_window_size(logical_available).height() <= 512
    assert _initial_window_size(logical_available).height() <= 512
