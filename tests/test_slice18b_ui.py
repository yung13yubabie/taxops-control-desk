"""Slice 18B smoke tests: recurring billing UI page wiring."""

from __future__ import annotations

import pytest

from taxops.ui.action_registry import (
    ACTION_REGISTRY,
    NAV_ORDER,
    PAGE_RECURRING_BILLING,
    actions_for_page,
)
from taxops.i18n.labels import NAV_LABELS


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def seed_client_id(container):
    from taxops.services.clients import CreateClientInput
    client = container.clients.create_client(CreateClientInput(
        client_code="C001", client_name="測試客戶",
    ))
    return client.id


# ── nav / registry ────────────────────────────────────────────────────────────

def test_recurring_billing_in_nav_order():
    assert PAGE_RECURRING_BILLING in NAV_ORDER


def test_recurring_billing_nav_label():
    assert NAV_LABELS.get(PAGE_RECURRING_BILLING) == "固定開立"


def test_recurring_billing_nav_order_before_settings():
    order = list(NAV_ORDER)
    assert order.index(PAGE_RECURRING_BILLING) < order.index("settings")


def test_recurring_billing_action_contracts_registered():
    actions = actions_for_page(PAGE_RECURRING_BILLING)
    labels = {a.button_label for a in actions}
    assert "新增方案" in labels
    assert "編輯方案" in labels
    assert "新增明細" in labels
    assert "封存" in labels
    assert "確認開立" in labels
    assert "確定跳過" in labels


def test_recurring_billing_all_actions_enabled():
    for a in actions_for_page(PAGE_RECURRING_BILLING):
        assert a.enabled, f"{a.button_label!r} should be enabled"


# ── page instantiation ───────────────────────────────────────────────────────

@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_instantiates(container):
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    assert page is not None


@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_empty_state(container):
    """Page renders without error when no plans exist."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage

    page = RecurringBillingPage(container)
    page._rebuild_accordion()


@pytest.mark.usefixtures("qapp")
def test_recurring_billing_page_with_plan(container, seed_client_id):
    """Page renders client group when a plan exists."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage, _ClientGroup
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="月度服務費",
        start_date="2026-01-01",
        frequency="monthly",
        issue_day=1,
    ))
    rb.create_line(CreateLineInput(
        plan_id=plan.id,
        bill_to_name="測試公司",
        amount=100000,
    ))

    page = RecurringBillingPage(container)
    page._refresh()

    groups = [
        page._content_layout.itemAt(i).widget()
        for i in range(page._content_layout.count())
        if isinstance(page._content_layout.itemAt(i).widget(), _ClientGroup)
    ]
    assert len(groups) >= 1


# ── dialog instantiation ─────────────────────────────────────────────────────

@pytest.mark.usefixtures("qapp")
def test_plan_dialog_new_mode(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog

    dlg = PlanDialog(container.recurring_billing, client_id=seed_client_id)
    assert dlg.windowTitle() == "新增方案"
    dlg.reject()


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_edit_mode(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog
    from taxops.services.recurring_billing import CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="季度顧問費",
        start_date="2026-01-01",
        frequency="quarterly",
        issue_day=15,
    ))
    dlg = PlanDialog(container.recurring_billing, client_id=seed_client_id, plan=plan)
    assert dlg.windowTitle() == "編輯方案"
    assert dlg._name.text() == "季度顧問費"
    dlg.reject()


@pytest.mark.usefixtures("qapp")
def test_line_dialog_instantiates(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import LineDialog
    from taxops.services.recurring_billing import CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="測試方案",
        start_date="2026-01-01",
    ))
    dlg = LineDialog(container.recurring_billing, plan_id=plan.id)
    assert dlg.windowTitle() == "新增明細"
    dlg.reject()


@pytest.mark.usefixtures("qapp")
def test_confirm_dialog_prefills_amount(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import ConfirmOccurrenceDialog
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="確認測試",
        start_date="2026-01-01",
    ))
    line = rb.create_line(CreateLineInput(
        plan_id=plan.id,
        bill_to_name="公司A",
        amount=50000,
    ))
    rb.generate_occurrences(plan.id)
    occs = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(occs) > 0

    dlg = ConfirmOccurrenceDialog(rb, occs[0], line)
    assert dlg._amount.text() == "50000"
    assert dlg._issue_date.value() == occs[0].expected_issue_date
    dlg.reject()


@pytest.mark.usefixtures("qapp")
def test_skip_dialog_instantiates(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import SkipOccurrenceDialog
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="跳過測試",
        start_date="2026-01-01",
    ))
    line = rb.create_line(CreateLineInput(
        plan_id=plan.id,
        bill_to_name="公司B",
        amount=30000,
    ))
    rb.generate_occurrences(plan.id)
    occs = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(occs) > 0

    dlg = SkipOccurrenceDialog(rb, occs[0], line)
    assert dlg is not None
    dlg.reject()


# ── custom_months freq toggle ─────────────────────────────────────────────────

