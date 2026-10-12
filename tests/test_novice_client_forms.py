"""Synthetic Qt regressions for novice forms; no user data or network."""
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QFormLayout

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.engagements import CreateEngagementInput
from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog
from taxops.ui.dialogs.compliance_profile_dialog import ComplianceProfileDialog
from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog
from taxops.ui.style import APP_STYLESHEET


@pytest.fixture
def styled(qapp):
    previous = qapp.styleSheet()
    qapp.setStyleSheet(APP_STYLESHEET)
    yield qapp
    qapp.setStyleSheet(previous)


def client(container, code="SYNTHETIC"):
    return container.clients.create_client(CreateClientInput(code, "合成測試客戶"))


def test_profile_read_failure_cannot_overwrite_real_profile(container, qtbot, styled, monkeypatch):
    customer = client(container)
    container.compliance_profiles.upsert_profile(customer.id, 4, [
        ComplianceProfileItemInput("vat", "monthly", enabled=True),
    ])
    read = container.compliance_profiles.get_for_client
    monkeypatch.setattr(container.compliance_profiles, "get_for_client", Mock(side_effect=RuntimeError("synthetic")))
    dialog = ComplianceProfileDialog(container, customer.id)
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.save_button.isEnabled()
    assert not dialog.items_table.isEnabled()
    assert dialog.retry_button.isVisible()
    assert "載入設定檔失敗" in dialog.feedback_label.text()
    dialog._save()  # gate also protects direct/reentrant invocation
    assert read(customer.id).profile.fiscal_year_start_month == 4
    monkeypatch.setattr(container.compliance_profiles, "get_for_client", read)
    dialog.retry_button.click()
    assert dialog.save_button.isEnabled()
    assert dialog.fiscal_month_spin.value() == 4
    assert not dialog.retry_button.isVisible()
    dialog.save_button.click()
    assert read(customer.id).profile.fiscal_year_start_month == 4


def test_client_list_failure_is_distinct_from_empty_and_can_retry(container, qtbot, styled, monkeypatch):
    customer = client(container)
    read = container.clients.search_clients
    monkeypatch.setattr(container.clients, "search_clients", Mock(side_effect=RuntimeError("synthetic")))
    dialog = ComplianceProfileDialog(container, customer.id)
    qtbot.addWidget(dialog)
    assert "客戶清單載入失敗" in dialog.feedback_label.text()
    assert not dialog.save_button.isEnabled()
    monkeypatch.setattr(container.clients, "search_clients", read)
    dialog.retry_button.click()
    assert dialog.save_button.isEnabled()
    assert dialog.client_combo.currentData() == customer.id


def test_empty_client_list_can_retry_after_new_client(container, qtbot, styled):
    dialog = ComplianceProfileDialog(container)
    qtbot.addWidget(dialog)
    assert "尚無可設定的客戶" in dialog.feedback_label.text()
    assert dialog.items_table.rowCount() == 0
    customer = client(container)
    dialog.retry_button.click()
    assert dialog.client_combo.currentData() == customer.id
    assert dialog.save_button.isEnabled()
    assert "尚無設定檔" in dialog.feedback_label.text()


def test_switching_client_read_failure_cannot_save_old_client_values(container, qtbot, styled, monkeypatch):
    first, second = client(container, "A"), client(container, "B")
    dialog = ComplianceProfileDialog(container, first.id)
    qtbot.addWidget(dialog)
    real_read = container.compliance_profiles.get_for_client
    monkeypatch.setattr(container.compliance_profiles, "get_for_client", Mock(side_effect=RuntimeError("synthetic")))
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(second.id))
    dialog._save()
    assert not dialog.save_button.isEnabled()
    assert real_read(second.id) is None


def test_profile_frequency_editors_fit_rows_and_long_client_stays_bounded(container, qtbot, styled):
    customer = container.clients.create_client(CreateClientInput("LONG", "合成長中文客戶名稱" * 15))
    dialog = ComplianceProfileDialog(container, customer.id)
    qtbot.addWidget(dialog)
    dialog.resize(680, 460)
    dialog.show()
    QApplication.processEvents()
    assert dialog.width() == 680
    assert customer.client_name in dialog.client_combo.toolTip()
    for row in range(dialog.items_table.rowCount()):
        combo = dialog.items_table.cellWidget(row, 2)
        assert dialog.items_table.rowHeight(row) >= combo.sizeHint().height()
        assert combo.accessibleName()
    assert dialog.rect().contains(dialog.save_button.mapTo(dialog, dialog.save_button.rect().bottomRight()))


