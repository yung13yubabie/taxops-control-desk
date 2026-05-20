"""Regression tests for stale UI state and unsafe date defaults."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from taxops.services.clients import CreateClientInput
from taxops.services.container import ServiceContainer
from taxops.services.engagements import CreateEngagementInput


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_nullable_date_edit_defaults_to_sentinel_not_today(qapp: QApplication) -> None:
    """Fresh widget defaults to 'not set' sentinel to prevent silent data overwrites."""
    from taxops.ui.dialogs._shared import date_edit_value, make_nullable_date_edit

    widget = make_nullable_date_edit()

    assert widget.date() == widget.minimumDate()
    assert date_edit_value(widget) is None


def test_invalid_date_value_resets_to_sentinel_not_today(qapp: QApplication) -> None:
    """Invalid ISO date resets to sentinel (not set) rather than silently writing today."""
    from taxops.ui.dialogs._shared import date_edit_value, make_nullable_date_edit, set_date_edit_value

    widget = make_nullable_date_edit()

    set_date_edit_value(widget, "not-a-date")

    assert widget.date() == widget.minimumDate()
    assert date_edit_value(widget) is None


def test_engagements_page_refresh_context_loads_newly_created_client(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    assert page._client_combo.count() == 0
    assert not page._new_btn.isEnabled()

    client = container.clients.create_client(
        CreateClientInput(client_code="SYNC001", client_name="同步測試客戶")
    )
    page.refresh_context()

    assert page._client_combo.count() == 1
    assert page._client_combo.itemData(0) == client.id
    assert page._new_btn.isEnabled()


def test_tasks_page_refresh_context_loads_newly_created_engagement(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from taxops.ui.pages.tasks_page import TasksPage

    page = TasksPage(container)
    assert page._eng_combo.count() == 1

    client = container.clients.create_client(
        CreateClientInput(client_code="SYNC002", client_name="待辦同步客戶")
    )
    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="待辦同步案件",
            tax_type="vat",
            period_name="2026",
        )
    )
    page.refresh_context()

    combo_ids = [page._eng_combo.itemData(i) for i in range(page._eng_combo.count())]
    assert eng.id in combo_ids


def test_clients_page_purge_button_permanently_deletes_soft_deleted_client(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from unittest.mock import patch

    from PySide6.QtWidgets import QMessageBox
    from taxops.ui.pages.clients_page import ClientsPage

    client = container.clients.create_client(
        CreateClientInput(client_code="PURGEUI", client_name="UI 永久刪除")
    )
    container.clients.delete_client(client.id)

    page = ClientsPage(container)
    page._show_deleted_check.setChecked(True)
    page.on_refresh()
    page._table.selectRow(0)

    assert page._purge_btn.isEnabled()

    with patch(
        "taxops.ui.pages.clients_page.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        page.on_purge_client()

    raw = container.conn.execute(
        "SELECT id FROM clients WHERE id = ?", (client.id,)
    ).fetchone()
    assert raw is None
