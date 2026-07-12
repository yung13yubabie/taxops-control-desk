from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_blocking_message_boxes(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    return warnings


def _client(container, code: str):
    return container.clients.create_client(
        CreateClientInput(client_code=code, client_name=f"{code} 中文客戶")
    )


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_is_scrollable_and_reuses_last_blank_line(container) -> None:
    client = _client(container, "PLAN-RWD")
    dialog = PlanDialog(container.recurring_billing, client.id)

    assert isinstance(dialog._scroll, QScrollArea)
    assert dialog.minimumHeight() <= 500
    dialog.resize(680, 500)
    dialog.show()
    QApplication.processEvents()
    assert dialog._scroll.horizontalScrollBar().maximum() == 0

    dialog._add_line_btn.click()
    dialog._add_line_btn.click()
    assert dialog._lines_table.rowCount() == 1

    dialog._set_line_cell(0, "bill_to", "第一列")
    dialog._set_line_cell(0, "amount", "1000")
    dialog._add_line_btn.click()
    assert dialog._lines_table.rowCount() == 2


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_line_reader_reports_each_visible_row_error(container) -> None:
    client = _client(container, "PLAN-READ")
    dialog = PlanDialog(container.recurring_billing, client.id)
    dialog._add_line_btn.click()

    lines, errors = dialog._read_lines_from_table()
    assert lines == [] and errors == []

    dialog._set_line_cell(0, "amount", "100")
    lines, errors = dialog._read_lines_from_table()
    assert lines == [] and len(errors) == 1

    dialog._set_line_cell(0, "bill_to", "測試客戶")
    dialog._set_line_cell(0, "amount", "not-a-number")
    lines, errors = dialog._read_lines_from_table()
    assert lines == [] and len(errors) == 1

    dialog._set_line_cell(0, "amount", "0")
    lines, errors = dialog._read_lines_from_table()
    assert lines == [] and len(errors) == 1

    dialog._set_line_cell(0, "amount", "100")
    lines, errors = dialog._read_lines_from_table()
    assert errors == []
    assert [(line.bill_to_name, line.amount) for line in lines] == [("測試客戶", 100)]


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_bulk_paste_surfaces_reject_error_empty_and_success(
    container, monkeypatch
) -> None:
    from PySide6.QtWidgets import QDialog
    from taxops.ui.dialogs.recurring_billing_dialogs import _BulkPasteDialog

    client = _client(container, "PLAN-PASTE")
    dialog = PlanDialog(container.recurring_billing, client.id)
    warnings = []
    information = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs.QMessageBox.information",
        lambda *args: information.append(args),
    )

    monkeypatch.setattr(_BulkPasteDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)
    dialog._on_bulk_paste()
    assert dialog._lines_table.rowCount() == 0

    monkeypatch.setattr(_BulkPasteDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(_BulkPasteDialog, "text", lambda _self: "bad-row")
    dialog._on_bulk_paste()
    assert len(warnings) == 1
    assert dialog._lines_table.rowCount() == 0

    monkeypatch.setattr(_BulkPasteDialog, "text", lambda _self: "\n")
    dialog._on_bulk_paste()
    assert len(information) == 1
    assert dialog._lines_table.rowCount() == 0

    monkeypatch.setattr(
        _BulkPasteDialog,
        "text",
        lambda _self: "甲客戶\t1200\tvat\t月費",
    )
    dialog._on_bulk_paste()
    assert dialog._lines_table.rowCount() == 1
    assert dialog._lines_table.item(0, 0).text() == "甲客戶"
    assert dialog._lines_table.item(0, 1).text() == "1200"


def _plan_line_occurrence(container, code: str):
    client = _client(container, code)
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="每月記帳費",
            start_date="2026-01-01",
        )
    )
    line = container.recurring_billing.create_line(
        CreateLineInput(
            plan_id=plan.id,
            bill_to_name="王小明事務所",
            amount=12000,
        )
    )
    container.recurring_billing.generate_occurrences(plan.id)
    occurrence = container.recurring_billing.list_occurrences(
        plan_id=plan.id, status="pending"
    )[0]
    return plan, line, occurrence


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_real_save_creates_plan_lines_and_audit(
    container, no_blocking_message_boxes
) -> None:
    client = _client(container, "PLAN-DLG")
    dialog = PlanDialog(container.recurring_billing, client.id)
    dialog._name.setText("年度申報固定費")
    dialog._start_date.set_value("2026-01-01")
    dialog._issue_day.setValue(8)
    dialog._contract_ref.setText("CTR-2026-001")
    dialog._notes.setPlainText("真實表單建立")
    dialog._add_line_btn.click()
    dialog._set_line_cell(0, "bill_to", "林先生公司")
    dialog._set_line_cell(0, "amount", "36000")
    dialog._set_line_cell(0, "tax_type", "vat")
    dialog._set_line_cell(0, "description", "年度申報服務")

    dialog._save_btn.click()

    assert dialog.result() == dialog.DialogCode.Accepted, no_blocking_message_boxes
    plans = container.recurring_billing.list_plans(client_id=client.id)
    assert len(plans) == 1
    assert plans[0].plan_name == "年度申報固定費"
    assert plans[0].contract_ref == "CTR-2026-001"
    lines = container.recurring_billing.list_lines(plans[0].id)
    assert [(row.bill_to_name, row.amount, row.tax_type, row.description) for row in lines] == [
        ("林先生公司", 36000, "vat", "年度申報服務")
    ]


