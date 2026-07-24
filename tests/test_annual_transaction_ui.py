from __future__ import annotations

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_transactions import AnnualTransactionError
from taxops.ui.action_registry import PAGE_ANNUAL_WORKBENCH, actions_for_page
from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog
from taxops.ui.dialogs.annual_transaction_dialog import (
    AnnualTransactionDeleteDialog,
    AnnualTransactionDialog,
)
from taxops.ui.widgets.annual_transaction_panel import AnnualTransactionPanel


def _work_item(container: object):
    client = container.clients.create_client(
        CreateClientInput(
            client_code="C-TX-UI",
            client_name="年度交易介面測試客戶",
        )
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
        ),
    )
    annual_work = container.annual_work
    return annual_work.confirm_preview(
        client.id,
        2026,
        annual_work.preview(client.id, 2026),
    ).items[0]


def test_panel_loads_first_bounded_page_and_exact_derived_balances(
    qtbot, container
) -> None:
    item = _work_item(container)
    service = container.annual_transactions
    transaction = service.add(
        item.id,
        "tax_liability",
        62_000,
        "2026-05-10",
        "115年度營所稅",
        "第一行\n第二行",
    )
    service.add(
        item.id,
        "client_tax_collection",
        43_400,
        "2026-05-12",
    )

    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)

    assert panel.page_size <= 100
    assert panel.table.rowCount() == 2
    assert panel.transaction_id_at(0) == transaction.id
    assert panel.table.item(0, panel.DATE_COLUMN).text() == "2026-05-10"
    assert panel.table.item(0, panel.CATEGORY_COLUMN).text() == "應納稅額"
    assert panel.table.item(0, panel.AMOUNT_COLUMN).text() == "NT$ 62,000"
    assert panel.table.item(0, panel.REFERENCE_COLUMN).toolTip() == "115年度營所稅"
    assert panel.tax_liability_label.text() == "NT$ 62,000"
    assert panel.client_tax_collection_label.text() == "NT$ 43,400"
    assert panel.collection_shortfall_label.text() == "NT$ 18,600"
    assert panel.unpaid_tax_label.text() == "NT$ 62,000"


def test_add_dialog_saves_large_text_amount_and_panel_rereads_balance(
    qtbot, container
) -> None:
    item = _work_item(container)
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
        parent=panel,
    )
    qtbot.addWidget(dialog)
    dialog.committed.connect(panel._on_mutation_committed)

    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("tax_payment")
    )
    dialog.transaction_date_input.setText("2026-06-01")
    dialog.amount_input.setText("2147483648")
    dialog.reference_input.setText("大額稅款繳納")
    dialog.notes_input.setPlainText("保留繁中\n與換行")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    rows = container.annual_transactions.page(
        item.id, limit=100, offset=0
    ).rows
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(rows) == 1
    assert rows[0].amount == 2_147_483_648
    assert rows[0].reference == "大額稅款繳納"
    assert rows[0].notes == "保留繁中\n與換行"
    assert panel.transaction_id_at(0) == rows[0].id
    assert panel.tax_payment_label.text() == "NT$ 2,147,483,648"
    assert panel.tax_overpayment_label.text() == "NT$ 2,147,483,648"
    assert (
        panel.feedback_label.text()
        == "交易紀錄已儲存並重新核對帳務。"
    )