@pytest.mark.parametrize("editing", [False, True])
def test_engagement_short_window_keeps_footer_and_tabs_in_form_order(container, qtbot, styled, editing):
    customer = client(container)
    if editing:
        engagement = container.engagements.create_engagement(CreateEngagementInput(customer.id, "合成案件", "vat", "2026-01"))
        dialog = EditEngagementDialog(container.engagements, engagement)
    else:
        dialog = NewEngagementDialog(container.engagements, customer.id)
    qtbot.addWidget(dialog)
    dialog.resize(460, 300)
    dialog.show()
    QApplication.processEvents()
    assert dialog.height() == 300
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    assert dialog.rect().contains(dialog._save_btn.mapTo(dialog, dialog._save_btn.rect().bottomRight()))
    dialog._owner.setFocus()
    QTest.keyClick(dialog._owner, Qt.Key.Key_Tab)
    assert dialog._due_date.isAncestorOf(QApplication.focusWidget()) or dialog._due_date.hasFocus()
    assert dialog._owner.accessibleName() == "負責人"
    form = dialog.scroll_area.widget().layout()
    assert isinstance(form, QFormLayout)
    for row in range(form.rowCount()):
        label = form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
        assert label.buddy() is not None


def test_lease_missing_name_is_labelled_and_returns_focus_without_losing_input(qtbot, styled, monkeypatch):
    monkeypatch.setattr("taxops.ui.dialogs.client_lease_dialog.QMessageBox.warning", lambda *_: None)
    dialog = ClientLeaseDialog()
    qtbot.addWidget(dialog)
    dialog.resize(460, 420)
    dialog.show()
    dialog.notes.setPlainText("合成備註，不可丟失")
    dialog.save_button.setFocus()
    dialog.save_button.click()
    QApplication.processEvents()
    assert any("租約名稱（必填）" == label.text() for label in dialog.findChildren(QLabel))
    assert dialog.lease_name.hasFocus()
    assert dialog.notes.toPlainText() == "合成備註，不可丟失"
    assert dialog.save_button.isEnabled()
    assert "請輸入租約名稱" in dialog.feedback_label.text()
    dialog.lease_name.setText("合成辦公室租約")
    dialog.save_button.click()
    assert dialog.lease_input.notes == "合成備註，不可丟失"


@pytest.mark.parametrize("selected_offset", [500, 501])
def test_profile_exact_preselected_client_beyond_first_page(container, qtbot, styled, selected_offset):
    customers = [client(container, f"CLIENT-{index:04}") for index in range(502)]
    selected = customers[selected_offset]
    dialog = ComplianceProfileDialog(container, selected.id)
    qtbot.addWidget(dialog)
    assert dialog.client_combo.currentData() == selected.id
    assert dialog.save_button.isEnabled()
    dialog.fiscal_month_spin.setValue(4)
    dialog.save_button.click()
    assert container.compliance_profiles.get_for_client(selected.id).profile.fiscal_year_start_month == 4
    assert container.compliance_profiles.get_for_client(customers[0].id) is None


def test_profile_missing_preselected_client_never_falls_back(container, qtbot, styled):
    first = client(container, "FIRST")
    deleted = client(container, "DELETED")
    container.clients.delete_client(deleted.id)
    dialog = ComplianceProfileDialog(container, deleted.id)
    qtbot.addWidget(dialog)
    assert dialog.client_combo.currentData() is None
    assert not dialog.save_button.isEnabled()
    assert "指定客戶不存在或已停用" in dialog.feedback_label.text()
    dialog._save()
    assert container.compliance_profiles.get_for_client(first.id) is None


def test_profile_exact_client_read_failure_retry_keeps_requested_identity(container, qtbot, styled, monkeypatch):
    first, selected = client(container, "FIRST"), client(container, "SELECTED")
    monkeypatch.setattr(container.clients, "search_clients", lambda *a, **kw: [first])
    get = container.clients.get_client
    monkeypatch.setattr(container.clients, "get_client", Mock(side_effect=RuntimeError("synthetic")))
    dialog = ComplianceProfileDialog(container, selected.id)
    qtbot.addWidget(dialog)
    assert not dialog.save_button.isEnabled()
    assert dialog.client_combo.currentData() is None
    monkeypatch.setattr(container.clients, "get_client", get)
    dialog.retry_button.click()
    assert dialog.client_combo.currentData() == selected.id
    assert dialog.save_button.isEnabled()


