"""Real user-path coverage for the recurring-billing page.

The modal hooks below drive the real dialog widgets and click their real save
buttons.  They intentionally never replace a dialog with a service-writing
test double.
"""

from __future__ import annotations

import datetime

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton

from taxops.services.clients import CreateClientInput
from taxops.services.recurring_billing import (
    CreateLineInput,
    CreatePlanInput,
    RecurringBillingError,
)
from taxops.ui.dialogs.recurring_billing_dialogs import (
    ConfirmOccurrenceDialog,
    LineDialog,
    PlanDialog,
    SkipOccurrenceDialog,
)
from taxops.ui.pages.recurring_billing_page import (
    RecurringBillingPage,
    _ClientGroup,
    _LineRow,
    _OccRow,
    _PlanSection,
)


pytestmark = pytest.mark.usefixtures("qapp")


def _client(container, code: str = "RB-PAGE"):
    return container.clients.create_client(
        CreateClientInput(client_code=code, client_name="真實操作測試客戶")
    )


def _plan(container, client_id: int, name: str = "每月申報"):
    return container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client_id,
            plan_name=name,
            start_date="2026-07-01",
            frequency="monthly",
            issue_day=11,
        )
    )


def _line(container, plan_id: int, name: str = "財務部"):
    return container.recurring_billing.create_line(
        CreateLineInput(plan_id=plan_id, bill_to_name=name, amount=12_000)
    )


def _audit_actions(container) -> list[str]:
    return [
        row["action"]
        for row in container.conn.execute("SELECT action FROM audit_logs ORDER BY id")
    ]


def _fill_create_plan(dialog: PlanDialog, name: str) -> None:
    dialog._name.setText(name)
    dialog._start_date.set_value("2026-07-01")
    dialog._issue_day.setValue(15)
    dialog._add_line_btn.click()
    dialog._set_line_cell(0, "bill_to", "台北總公司")
    dialog._set_line_cell(0, "amount", "88000")
    dialog._set_line_cell(0, "tax_type", "vat")
    dialog._set_line_cell(0, "description", "中文帳務明細")
    dialog._save_btn.click()


def test_global_add_plan_button_drives_real_dialog_sqlite_and_audit(
    container, monkeypatch
):
    client = _client(container, "RB-GLOBAL")
    page = RecurringBillingPage(container)
    page._refresh()
    page._client_combo.setCurrentIndex(page._client_combo.findData(client.id))

    def interact(dialog: PlanDialog):
        _fill_create_plan(dialog, "全域按鈕方案")
        return dialog.result()

    monkeypatch.setattr(PlanDialog, "exec", interact)
    page._add_plan_btn.click()

    plans = container.recurring_billing.list_plans(client_id=client.id)
    assert [plan.plan_name for plan in plans] == ["全域按鈕方案"]
    lines = container.recurring_billing.list_lines(plans[0].id)
    assert [(line.bill_to_name, line.amount) for line in lines] == [
        ("台北總公司", 88_000)
    ]
    assert container.recurring_billing.list_occurrences(plan_id=plans[0].id)
    assert "recurring_billing.plan.create_with_lines" in _audit_actions(container)


def test_client_group_add_plan_button_drives_real_dialog_and_refreshes(
    container, monkeypatch
):
    client = _client(container, "RB-GROUP")
    original = _plan(container, client.id, "既有方案")
    _line(container, original.id)
    page = RecurringBillingPage(container)
    page._refresh()
    group = page.findChildren(_ClientGroup)[0]
    group.expand()

    def interact(dialog: PlanDialog):
        _fill_create_plan(dialog, "群組新增方案")
        return dialog.result()

    monkeypatch.setattr(PlanDialog, "exec", interact)
    group._new_plan_btn.click()

    assert {p.plan_name for p in container.recurring_billing.list_plans(client_id=client.id)} == {
        "既有方案",
        "群組新增方案",
    }
    assert any(
        section._plan.plan_name == "群組新增方案"
        for section in page.findChildren(_PlanSection)
    )


