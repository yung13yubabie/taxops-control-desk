from __future__ import annotations

import datetime
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_profile_form_keeps_multiline_values_and_same_address_semantics() -> None:
    _app()
    from taxops.ui.widgets.client_profile_form import ClientProfileForm

    form = ClientProfileForm()
    form.registered_address.setPlainText("臺北市中正區\n忠孝東路一段")
    form.contact_address.setPlainText("寄件：新北市板橋區\n請交警衛")
    form.note.setPlainText("只收電子檔\n申報前先通知")

    form.contact_same.setChecked(True)
    assert not form.contact_address.isEnabled()
    assert form.contact_address.toPlainText() == "寄件：新北市板橋區\n請交警衛"
    values = form.values_for_save()
    assert values["contact_address"] == "臺北市中正區\n忠孝東路一段"
    assert form.contact_address.toPlainText() == "寄件：新北市板橋區\n請交警衛"

    form.contact_same.setChecked(False)
    assert form.contact_address.isEnabled()
    assert form.values_for_save()["contact_address"] == "寄件：新北市板橋區\n請交警衛"
    for editor in (form.registered_address, form.contact_address, form.note):
        assert editor.minimumHeight() == 72
        assert editor.maximumHeight() == 16777215
        assert editor.wordWrapMode() == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere


def test_new_dialog_actual_save_persists_multiline_profile_and_two_leases(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container)
    dialog.profile_form.client_code.setText("PROFILE01")
    dialog.profile_form.client_name.setText("多租約股份有限公司")
    dialog.profile_form.registered_address.setPlainText("臺北市信義區\n市府路 1 號")
    dialog.profile_form.contact_same.setChecked(False)
    dialog.profile_form.contact_address.setPlainText("臺中市西區\n公益路 2 號")
    dialog.profile_form.note.setPlainText("每月五日前提醒\n紙本寄兩份")
    dialog.add_staged_lease(
        LeaseInput("總公司", "臺北市信義區", "林房東", "2026-01-01", "2026-12-31", 50000, 100000, 60, "一樓")
    )
    dialog.add_staged_lease(
        LeaseInput("倉庫", "新北市五股區", "陳房東", "2026-02-01", "2027-01-31", 30000, 60000, 45, "有貨梯")
    )

    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    saved = container.clients.search_clients("PROFILE01")[0]
    assert saved.registered_address == "臺北市信義區\n市府路 1 號"
    assert saved.contact_address == "臺中市西區\n公益路 2 號"
    assert saved.note == "每月五日前提醒\n紙本寄兩份"
    assert [row.lease_name for row in container.client_leases.list_for_client(saved.id)] == ["總公司", "倉庫"]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_profile_failure_keeps_dialog_inputs_rows_and_reenables_save(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container)
    dialog.profile_form.client_code.setText("FAILPROFILE")
    dialog.profile_form.client_name.setText("失敗保留測試")
    dialog.profile_form.note.setPlainText("第一行\n第二行")
    dialog.add_staged_lease(LeaseInput("不應消失", start_date="2026-01-01"))
    with patch.object(container.client_profiles, "create_client_with_leases", side_effect=RuntimeError("database locked")), patch(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", return_value=None
    ) as warning:
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog.profile_form.note.toPlainText() == "第一行\n第二行"
    assert dialog.lease_table.rowCount() == 1
    assert dialog.save_button.isEnabled()
    assert warning.call_count == 1
    assert "database locked" not in warning.call_args.args[2]
    assert container.clients.search_clients("FAILPROFILE") == []


def test_profile_dialog_constrained_geometry_keeps_actions_outside_scroll(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container)
    dialog.resize(900, 540)
    dialog.show()
    QApplication.processEvents()
    ys = [widget.mapTo(dialog, widget.rect().topLeft()).y() for widget in dialog.profile_form.field_widgets]
    assert ys == sorted(ys)
    assert dialog.scroll_area.geometry().bottom() < dialog.save_button.geometry().top()
    assert dialog.save_button.isVisible()
    assert dialog.cancel_button.isVisible()
    dialog.close()


