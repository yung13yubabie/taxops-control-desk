"""Regression tests for stale UI state and unsafe date defaults."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from taxops.services.clients import CreateClientInput, UpdateClientInput
from taxops.services.container import ServiceContainer
from taxops.services.engagements import CreateEngagementInput


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_date_field_optional_defaults_to_none(qapp: QApplication) -> None:
    """Optional DateField initializes empty — value is None, not any sentinel date."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    assert field.value() is None
    assert field.raw_text() == ""


def test_date_field_invalid_input_does_not_silently_return_value(qapp: QApplication) -> None:
    """Invalid text: value() returns None; raw_text() preserves the bad input."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("not-a-date")
    assert field.value() is None
    assert field.raw_text() == "not-a-date"


def test_engagements_page_refresh_context_loads_newly_created_client(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from taxops.ui.pages.engagements_page import EngagementsPage

    page = EngagementsPage(container)
    # "全部客戶" sentinel is always present as index 0
    assert page._client_combo.count() == 1
    assert not page._new_btn.isEnabled()

    client = container.clients.create_client(
        CreateClientInput(client_code="SYNC001", client_name="同步測試客戶")
    )
    page.refresh_context()

    # After refresh: index 0 = "全部客戶", index 1 = newly created client
    assert page._client_combo.count() == 2
    from taxops.ui.pages.engagements_page import _ALL_CLIENTS
    assert page._client_combo.itemData(0) == _ALL_CLIENTS
    assert page._client_combo.itemData(1) == client.id
    # Select specific client to verify button enables
    page._client_combo.setCurrentIndex(1)
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


def test_clients_refresh_preserves_selection_by_client_id(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from taxops.ui.pages.clients_page import ClientsPage

    first = container.clients.create_client(
        CreateClientInput(client_code="SEL001", client_name="第一位客戶")
    )
    selected = container.clients.create_client(
        CreateClientInput(client_code="SEL002", client_name="保留選取客戶")
    )
    page = ClientsPage(container)
    page.on_refresh()
    for row in range(page._table.rowCount()):
        if int(page._table.item(row, 0).text()) == selected.id:
            page._table.selectRow(row)
            break

    container.clients.update_client(
        first.id,
        UpdateClientInput(client_code="ZZZ001", client_name="排序後客戶"),
    )
    page.on_refresh()

    assert page._selected_client_id() == selected.id


def test_engagements_refresh_preserves_selection_by_engagement_id(
    qapp: QApplication,
    container: ServiceContainer,
) -> None:
    from taxops.ui.pages.engagements_page import EngagementsPage

    client = container.clients.create_client(
        CreateClientInput(client_code="ENGSEL", client_name="案件選取客戶")
    )
    first = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="第一案件",
            tax_type="vat",
            period_name="2026",
        )
    )
    selected = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="保留選取案件",
            tax_type="vat",
            period_name="2026",
        )
    )
    page = EngagementsPage(container)
    page.refresh_context()
    for row in range(page._table.rowCount()):
        if int(page._table.item(row, 0).text()) == selected.id:
            page._table.selectRow(row)
            break

    container.engagements.delete_engagement(first.id)
    page._refresh_engagements()

    assert page._selected_engagement_id() == selected.id
    assert page._requests_page._engagement_id == selected.id


def test_main_window_refuses_close_while_settings_worker_is_active(
    qapp: QApplication,
    container: ServiceContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    monkeypatch.setattr(
        window._settings_page,
        "has_active_operation",
        lambda: True,
    )
    warnings = []
    monkeypatch.setattr(
        "taxops.ui.main_window.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert len(warnings) == 1


def test_main_window_refuses_close_while_gcis_worker_is_active(
    qapp: QApplication,
    container: ServiceContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    monkeypatch.setattr(
        window._registry_page,
        "has_active_operation",
        lambda: True,
    )
    warnings = []
    monkeypatch.setattr(
        "taxops.ui.main_window.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert len(warnings) == 1