def test_plan_and_line_edit_buttons_drive_real_dialog_fields_and_audit(
    container, monkeypatch
):
    client = _client(container, "RB-EDIT")
    plan = _plan(container, client.id, "修改前方案")
    line = _line(container, plan.id, "修改前對象")
    page = RecurringBillingPage(container)
    page._refresh()
    section = page.findChildren(_PlanSection)[0]
    assert all(button.isVisibleTo(section) for button in section._action_btns)
    section.expand()

    def edit_plan(dialog: PlanDialog):
        assert dialog._plan.id == plan.id
        dialog._name.setText("修改後方案")
        dialog._start_date.set_value("2026-08-01")
        dialog._notes.setPlainText("由真實編輯按鈕保存")
        dialog._save_btn.click()
        return dialog.result()

    monkeypatch.setattr(PlanDialog, "exec", edit_plan)
    section._action_btns[0].click()
    updated_plan = container.recurring_billing.get_plan(plan.id)
    assert (updated_plan.plan_name, updated_plan.start_date) == (
        "修改後方案",
        "2026-08-01",
    )

    row = page.findChildren(_LineRow)[0]

    def edit_line(dialog: LineDialog):
        assert dialog._line.id == line.id
        dialog._bill_to.setText("修改後對象")
        dialog._amount.setText("34567")
        dialog._desc.setText("實際 UI 編輯")
        dialog._save_btn.click()
        return dialog.result()

    monkeypatch.setattr(LineDialog, "exec", edit_line)
    row._edit_btn.click()
    stored = container.recurring_billing.list_lines(plan.id)[0]
    assert (stored.bill_to_name, stored.amount, stored.description) == (
        "修改後對象",
        34_567,
        "實際 UI 編輯",
    )
    actions = _audit_actions(container)
    assert "recurring_billing.plan.update" in actions
    assert "recurring_billing.line.update" in actions


def test_add_line_button_drives_real_dialog_then_generates_occurrence(
    container, monkeypatch
):
    client = _client(container, "RB-ADD-LINE")
    plan = _plan(container, client.id)
    page = RecurringBillingPage(container)
    page._refresh()
    section = page.findChildren(_PlanSection)[0]
    section.expand()

    def add_line(dialog: LineDialog):
        assert dialog._line is None
        dialog._bill_to.setText("新增開立對象")
        dialog._amount.setText("9900")
        dialog._save_btn.click()
        return dialog.result()

    monkeypatch.setattr(LineDialog, "exec", add_line)
    section._action_btns[1].click()

    assert container.recurring_billing.list_lines(plan.id)[0].bill_to_name == "新增開立對象"
    assert container.recurring_billing.list_occurrences(plan_id=plan.id)
    assert "recurring_billing.line.create" in _audit_actions(container)


def test_pending_row_confirm_and_skip_buttons_use_real_dialogs_and_persist(
    container, monkeypatch
):
    client = _client(container, "RB-OCC")
    plan = _plan(container, client.id)
    _line(container, plan.id, "發票收件人")
    occurrences = container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 8, 11)
    )
    assert len(occurrences) == 2
    page = RecurringBillingPage(container)
    page._refresh()

    def confirm(dialog: ConfirmOccurrenceDialog):
        dialog._amount.setText("12500")
        dialog._invoice_no.setText("AB12345678")
        dialog._notes.setPlainText("已核對紙本發票")
        dialog._save_btn.click()
        return dialog.result()

    monkeypatch.setattr(ConfirmOccurrenceDialog, "exec", confirm)
    first = next(row for row in page.findChildren(_OccRow) if row._occ.id == occurrences[0].id)
    first.findChildren(QPushButton)[0].click()

    def skip(dialog: SkipOccurrenceDialog):
        dialog._reason.setPlainText("客戶本月暫停服務")
        dialog._skip_btn.click()
        return dialog.result()

    monkeypatch.setattr(SkipOccurrenceDialog, "exec", skip)
    second = next(row for row in page.findChildren(_OccRow) if row._occ.id == occurrences[1].id)
    second.findChildren(QPushButton)[1].click()

    rows = container.recurring_billing.list_occurrences(plan_id=plan.id)
    assert [(row.status, row.confirmed_amount, row.skipped_reason) for row in rows] == [
        ("confirmed", 12_500, None),
        ("skipped", None, "客戶本月暫停服務"),
    ]
    actions = _audit_actions(container)
    assert "recurring_billing.occurrence.confirm" in actions
    assert "recurring_billing.occurrence.skip" in actions


