from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_lease_dialog_actual_save_returns_validated_input() -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog

    dialog = ClientLeaseDialog()
    dialog.lease_name.setText("辦公室")
    dialog.premises_address.setPlainText("臺北市大安區\n復興南路")
    dialog.landlord_name.setText("王房東")
    dialog.start_date.set_value("2026-01-01")
    dialog.end_date.set_value("2026-12-31")
    dialog.monthly_rent.setText("45,000")
    dialog.deposit_amount.setText("90000")
    dialog.reminder_days.setValue(30)
    dialog.notes.setPlainText("續約前兩個月\n先議價")
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.lease_input == LeaseInput(
        "辦公室", "臺北市大安區\n復興南路", "王房東", "2026-01-01", "2026-12-31", 45000, 90000, 30, "續約前兩個月\n先議價", "active"
    )


def test_lease_dialog_invalid_amount_stays_open_and_shows_chinese() -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog

    dialog = ClientLeaseDialog()
    dialog.lease_name.setText("錯誤金額")
    dialog.monthly_rent.setText("四萬五")
    with patch("taxops.ui.dialogs.client_lease_dialog.QMessageBox.warning", return_value=None) as warning:
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog.monthly_rent.text() == "四萬五"
    assert dialog.save_button.isEnabled()
    assert "金額" in warning.call_args.args[2]


def test_edit_dialog_stages_update_archive_and_create_in_one_save(container) -> None:
    _app()
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog

    client = container.clients.create_client(CreateClientInput(client_code="LEASEUI01", client_name="租約編輯客戶"))
    first = container.client_leases.create(client.id, LeaseInput("舊辦公室", start_date="2025-01-01"))
    second = container.client_leases.create(client.id, LeaseInput("待封存倉庫", start_date="2025-02-01"))
    dialog = EditClientDialog(container, client)
    dialog.stage_lease_update(first.id, LeaseInput("新辦公室", start_date="2026-01-01", notes="更新成功"))
    dialog.lease_table.selectRow(1)
    with patch(
        "taxops.ui.widgets.client_leases_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        QTest.mouseClick(dialog.leases_editor.archive_button, Qt.MouseButton.LeftButton)
    dialog.add_staged_lease(LeaseInput("新增分所", start_date="2026-03-01"))
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    active = container.client_leases.list_for_client(client.id)
    assert [(row.lease_name, row.notes) for row in active] == [("新辦公室", "更新成功"), ("新增分所", None)]
    archived = container.client_leases.get(second.id, include_deleted=True)
    assert archived is not None and archived.deleted_at is not None


def test_new_lease_attachment_action_is_disabled_with_visible_explanation() -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog

    dialog = ClientLeaseDialog()
    assert not dialog.upload_attachment_button.isEnabled()
    assert "儲存客戶" in dialog.attachment_explanation.text()


def test_persisted_lease_upload_button_calls_real_attachment_service(container, tmp_path: Path) -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog

    client = container.clients.create_client(CreateClientInput(client_code="LEASEATT", client_name="附件客戶"))
    lease = container.client_leases.create(client.id, LeaseInput("有附件租約"))
    source = tmp_path / "租約.pdf"
    source.write_bytes(b"%PDF-1.4 test")
    dialog = ClientLeaseDialog(container=container, client_id=client.id, lease_id=lease.id, initial=LeaseInput("有附件租約"))
    with patch("taxops.ui.dialogs.client_lease_dialog.QFileDialog.getOpenFileName", return_value=(str(source), "PDF (*.pdf)")), patch.object(
        container.attachments, "upload_lease_attachment", wraps=container.attachments.upload_lease_attachment
    ) as upload, patch("taxops.ui.dialogs.client_lease_dialog.QMessageBox.information", return_value=None):
        QTest.mouseClick(dialog.upload_attachment_button, Qt.MouseButton.LeftButton)
    upload.assert_called_once_with(client.id, lease.id, source)
    assert container.attachments.list_by_lease(lease.id)[0].original_filename == "租約.pdf"


def test_double_click_save_cannot_create_duplicate_profile(container) -> None:
    _app()
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container)
    dialog.profile_form.client_code.setText("DOUBLE01")
    dialog.profile_form.client_name.setText("雙擊測試")
    dialog.add_staged_lease(LeaseInput("唯一租約"))
    # QTest.mouseDClick emits a mouse-double-click event only; QPushButton's
    # real activation contract is its clicked signal. Two immediate clicks
    # reproduce a user's repeated activation and exercise the disabled guard.
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert len(container.clients.search_clients("DOUBLE01")) == 1
    client = container.clients.search_clients("DOUBLE01")[0]
    assert len(container.client_leases.list_for_client(client.id)) == 1