@pytest.mark.usefixtures("qapp")
def test_line_dialog_real_save_creates_exact_line(
    container, no_blocking_message_boxes
) -> None:
    client = _client(container, "LINE-DLG")
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="明細測試",
            start_date="2026-01-01",
        )
    )
    dialog = LineDialog(container.recurring_billing, plan.id)
    dialog._bill_to.setText("陳小姐工作室")
    dialog._amount.setText("18000")
    dialog._desc.setText("雙月服務")
    dialog._tax_type.setCurrentIndex(dialog._tax_type.findData("vat"))
    dialog._sort_order.setValue(3)

    dialog._save_btn.click()

    assert dialog.result() == dialog.DialogCode.Accepted, no_blocking_message_boxes
    line = container.recurring_billing.list_lines(plan.id)[0]
    assert (line.bill_to_name, line.amount, line.description, line.tax_type, line.sort_order) == (
        "陳小姐工作室",
        18000,
        "雙月服務",
        "vat",
        3,
    )


@pytest.mark.usefixtures("qapp")
def test_confirm_occurrence_dialog_real_save_persists_exact_values(
    container, no_blocking_message_boxes
) -> None:
    plan, line, occurrence = _plan_line_occurrence(container, "CONFIRM-DLG")
    dialog = ConfirmOccurrenceDialog(container.recurring_billing, occurrence, line)
    dialog._amount.setText("12500")
    dialog._invoice_no.setText("AB12345678")
    dialog._notes.setPlainText("已與客戶確認")

    dialog._save_btn.click()

    assert dialog.result() == dialog.DialogCode.Accepted, no_blocking_message_boxes
    confirmed = container.recurring_billing.list_occurrences(
        plan_id=plan.id, status="confirmed"
    )[0]
    assert container.recurring_billing.list_lines(plan.id)[0].amount == 12000
    assert confirmed.confirmed_amount == 12500
    assert confirmed.confirmed_invoice_no == "AB12345678"
    assert confirmed.notes == "已與客戶確認"


@pytest.mark.usefixtures("qapp")
def test_skip_occurrence_dialog_requires_visible_reason_then_persists(
    container, monkeypatch
) -> None:
    plan, line, occurrence = _plan_line_occurrence(container, "SKIP-DLG")
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    dialog = SkipOccurrenceDialog(container.recurring_billing, occurrence, line)

    dialog._skip_btn.click()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._skip_btn.isEnabled()
    assert warnings == ["請填寫跳過原因"]

    dialog._reason.setPlainText("客戶本月暫停營業")
    dialog._skip_btn.click()

    assert dialog.result() == dialog.DialogCode.Accepted
    skipped = container.recurring_billing.list_occurrences(
        plan_id=plan.id, status="skipped"
    )[0]
    assert skipped.skipped_reason == "客戶本月暫停營業"


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_edit_real_save_persists_changes(
    container, no_blocking_message_boxes
) -> None:
    client = _client(container, "PLAN-EDIT")
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="修改前",
            start_date="2026-01-01",
        )
    )
    dialog = PlanDialog(container.recurring_billing, client.id, plan=plan)
    dialog._name.setText("修改後方案")
    dialog._issue_day.setValue(22)
    dialog._notes.setPlainText("編輯表單已儲存")

    dialog._save_btn.click()

    assert dialog.result() == dialog.DialogCode.Accepted, no_blocking_message_boxes
    updated = container.recurring_billing.get_plan(plan.id)
    assert (updated.plan_name, updated.issue_day, updated.notes) == (
        "修改後方案",
        22,
        "編輯表單已儲存",
    )


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_rejects_empty_lines_and_empty_custom_months(
    container, no_blocking_message_boxes
) -> None:
    client = _client(container, "PLAN-INVALID")
    dialog = PlanDialog(container.recurring_billing, client.id)
    dialog._name.setText("不完整方案")
    dialog._start_date.set_value("2026-01-01")

    dialog._save_btn.click()
    assert "至少新增一筆" in no_blocking_message_boxes[-1]
    assert dialog._save_btn.isEnabled()

    dialog._freq.setCurrentIndex(dialog._freq.findData("custom_months"))
    dialog._save_btn.click()
    assert "至少選擇一個月份" in no_blocking_message_boxes[-1]
    assert container.recurring_billing.list_plans(client_id=client.id) == []