def test_page_shows_full_plan_history_back_to_start_date(container, monkeypatch):
    monkeypatch.setattr(
        "taxops.ui.pages.recurring_billing_page.project_today_iso",
        lambda: "2026-07-12",
    )
    client = _client(container, "RB-HISTORY")
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="全年固定開立",
            start_date="2026-01-01",
            frequency="monthly",
            issue_day=1,
        )
    )
    _line(container, plan.id)
    container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 12, 1)
    )

    page = RecurringBillingPage(container)
    page._refresh()

    visible_dates = {row._occ.expected_issue_date for row in page.findChildren(_OccRow)}
    assert "2026-01-01" in visible_dates
    assert "2026-08-01" in visible_dates
    assert "2026-12-01" in visible_dates


def test_confirmed_row_can_be_reopened_to_pending_then_plan_deleted(
    container, monkeypatch
):
    from taxops.services.recurring_billing import ConfirmOccurrenceInput

    client = _client(container, "RB-REOPEN")
    plan = _plan(container, client.id)
    _line(container, plan.id)
    occurrence = container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 7, 31)
    )[0]
    container.recurring_billing.confirm_occurrence(
        occurrence.id,
        ConfirmOccurrenceInput(
            confirmed_amount=12_500,
            confirmed_invoice_no="AB12345678",
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = RecurringBillingPage(container)
    page._refresh()
    confirmed_row = next(
        row for row in page.findChildren(_OccRow) if row._occ.id == occurrence.id
    )

    confirmed_row._reopen_btn.click()

    reopened = container.recurring_billing.list_occurrences(plan_id=plan.id)[0]
    assert reopened.status == "pending"
    assert reopened.confirmed_amount is None
    assert reopened.confirmed_invoice_no is None
    assert reopened.confirmed_at is None
    assert "recurring_billing.occurrence.reopen" in _audit_actions(container)

    container.recurring_billing.delete_plan(plan.id)
    assert container.recurring_billing.get_plan(plan.id) is None


def test_real_modal_cancel_paths_leave_database_unchanged(container, monkeypatch):
    client = _client(container, "RB-CANCEL")
    plan = _plan(container, client.id)
    line = _line(container, plan.id)
    occurrence = container.recurring_billing.generate_occurrences(plan.id)[0]
    page = RecurringBillingPage(container)
    page._refresh()

    monkeypatch.setattr(QDialog, "exec", lambda dialog: (dialog.reject(), dialog.result())[1])
    section = page.findChildren(_PlanSection)[0]
    section.expand()
    section._action_btns[0].click()
    section._action_btns[1].click()
    row = page.findChildren(_LineRow)[0]
    row._edit_btn.click()
    occ_row = next(r for r in page.findChildren(_OccRow) if r._occ.id == occurrence.id)
    for button in occ_row.findChildren(QPushButton):
        button.click()

    assert container.recurring_billing.get_plan(plan.id).plan_name == "每月申報"
    assert [(r.id, r.bill_to_name) for r in container.recurring_billing.list_lines(plan.id)] == [
        (line.id, "財務部")
    ]
    assert container.recurring_billing.list_occurrences(plan_id=plan.id)[0].status == "pending"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (RecurringBillingError("recurring_billing.line.not_found"), "recurring_billing.line.not_found"),
        (RuntimeError("disk I/O failure"), "system.unexpected"),
    ],
)
def test_line_delete_failure_keeps_row_and_shows_error(
    container, monkeypatch, failure, expected_code
):
    client = _client(container, f"RB-DEL-{expected_code[-3:]}")
    plan = _plan(container, client.id)
    line = _line(container, plan.id)
    page = RecurringBillingPage(container)
    page._refresh()
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_kw: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(container.recurring_billing, "deactivate_line", lambda _id: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, body: warnings.append((title, body)))

    page.findChildren(_LineRow)[0]._delete_btn.click()

    assert container.recurring_billing.list_lines(plan.id)[0].id == line.id
    assert warnings and warnings[0][1]


