"""Public navigation contract for the annual workbench."""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QStackedWidget

from taxops.i18n import NAV_LABELS
from taxops.ui.action_registry import (
    NAV_ORDER,
    PAGE_ANNUAL_WORKBENCH,
    PAGE_CLIENTS,
    PAGE_ENGAGEMENTS,
    actions_for_page,
)
from taxops.ui.main_window import MainWindow
from taxops.ui.pages.annual_workbench_page import AnnualWorkbenchPage
from taxops.ui.style import apply as apply_style


def _nav_row(nav: QListWidget, label: str) -> int:
    for row in range(nav.count()):
        item = nav.item(row)
        if item is not None and item.text() == label:
            return row
    raise AssertionError(f"navigation item not found: {label}")


def test_annual_workbench_is_after_clients_and_before_engagements() -> None:
    assert NAV_LABELS[PAGE_ANNUAL_WORKBENCH] == "年度工作檯"
    annual_index = NAV_ORDER.index(PAGE_ANNUAL_WORKBENCH)
    assert NAV_ORDER[annual_index - 1] == PAGE_CLIENTS
    assert NAV_ORDER[annual_index + 1] == PAGE_ENGAGEMENTS


def test_sidebar_click_opens_real_annual_workbench(qtbot, container) -> None:
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()

    nav = window.findChild(QListWidget, "MainNav")
    stack = window.findChild(QStackedWidget)
    assert nav is not None
    assert stack is not None

    annual_row = _nav_row(nav, "年度工作檯")
    item_rect = nav.visualItemRect(nav.item(annual_row))
    qtbot.mouseClick(
        nav.viewport(),
        Qt.MouseButton.LeftButton,
        pos=item_rect.center(),
    )

    page = stack.currentWidget()
    assert isinstance(page, AnnualWorkbenchPage)
    assert page.title_label.text() == "年度工作檯"


def test_navigation_reuses_page_and_runs_refresh_clear_filter_contract(
    qtbot, container
) -> None:
    window = MainWindow(container)
    qtbot.addWidget(window)
    stack = window.findChild(QStackedWidget)
    assert stack is not None

    window.navigate_to(PAGE_ANNUAL_WORKBENCH, filter_key="overdue")
    page = stack.currentWidget()
    assert isinstance(page, AnnualWorkbenchPage)
    filter_notice = page.findChild(QLabel, "AnnualFilterNotice")
    assert filter_notice is not None
    assert filter_notice.isVisibleTo(page)
    assert "overdue" not in filter_notice.text()

    refresh_spy = Mock(wraps=page.refresh_context)
    page.refresh_context = refresh_spy
    window.navigate_to(PAGE_CLIENTS)
    window.navigate_to(PAGE_ANNUAL_WORKBENCH)

    assert stack.currentWidget() is page
    assert refresh_spy.call_count == 1
    assert not filter_notice.isVisibleTo(page)


def test_annual_workbench_exposes_enabled_create_action(
    qtbot, container
) -> None:
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    actions = actions_for_page(PAGE_ANNUAL_WORKBENCH)

    assert len(actions) == 1
    action = actions[0]
    assert action.button_label == "建立年度工作"
    assert action.enabled
    assert action.handler == "AnnualWorkbenchPage._open_create_dialog"
    assert page.future_action_button.text() == action.button_label
    assert page.future_action_button.isEnabled()


def test_annual_empty_state_text_stays_legible_without_compact_clipping(
    qtbot, qapp, container
) -> None:
    previous_stylesheet = qapp.styleSheet()
    try:
        apply_style(qapp)
        page = AnnualWorkbenchPage(container)
        qtbot.addWidget(page)
        page.resize(900, 540)
        page.show()
        QApplication.processEvents()

        empty_title = page.findChild(QLabel, "EmptyStateTitle")
        empty_body = page.findChild(QLabel, "EmptyStateBody")
        assert empty_title is not None
        assert empty_body is not None
        text_widgets = (
            empty_title,
            empty_body,
            page.future_action_button,
        )
        assert all(widget.font().pixelSize() >= 14 for widget in text_widgets)
        assert page.minimumSizeHint().width() <= 900
        assert page.minimumSizeHint().height() <= 540
        for widget in text_widgets:
            top_left = widget.mapTo(page, widget.rect().topLeft())
            bottom_right = widget.mapTo(page, widget.rect().bottomRight())
            assert page.rect().contains(top_left)
            assert page.rect().contains(bottom_right)
    finally:
        qapp.setStyleSheet(previous_stylesheet)