def test_edit_dialog_updates_same_id_and_panel_rereads_balance(
    qtbot, container
) -> None:
    item = _work_item(container)
    original = container.annual_transactions.add(
        item.id,
        "fee_receivable",
        8_000,
        "2026-01-01",
        "原始應收",
        "原始備註",
    )
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
        transaction_id=original.id,
        parent=panel,
    )
    qtbot.addWidget(dialog)
    dialog.committed.connect(panel.reload)

    assert dialog.amount_input.text() == "8000"
    dialog.amount_input.setText("6000")
    dialog.reference_input.setText("修正後應收")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    page = container.annual_transactions.page(
        item.id, limit=100, offset=0
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert page.total == 1
    assert page.rows[0].id == original.id
    assert page.rows[0].amount == 6_000
    assert page.rows[0].reference == "修正後應收"
    assert panel.transaction_id_at(0) == original.id
    assert panel.fee_receivable_label.text() == "NT$ 6,000"
    assert panel.outstanding_fee_label.text() == "NT$ 6,000"


def test_item_dialog_uses_horizontal_splitter_for_fields_and_ledger(
    qtbot, container
) -> None:
    item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.resize(900, 540)
    dialog.show()

    assert dialog.splitter.orientation() == Qt.Orientation.Horizontal
    assert dialog.splitter.count() == 2
    assert dialog.splitter.widget(0) is dialog.detail
    assert dialog.splitter.widget(1) is dialog.ledger
    assert dialog.detail.save_button.isVisible()
    assert dialog.ledger.table.isVisible()


def test_panel_requires_a_real_selected_id_for_edit_and_delete(
    qtbot, container
) -> None:
    item = _work_item(container)
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    panel.show()
    panel.table.clearSelection()

    qtbot.mouseClick(panel.edit_button, Qt.MouseButton.LeftButton)

    assert panel.feedback_label.text() == "請先選取要編輯的交易紀錄。"
    qtbot.waitUntil(panel.table.hasFocus, timeout=500)

    qtbot.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)

    assert panel.feedback_label.text() == "請先選取要刪除的交易紀錄。"
    qtbot.waitUntil(panel.table.hasFocus, timeout=500)


def test_delete_dialog_requires_reason_soft_deletes_and_rereads_balance(
    qtbot, container
) -> None:
    item = _work_item(container)
    transaction = container.annual_transactions.add(
        item.id,
        "tax_liability",
        12_345,
        "2026-04-01",
    )
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    dialog = AnnualTransactionDeleteDialog(
        container.annual_transactions,
        transaction.id,
        parent=panel,
    )
    qtbot.addWidget(dialog)
    dialog.committed.connect(panel._on_mutation_committed)
    dialog.reason_input.setPlainText("重複登錄，保留刪除軌跡")

    qtbot.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)

    deleted = container.annual_transactions.get(
        transaction.id, include_deleted=True
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert deleted is not None
    assert deleted.deleted_at is not None
    assert panel.table.rowCount() == 0
    assert panel.tax_liability_label.text() == "NT$ 0"
    audit = container.annual_transactions.connection.execute(
        "SELECT detail_json FROM audit_logs "
        "WHERE action = 'annual_transaction.delete' AND target_id = ?",
        (str(transaction.id),),
    ).fetchone()
    assert audit is not None
    assert "重複登錄，保留刪除軌跡" in audit["detail_json"]


def test_service_validation_focuses_reference_and_writes_nothing(
    qtbot, container
) -> None:
    item = _work_item(container)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("tax_liability")
    )
    dialog.transaction_date_input.setText("2026-01-01")
    dialog.amount_input.setText("100")
    dialog.reference_input.setText("不可含控制字元\u0001")

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert (
        dialog.feedback_label.text()
        == "交易參考資訊過長或包含不安全字元"
    )
    assert dialog.reference_input.text() == "不可含控制字元\u0001"
    qtbot.waitUntil(dialog.reference_input.hasFocus, timeout=500)
    assert container.annual_transactions.page(
        item.id, limit=100, offset=0
    ).total == 0


