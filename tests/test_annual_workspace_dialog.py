from __future__ import annotations

from dataclasses import replace
import time
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError
from taxops.ui.dialogs.annual_workspace_dialog import AnnualWorkspaceDialog
from taxops.ui.dialogs import annual_workspace_dialog
from taxops.ui.workers import annual_client_search


def _client_with_two_drafts(container):
    client = container.clients.create_client(
        CreateClientInput(client_code="ANNUAL-001", client_name="安年會計測試客戶")
    )
    container.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("corporate_income_tax", "annual"),
            ComplianceProfileItemInput("company_annual", "annual"),
        ),
    )
    return client


def _add_dialog(qtbot, dialog: AnnualWorkspaceDialog) -> None:
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: not dialog._search_workers, timeout=2000)


def test_double_click_confirm_calls_service_once_and_persists_exact_selection(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    assert dialog.preview_table.rowCount() == 2
    dialog.preview_table.set_checked(1, False)

    confirm_spy = Mock(wraps=container.annual_work.confirm_preview_selection)
    monkeypatch.setattr(
        container.annual_work, "confirm_preview_selection", confirm_spy
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert confirm_spy.call_count == 1
    qtbot.waitUntil(
        lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    rows = container.conn.execute(
        "SELECT item_key FROM annual_work_items ORDER BY item_key"
    ).fetchall()
    assert [row["item_key"] for row in rows] == [
        dialog.expected_drafts[0].item_key
    ]


def test_native_mouse_double_click_never_confirms_twice(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    confirm_spy = Mock(wraps=container.annual_work.confirm_preview_selection)
    monkeypatch.setattr(
        container.annual_work, "confirm_preview_selection", confirm_spy
    )

    qtbot.mouseDClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert confirm_spy.call_count <= 1


def test_edited_standard_subset_and_custom_row_are_persisted_exactly(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)

    standard_key = dialog.preview_table.item_key(0)
    dialog.preview_table.set_title(0, "安年精確編輯標準列")
    dialog.preview_table.set_tax_year(0, 2024)
    dialog.preview_table.set_period_code(0, "FY-2024")
    dialog.preview_table.set_due_date(0, "2026-06-30")
    dialog.preview_table.set_checked(1, False)

    qtbot.mouseClick(dialog.add_custom_button, Qt.MouseButton.LeftButton)
    custom_row = dialog.preview_table.rowCount() - 1
    custom_key = dialog.preview_table.item_key(custom_row)
    assert custom_key.startswith("custom:")
    assert custom_key == custom_key.lower()
    dialog.preview_table.set_work_type(custom_row, "vat")
    dialog.preview_table.set_title(custom_row, "安年客製加值稅覆核")
    dialog.preview_table.set_tax_year(custom_row, 2025)
    dialog.preview_table.set_period_code(custom_row, "11-12")
    dialog.preview_table.set_due_date(custom_row, "2026-01-15")
    assert dialog.preview_table.item_key(custom_row) == custom_key

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    rows = container.conn.execute(
        "SELECT item_key, work_type, title, tax_year, period_code, due_date "
        "FROM annual_work_items ORDER BY item_key"
    ).fetchall()
    by_key = {row["item_key"]: dict(row) for row in rows}
    assert by_key == {
        standard_key: {
            "item_key": standard_key,
            "work_type": "corporate_income_tax",
            "title": "安年精確編輯標準列",
            "tax_year": 2024,
            "period_code": "FY-2024",
            "due_date": "2026-06-30",
        },
        custom_key: {
            "item_key": custom_key,
            "work_type": "vat",
            "title": "安年客製加值稅覆核",
            "tax_year": 2025,
            "period_code": "11-12",
            "due_date": "2026-01-15",
        },
    }


def test_no_selection_and_invalid_date_keep_dialog_open_and_focus_first_error(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    for row in range(dialog.preview_table.rowCount()):
        dialog.preview_table.set_checked(row, False)

    assert dialog.confirm_button.isEnabled()
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "請至少勾選一項年度工作。"
    first_selection = dialog.preview_table.row_widgets(0).selected
    qtbot.waitUntil(first_selection.hasFocus, timeout=500)

    dialog.preview_table.set_checked(0, True)
    due_input = dialog.preview_table.row_widgets(0).due_date
    due_input.setText("2026-02-30")
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "到期日須為 YYYY-MM-DD 格式。"
    assert due_input.hasFocus()


def test_invalid_confirm_focus_survives_delayed_initial_client_search(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)

    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.15)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.client_combo.isEnabled()
    assert not dialog.load_button.isEnabled()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    assert dialog.preview_table.rowCount() == 0
    qtbot.waitUntil(lambda: not dialog._search_workers, timeout=1000)
    assert dialog.client_combo.isEnabled()
    assert dialog.load_button.isEnabled()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    for row in range(dialog.preview_table.rowCount()):
        dialog.preview_table.set_checked(row, False)
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text() == "請至少勾選一項年度工作。"
    assert dialog.preview_table.rowCount() == 2
    assert dialog.preview_table.row_widgets(0).selected.hasFocus()


def test_preview_load_does_not_pump_nested_qt_events(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    process_events = Mock()
    monkeypatch.setattr(QApplication, "processEvents", process_events)

    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)

    assert dialog.preview_table.rowCount() == 2
    process_events.assert_not_called()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("title", "工" * 501),
        ("period_code", "期" * 51),
        ("tax_year", "10000"),
        ("due_date", "2026-01-010"),
    ),
)
def test_overlong_preview_input_is_preserved_then_rejected_without_writing(
    qtbot, container, field_name, value
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.waitUntil(lambda: not dialog._search_workers, timeout=2000)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    widget = getattr(dialog.preview_table.row_widgets(0), field_name)

    widget.setText(value)
    assert widget.text() == value
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    qtbot.waitUntil(widget.hasFocus, timeout=500)
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0


def test_stale_error_preserves_inputs_checks_custom_uuid_and_can_retry(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_checked(1, False)
    qtbot.mouseClick(dialog.add_custom_button, Qt.MouseButton.LeftButton)
    custom_row = dialog.preview_table.rowCount() - 1
    custom_key = dialog.preview_table.item_key(custom_row)
    dialog.preview_table.set_title(custom_row, "錯誤後仍保留")
    expected_before = dialog.expected_drafts
    real_confirm = container.annual_work.confirm_preview_selection
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AnnualWorkValidationError(
                "annual_work.drafts.profile_mismatch"
            )
        return real_confirm(*args, **kwargs)

    monkeypatch.setattr(
        container.annual_work, "confirm_preview_selection", fail_once
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "預覽已過期，請重新載入後再試。"
    assert "annual_work.drafts.profile_mismatch" not in dialog.feedback_label.text()
    assert dialog.expected_drafts == expected_before
    assert dialog.preview_table.item_key(custom_row) == custom_key
    assert dialog.preview_table.row_widgets(custom_row).title.text() == "錯誤後仍保留"
    assert not dialog.preview_table.is_checked(1)
    assert all(
        control.isEnabled()
        for control in (
            dialog.client_combo,
            dialog.operation_year_spin,
            dialog.load_button,
            dialog.add_custom_button,
            dialog.confirm_button,
        )
    )

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert calls == 2
    qtbot.waitUntil(
        lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_work_items WHERE item_key = ?", (custom_key,)
    ).fetchone()[0] == 1


def test_snapshot_none_never_shows_success_and_same_payload_can_retry(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_checked(1, False)
    qtbot.mouseClick(dialog.add_custom_button, Qt.MouseButton.LeftButton)
    custom_row = dialog.preview_table.rowCount() - 1
    dialog.preview_table.set_title(custom_row, "快照重試保留")
    custom_key = dialog.preview_table.item_key(custom_row)
    real_snapshot = container.annual_work.get_workspace_snapshot
    reads = 0

    def missing_once(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            return None
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(container.annual_work, "get_workspace_snapshot", missing_once)
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )
    assert "建立成功" not in dialog.feedback_label.text()
    assert dialog.preview_table.item_key(custom_row) == custom_key
    assert dialog.preview_table.row_widgets(custom_row).title.text() == "快照重試保留"
    assert dialog.confirm_button.isEnabled()
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_work_items"
    ).fetchone()[0] == 2

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "此年度工作已存在，未新增重複資料。"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_work_items"
    ).fetchone()[0] == 2


def test_client_or_year_change_invalidates_preview_and_old_expected_token(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    original = dialog.expected_drafts
    assert original

    dialog.operation_year_spin.setValue(2025)
    assert dialog.expected_drafts == ()
    assert dialog.preview_table.rowCount() == 0
    assert not dialog.confirm_button.isEnabled()
    assert "請重新載入預覽" in dialog.feedback_label.text()

    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    assert dialog.expected_drafts
    assert dialog.expected_drafts != original
    dialog.client_combo.setCurrentIndex(0)
    assert dialog.expected_drafts == ()
    assert dialog.preview_table.rowCount() == 0
    assert not dialog.confirm_button.isEnabled()


def test_profile_missing_and_all_disabled_use_fixed_safe_chinese_errors(
    qtbot, container
) -> None:
    missing = container.clients.create_client(
        CreateClientInput(client_code="NO-PROFILE", client_name="未設定檔客戶")
    )
    disabled = container.clients.create_client(
        CreateClientInput(client_code="DISABLED", client_name="全停用客戶")
    )
    container.compliance_profiles.upsert_profile(
        disabled.id,
        fiscal_year_start_month=1,
        items=(
            ComplianceProfileItemInput("corporate_income_tax", "annual", False),
        ),
    )
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=missing.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text() == "此客戶尚未設定年度法遵檔案。"
    assert "annual_work.profile_not_found" not in dialog.feedback_label.text()

    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(disabled.id))
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    assert dialog.feedback_label.text() == (
        "此客戶的年度法遵檔案未啟用任何工作類型。"
    )
    assert "annual_work.enabled_items.empty" not in dialog.feedback_label.text()


def test_fixed_900_by_540_layout_keeps_scroll_table_and_bottom_actions_visible(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.resize(900, 540)
    dialog.show()
    QApplication.processEvents()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)

    assert dialog.minimumSizeHint().width() <= 900
    assert dialog.minimumSizeHint().height() <= 540
    assert dialog.preview_table.font().pixelSize() >= 13
    assert dialog.preview_table.horizontalScrollBarPolicy() != (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert all(
        button.font().pixelSize() >= 14
        for button in dialog.findChildren(QPushButton)
    )
    for button in (
        dialog.client_search_button,
        dialog.load_button,
        dialog.add_custom_button,
        dialog.cancel_button,
        dialog.confirm_button,
    ):
        assert dialog.rect().contains(
            button.mapTo(dialog, button.rect().topLeft())
        )
        assert dialog.rect().contains(
            button.mapTo(dialog, button.rect().bottomRight())
        )


def test_snapshot_workspace_mismatch_never_accepts_or_shows_success(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    real_snapshot = container.annual_work.get_workspace_snapshot

    def mismatched_snapshot(*args, **kwargs):
        snapshot = real_snapshot(*args, **kwargs)
        if snapshot is None:
            return None
        return replace(
            snapshot,
            workspace=replace(snapshot.workspace, id=snapshot.workspace.id + 100),
        )

    monkeypatch.setattr(
        container.annual_work, "get_workspace_snapshot", mismatched_snapshot
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )
    assert "建立成功" not in dialog.feedback_label.text()
    assert dialog.confirm_button.isEnabled()


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    (
        ("title", "錯誤的快照標題"),
        ("work_type", "vat"),
        ("tax_year", 1912),
        ("period_code", "錯誤期間"),
        ("suggested_due_date", "2099-11-30"),
        ("due_date", "2099-12-31"),
    ),
)
def test_new_item_field_mismatch_never_accepts_or_shows_success(
    qtbot, container, monkeypatch, field, wrong_value
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    expected_before = dialog.expected_drafts
    first_key = dialog.preview_table.item_key(0)
    first_title = dialog.preview_table.row_widgets(0).title.text()
    real_snapshot = container.annual_work.get_workspace_snapshot

    def wrong_item_snapshot(*args, **kwargs):
        snapshot = real_snapshot(*args, **kwargs)
        if snapshot is None:
            return None
        return replace(
            snapshot,
            items=(replace(snapshot.items[0], **{field: wrong_value}),)
            + snapshot.items[1:],
        )

    monkeypatch.setattr(
        container.annual_work, "get_workspace_snapshot", wrong_item_snapshot
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )
    assert "建立成功" not in dialog.feedback_label.text()
    assert dialog.expected_drafts == expected_before
    assert dialog.preview_table.item_key(0) == first_key
    assert dialog.preview_table.row_widgets(0).title.text() == first_title
    assert dialog.confirm_button.isEnabled()


def test_snapshot_precheck_failure_never_writes_and_preserves_payload(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_title(0, "前置讀取失敗仍保留")
    expected = dialog.expected_drafts
    confirm_spy = Mock(wraps=container.annual_work.confirm_preview_selection)
    monkeypatch.setattr(
        container.annual_work, "confirm_preview_selection", confirm_spy
    )
    monkeypatch.setattr(
        container.annual_work,
        "get_workspace_snapshot",
        Mock(side_effect=RuntimeError("RAW PRECHECK SECRET")),
    )

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert confirm_spy.call_count == 0
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_workspaces"
    ).fetchone()[0] == 0
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "無法讀取目前的年度工作，請稍後再試。"
    assert "SECRET" not in dialog.feedback_label.text()
    assert dialog.expected_drafts == expected
    assert dialog.preview_table.row_widgets(0).title.text() == "前置讀取失敗仍保留"
    assert dialog.confirm_button.isEnabled()


def test_post_snapshot_missing_selected_key_never_accepts(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    real_snapshot = container.annual_work.get_workspace_snapshot

    def missing_selected(*args, **kwargs):
        snapshot = real_snapshot(*args, **kwargs)
        if snapshot is None:
            return None
        return replace(snapshot, items=snapshot.items[1:])

    monkeypatch.setattr(
        container.annual_work, "get_workspace_snapshot", missing_selected
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )


def test_post_snapshot_missing_existing_unselected_item_never_accepts(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    service = container.annual_work
    expected = service.preview(client.id, 2026)
    first = service.confirm_preview_selection(
        client.id,
        2026,
        expected_drafts=expected,
        selected_drafts=expected[:1],
    )
    existing_key = first.items[0].item_key
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_checked(0, False)
    expected_before = dialog.expected_drafts
    first_key = dialog.preview_table.item_key(0)
    first_title = dialog.preview_table.row_widgets(0).title.text()
    real_snapshot = service.get_workspace_snapshot
    calls = 0

    def missing_existing_only_post_confirm(*args, **kwargs):
        nonlocal calls
        calls += 1
        snapshot = real_snapshot(*args, **kwargs)
        if snapshot is None or calls == 1:
            return snapshot
        return replace(
            snapshot,
            items=tuple(
                item for item in snapshot.items if item.item_key != existing_key
            ),
        )

    monkeypatch.setattr(
        service, "get_workspace_snapshot", missing_existing_only_post_confirm
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )
    assert "建立成功" not in dialog.feedback_label.text()
    assert dialog.expected_drafts == expected_before
    assert dialog.preview_table.item_key(0) == first_key
    assert dialog.preview_table.row_widgets(0).title.text() == first_title
    assert dialog.confirm_button.isEnabled()


def test_post_snapshot_unexpected_extra_item_never_accepts(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_checked(1, False)
    expected_before = dialog.expected_drafts
    first_key = dialog.preview_table.item_key(0)
    first_title = dialog.preview_table.row_widgets(0).title.text()
    real_snapshot = container.annual_work.get_workspace_snapshot

    def unexpected_extra_only_post_confirm(*args, **kwargs):
        snapshot = real_snapshot(*args, **kwargs)
        if snapshot is None:
            return None
        unexpected = replace(
            snapshot.items[0],
            id=snapshot.items[0].id + 100,
            item_key="unexpected:post-snapshot",
        )
        return replace(snapshot, items=snapshot.items + (unexpected,))

    monkeypatch.setattr(
        container.annual_work,
        "get_workspace_snapshot",
        unexpected_extra_only_post_confirm,
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )
    assert "建立成功" not in dialog.feedback_label.text()
    assert dialog.expected_drafts == expected_before
    assert dialog.preview_table.item_key(0) == first_key
    assert dialog.preview_table.row_widgets(0).title.text() == first_title
    assert dialog.confirm_button.isEnabled()


def test_result_insert_count_mismatch_never_accepts(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    real_confirm = container.annual_work.confirm_preview_selection

    def wrong_count(*args, **kwargs):
        result = real_confirm(*args, **kwargs)
        return replace(result, inserted_item_count=result.inserted_item_count + 1)

    monkeypatch.setattr(
        container.annual_work, "confirm_preview_selection", wrong_count
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == (
        "資料可能已寫入，但重新讀取驗證失敗，請重新整理後再試。"
    )


def test_existing_manually_edited_item_is_not_overwritten_on_second_confirm(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    service = container.annual_work
    expected = service.preview(client.id, 2026)
    first = service.confirm_preview_selection(
        client.id,
        2026,
        expected_drafts=expected,
        selected_drafts=expected[:1],
    )
    container.conn.execute(
        "UPDATE annual_work_items SET work_type = ?, title = ?, tax_year = ?, "
        "period_code = ?, due_date = ? WHERE id = ?",
        ("vat", "人工保留標題", 2023, "人工期間", "2026-12-20", first.items[0].id),
    )
    container.conn.commit()
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_checked(1, False)

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=2000
    )
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "此年度工作已存在，未新增重複資料。"
    row = container.conn.execute(
        "SELECT work_type, title, tax_year, period_code, due_date "
        "FROM annual_work_items WHERE id = ?",
        (first.items[0].id,),
    ).fetchone()
    assert dict(row) == {
        "work_type": "vat",
        "title": "人工保留標題",
        "tax_year": 2023,
        "period_code": "人工期間",
        "due_date": "2026-12-20",
    }


def test_dialog_owns_parent_and_is_modal(qtbot, container) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)

    dialog = AnnualWorkspaceDialog(container, parent=parent)
    _add_dialog(qtbot, dialog)

    assert dialog.parent() is parent
    assert dialog.isModal()


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (
            AnnualWorkError("annual_work.transaction.busy"),
            "資料庫忙碌中，請稍後再試。",
        ),
        (
            AnnualWorkValidationError("annual_work.snapshot.too_many_items"),
            "項目數超過上限 500，請減少後再試。",
        ),
        (
            AnnualWorkValidationError("annual_work.draft.invalid"),
            "輸入資料驗證失敗，請檢查後再試。",
        ),
        (
            RuntimeError("RAW PRIVATE SECRET"),
            "建立年度工作失敗，請稍後再試。",
        ),
    ),
)
def test_confirm_error_mapping_is_fixed_safe_and_preserves_payload(
    qtbot, container, monkeypatch, failure, expected
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    dialog.preview_table.set_title(0, "服務錯誤仍保留")
    monkeypatch.setattr(
        container.annual_work,
        "confirm_preview_selection",
        Mock(side_effect=failure),
    )

    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == expected
    assert "annual_work." not in dialog.feedback_label.text()
    assert "SECRET" not in dialog.feedback_label.text()
    assert dialog.preview_table.row_widgets(0).title.text() == "服務錯誤仍保留"
    assert dialog.confirm_button.isEnabled()
    assert dialog.load_button.isEnabled()


def test_selector_bounds_immutable_standard_identity_tooltips_and_cancel_wiring(
    qtbot, container
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    _add_dialog(qtbot, dialog)
    dialog.show()
    assert dialog.client_combo.currentData() == client.id
    assert dialog.client_combo.currentText() == (
        f"{client.client_code}｜{client.client_name}"
    )
    assert dialog.operation_year_spin.minimum() == 1912
    assert dialog.operation_year_spin.maximum() == 9999
    assert dialog.operation_year_spin.value() == 2026
    dialog.operation_year_spin.setValue(1912)
    assert dialog.operation_year_spin.value() == 1912
    dialog.operation_year_spin.setValue(2026)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)

    standard_key = dialog.preview_table.item_key(0)
    assert dialog.preview_table.row_widgets(0).work_type is None
    with pytest.raises(ValueError, match="immutable"):
        dialog.preview_table.set_work_type(0, "vat")
    dialog.preview_table.set_title(0, "完整年度工作標題 tooltip")
    assert dialog.preview_table.row_widgets(0).title.toolTip() == (
        "完整年度工作標題 tooltip"
    )
    assert dialog.preview_table.item_key(0) == standard_key

    qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected
