from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput
from taxops.services.engagements import (
    BulkCreateEngagementInput,
    EngagementValidationError,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _client(container, code: str, name: str):
    return container.clients.create_client(
        CreateClientInput(client_code=code, client_name=name)
    )


def test_client_profile_address_editors_match_other_field_width() -> None:
    _app()
    from taxops.ui.widgets.client_profile_form import ClientProfileForm

    form = ClientProfileForm()

    expected = form.client_name.maximumWidth()
    assert expected < 16777215
    assert form.registered_address.maximumWidth() == expected
    assert form.contact_address.maximumWidth() == expected


def test_client_page_marks_and_expands_real_lease_rows_without_n_plus_one(
    container,
) -> None:
    _app()
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    client = _client(container, "LEASE-MARK", "看得到租約的客戶")
    container.client_leases.create(
        client.id,
        LeaseInput(
            "台北辦公室",
            premises_address="台北市中山區",
            start_date="2026-01-01",
            end_date="2026-12-31",
        ),
    )

    with patch.object(
        container.client_leases,
        "list_for_client",
        side_effect=AssertionError("collapsed list must not load lease detail"),
    ):
        page = ClientsPage(container)

    row = next(
        row
        for row in range(page._table.rowCount())
        if int(page._table.item(row, _COLUMN_ORDER.index("id")).text()) == client.id
    )
    assert "租約 1" in page._table.item(
        row, _COLUMN_ORDER.index("client_name")
    ).text()
    page._table.selectRow(row)
    page._lease_group.setChecked(True)
    QApplication.processEvents()
    assert page._lease_table.isVisibleTo(page)
    assert page._lease_table.rowCount() == 1
    assert page._lease_table.item(0, 0).text() == "台北辦公室"


def test_compliance_profile_dialog_creates_profile_and_is_reachable_from_workbench(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.dialogs.compliance_profile_dialog import ComplianceProfileDialog
    from taxops.ui.pages.annual_workbench_page import AnnualWorkbenchPage

    client = _client(container, "ANNUAL-PROFILE", "年度設定入口")
    dialog = ComplianceProfileDialog(container, preselected_client_id=client.id)
    assert dialog.client_combo.currentData() == client.id
    assert dialog.items_table.rowCount() > 0
    dialog.save_button.click()

    saved = container.compliance_profiles.get_for_client(client.id)
    assert saved is not None
    assert any(item.enabled for item in saved.items)

    opened: list[bool] = []

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            opened.append(True)

        def exec(self):
            return self.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.pages.annual_workbench_page.ComplianceProfileDialog", _Dialog
    )
    page = AnnualWorkbenchPage(container)
    QTest.mouseClick(page.profile_button, Qt.MouseButton.LeftButton)
    assert opened == [True]


def test_compliance_profile_dialog_blocks_empty_profile_and_reports_save_errors(
    container, monkeypatch
) -> None:
    _app()
    from PySide6.QtWidgets import QCheckBox

    from taxops.services.compliance_profiles import ComplianceProfileValidationError
    from taxops.ui.dialogs.compliance_profile_dialog import ComplianceProfileDialog

    client = _client(container, "PROFILE-ERROR", "設定檔錯誤")
    dialog = ComplianceProfileDialog(container, preselected_client_id=client.id)
    for row in range(dialog.items_table.rowCount()):
        checkbox = dialog.items_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(False)
    dialog.save_button.click()
    assert "至少啟用一項" in dialog.feedback_label.text()
    assert container.compliance_profiles.get_for_client(client.id) is None

    first_checkbox = dialog.items_table.cellWidget(0, 0)
    assert isinstance(first_checkbox, QCheckBox)
    first_checkbox.setChecked(True)
    monkeypatch.setattr(
        container.compliance_profiles,
        "upsert_profile",
        lambda *_args: (_ for _ in ()).throw(
            ComplianceProfileValidationError("compliance_profile.items.invalid")
        ),
    )
    dialog.save_button.click()
    assert "驗證失敗" in dialog.feedback_label.text()
    assert dialog.save_button.isEnabled()


def test_compliance_profile_dialog_handles_client_load_and_unexpected_save_failure(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.dialogs.compliance_profile_dialog import ComplianceProfileDialog

    monkeypatch.setattr(
        container.clients,
        "search_clients",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("read failed")),
    )
    empty = ComplianceProfileDialog(container)
    assert empty.client_combo.count() == 0
    assert not empty.save_button.isEnabled()

    monkeypatch.undo()
    client = _client(container, "PROFILE-LOCK", "設定檔鎖定")
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.compliance_profile_dialog.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        container.compliance_profiles,
        "upsert_profile",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("database locked")),
    )
    dialog = ComplianceProfileDialog(container, preselected_client_id=client.id)
    dialog.save_button.click()
    assert warnings == ["年度法遵設定檔未儲存，請稍後再試。"]
    assert dialog.save_button.isEnabled()


