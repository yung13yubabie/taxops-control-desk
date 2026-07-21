from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError
from taxops.ui.dialogs.annual_workspace_dialog import AnnualWorkspaceDialog


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


def test_double_click_confirm_calls_service_once_and_persists_exact_selection(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    for row in range(dialog.preview_table.rowCount()):
        dialog.preview_table.set_checked(row, False)

    assert dialog.confirm_button.isEnabled()
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "請至少勾選一項年度工作。"
    assert dialog.preview_table.hasFocus()

    dialog.preview_table.set_checked(0, True)
    due_input = dialog.preview_table.row_widgets(0).due_date
    due_input.setText("2026-02-30")
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.feedback_label.text() == "到期日須為 YYYY-MM-DD 格式。"
    assert due_input.hasFocus()


def test_stale_error_preserves_inputs_checks_custom_uuid_and_can_retry(
    qtbot, container, monkeypatch
) -> None:
    client = _client_with_two_drafts(container)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=client.id, operation_year=2026
    )
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
        if reads == 1:
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
    qtbot.mouseClick(dialog.load_button, Qt.MouseButton.LeftButton)
    real_snapshot = container.annual_work.get_workspace_snapshot

    def mismatched_snapshot(*args, **kwargs):
        snapshot = real_snapshot(*args, **kwargs)
        assert snapshot is not None
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
    qtbot.addWidget(dialog)
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
    qtbot.addWidget(dialog)
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