def test_plan_delete_cancel_domain_unexpected_and_success_are_distinct(
    container, monkeypatch
):
    client = _client(container, "RB-ARCHIVE")
    plan = _plan(container, client.id)
    _line(container, plan.id)
    container.recurring_billing.generate_occurrences(plan.id)
    page = RecurringBillingPage(container)
    page._refresh()
    section = page.findChildren(_PlanSection)[0]
    section.expand()

    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.No)
    section._action_btns[2].click()
    assert container.recurring_billing.get_plan(plan.id).status == "active"

    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, body: warnings.append((title, body)))
    original = container.recurring_billing.delete_plan
    monkeypatch.setattr(
        container.recurring_billing,
        "delete_plan",
        lambda _id: (_ for _ in ()).throw(RecurringBillingError("recurring_billing.plan.not_found")),
    )
    section._action_btns[2].click()
    monkeypatch.setattr(
        container.recurring_billing,
        "delete_plan",
        lambda _id: (_ for _ in ()).throw(RuntimeError("database locked")),
    )
    section._action_btns[2].click()
    assert len(warnings) == 2
    assert container.recurring_billing.get_plan(plan.id).status == "active"

    monkeypatch.setattr(container.recurring_billing, "delete_plan", original)
    section._action_btns[2].click()
    stored = container.conn.execute(
        "SELECT 1 FROM recurring_billing_plans WHERE id = ?", (plan.id,)
    ).fetchone()
    assert stored is None
    assert "recurring_billing.plan.delete" in _audit_actions(container)


def test_generate_button_partial_domain_and_unexpected_results_are_visible(
    container, monkeypatch
):
    client = _client(container, "RB-PARTIAL")
    ok_plan = _plan(container, client.id, "成功方案")
    domain_plan = _plan(container, client.id, "規則錯誤方案")
    crash_plan = _plan(container, client.id, "非預期錯誤方案")
    for plan in (ok_plan, domain_plan, crash_plan):
        _line(container, plan.id, f"{plan.plan_name}收件人")
    page = RecurringBillingPage(container)
    page._refresh()
    warnings = []
    original = container.recurring_billing.generate_occurrences

    def generate(plan_id, *args, **kwargs):
        if plan_id == domain_plan.id:
            raise RecurringBillingError("recurring_billing.frequency.invalid")
        if plan_id == crash_plan.id:
            raise RuntimeError("database unavailable")
        return original(plan_id, *args, **kwargs)

    monkeypatch.setattr(container.recurring_billing, "generate_occurrences", generate)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, body: warnings.append((title, body)))
    page._gen_btn.click()

    assert page._gen_btn.isEnabled()
    assert container.recurring_billing.list_occurrences(plan_id=ok_plan.id)
    assert not container.recurring_billing.list_occurrences(plan_id=domain_plan.id)
    assert not container.recurring_billing.list_occurrences(plan_id=crash_plan.id)
    assert len(warnings) == 1
    assert "規則錯誤方案" in warnings[0][1]
    assert "非預期錯誤方案" in warnings[0][1]
    logs = container.conn.execute(
        "SELECT detail_json FROM system_logs WHERE message = 'recurring billing generation failed'"
    ).fetchall()
    assert len(logs) == 2


def test_page_recovery_paths_keep_controls_usable(container, monkeypatch):
    page = RecurringBillingPage(container)
    page._client_combo.addItem("暫存選項", userData=999)
    page._client_combo.setCurrentIndex(1)
    page._archived_check.setChecked(True)
    page.clear_filter()
    assert page._client_combo.currentIndex() == 0
    assert not page._archived_check.isChecked()

    monkeypatch.setattr(
        container.clients,
        "list_clients",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("clients unavailable")),
    )
    page._repopulate_client_combo()
    assert page._client_combo.count() == 1
    assert page._status_lbl.text()

    monkeypatch.setattr(
        container.recurring_billing,
        "list_plans",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("plans unavailable")),
    )
    page._rebuild_accordion()
    assert page._status_lbl.text()
    assert not page._add_plan_btn.isEnabled()


def test_line_delete_cancel_button_preserves_sqlite_and_audit(container, monkeypatch):
    client = _client(container, "RB-DEL-CANCEL")
    plan = _plan(container, client.id)
    line = _line(container, plan.id)
    page = RecurringBillingPage(container)
    page._refresh()
    before_actions = _audit_actions(container)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_kw: QMessageBox.StandardButton.No,
    )

    page.findChildren(_LineRow)[0]._delete_btn.click()

    assert container.recurring_billing.list_lines(plan.id)[0].id == line.id
    assert _audit_actions(container) == before_actions


