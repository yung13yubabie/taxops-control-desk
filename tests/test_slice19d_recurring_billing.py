"""Slice 19D: Recurring billing always-visible new plan entry point."""

from __future__ import annotations

import pytest
from unittest.mock import patch


@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_has_always_visible_new_plan_btn(container):
    """A '新增方案' button must exist in the filter row and always be visible."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    assert hasattr(page, "_add_plan_btn"), "page must have _add_plan_btn"
    assert not page._add_plan_btn.isHidden(), "_add_plan_btn must be visible"


@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_add_plan_btn_visible_when_no_plans(container):
    """Button is visible even when there are zero plans."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    page._rebuild_accordion()
    assert not page._add_plan_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_add_plan_btn_visible_with_plans(container):
    """Button remains visible when plans exist."""
    from taxops.services.recurring_billing import CreatePlanInput
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    client = container.clients.create_client(
        CreateClientInput(client_code="RB001", client_name="固定客戶")
    )
    container.recurring_billing.create_plan(CreatePlanInput(
        client_id=client.id,
        plan_name="月費",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=1,
    ))
    page = RecurringBillingPage(container)
    page._refresh()
    assert not page._add_plan_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_add_plan_btn_all_clients_is_disabled(container):
    """When '全部客戶' is selected, the 新增方案 button must be disabled."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage, _ALL_CLIENTS

    page = RecurringBillingPage(container)
    page._refresh()  # populate combo (normally triggered by showEvent)
    assert page._client_combo.currentData() == _ALL_CLIENTS
    assert not page._add_plan_btn.isEnabled(), "Button must be disabled in '全部客戶' mode"


@pytest.mark.usefixtures("qapp")
def test_add_plan_btn_specific_client_opens_plan_dialog(container):
    """When a specific client is selected, clicking 新增方案 opens PlanDialog."""
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    from PySide6.QtWidgets import QDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RB002", client_name="特定客戶")
    )
    page = RecurringBillingPage(container)
    page._refresh()  # populate combo (normally triggered by showEvent)
    idx = page._client_combo.findData(client.id)
    assert idx >= 1, "Client must appear in combo after 全部客戶"
    page._client_combo.setCurrentIndex(idx)
    assert page._client_combo.currentData() == client.id

    with patch.object(PlanDialog, "__init__", return_value=None), \
         patch.object(PlanDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        page._on_add_plan_global()
        PlanDialog.exec.assert_called_once()


@pytest.mark.usefixtures("qapp")
def test_bulk_paste_dialog_can_pull_from_clipboard(container):
    from PySide6.QtWidgets import QApplication
    from taxops.ui.dialogs.recurring_billing_dialogs import _BulkPasteDialog

    QApplication.clipboard().setText("台積電\t120000\tvat\t月度顧問費")
    dlg = _BulkPasteDialog()
    dlg._paste_clipboard()

    assert dlg.text() == "台積電\t120000\tvat\t月度顧問費"


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_line_table_keeps_amount_and_tax_columns_visible(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RB003", client_name="欄寬客戶")
    )
    dlg = PlanDialog(container.recurring_billing, client.id)

    assert dlg._lines_table is not None
    assert dlg.minimumWidth() >= 760
    assert dlg._lines_table.columnWidth(1) >= 120
    assert dlg._lines_table.columnWidth(2) >= 110


@pytest.mark.usefixtures("qapp")
def test_line_dialog_single_entry_fields_have_stable_width(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import CreatePlanInput
    from taxops.ui.dialogs.recurring_billing_dialogs import LineDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RB004", client_name="單筆客戶")
    )
    plan = container.recurring_billing.create_plan(CreatePlanInput(
        client_id=client.id,
        plan_name="月費",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=1,
    ))
    dlg = LineDialog(container.recurring_billing, plan.id)

    assert dlg.minimumWidth() >= 560
    assert dlg._bill_to.minimumWidth() >= 320
    assert dlg._amount.minimumWidth() >= 180


@pytest.mark.usefixtures("qapp")
def test_auto_generation_failure_shows_warning_and_writes_system_log(container):
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import (
        CreatePlanInput,
        RecurringBillingError,
    )
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    client = container.clients.create_client(
        CreateClientInput(client_code="RB005", client_name="產生失敗客戶")
    )
    container.recurring_billing.create_plan(CreatePlanInput(
        client_id=client.id,
        plan_name="壞資料方案",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=1,
    ))
    page = RecurringBillingPage(container)

    with patch.object(
        container.recurring_billing,
        "generate_occurrences",
        side_effect=RecurringBillingError("recurring_billing.frequency.invalid"),
    ), patch.object(QMessageBox, "warning") as warning:
        succeeded = page._generate_for_client(client.id)

    assert succeeded is False
    warning.assert_called_once()
    log = container.conn.execute(
        """
        SELECT level, message
          FROM system_logs
         WHERE message = 'recurring billing auto-generation failed'
         ORDER BY id DESC
         LIMIT 1
        """
    ).fetchone()
    assert log is not None
    assert log["level"] == "ERROR"