def test_compliance_profile_dialog_loads_existing_month_frequency_and_enabled_state(
    container,
) -> None:
    _app()
    from PySide6.QtWidgets import QCheckBox, QComboBox

    from taxops.services.compliance_profiles import ComplianceProfileItemInput
    from taxops.ui.dialogs.compliance_profile_dialog import ComplianceProfileDialog

    client = _client(container, "PROFILE-EXIST", "既有設定檔")
    container.compliance_profiles.upsert_profile(
        client.id,
        4,
        (ComplianceProfileItemInput("vat", "monthly", enabled=False),),
    )
    dialog = ComplianceProfileDialog(container, preselected_client_id=client.id)
    assert dialog.fiscal_month_spin.value() == 4
    vat_row = next(
        row
        for row in range(dialog.items_table.rowCount())
        if dialog.items_table.item(row, 1).data(Qt.ItemDataRole.UserRole) == "vat"
    )
    enabled = dialog.items_table.cellWidget(vat_row, 0)
    frequency = dialog.items_table.cellWidget(vat_row, 2)
    assert isinstance(enabled, QCheckBox) and not enabled.isChecked()
    assert isinstance(frequency, QComboBox) and frequency.currentData() == "monthly"


def test_bulk_engagement_create_is_atomic_and_page_has_real_entry(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.pages.engagements_page import EngagementsPage

    first = _client(container, "BULK-ENG-1", "批次案件一")
    second = _client(container, "BULK-ENG-2", "批次案件二")
    rows = container.engagements.create_for_clients(
        BulkCreateEngagementInput(
            client_ids=(first.id, second.id),
            engagement_name="2026 年度申報",
            tax_type="cit",
            period_name="2026",
        )
    )
    assert [row.client_id for row in rows] == [first.id, second.id]

    with pytest.raises(EngagementValidationError):
        container.engagements.create_for_clients(
            BulkCreateEngagementInput(
                client_ids=(first.id, 999999),
                engagement_name="不可部分成功",
                tax_type="cit",
                period_name="2026",
            )
        )
    assert not any(
        row.engagement_name == "不可部分成功"
        for row in container.engagements.list_by_client(first.id)
    )

    accepted: list[bool] = []

    class _Dialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            accepted.append(True)

        def exec(self):
            return self.DialogCode.Rejected

    monkeypatch.setattr(
        "taxops.ui.pages.engagements_page.BulkNewEngagementDialog", _Dialog
    )
    page = EngagementsPage(container)
    assert page._bulk_new_btn.text() == "多客戶新增"
    QTest.mouseClick(page._bulk_new_btn, Qt.MouseButton.LeftButton)
    assert accepted == [True]


def test_bulk_engagement_real_dialog_persists_checked_clients(container) -> None:
    _app()
    from taxops.ui.dialogs.bulk_new_engagement_dialog import (
        BulkNewEngagementDialog,
    )

    first = _client(container, "REAL-BULK-1", "真實批次一")
    second = _client(container, "REAL-BULK-2", "真實批次二")
    dialog = BulkNewEngagementDialog(
        container.engagements,
        [first, second],
    )
    dialog.clients_list.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.clients_list.item(1).setCheckState(Qt.CheckState.Checked)
    dialog.name_input.setText("同批年度案件")
    dialog.period_input.setText("2026")
    dialog.owner_input.setText("林會計師")
    dialog.due_date_input.set_value("2026-05-31")
    dialog.notes_input.setPlainText("第一行\n第二行")
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Accepted
    rows = [
        container.engagements.list_by_client(client.id)[0]
        for client in (first, second)
    ]
    assert {row.engagement_name for row in rows} == {"同批年度案件"}
    assert {row.owner for row in rows} == {"林會計師"}
    assert {row.due_date for row in rows} == {"2026-05-31"}


def test_bulk_engagement_dialog_blocks_empty_selection_and_validation_failure(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.dialogs.bulk_new_engagement_dialog import (
        BulkNewEngagementDialog,
    )

    client = _client(container, "BULK-ERROR", "批次錯誤")
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_new_engagement_dialog.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    dialog = BulkNewEngagementDialog(container.engagements, [client])
    dialog.save_button.click()
    assert warnings == ["請至少勾選一位客戶。"]

    dialog.clients_list.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.period_input.setText("2026")
    dialog.save_button.click()
    assert len(warnings) == 2
    assert dialog.save_button.isEnabled()
    assert container.engagements.list_by_client(client.id) == []


def test_bulk_engagement_dialog_unexpected_failure_is_visible_and_atomic(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.dialogs.bulk_new_engagement_dialog import (
        BulkNewEngagementDialog,
    )

    client = _client(container, "BULK-LOCK", "批次鎖定")
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_new_engagement_dialog.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        container.engagements,
        "create_for_clients",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("database locked")),
    )
    dialog = BulkNewEngagementDialog(container.engagements, [client])
    dialog.clients_list.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.name_input.setText("不可假成功")
    dialog.period_input.setText("2026")
    dialog.save_button.click()

    assert warnings == ["整批案件均未建立，請稍後再試。"]
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.save_button.isEnabled()


def test_tasks_page_exposes_clickable_sorting_by_default(container) -> None:
    _app()
    from taxops.ui.pages.tasks_page import TasksPage

    page = TasksPage(container)
    assert page._table.isSortingEnabled()
    assert page._table.horizontalHeader().sectionsClickable()


def test_lease_count_api_rejects_invalid_bulk_ids_and_handles_empty(container) -> None:
    from taxops.services.client_leases import ClientLeaseValidationError

    assert container.client_leases.counts_for_clients([]) == {}
    with pytest.raises(ClientLeaseValidationError):
        container.client_leases.counts_for_clients([True])


def test_real_client_template_preview_rejects_missing_client(container) -> None:
    from taxops.services.generated_messages import GeneratedMessageValidationError

    with pytest.raises(GeneratedMessageValidationError) as caught:
        container.gen_messages.build_client_example_variables(999999)
    assert caught.value.code == "gen_message.client_not_found"


def test_real_client_template_preview_prefers_linked_request_and_annual_item(
    container,
) -> None:
    from taxops.services.compliance_profiles import ComplianceProfileItemInput
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.services.engagements import CreateEngagementInput

    client = _client(container, "TMPL-LINKED", "已連動客戶")
    container.compliance_profiles.upsert_profile(
        client.id,
        1,
        (ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    annual = container.annual_work.confirm_preview(
        client.id,
        2026,
        container.annual_work.preview(client.id, 2026),
    ).items[0]
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="2026 年度結算",
            tax_type="cit",
            period_name="2026",
        )
    )
    container.annual_work.link_existing_engagement(annual.id, engagement.id)
    request, _items = container.doc_requests.create_request(
        CreateDocumentRequestInput(
            engagement_id=engagement.id,
            tax_type="cit",
            period_name="2026",
            item_names=("試算表",),
            due_date="2026-05-20",
        )
    )

    variables = container.gen_messages.build_client_example_variables(client.id)

    assert variables["engagement_name"] == "2026 年度結算"
    assert variables["period_name"] == request.period_name
    assert variables["annual_work_title"] == annual.title


def test_work_records_visually_groups_context_and_only_double_click_zooms(
    container, monkeypatch
) -> None:
    _app()
    from taxops.ui.pages.work_records_page import WorkRecordsPage

    page = WorkRecordsPage(container)
    assert page._template_group.title() == "流程範本與說明"
    assert page._run_group.title() == "執行中流程"
    assert "雙擊" in page._workflow_image.toolTip()

    opened: list[bool] = []
    monkeypatch.setattr(
        page, "_on_preview_workflow_image", lambda: opened.append(True)
    )
    QTest.mouseClick(page._workflow_image, Qt.MouseButton.LeftButton)
    assert opened == []
    QTest.mouseDClick(page._workflow_image, Qt.MouseButton.LeftButton)
    assert opened == [True]


def test_template_dialog_previews_real_client_and_annual_work_variables(
    container,
) -> None:
    _app()
    from taxops.services.compliance_profiles import ComplianceProfileItemInput
    from taxops.services.templates import ALLOWED_VARIABLES
    from taxops.ui.dialogs.template_form_dialog import TemplateFormDialog

    client = _client(container, "TMPL-ANNUAL", "真實範例客戶")
    container.compliance_profiles.upsert_profile(
        client.id,
        1,
        (ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    drafts = container.annual_work.preview(client.id, 2026)
    annual = container.annual_work.confirm_preview(client.id, 2026, drafts).items[0]

    variables = container.gen_messages.build_client_example_variables(client.id)
    assert variables["client_name"] == "真實範例客戶"
    assert variables["annual_work_title"] == annual.title
    assert variables["annual_operation_year"] == "2026"
    assert {
        "annual_work_title",
        "annual_operation_year",
        "annual_due_date",
        "annual_work_status",
    }.issubset(ALLOWED_VARIABLES)

    dialog = TemplateFormDialog(
        container.templates,
        container=container,
    )
    dialog._body.setPlainText("您好【客戶名稱】，年度工作：【年度工作標題】")
    index = dialog._example_client.findData(client.id)
    dialog._example_client.setCurrentIndex(index)
    dialog._refresh_example_preview()
    assert "真實範例客戶" in dialog._example_preview.toPlainText()
    assert annual.title in dialog._example_preview.toPlainText()
