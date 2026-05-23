"""Slice 19D: Recurring billing always-visible new plan entry point."""

from __future__ import annotations

import pytest


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