@pytest.mark.parametrize("kind", ["new", "edit", "lease", "profile"])
@pytest.mark.parametrize("dismissal", ["escape", "close", "cancel"])
def test_dirty_form_cancel_can_continue_then_discard_without_writing(container, qtbot, styled, kind, dismissal):
    from PySide6.QtWidgets import QMessageBox
    customer = client(container)
    if kind == "new":
        dialog = NewEngagementDialog(container.engagements, customer.id)
        dialog._name.setText("未儲存合成案件")
    elif kind == "edit":
        row = container.engagements.create_engagement(CreateEngagementInput(customer.id, "既有合成案件", "vat", "2026"))
        dialog = EditEngagementDialog(container.engagements, row)
        dialog._name.setText("未儲存更名")
    elif kind == "lease":
        dialog = ClientLeaseDialog()
        dialog.lease_name.setText("未儲存合成租約")
    else:
        dialog = ComplianceProfileDialog(container, customer.id)
        dialog.fiscal_month_spin.setValue(4)
    qtbot.addWidget(dialog)
    dialog.show()
    if dismissal == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    elif dismissal == "close":
        dialog.close()
    else:
        dialog.reject()
    assert dialog.isVisible()
    question = dialog._discard_confirmation
    question.button(QMessageBox.StandardButton.Cancel).click()
    assert dialog.isVisible()
    assert dialog._form_values() != dialog._initial_values
    dialog.reject()
    dialog._discard_confirmation.button(QMessageBox.StandardButton.Discard).click()
    assert not dialog.isVisible()
    assert dialog.result() == dialog.DialogCode.Rejected
    assert container.compliance_profiles.get_for_client(customer.id) is None
    rows = container.engagements.list_by_client(customer.id)
    assert len(rows) == (1 if kind == "edit" else 0)
    if rows:
        assert rows[0].engagement_name == "既有合成案件"
    if kind == "lease":
        assert dialog.lease_input is None


def test_profile_dirty_switch_keeps_correct_client_until_explicit_discard(container, qtbot, styled):
    from PySide6.QtWidgets import QMessageBox
    first, second = client(container, "FIRST"), client(container, "SECOND")
    dialog = ComplianceProfileDialog(container, first.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.fiscal_month_spin.setValue(4)
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(second.id))
    assert dialog.client_combo.currentData() == first.id
    dialog._save()  # no commit while confirmation is pending
    dialog._discard_confirmation.button(QMessageBox.StandardButton.Cancel).click()
    assert dialog.fiscal_month_spin.value() == 4
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(second.id))
    dialog._discard_confirmation.button(QMessageBox.StandardButton.Discard).click()
    assert dialog.client_combo.currentData() == second.id
    assert dialog.fiscal_month_spin.value() == 1
    assert container.compliance_profiles.get_for_client(first.id) is None
    assert container.compliance_profiles.get_for_client(second.id) is None


def test_engagement_notes_tab_reaches_save(container, qtbot, styled):
    dialog = NewEngagementDialog(container.engagements, client(container).id)
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()
    dialog.activateWindow()
    dialog._notes.setFocus()
    QTest.keyClick(dialog._notes, Qt.Key.Key_Tab)
    assert dialog._save_btn.hasFocus()
    assert dialog._notes.toPlainText() == ""


def test_long_annual_client_has_no_horizontal_overflow_and_optional_calendar(container, qtbot, styled):
    from taxops.ui.dialogs.annual_item_dialog import AnnualItemDialog
    from taxops.ui.widgets.date_field import DateField
    customer = container.clients.create_client(CreateClientInput("LONG", "合成測試長中文客戶名稱股份有限公司" * 10))
    container.compliance_profiles.upsert_profile(customer.id, 1, [ComplianceProfileItemInput("vat", "monthly")])
    result = container.annual_work.confirm_preview(customer.id, 2026, container.annual_work.preview(customer.id, 2026))
    dialog = AnnualItemDialog(container, result.items[0].id)
    qtbot.addWidget(dialog)
    dialog.resize(900, 540)
    dialog.show()
    QApplication.processEvents()
    fields = dialog.detail.fields
    assert fields.horizontalScrollBar().maximum() == 0
    assert fields.client_label.isReadOnly()
    assert fields.client_label.cursorPosition() == 0
    assert customer.client_name in fields.client_label.toolTip()
    assert isinstance(fields.due_date_input, DateField)
    fields.due_date_input.set_value("2026-05-01")
    assert dialog.detail.save_in_place()
    assert container.annual_work.get_item_context(result.items[0].id).item.due_date == "2026-05-01"
    fields.due_date_input.clear()
    assert dialog.detail.save_in_place()
    assert container.annual_work.get_item_context(result.items[0].id).item.due_date is None