def test_committed_add_with_reread_failure_disables_mutations_until_retry(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    item_dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(item_dialog)
    item_dialog.show()
    panel = item_dialog.ledger
    transaction_dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
        parent=panel,
    )
    qtbot.addWidget(transaction_dialog)
    transaction_dialog.committed.connect(panel._on_mutation_committed)
    transaction_dialog.category_combo.setCurrentIndex(
        transaction_dialog.category_combo.findData("tax_liability")
    )
    transaction_dialog.transaction_date_input.setText("2026-01-02")
    transaction_dialog.amount_input.setText("900")
    real_page = container.annual_transactions.page
    monkeypatch.setattr(
        container.annual_transactions,
        "page",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AnnualTransactionError("annual_transactions.page.failed")
        ),
    )

    qtbot.mouseClick(
        transaction_dialog.save_button, Qt.MouseButton.LeftButton
    )

    assert transaction_dialog.result() == QDialog.DialogCode.Accepted
    assert real_page(item.id, limit=100, offset=0).total == 1
    assert item_dialog.has_committed_change is True
    assert "資料已寫入但重新讀取失敗" in panel.feedback_label.text()
    assert panel.retry_button.isVisible()
    assert panel.retry_button.isEnabled()
    assert not panel.add_button.isEnabled()
    assert not panel.edit_button.isEnabled()
    assert not panel.delete_button.isEnabled()

    monkeypatch.setattr(container.annual_transactions, "page", real_page)
    qtbot.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)

    assert panel.table.rowCount() == 1
    assert panel.add_button.isEnabled()
    assert not panel.retry_button.isVisible()


def test_pagination_reaches_transaction_501_and_double_click_opens_its_id_once(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    service = container.annual_transactions
    ids = [
        service.add(
            item.id,
            "fee_receipt",
            index,
            "2026-01-01",
            f"第 {index} 筆",
        ).id
        for index in range(1, 502)
    ]
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    panel.resize(620, 540)
    panel.show()

    assert panel.page_label.text() == "第 1 / 11 頁，共 501 筆"
    assert panel.table.rowCount() == 50
    assert panel.transaction_id_at(0) == ids[0]
    for _ in range(10):
        qtbot.mouseClick(panel.next_button, Qt.MouseButton.LeftButton)

    assert panel.page_label.text() == "第 11 / 11 頁，共 501 筆"
    assert panel.table.rowCount() == 1
    assert panel.transaction_id_at(0) == ids[-1]
    opened: list[int] = []

    def fake_exec(dialog) -> int:
        opened.append(dialog.transaction_id)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(AnnualTransactionDialog, "exec", fake_exec)
    rect = panel.table.visualItemRect(panel.table.item(0, 0))
    assert rect.isValid(), (
        rect.width(),
        rect.height(),
        panel.table.viewport().size(),
    )
    qtbot.mouseClick(
        panel.table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )
    qtbot.mouseDClick(
        panel.table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )

    qtbot.waitUntil(lambda: opened == [ids[-1]], timeout=500)


def test_selected_delete_button_opens_reason_dialog_and_refreshes_real_row(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    transaction = container.annual_transactions.add(
        item.id,
        "tax_payment",
        300,
        "2026-03-03",
    )
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    panel.show()
    opened: list[int] = []

    def accept_delete(dialog) -> int:
        opened.append(dialog.transaction_id)
        dialog.reason_input.setPlainText("UI 按鈕確認刪除")
        qtbot.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)
        return dialog.result()

    monkeypatch.setattr(
        AnnualTransactionDeleteDialog,
        "exec",
        accept_delete,
    )
    cell = panel.table.item(0, 0)
    qtbot.mouseClick(
        panel.table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=panel.table.visualItemRect(cell).center(),
    )
    qtbot.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)

    assert opened == [transaction.id]
    assert container.annual_transactions.page(
        item.id, limit=100, offset=0
    ).total == 0
    assert panel.table.rowCount() == 0
    assert panel.tax_payment_label.text() == "NT$ 0"