def test_archived_lease_reopens_as_read_only_history_with_attachment(
    container, tmp_path: Path
) -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseHistoryDialog
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="LEASE-HISTORY", client_name="歷史租約客戶")
    )
    lease = container.client_leases.create(
        client.id,
        LeaseInput(
            "歷史總公司",
            "臺北市中山區\n南京東路一段",
            "歷史房東",
            "2025-01-01",
            "2025-12-31",
            45678,
            90000,
            75,
            "完整備註\n第二行",
        ),
    )
    source = tmp_path / "歷史附件.pdf"
    source.write_bytes(b"%PDF-1.4 historical")
    container.attachments.upload_lease_attachment(client.id, lease.id, source)

    edit = EditClientDialog(container, client)
    edit.lease_table.selectRow(0)
    with patch(
        "taxops.ui.widgets.client_leases_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        QTest.mouseClick(edit.leases_editor.archive_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(edit.save_button, Qt.MouseButton.LeftButton)

    reopened = EditClientDialog(container, container.clients.get_client(client.id))
    assert reopened.lease_table.rowCount() == 1
    assert reopened.lease_table.item(0, 6).text() == "已封存（歷史）"
    reopened.lease_table.selectRow(0)
    assert not reopened.leases_editor.edit_button.isEnabled()
    assert not reopened.leases_editor.archive_button.isEnabled()
    assert reopened.leases_editor.view_button.isEnabled()

    observed: dict[str, object] = {}

    def inspect_history_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ClientLeaseHistoryDialog)
        observed["details"] = dialog.details_text.toPlainText()
        observed["attachments"] = dialog.attachments_text.toPlainText()
        observed["button_texts"] = [
            button.text() for button in dialog.findChildren(QPushButton)
        ]
        QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, inspect_history_dialog)
    QTest.mouseClick(reopened.leases_editor.view_button, Qt.MouseButton.LeftButton)
    assert "歷史總公司" in str(observed["details"])
    assert "臺北市中山區\n南京東路一段" in str(observed["details"])
    assert "45,678" in str(observed["details"])
    assert "完整備註\n第二行" in str(observed["details"])
    assert observed["attachments"] == "歷史附件.pdf"
    assert not any(
        token in text
        for text in observed["button_texts"]
        for token in ("上傳", "套用", "儲存", "刪除", "封存")
    )
    reopened.close()
    edit.close()
    reopened.deleteLater()
    edit.deleteLater()
    QApplication.processEvents()


def test_profile_and_lease_dialog_actions_reachable_after_scroll(container) -> None:
    _app()
    from taxops.ui.dialogs.client_lease_dialog import ClientLeaseDialog
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    new_dialog = NewClientDialog(container)
    new_dialog.resize(900, 540)
    new_dialog.show()
    QApplication.processEvents()
    new_dialog.scroll_area.verticalScrollBar().setValue(
        new_dialog.scroll_area.verticalScrollBar().maximum()
    )
    QTest.mouseClick(new_dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert new_dialog.result() == new_dialog.DialogCode.Rejected

    client = container.clients.create_client(
        CreateClientInput(client_code="SCROLL-EDIT", client_name="捲動儲存")
    )
    edit_dialog = EditClientDialog(container, client)
    edit_dialog.resize(900, 540)
    edit_dialog.show()
    QApplication.processEvents()
    edit_dialog.scroll_area.verticalScrollBar().setValue(
        edit_dialog.scroll_area.verticalScrollBar().maximum()
    )
    QTest.mouseClick(edit_dialog.save_button, Qt.MouseButton.LeftButton)
    assert edit_dialog.result() == edit_dialog.DialogCode.Accepted

    invalid = ClientLeaseDialog()
    invalid.resize(900, 512)
    invalid.show()
    QApplication.processEvents()
    with patch(
        "taxops.ui.dialogs.client_lease_dialog.QMessageBox.warning",
        return_value=None,
    ):
        QTest.mouseClick(invalid.save_button, Qt.MouseButton.LeftButton)
    assert invalid.result() != invalid.DialogCode.Accepted
    invalid.lease_name.setText("縮放租約")
    QTest.mouseClick(invalid.save_button, Qt.MouseButton.LeftButton)
    assert invalid.result() == invalid.DialogCode.Accepted

    cancelled = ClientLeaseDialog()
    cancelled.resize(900, 540)
    cancelled.show()
    QApplication.processEvents()
    QTest.mouseClick(cancelled.cancel_button, Qt.MouseButton.LeftButton)
    assert cancelled.result() == cancelled.DialogCode.Rejected
    for dialog in (new_dialog, edit_dialog, invalid, cancelled):
        dialog.close()
        dialog.deleteLater()
    QApplication.processEvents()