def test_registry_prefill_changes_registered_but_not_contact_address(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog.profile_form.contact_same.setChecked(False)
    dialog.profile_form.contact_address.setPlainText("原本聯絡地址\n請勿覆蓋")
    dialog._registry_results = [{
        "business_name": "登記公司",
        "tax_id": "12345678",
        "business_address": "登記資料地址",
        "cache_version": "202607",
    }]
    dialog._result_combo.addItem("12345678 登記公司")
    dialog._result_combo.setCurrentIndex(0)
    dialog._on_fill()
    assert dialog.profile_form.registered_address.toPlainText() == "登記資料地址"
    assert dialog.profile_form.contact_address.toPlainText() == "原本聯絡地址\n請勿覆蓋"


def test_legacy_clients_service_constructor_disables_multiple_leases(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container.clients)
    assert not dialog.add_lease_button.isEnabled()
    assert "客戶管理" in dialog.lease_availability_label.text()


def test_clients_page_exposes_exact_addresses_and_lease_entry_without_n_plus_one(container) -> None:
    _app()
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    created = container.clients.create_client(
        CreateClientInput(
            client_code="PAGEPROFILE",
            client_name="頁面客戶",
            registered_address="登記第一行\n登記第二行",
            contact_address="聯絡第一行\n聯絡第二行",
            contact_address_same=False,
            note="紙本兩份\n先打電話",
        )
    )
    with patch.object(
        container.client_leases,
        "list_for_client",
        side_effect=AssertionError("client list refresh must not issue one lease query per row"),
    ):
        page = ClientsPage(container)
    page._table.selectRow(0)
    QApplication.processEvents()
    registered = page._table.item(0, _COLUMN_ORDER.index("registered_address"))
    contact = page._table.item(0, _COLUMN_ORDER.index("contact_address"))
    note = page._table.item(0, _COLUMN_ORDER.index("note"))
    assert registered.toolTip() == "登記第一行\n登記第二行"
    assert contact.toolTip() == "聯絡第一行\n聯絡第二行"
    assert note.toolTip() == "紙本兩份\n先打電話"
    assert page._note_detail.toPlainText() == "紙本兩份\n先打電話"
    assert page._leases_btn.text() == "租約管理"
    assert page._leases_btn.isEnabled()
    assert int(page._table.item(0, _COLUMN_ORDER.index("id")).text()) == created.id


def test_clients_page_registered_address_header_sorts_the_visible_column(container) -> None:
    _app()
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    container.clients.create_client(
        CreateClientInput(client_code="SORT-A", client_name="原本第一", registered_address="新竹市")
    )
    expected_first = container.clients.create_client(
        CreateClientInput(client_code="SORT-B", client_name="地址第一", registered_address="台中市")
    )
    page = ClientsPage(container)
    column = _COLUMN_ORDER.index("registered_address")
    page._table.horizontalHeader().sectionClicked.emit(column)
    first_id = int(page._table.item(0, _COLUMN_ORDER.index("id")).text())
    assert first_id == expected_first.id


def test_full_profile_save_keeps_multiple_lease_expiry_filter_authoritative(container) -> None:
    _app()
    from taxops.core.clock import today_iso
    from taxops.ui.action_registry import FilterKey
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    today = datetime.date.fromisoformat(today_iso())
    until = today + datetime.timedelta(days=30)
    inside = container.clients.create_client(
        CreateClientInput(
            client_code="EXP-IN",
            client_name="到期篩選保留",
            lease_start=today.isoformat(),
            lease_end=until.isoformat(),
        )
    )
    container.client_leases.create(
        inside.id, LeaseInput("下界租約", end_date=today.isoformat(), status="active")
    )
    container.client_leases.create(
        inside.id, LeaseInput("上界租約", end_date=until.isoformat(), status="active")
    )

    # Production dialog saves only the profile. It currently clears the legacy
    # scalar dates, so the expiry feature must rely on client_leases instead.
    dialog = EditClientDialog(container, inside)
    dialog.profile_form.note.setPlainText("只更新客戶說明")
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    saved = container.clients.get_client(inside.id)
    assert saved is not None and saved.lease_end is None

    archived_client = container.clients.create_client(
        CreateClientInput(client_code="EXP-ARCH", client_name="封存租約")
    )
    archived_lease = container.client_leases.create(
        archived_client.id, LeaseInput("已封存", end_date=today.isoformat())
    )
    container.client_leases.archive(archived_lease.id)

    expired_status_client = container.clients.create_client(
        CreateClientInput(client_code="EXP-STATUS", client_name="狀態已到期")
    )
    container.client_leases.create(
        expired_status_client.id,
        LeaseInput("非有效狀態", end_date=today.isoformat(), status="expired"),
    )

    deleted_client = container.clients.create_client(
        CreateClientInput(client_code="EXP-DEL", client_name="已停用客戶")
    )
    container.client_leases.create(
        deleted_client.id, LeaseInput("客戶已停用", end_date=today.isoformat())
    )
    container.clients.delete_client(deleted_client.id)

    before_client = container.clients.create_client(
        CreateClientInput(client_code="EXP-BEFORE", client_name="早於範圍")
    )
    container.client_leases.create(
        before_client.id,
        LeaseInput("昨日到期", end_date=(today - datetime.timedelta(days=1)).isoformat()),
    )
    after_client = container.clients.create_client(
        CreateClientInput(client_code="EXP-AFTER", client_name="晚於範圍")
    )
    container.client_leases.create(
        after_client.id,
        LeaseInput("範圍外", end_date=(until + datetime.timedelta(days=1)).isoformat()),
    )

    page = ClientsPage(container)
    page.set_filter(FilterKey.LEASE_EXPIRING)
    ids = [
        int(page._table.item(row, _COLUMN_ORDER.index("id")).text())
        for row in range(page._table.rowCount())
    ]
    assert ids == [inside.id]
    assert "lease_start" not in _COLUMN_ORDER
    assert "lease_end" not in _COLUMN_ORDER