def test_archived_checkbox_renders_archived_plan_without_action_buttons(container):
    client = _client(container, "RB-ARCHIVED-VIEW")
    plan = _plan(container, client.id, "已封存方案")
    _line(container, plan.id)
    container.recurring_billing.archive_plan(plan.id)
    page = RecurringBillingPage(container)
    page._refresh()
    assert not page.findChildren(_PlanSection)

    page._archived_check.setChecked(True)

    sections = page.findChildren(_PlanSection)
    assert len(sections) == 1
    assert sections[0]._plan.id == plan.id
    assert sections[0]._action_btns == []


def test_generate_for_client_unexpected_plan_error_is_visible_and_logged(
    container, monkeypatch
):
    client = _client(container, "RB-CLIENT-FAIL")
    plan = _plan(container, client.id, "損壞方案")
    _line(container, plan.id)
    page = RecurringBillingPage(container)
    warnings = []
    monkeypatch.setattr(
        container.recurring_billing,
        "generate_occurrences",
        lambda _id: (_ for _ in ()).throw(RuntimeError("read-only database")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _p, title, body: warnings.append((title, body)),
    )

    assert page._generate_for_client(client.id) is False
    assert len(warnings) == 1 and "損壞方案" in warnings[0][1]
    log = container.conn.execute(
        """
        SELECT detail_json FROM system_logs
         WHERE message = 'recurring billing auto-generation failed'
         ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert log is not None and f'"plan_id": {plan.id}' in log["detail_json"]


def test_generate_button_second_click_reports_idempotent_result(container):
    client = _client(container, "RB-IDEMPOTENT")
    plan = _plan(container, client.id)
    _line(container, plan.id)
    page = RecurringBillingPage(container)
    page._refresh()

    page._gen_btn.click()
    first_ids = [row.id for row in container.recurring_billing.list_occurrences(plan_id=plan.id)]
    page._gen_btn.click()

    assert [row.id for row in container.recurring_billing.list_occurrences(plan_id=plan.id)] == first_ids
    assert page._status_lbl.text()


def test_bulk_confirm_selected_pending_rows_uses_real_page_action(
    container, monkeypatch
):
    client = _client(container, "RB-BULK-CONFIRM")
    plan = _plan(container, client.id)
    _line(container, plan.id, "批量核對對象")
    occurrences = container.recurring_billing.generate_occurrences(
        plan.id, until_date=datetime.date(2026, 8, 11)
    )
    page = RecurringBillingPage(container)
    page._refresh()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_kw: QMessageBox.StandardButton.Yes,
    )

    pending_rows = [
        row for row in page.findChildren(_OccRow)
        if row._occ.id in {occ.id for occ in occurrences}
    ]
    assert len(pending_rows) == 2
    for row in pending_rows:
        row._select_box.setChecked(True)
    assert page._bulk_confirm_btn.isEnabled()
    page._bulk_confirm_btn.click()

    stored = container.recurring_billing.list_occurrences(plan_id=plan.id)
    assert [row.status for row in stored] == ["confirmed", "confirmed"]
    assert [row.confirmed_amount for row in stored] == [12_000, 12_000]
    assert "recurring_billing.occurrence.bulk_confirm" in _audit_actions(container)


def test_plan_detail_load_failure_keeps_other_page_controls_usable(
    container, monkeypatch
):
    client = _client(container, "RB-DETAIL-FAIL")
    plan = _plan(container, client.id, "明細損壞方案")
    page = RecurringBillingPage(container)
    page._repopulate_client_combo()
    original = container.recurring_billing.list_lines

    def list_lines(plan_id):
        if plan_id == plan.id:
            raise RuntimeError("corrupt row")
        return original(plan_id)

    monkeypatch.setattr(container.recurring_billing, "list_lines", list_lines)
    page._rebuild_accordion()

    sections = page.findChildren(_PlanSection)
    assert len(sections) == 1
    assert sections[0]._line_rows == []
    assert page._status_lbl.text()
    assert page._gen_btn.isEnabled()
    log = container.conn.execute(
        """
        SELECT detail_json FROM system_logs
         WHERE message = 'recurring billing plan detail load failed'
         ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert log is not None and f'"plan_id": {plan.id}' in log["detail_json"]
