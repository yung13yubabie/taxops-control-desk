"""v0.32 shell keeps every module and resolves read-only targets by real IDs."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox, QVBoxLayout

from taxops.i18n import NAV_LABELS
from taxops.services.attachments import UploadAttachmentInput
from taxops.services.clients import CreateClientInput
from taxops.services.document_requests import CreateDocumentRequestInput
from taxops.services.engagements import CreateEngagementInput
from taxops.services.tasks import CreateTaskInput
from taxops.ui import tokens
from taxops.ui.action_registry import (
    NAV_ORDER, PAGE_ANNUAL_WORKBENCH, PAGE_ATTACHMENTS, PAGE_CLIENTS,
    PAGE_ENGAGEMENTS, PAGE_TASKS,
)
from taxops.ui.main_window import MainWindow
from taxops.ui.navigation import NavigationTarget
from taxops.ui.pages.annual_workbench_page import AnnualWorkbenchPage
from taxops.ui.pages.clients_page import ClientsPage
from taxops.ui.pages.document_requests_page import (
    DocumentMutationEvidence, DocumentRequestsPage, _PAGE_SIZE,
)
from taxops.ui.style import apply as apply_style
from taxops.ui.widgets.workspace_navigation import (
    PRIMARY_DESTINATIONS, PRIMARY_LABELS, TOOL_GROUPS, WorkspaceNavigation,
)


@pytest.fixture
def records(container, tmp_path):
    rows = []
    for index in range(2):
        client = container.clients.create_client(CreateClientInput(
            client_code=f"W032-{index}", client_name=f"測試客戶{index}",
        ))
        case = container.engagements.create_engagement(CreateEngagementInput(
            client_id=client.id, engagement_name="同名案件",
            tax_type="vat", period_name="2026-10",
        ))
        request, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
            engagement_id=case.id, tax_type="vat", period_name="2026-10",
            request_name="同名批次", item_names=(f"憑證{index}",),
        ))
        task = container.tasks.create_task(CreateTaskInput(
            client_id=client.id, engagement_id=case.id, title="同名待辦",
        ))
        source = tmp_path / f"憑證{index}.txt"
        source.write_text(f"合成測試{index}", encoding="utf-8")
        attachment = container.attachments.upload_attachment(UploadAttachmentInput(
            engagement_id=case.id, request_id=request.id, source_path=source,
        ))
        rows.append((client, case, request, task, attachment))
    return rows


@pytest.fixture
def warnings(monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    return messages


@pytest.fixture
def window(qapp, container, records, warnings):
    widget = MainWindow(container)
    widget.resize(1093, 614)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def business_snapshot(container):
    return {
        name: tuple(tuple(row) for row in container.conn.execute(f"SELECT * FROM {name} ORDER BY id"))
        for name in ("clients", "engagements", "attachments", "workflow_tasks",
                     "document_requests", "document_request_items", "annual_work_items")
    }


def request_ids(page):
    return {page.request_id_at(row) for row in range(page._req_table.rowCount())}


def test_all_twelve_destinations_are_present_once_with_true_labels(window):
    grouped = tuple(p for _, destinations in TOOL_GROUPS for p in destinations)
    assert len(NAV_ORDER) == 12
    assert len(PRIMARY_DESTINATIONS + grouped) == len(set(NAV_ORDER))
    assert set(PRIMARY_DESTINATIONS + grouped) == set(NAV_ORDER)
    assert set(window._page_indices) == set(NAV_ORDER)
    assert set(window._nav._buttons) | set(window._nav._actions) == set(NAV_ORDER)
    for page_id, button in window._nav._buttons.items():
        assert button.text() == PRIMARY_LABELS[page_id]
        assert button.toolTip() == NAV_LABELS[page_id]
        assert button.property("role") in tokens.BUTTON_ROLES
        assert not button.icon().isNull()
    for page_id, action in window._nav._actions.items():
        assert action.text() == NAV_LABELS[page_id]
        assert action.data() == page_id
        assert not action.icon().isNull()
    assert window._stack.currentIndex() == window._page_indices[PAGE_ATTACHMENTS]


def test_real_buttons_and_tools_actions_open_all_twelve_real_pages(window, qapp):
    expected = {
        "clients": "ClientsPage", "annual_workbench": "AnnualWorkbenchPage",
        "engagements": "EngagementsPage", "tasks": "TasksPage",
        "work_records": "WorkRecordsPage", "templates": "TemplatesPage",
        "registry": "RegistryPage", "late_fee": "LateFeePage",
        "attachments": "AttachmentsPage", "folder_bookmarks": "FolderBookmarksPage",
        "recurring_billing": "RecurringBillingPage", "settings": "SettingsPage",
    }
    assert set(expected) == set(NAV_ORDER)
    for page_id, button in window._nav._buttons.items():
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert type(window._stack.currentWidget()).__name__ == expected[page_id]
        assert window._nav.currentRow() == NAV_ORDER.index(page_id)
        assert button.isChecked()
    for page_id, action in window._nav._actions.items():
        action.trigger()
        qapp.processEvents()
        assert type(window._stack.currentWidget()).__name__ == expected[page_id]
        assert action.isChecked()
        assert window._nav._tools_button.text() == NAV_LABELS[page_id]


def test_annual_is_one_click_primary_and_new_clients_page_is_unchanged(window):
    window._nav._buttons[PAGE_ANNUAL_WORKBENCH].click()
    assert isinstance(window._stack.currentWidget(), AnnualWorkbenchPage)
    assert window._stack.currentWidget().future_action_button.isEnabled()
    assert window.open_target(NavigationTarget(PAGE_CLIENTS))
    assert isinstance(window._stack.currentWidget(), ClientsPage)
    assert window._stack.currentWidget()._inspector is not None


@pytest.mark.parametrize("width", [900, 1093, 1366])
def test_navigation_labels_fit_without_tiny_fonts(qapp, qtbot, width):
    old_style = qapp.styleSheet()
    try:
        apply_style(qapp)
        nav = WorkspaceNavigation()
        qtbot.addWidget(nav)
        nav.resize(width, nav.sizeHint().height())
        nav.show()
        qapp.processEvents()
        assert nav.width() == width
        widgets = [*nav._buttons.values(), nav._tools_button]
        for widget in widgets:
            assert widget.isVisible()
            assert widget.font().pixelSize() >= 14
            assert widget.width() >= widget.minimumSizeHint().width()
            assert nav.rect().contains(widget.geometry())
        assert all(not a.geometry().intersects(b.geometry())
                   for a, b in zip(widgets, widgets[1:]))
    finally:
        qapp.setStyleSheet(old_style)


@pytest.mark.parametrize("limited", [False, True])
@pytest.mark.parametrize("old_selection", [False, True])
@pytest.mark.parametrize("with_request", [False, True])
def test_exact_case_scope_survives_hidden_master_refresh(
    window, container, records, monkeypatch, limited, old_selection, with_request,
):
    _, case, request, _, _ = records[0]
    other_case, other_request = records[1][1:3]
    page = window._eng_page
    if old_selection:
        for row in range(page._table.rowCount()):
            if int(page._table.item(row, 0).text()) == other_case.id:
                page._table.selectRow(row)
                break
    else:
        page._table.clearSelection()
    if limited:
        monkeypatch.setattr(container.engagements, "list_all", lambda **kw: [other_case])
    assert window.open_target(NavigationTarget(
        PAGE_ENGAGEMENTS, engagement_id=case.id,
        request_id=request.id if with_request else None,
    ))
    for refresh in (lambda: None, page.refresh_context, page._on_load_and_refresh):
        refresh()
        assert page._current_engagement_id == case.id
        assert page._requests_page._engagement_id == case.id
        assert page._requests_page._engagement_combo.currentData() == case.id
        assert request_ids(page._requests_page) == {request.id}
        assert other_request.id not in request_ids(page._requests_page)
        assert page._stack.currentIndex() == (2 if with_request else 1)
        if with_request:
            assert page._current_request_id == request.id
            assert page._requests_page._selected_request_id() == request.id
            assert page._items_page._items_only_request_id == request.id
            assert page._bc_request_btn.text() == request.request_name


def test_request_after_first_page_is_selected_through_public_api(window, container, records):
    case = records[0][1]
    request = None
    for index in range(_PAGE_SIZE + 2):
        request, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
            engagement_id=case.id, tax_type="vat", period_name=f"2026-{index}",
            request_name="分頁批次", item_names=(f"第{index}筆文件",),
        ))
    assert window.open_target(NavigationTarget(
        PAGE_ENGAGEMENTS, engagement_id=case.id, request_id=request.id,
    ))
    page = window._eng_page
    assert page._requests_page._request_page > 0
    assert page._requests_page._selected_request_id() == request.id
    assert page._items_page.item_ids() == tuple(
        item.id for item in container.doc_requests.list_items(request.id)
    )


@pytest.mark.parametrize("scope", ["case", "client", "global"])
def test_task_target_keeps_exact_id_scope_and_new_task_prefills(
    window, container, records, monkeypatch, scope,
):
    client, case, _, case_task, _ = records[0]
    other_client, other_case = records[1][:2]
    task = case_task if scope == "case" else container.tasks.create_task(CreateTaskInput(
        title="<b>字面待辦標題</b>", engagement_id=None,
        client_id=client.id if scope == "client" else None,
    ))
    window.navigate_to(PAGE_TASKS)
    page = window._stack.currentWidget()
    page._client_combo.setCurrentIndex(page._client_combo.findData(other_client.id))
    page._eng_combo.setCurrentIndex(page._eng_combo.findData(other_case.id))
    monkeypatch.setattr(container.clients, "list_clients", lambda **kw: [other_client])
    monkeypatch.setattr(container.engagements, "list_by_client", lambda *a, **kw: [])
    assert window.open_target(NavigationTarget(PAGE_TASKS, task_id=task.id))
    page.refresh_context()
    expected_client = client.id if scope != "global" else -1
    expected_case = case.id if scope == "case" else -1
    assert page._selected_task_id() == task.id
    assert page._table.rowCount() == 1
    assert page._client_combo.currentData() == expected_client
    assert page._eng_combo.currentData() == expected_case
    assert not page._client_combo.isEnabled() and not page._eng_combo.isEnabled()
    assert page._navigation_label.textFormat() == Qt.TextFormat.PlainText
    assert task.title in page._navigation_label.text()
    captured = {}

    class FakeDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def exec(self):
            return 0

    monkeypatch.setattr("taxops.ui.pages.tasks_page.NewTaskDialog", FakeDialog)
    page._on_new_task()
    assert captured["preset_client_id"] == (None if expected_client == -1 else expected_client)
    assert captured["engagement_id"] == (None if expected_case == -1 else expected_case)
    page._show_all_btn.click()
    assert page._navigation_task_id is None
    assert page._navigation_scope.isHidden()
    assert page._client_combo.isEnabled() and page._eng_combo.isEnabled()
    assert page._client_combo.currentData() == page._eng_combo.currentData() == -1


@pytest.mark.parametrize("deleted", ["task", "case", "client", "request", "attachment"])
def test_deleted_target_keeps_source_page_and_data(window, container, records, warnings, deleted):
    client, case, request, task, attachment = records[0]
    target = NavigationTarget(PAGE_TASKS, task_id=task.id)
    if deleted == "task":
        container.tasks.delete_task(task.id)
    elif deleted == "case":
        container.engagements.delete_engagement(case.id)
    elif deleted == "client":
        container.clients.delete_client(client.id)
    elif deleted == "request":
        container.doc_requests.delete_request(request.id)
        target = NavigationTarget(PAGE_ENGAGEMENTS, engagement_id=case.id, request_id=request.id)
    else:
        container.attachments.delete_attachment(attachment.id)
        target = NavigationTarget(PAGE_ATTACHMENTS, engagement_id=case.id, attachment_id=attachment.id)
    source = window._stack.currentWidget()
    before = business_snapshot(container)
    assert not window.open_target(target)
    assert window._stack.currentWidget() is source
    assert business_snapshot(container) == before
    assert warnings


@pytest.mark.parametrize("kind", ["task", "request", "attachment"])
def test_wrong_case_target_keeps_source_and_business_data(window, container, records, kind):
    _, _, request, task, attachment = records[0]
    other_case = records[1][1]
    target = {
        "task": NavigationTarget(PAGE_TASKS, engagement_id=other_case.id, task_id=task.id),
        "request": NavigationTarget(PAGE_ENGAGEMENTS, engagement_id=other_case.id, request_id=request.id),
        "attachment": NavigationTarget(PAGE_ATTACHMENTS, engagement_id=other_case.id, attachment_id=attachment.id),
    }[kind]
    source = window._stack.currentWidget()
    before = business_snapshot(container)
    assert not window.open_target(target)
    assert window._stack.currentWidget() is source
    assert business_snapshot(container) == before


def test_modal_unsaved_input_blocks_every_navigation_path(window, records, qapp):
    task = records[0][3]
    dialog = QDialog(window)
    dialog.setModal(True)
    edit = QLineEdit("尚未儲存的內容")
    QVBoxLayout(dialog).addWidget(edit)
    dialog.show()
    qapp.processEvents()
    source = window._stack.currentWidget()
    assert not window.open_target(NavigationTarget(PAGE_TASKS, task_id=task.id))
    window.navigate_to(PAGE_CLIENTS)
    window._nav._actions[PAGE_CLIENTS].trigger()
    assert window._stack.currentWidget() is source
    assert window._nav.currentRow() == window._page_indices[PAGE_ATTACHMENTS]
    assert edit.text() == "尚未儲存的內容"
    dialog.reject()
    qapp.processEvents()
    assert window.open_target(NavigationTarget(PAGE_TASKS, task_id=task.id))


def test_repeated_exact_links_and_generic_client_route_do_not_mutate_business_records(
    window, container, records,
):
    _, case, request, task, _ = records[0]
    before = business_snapshot(container)
    for _ in range(3):
        assert window.open_target(NavigationTarget(PAGE_TASKS, task_id=task.id))
        assert window.open_target(NavigationTarget(
            PAGE_ENGAGEMENTS, engagement_id=case.id, request_id=request.id,
        ))
        assert window.open_target(NavigationTarget(PAGE_CLIENTS))
    assert business_snapshot(container) == before


@pytest.mark.parametrize("load_step", ["load_engagement", "select_request_id", "load_request_items"])
def test_failed_request_readback_does_not_switch_page(window, records, monkeypatch, load_step):
    _, case, request, _, _ = records[0]
    source = window._stack.currentWidget()
    page = window._eng_page
    child = page._items_page if load_step == "load_request_items" else page._requests_page
    monkeypatch.setattr(child, load_step, lambda *args: False)
    assert not window.open_target(NavigationTarget(
        PAGE_ENGAGEMENTS, engagement_id=case.id, request_id=request.id,
    ))
    assert window._stack.currentWidget() is source


def test_deleted_scoped_case_stays_scoped_until_explicit_clear(qapp, qtbot, container, records):
    case, request = records[0][1:3]
    other_request = records[1][2]
    page = DocumentRequestsPage(container)
    qtbot.addWidget(page)
    assert page.load_engagement(case.id)
    assert request_ids(page) == {request.id}
    container.engagements.delete_engagement(case.id)
    assert not page.refresh_context()
    assert page._engagement_id == page._engagement_combo.currentData() == case.id
    assert page._req_table.rowCount() == page._item_table.rowCount() == 0
    assert not page._new_req_btn.isEnabled()
    assert "失效" in page._context_banner.text()
    page.clear_filter()
    assert page.refresh_context()
    assert request_ids(page) == {other_request.id}
    assert page._new_req_btn.isEnabled()


def test_pending_postcommit_recovery_locks_survive_request_navigation(window, records):
    _, case, request, _, _ = records[0]
    evidence = DocumentMutationEvidence(
        operation="item.create", engagement_id=case.id, request_id=request.id,
        request_before=request, request_after=request, items_before=(),
    )
    page = window._eng_page
    for child in (page._requests_page, page._items_page):
        child._pending_mutation = evidence
        child._show_pending_recovery()
    assert window.open_target(NavigationTarget(
        PAGE_ENGAGEMENTS, engagement_id=case.id, request_id=request.id,
    ))
    page.refresh_context()
    for child in (page._requests_page, page._items_page):
        assert child.pending_mutation_evidence is evidence
        assert all(not button.isEnabled() for button in child._mutation_buttons)
        assert not child._recovery_panel.isHidden()


def test_f6_focuses_active_navigation_without_changing_page(window, qapp):
    window.navigate_to(PAGE_ANNUAL_WORKBENCH)
    source = window._stack.currentWidget()
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_F6)
    qapp.processEvents()
    assert window._nav._buttons[PAGE_ANNUAL_WORKBENCH].hasFocus()
    assert window._stack.currentWidget() is source


@pytest.mark.parametrize("with_attachment", [False, True])
def test_attachment_target_opens_real_case_and_exact_file(
    window, records, with_attachment,
):
    _, case, _, task, attachment = records[0]
    assert window.open_target(NavigationTarget(PAGE_TASKS, task_id=task.id))
    assert window.open_target(NavigationTarget(
        PAGE_ATTACHMENTS, engagement_id=case.id,
        attachment_id=attachment.id if with_attachment else None,
    ))
    page = window._stack.currentWidget()
    assert page._eng_combo.currentData() == case.id
    if with_attachment:
        assert page._selected_attachment().id == attachment.id


@pytest.mark.parametrize("target", [
    NavigationTarget("unknown"),
    NavigationTarget(PAGE_TASKS, task_id=0),
    NavigationTarget(PAGE_TASKS, task_id=True),
    NavigationTarget(PAGE_CLIENTS, engagement_id=1),
    NavigationTarget(PAGE_TASKS, engagement_id=1),
    NavigationTarget(PAGE_ENGAGEMENTS, request_id=1),
    NavigationTarget(PAGE_ATTACHMENTS, attachment_id=1),
])
def test_invalid_or_incomplete_target_does_not_change_source(window, target):
    source = window._stack.currentWidget()
    assert not window.open_target(target)
    assert window._stack.currentWidget() is source


def test_page_leave_guard_blocks_deep_link_and_global_entry(window, records, monkeypatch):
    source = window._stack.currentWidget()
    monkeypatch.setattr(source, "can_leave_page", lambda: False, raising=False)
    assert not window.open_target(NavigationTarget(PAGE_TASKS, task_id=records[0][3].id))
    window.navigate_to(PAGE_CLIENTS)
    window._nav._buttons[PAGE_ANNUAL_WORKBENCH].click()
    assert window._stack.currentWidget() is source
    assert window._nav.currentRow() == window._page_indices[PAGE_ATTACHMENTS]