@pytest.mark.usefixtures("qapp")
def test_plan_dialog_months_widget_hidden_by_default(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog

    dlg = PlanDialog(container.recurring_billing, client_id=seed_client_id)
    assert dlg._months_widget.isHidden()
    dlg.reject()


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_months_widget_shown_for_custom(container, seed_client_id):
    from taxops.ui.dialogs.recurring_billing_dialogs import PlanDialog

    dlg = PlanDialog(container.recurring_billing, client_id=seed_client_id)
    idx = dlg._freq.findData("custom_months")
    dlg._freq.setCurrentIndex(idx)
    assert not dlg._months_widget.isHidden()
    dlg.reject()


# ── regression: _refresh() must not write DB ─────────────────────────────────

@pytest.mark.usefixtures("qapp")
def test_refresh_does_not_generate_occurrences(container, seed_client_id):
    """_refresh() is read-only; occurrence count must not change."""
    from taxops.ui.pages.recurring_billing_page import RecurringBillingPage
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="讀取測試方案",
        start_date="2026-01-01",
    ))
    rb.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="甲公司", amount=10000))

    before = len(rb.list_occurrences(plan_id=plan.id))

    page = RecurringBillingPage(container)
    page._refresh()
    page._refresh()

    after = len(rb.list_occurrences(plan_id=plan.id))
    assert after == before, (
        f"_refresh() wrote {after - before} occurrence(s) — it must be read-only"
    )


# ── regression: skip reason validation ───────────────────────────────────────

def test_skip_empty_reason_raises(container, seed_client_id):
    """skip_occurrence with empty reason must raise, not write to DB."""
    from taxops.services.recurring_billing import (
        CreateLineInput, CreatePlanInput, RecurringBillingError,
    )

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="跳過原因測試",
        start_date="2026-01-01",
    ))
    rb.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="乙公司", amount=5000))
    rb.generate_occurrences(plan.id)
    occs = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(occs) > 0

    with pytest.raises(RecurringBillingError) as exc_info:
        rb.skip_occurrence(occs[0].id, "")
    assert exc_info.value.code == "recurring_billing.skip_reason.empty"

    still_pending = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(still_pending) == len(occs), "Occurrence must not be written on empty reason"


def test_skip_valid_reason_writes_db_and_audit(container, seed_client_id):
    """skip_occurrence with valid reason persists the record."""
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="跳過成功測試",
        start_date="2026-01-01",
    ))
    rb.create_line(CreateLineInput(plan_id=plan.id, bill_to_name="丙公司", amount=8000))
    rb.generate_occurrences(plan.id)
    occs = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(occs) > 0

    rb.skip_occurrence(occs[0].id, "客戶要求暫停")

    skipped = rb.list_occurrences(plan_id=plan.id, status="skipped")
    assert len(skipped) == 1


# ── regression: custom_months empty validation ────────────────────────────────

def test_service_rejects_custom_months_with_empty_list(container, seed_client_id):
    """create_plan with custom_months frequency and empty months_json must raise."""
    from taxops.services.recurring_billing import CreatePlanInput, RecurringBillingError

    rb = container.recurring_billing
    with pytest.raises(RecurringBillingError) as exc_info:
        rb.create_plan(CreatePlanInput(
            client_id=seed_client_id,
            plan_name="空月份方案",
            start_date="2026-01-01",
            frequency="custom_months",
            months_json="[]",
        ))
    assert exc_info.value.code == "recurring_billing.months_json.empty"


# ── regression: handler strings resolve to callables ─────────────────────────

def test_recurring_billing_handler_strings_resolve():
    """Every enabled recurring_billing action handler must be a callable on the module."""
    import importlib
    import taxops.ui.pages.recurring_billing_page as rb_page

    for action in actions_for_page(PAGE_RECURRING_BILLING):
        if not action.enabled:
            continue
        handler = action.handler
        parts = handler.split(".")
        obj = rb_page
        for part in parts:
            obj = getattr(obj, part, None)
            assert obj is not None, (
                f"Handler {handler!r} failed to resolve at {part!r}"
            )
        assert callable(obj), f"Handler {handler!r} resolved but is not callable"


# ── regression: HTML escaping in ConfirmOccurrenceDialog ─────────────────────

@pytest.mark.usefixtures("qapp")
def test_confirm_dialog_html_escapes_bill_to_name(container, seed_client_id):
    """Malicious bill_to_name must appear as plain text, not rendered HTML."""
    from taxops.ui.dialogs.recurring_billing_dialogs import ConfirmOccurrenceDialog
    from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput

    rb = container.recurring_billing
    plan = rb.create_plan(CreatePlanInput(
        client_id=seed_client_id,
        plan_name="HTML 注入測試",
        start_date="2026-01-01",
    ))
    malicious_name = '<img src=x onerror=alert(1)>'
    line = rb.create_line(CreateLineInput(
        plan_id=plan.id,
        bill_to_name=malicious_name,
        amount=1000,
    ))
    rb.generate_occurrences(plan.id)
    occs = rb.list_occurrences(plan_id=plan.id, status="pending")
    assert len(occs) > 0

    dlg = ConfirmOccurrenceDialog(rb, occs[0], line)
    # The header label is the first widget in the outer VBoxLayout.
    header_label = dlg.layout().itemAt(0).widget()
    label_text = header_label.text()
    assert "<img" not in label_text, "Raw HTML tag must not appear in label text"
    assert "&lt;img" in label_text, "bill_to_name must be HTML-escaped in the dialog header"
    dlg.reject()