@pytest.mark.usefixtures("qapp")
def test_plan_dialog_reports_each_invalid_line_without_writing(
    container, no_blocking_message_boxes
) -> None:
    client = _client(container, "PLAN-LINE-INVALID")
    dialog = PlanDialog(container.recurring_billing, client.id)
    dialog._name.setText("明細錯誤")
    dialog._start_date.set_value("2026-01-01")
    dialog._add_line_btn.click()
    dialog._set_line_cell(0, "amount", "1000")
    dialog._add_line_btn.click()
    dialog._set_line_cell(1, "bill_to", "金額錯誤公司")
    dialog._set_line_cell(1, "amount", "not-int")

    dialog._save_btn.click()

    message = no_blocking_message_boxes[-1]
    assert "第 1 列：開立對象不可為空" in message
    assert "第 2 列：金額必須為正整數" in message
    assert dialog._save_btn.isEnabled()
    assert container.recurring_billing.list_plans(client_id=client.id) == []


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("unexpected", [False, True])
def test_plan_dialog_create_failure_stays_open_and_visible(
    container, monkeypatch, no_blocking_message_boxes, unexpected
) -> None:
    client = _client(container, f"PLAN-FAIL-{int(unexpected)}")
    dialog = PlanDialog(container.recurring_billing, client.id)
    dialog._name.setText("服務失敗方案")
    dialog._start_date.set_value("2026-01-01")
    dialog._add_line_btn.click()
    dialog._set_line_cell(0, "bill_to", "測試公司")
    dialog._set_line_cell(0, "amount", "1000")
    error = RuntimeError("database locked") if unexpected else RecurringBillingError(
        "recurring_billing.plan.name.empty"
    )
    monkeypatch.setattr(
        container.recurring_billing,
        "create_plan_with_lines",
        lambda *_args: (_ for _ in ()).throw(error),
    )

    dialog._save_btn.click()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._save_btn.isEnabled()
    assert len(no_blocking_message_boxes) == 1
    assert "database locked" not in no_blocking_message_boxes[0]


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("unexpected", [False, True])
def test_plan_dialog_edit_failure_stays_open_and_visible(
    container, monkeypatch, no_blocking_message_boxes, unexpected
) -> None:
    client = _client(container, f"PLAN-EDIT-FAIL-{int(unexpected)}")
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="修改會失敗",
            start_date="2026-01-01",
        )
    )
    dialog = PlanDialog(container.recurring_billing, client.id, plan=plan)
    error = RuntimeError("secret edit error") if unexpected else RecurringBillingError(
        "recurring_billing.not_found"
    )
    monkeypatch.setattr(
        container.recurring_billing,
        "update_plan",
        lambda *_args: (_ for _ in ()).throw(error),
    )

    dialog._save_btn.click()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._save_btn.isEnabled()
    assert len(no_blocking_message_boxes) == 1
    assert "secret edit error" not in no_blocking_message_boxes[0]