@pytest.mark.parametrize("kind", ["new", "edit", "lease", "profile"])
def test_unchanged_initial_form_closes_without_confirmation(container, qtbot, styled, kind):
    customer = client(container)
    if kind == "new":
        dialog = NewEngagementDialog(container.engagements, customer.id)
    elif kind == "edit":
        row = container.engagements.create_engagement(CreateEngagementInput(customer.id, "既有合成案件", "vat", "2026"))
        dialog = EditEngagementDialog(container.engagements, row)
    elif kind == "lease":
        from taxops.services.client_leases import LeaseInput
        dialog = ClientLeaseDialog(LeaseInput("既有合成租約", notes="初始備註"))
    else:
        container.compliance_profiles.upsert_profile(customer.id, 4, [ComplianceProfileItemInput("vat", "monthly")])
        dialog = ComplianceProfileDialog(container, customer.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.reject()
    assert not dialog.isVisible()
    assert getattr(dialog, "_discard_confirmation", None) is None


@pytest.mark.parametrize("count,has_limit", [(500, False), (501, True)])
def test_profile_only_exposes_list_limit_when_truly_truncated(container, qtbot, styled, count, has_limit):
    for index in range(count):
        client(container, f"C{index:04}")
    dialog = ComplianceProfileDialog(container)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.client_limit_hint.isVisible() == has_limit
    assert dialog.client_combo.count() == 500
    if has_limit:
        assert "500" in dialog.client_limit_hint.text()
        assert "建立年度工作" in dialog.client_limit_hint.text()
        assert "設定法遵檔案" in dialog.client_limit_hint.text()


def test_transaction_required_and_optional_fields_are_explained(container, qtbot, styled):
    from taxops.ui.dialogs.annual_transaction_dialog import AnnualTransactionDialog
    dialog = AnnualTransactionDialog(container.annual_transactions, 1)
    qtbot.addWidget(dialog)
    dialog.resize(520, 440)
    dialog.show()
    QApplication.processEvents()
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "金額（新臺幣元，必填）" in labels
    assert "日期（西元，必填）" in labels
    assert "參考資訊（可留空）" in labels
    assert "備註（可留空）" in labels
    assert "例如" in dialog.reference_input.placeholderText()
    assert "可留空" in dialog.notes_input.placeholderText()
    assert "西元年-月-日" in dialog.transaction_date_input.toolTip()
    dialog.notes_input.setFocus()
    QTest.keyClick(dialog.notes_input, Qt.Key.Key_Tab)
    assert dialog.save_button.hasFocus()
    assert dialog.rect().contains(dialog.save_button.mapTo(dialog, dialog.save_button.rect().bottomRight()))


def test_collaboration_long_context_and_each_visible_tab_fit(container, qtbot, styled):
    from taxops.ui.dialogs.annual_workflow_dialog import AnnualWorkflowDialog
    customer = container.clients.create_client(CreateClientInput("LONG", "合成中文長名稱股份有限公司" * 15))
    container.compliance_profiles.upsert_profile(customer.id, 1, [ComplianceProfileItemInput("vat", "monthly")])
    result = container.annual_work.confirm_preview(customer.id, 2026, container.annual_work.preview(customer.id, 2026))
    dialog = AnnualWorkflowDialog(container, result.items[0].id)
    qtbot.addWidget(dialog)
    dialog.resize(900, 540)
    dialog.show()
    QApplication.processEvents()
    assert dialog.width() == 900
    assert dialog.client_label.isReadOnly()
    assert dialog.client_label.toolTip() == customer.client_name
    assert dialog.client_label.cursorPosition() == 0
    assert dialog.summary_item_counts.wordWrap()
    assert dialog.summary_item_counts.toolTip() == dialog.summary_item_counts.text()
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        QApplication.processEvents()
        scroll = dialog.tabs.currentWidget()
        from qt_geometry_diagnostics import dump_qt_geometry

        overflow = scroll.horizontalScrollBar().maximum()
        dump_qt_geometry(
            dialog,
            f"annual-visible-tab-{index}",
            named_widgets={"active_scroll": scroll},
            extra={"tab_index": index, "tab_text": dialog.tabs.tabText(index)},
        )
        assert overflow == 0, f"visible tab {index}: {dialog.tabs.tabText(index)} overflows by {overflow}px"
        assert dialog.rect().contains(dialog.close_button.mapTo(dialog, dialog.close_button.rect().bottomRight()))
