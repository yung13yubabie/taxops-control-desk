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
    from PySide6.QtWidgets import QApplication
    from taxops.services.clients import CreateClientInput
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RB003", client_name="欄寬客戶")
    )
    dlg = PlanDialog(container.recurring_billing, client.id)
    dlg.resize(680, 500)
    dlg.show()
    QApplication.processEvents()

    assert dlg._lines_table is not None
    assert dlg.minimumWidth() <= 680
    assert dlg._lines_table.isVisible()
    assert dlg._scroll.horizontalScrollBar().maximum() == 0
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
@pytest.mark.usefixtures("qapp")
def test_page_renders_real_plan_line_and_occurrence_rows(container):
    import datetime

    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput
    from taxops.ui.pages.recurring_billing_page import (
        RecurringBillingPage,
        _ClientGroup,
        _LineRow,
        _OccRow,
        _PlanSection,
    )

    client = container.clients.create_client(
        CreateClientInput(client_code="RB-RENDER", client_name="Render client")
    )
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="Monthly plan",
            start_date="2026-07-01",
            frequency="monthly",
            issue_day=11,
        )
    )
    container.recurring_billing.create_line(
        CreateLineInput(
            plan_id=plan.id,
            bill_to_name="Billing recipient",
            amount=123456,
            tax_type="vat",
            description="Chinese-facing invoice flow",
        )
    )
    container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 9, 11)
    )

    page = RecurringBillingPage(container)
    page._refresh()

    groups = page.findChildren(_ClientGroup)
    sections = page.findChildren(_PlanSection)
    assert len(groups) == 1
    assert len(sections) == 1
    assert len(page.findChildren(_LineRow)) == 1
    assert len(page.findChildren(_OccRow)) >= 1
    assert groups[0]._expanded
    assert sections[0]._expanded

    sections[0]._toggle_btn.click()
    groups[0]._toggle_btn.click()
    assert not sections[0]._expanded
    assert not groups[0]._expanded


@pytest.mark.usefixtures("qapp")
def test_occurrence_rows_render_confirmed_and_skipped_states(container):
    import datetime

    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import (
        ConfirmOccurrenceInput,
        CreateLineInput,
        CreatePlanInput,
    )
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage, _OccRow

    client = container.clients.create_client(
        CreateClientInput(client_code="RB-STATUS", client_name="Status client")
    )
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="Status plan",
            start_date="2026-07-01",
            frequency="monthly",
            issue_day=1,
        )
    )
    container.recurring_billing.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="Recipient", amount=5000)
    )
    occurrences = container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 8, 1)
    )
    container.recurring_billing.confirm_occurrence(
        occurrences[0].id,
        ConfirmOccurrenceInput(
            confirmed_amount=5100,
            confirmed_invoice_no="AB12345678",
        ),
    )
    container.recurring_billing.skip_occurrence(
        occurrences[1].id, reason="Client postponed"
    )

    page = RecurringBillingPage(container)
    page._refresh()

    rows = page.findChildren(_OccRow)
    assert {row._occ.status for row in rows} == {"confirmed", "skipped"}


@pytest.mark.usefixtures("qapp")
def test_line_delete_button_click_deactivates_line(container, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage, _LineRow

    client = container.clients.create_client(
        CreateClientInput(client_code="RB-DELETE", client_name="Delete client")
    )
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="Delete plan",
            start_date="2026-07-01",
            frequency="monthly",
            issue_day=1,
        )
    )
    line = container.recurring_billing.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="Delete recipient", amount=5000)
    )
    monkeypatch.setattr(
        "taxops.ui.pages.recurring_billing_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = RecurringBillingPage(container)
    page._refresh()
    row = page.findChildren(_LineRow)[0]

    row._delete_btn.click()

    stored = container.conn.execute(
        "SELECT active FROM recurring_billing_lines WHERE id = ?", (line.id,)
    ).fetchone()
    assert stored is not None
    assert stored["active"] == 0


@pytest.mark.usefixtures("qapp")
def test_generate_button_creates_occurrences_and_reports_status(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    client = container.clients.create_client(
        CreateClientInput(client_code="RB-GEN", client_name="Generate client")
    )
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="Generate plan",
            start_date="2026-07-01",
            frequency="monthly",
            issue_day=11,
        )
    )
    container.recurring_billing.create_line(
        CreateLineInput(plan_id=plan.id, bill_to_name="Recipient", amount=1000)
    )
    page = RecurringBillingPage(container)
    page._refresh()

    page._gen_btn.click()

    assert page._gen_btn.isEnabled()
    assert container.recurring_billing.list_occurrences(plan_id=plan.id)
    assert page._status_lbl.text().strip()


@pytest.mark.usefixtures("qapp")
def test_generate_button_list_failure_reenables_button_and_warns(
    container, monkeypatch
):
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    warnings = []
    monkeypatch.setattr(
        container.recurring_billing,
        "list_plans",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.recurring_billing_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._gen_btn.click()

    assert page._gen_btn.isEnabled()
    assert len(warnings) == 1


@pytest.mark.usefixtures("qapp")
def test_generate_for_client_handles_plan_listing_failure(container, monkeypatch):
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    warnings = []
    monkeypatch.setattr(
        container.recurring_billing,
        "list_plans",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.recurring_billing_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    assert page._generate_for_client(123) is False
    assert len(warnings) == 1


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