@pytest.mark.usefixtures("qapp")
def test_line_dialog_edit_and_invalid_amount_paths(
    container, no_blocking_message_boxes
) -> None:
    plan, line, _occurrence = _plan_line_occurrence(container, "LINE-EDIT")
    dialog = LineDialog(container.recurring_billing, plan.id, line=line)
    assert dialog._bill_to.text() == "王小明事務所"
    dialog._amount.setText("not-an-int")
    dialog._save_btn.click()
    assert no_blocking_message_boxes[-1] == "金額必須為整數"
    assert dialog._save_btn.isEnabled()

    dialog._bill_to.setText("王小明事務所（更新）")
    dialog._amount.setText("13500")
    dialog._save_btn.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    updated = container.recurring_billing.list_lines(plan.id)[0]
    assert (updated.bill_to_name, updated.amount) == ("王小明事務所（更新）", 13500)


@pytest.mark.usefixtures("qapp")
def test_confirm_dialog_invalid_amount_and_date_stay_open(
    container, no_blocking_message_boxes
) -> None:
    _plan, line, occurrence = _plan_line_occurrence(container, "CONFIRM-INVALID")
    dialog = ConfirmOccurrenceDialog(container.recurring_billing, occurrence, line)
    dialog._amount.setText("not-int")
    dialog._save_btn.click()
    assert no_blocking_message_boxes[-1] == "金額必須為整數"
    assert dialog._save_btn.isEnabled()

    dialog._amount.setText("12000")
    dialog._issue_date._edit.setText("2026-99-99")
    dialog._save_btn.click()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._save_btn.isEnabled()
    assert "日期格式不正確" in dialog._issue_date._error_label.text()


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("dialog_kind,unexpected", [("line", False), ("line", True), ("confirm", False), ("confirm", True), ("skip", False), ("skip", True)])
def test_recurring_dialog_service_failures_stay_open_and_sanitize_errors(
    container, monkeypatch, no_blocking_message_boxes, dialog_kind, unexpected
) -> None:
    plan, line, occurrence = _plan_line_occurrence(
        container, f"FAIL-{dialog_kind}-{int(unexpected)}"
    )
    error = RuntimeError("secret database detail") if unexpected else RecurringBillingError(
        "recurring_billing.not_found"
    )
    if dialog_kind == "line":
        dialog = LineDialog(container.recurring_billing, plan.id)
        dialog._bill_to.setText("失敗明細")
        dialog._amount.setText("1000")
        monkeypatch.setattr(
            container.recurring_billing,
            "create_line",
            lambda *_args: (_ for _ in ()).throw(error),
        )
        button = dialog._save_btn
    elif dialog_kind == "confirm":
        dialog = ConfirmOccurrenceDialog(container.recurring_billing, occurrence, line)
        monkeypatch.setattr(
            container.recurring_billing,
            "confirm_occurrence",
            lambda *_args: (_ for _ in ()).throw(error),
        )
        button = dialog._save_btn
    else:
        dialog = SkipOccurrenceDialog(container.recurring_billing, occurrence, line)
        dialog._reason.setPlainText("測試失敗")
        monkeypatch.setattr(
            container.recurring_billing,
            "skip_occurrence",
            lambda *_args: (_ for _ in ()).throw(error),
        )
        button = dialog._skip_btn

    button.click()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert button.isEnabled()
    assert len(no_blocking_message_boxes) == 1
    assert "secret database detail" not in no_blocking_message_boxes[0]


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    "text,expected_rows,warning_fragment",
    [
        ("甲公司\t1000\tvat\t服務", 1, None),
        ("甲公司\t不是數字", 0, "第 1 行"),
        ("\n  \n", 0, "未偵測到"),
    ],
)
def test_plan_bulk_paste_handler_reports_exact_outcome(
    container, monkeypatch, no_blocking_message_boxes, text, expected_rows, warning_fragment
) -> None:
    from PySide6.QtWidgets import QDialog

    class PasteDialog:
        def __init__(self, _parent):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def text(self):
            return text

    client = _client(container, f"PASTE-{expected_rows}-{len(text)}")
    dialog = PlanDialog(container.recurring_billing, client.id)
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs._BulkPasteDialog", PasteDialog
    )
    infos: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.recurring_billing_dialogs.QMessageBox.information",
        lambda _parent, _title, body: infos.append(body),
    )

    dialog._bulk_paste_btn.click()

    assert dialog._lines_table.rowCount() == expected_rows
    messages = no_blocking_message_boxes + infos
    if warning_fragment is not None:
        assert any(warning_fragment in message for message in messages)