@pytest.mark.parametrize(
    ("field_name", "value", "expected_message"),
    [
        (
            "amount_input",
            "9,000",
            "交易金額不正確",
        ),
        (
            "transaction_date_input",
            "2026-2-01",
            "交易日期格式不正確，請使用 YYYY-MM-DD",
        ),
        (
            "reference_input",
            "參" * 501,
            "交易參考資訊過長或包含不安全字元",
        ),
        (
            "notes_input",
            "備" * 4001,
            "交易備註過長或包含不安全字元",
        ),
    ],
)
def test_invalid_fields_preserve_exact_input_focus_first_and_write_nothing(
    qtbot, container, field_name, value, expected_message
) -> None:
    item = _work_item(container)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("tax_liability")
    )
    dialog.transaction_date_input.setText("2026-02-01")
    dialog.amount_input.setText("100")
    field = getattr(dialog, field_name)
    if field_name == "notes_input":
        field.setPlainText(value)
        exact = field.toPlainText
    else:
        field.setText(value)
        exact = field.text

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.feedback_label.text() == expected_message
    assert exact() == value
    qtbot.waitUntil(field.hasFocus, timeout=500)
    assert container.annual_transactions.page(
        item.id, limit=100, offset=0
    ).total == 0


def test_transaction_actions_have_real_layered_contracts() -> None:
    contracts = {
        contract.button_label: contract
        for contract in actions_for_page(PAGE_ANNUAL_WORKBENCH)
    }
    expected = {
        "新增交易": (
            "AnnualTransactionPanel._open_add",
            "AnnualTransactionsService.add",
            "AnnualTransactionsRepository.insert",
            "annual_transaction.add",
            "test_add_dialog_saves_large_text_amount_and_panel_rereads_balance",
        ),
        "編輯交易": (
            "AnnualTransactionPanel._open_edit",
            "AnnualTransactionsService.update",
            "AnnualTransactionsRepository.update",
            "annual_transaction.update",
            "test_edit_dialog_updates_same_id_and_panel_rereads_balance",
        ),
        "刪除交易": (
            "AnnualTransactionPanel._delete_selected",
            "AnnualTransactionsService.delete",
            "AnnualTransactionsRepository.soft_delete",
            "annual_transaction.delete",
            "test_selected_delete_button_opens_reason_dialog_and_refreshes_real_row",
        ),
        "重新讀取交易": (
            "AnnualTransactionPanel.reload",
            "AnnualTransactionsService.page + balance",
            "AnnualTransactionsRepository.list + count + balance",
            None,
            "test_committed_add_with_reread_failure_disables_mutations_until_retry",
        ),
        "交易上一頁": (
            "AnnualTransactionPanel._previous_page",
            "AnnualTransactionsService.page",
            "AnnualTransactionsRepository.list + count",
            None,
            "test_pagination_reaches_transaction_501_and_double_click_opens_its_id_once",
        ),
        "交易下一頁": (
            "AnnualTransactionPanel._next_page",
            "AnnualTransactionsService.page",
            "AnnualTransactionsRepository.list + count",
            None,
            "test_pagination_reaches_transaction_501_and_double_click_opens_its_id_once",
        ),
    }
    for label, values in expected.items():
        contract = contracts[label]
        assert contract.enabled is True
        assert (
            contract.handler,
            contract.service,
            contract.repository,
            contract.audit_action,
            contract.test_marker,
        ) == values


def test_add_service_failure_preserves_all_fields_and_hides_raw_exception(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
    )
    qtbot.addWidget(dialog)
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("fee_receivable")
    )
    dialog.transaction_date_input.setText("2026-07-01")
    dialog.amount_input.setText("7000")
    dialog.reference_input.setText("七月服務費")
    dialog.notes_input.setPlainText("客戶要求\n月底前聯絡")
    monkeypatch.setattr(
        container.annual_transactions,
        "add",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("raw-database-secret")
        ),
    )

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.category_combo.currentData() == "fee_receivable"
    assert dialog.transaction_date_input.text() == "2026-07-01"
    assert dialog.amount_input.text() == "7000"
    assert dialog.reference_input.text() == "七月服務費"
    assert dialog.notes_input.toPlainText() == "客戶要求\n月底前聯絡"
    assert dialog.save_button.isEnabled()
    assert "raw-database-secret" not in dialog.feedback_label.text()


def test_nested_submit_during_one_click_calls_add_once(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    service = container.annual_transactions
    dialog = AnnualTransactionDialog(service, item.id)
    qtbot.addWidget(dialog)
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("tax_payment")
    )
    dialog.transaction_date_input.setText("2026-08-01")
    dialog.amount_input.setText("800")
    real_add = service.add
    calls = 0

    def reentrant_add(*args, **kwargs):
        nonlocal calls
        calls += 1
        dialog.save()
        return real_add(*args, **kwargs)

    monkeypatch.setattr(service, "add", reentrant_add)

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert calls == 1
    assert service.page(item.id, limit=100, offset=0).total == 1


def test_two_intentional_identical_dialog_adds_create_distinct_ids(
    qtbot, container
) -> None:
    item = _work_item(container)
    service = container.annual_transactions
    committed_ids: list[int] = []
    for _ in range(2):
        dialog = AnnualTransactionDialog(service, item.id)
        qtbot.addWidget(dialog)
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData("tax_liability")
        )
        dialog.transaction_date_input.setText("2026-09-01")
        dialog.amount_input.setText("900")
        dialog.reference_input.setText("合法相同資料")
        qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        assert dialog.committed_transaction_id is not None
        committed_ids.append(dialog.committed_transaction_id)

    assert committed_ids[0] != committed_ids[1]
    page = service.page(item.id, limit=100, offset=0)
    assert page.total == 2
    assert {row.id for row in page.rows} == set(committed_ids)


def test_900_by_540_keeps_ledger_actions_table_and_pagination_reachable(
    qtbot, container
) -> None:
    item = _work_item(container)
    dialog = AnnualItemDialog(container, item.id)
    qtbot.addWidget(dialog)
    dialog.resize(900, 540)
    dialog.show()
    qtbot.waitExposed(dialog)
    panel = dialog.ledger

    for widget in (
        dialog.detail.save_button,
        panel.add_button,
        panel.edit_button,
        panel.delete_button,
        panel.table,
        panel.previous_button,
        panel.next_button,
        panel.page_label,
    ):
        assert widget.isVisible()
        top_left = widget.mapTo(dialog, widget.rect().topLeft())
        bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
        assert dialog.rect().contains(top_left)
        assert dialog.rect().contains(bottom_right)
    assert panel.table.viewport().height() > 30
    assert panel.table.font().pointSize() >= 10
    for name in (
        "tax_liability",
        "client_tax_collection",
        "tax_payment",
        "tax_credit_or_refund",
        "fee_receivable",
        "fee_receipt",
        "collection_shortfall",
        "unpaid_tax",
        "outstanding_fee",
        "excess_client_collection",
        "tax_overpayment",
        "fee_overpayment",
    ):
        assert isinstance(getattr(panel, f"{name}_label"), QLabel)


def test_committed_add_does_not_depend_on_a_second_dialog_get(
    qtbot, container, monkeypatch
) -> None:
    item = _work_item(container)
    panel = AnnualTransactionPanel(container, item.id)
    qtbot.addWidget(panel)
    dialog = AnnualTransactionDialog(
        container.annual_transactions,
        item.id,
        parent=panel,
    )
    qtbot.addWidget(dialog)
    dialog.committed.connect(panel._on_mutation_committed)
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData("fee_receipt")
    )
    dialog.transaction_date_input.setText("2026-10-01")
    dialog.amount_input.setText("1000")
    monkeypatch.setattr(
        container.annual_transactions,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AnnualTransactionError("annual_transactions.page.failed")
        ),
    )

    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert container.annual_transactions.page(
        item.id, limit=100, offset=0
    ).total == 1
    assert panel.table.rowCount() == 1
    assert panel.fee_receipt_label.text() == "NT$ 1,000"
