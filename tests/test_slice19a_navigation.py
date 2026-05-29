"""Slice 19A regression tests: Dashboard filter pollution + view-all modes.

Tests are ordered: service-level (no UI) first, then page-level (needs QApp).
"""

from __future__ import annotations

import pytest


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def two_clients(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    c1 = container.clients.create_client(CreateClientInput(
        client_code="C001", client_name="客戶甲",
    ))
    c2 = container.clients.create_client(CreateClientInput(
        client_code="C002", client_name="客戶乙",
    ))
    e1 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c1.id, engagement_name="案件甲", tax_type="cit", period_name="2024",
    ))
    e2 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c2.id, engagement_name="案件乙", tax_type="vat", period_name="2024-Q1",
    ))
    return c1, c2, e1, e2


# ── service-level tests (no QApp needed) ──────────────────────────────────────

def test_document_requests_service_list_all(container, two_clients):
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, _, e1, e2 = two_clients
    r1, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    r2, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e2.id, tax_type="vat", period_name="2024-Q1",
    ))
    all_reqs = container.doc_requests.list_all()
    ids = {r.id for r in all_reqs}
    assert r1.id in ids
    assert r2.id in ids


def test_document_requests_list_all_excludes_deleted(container, two_clients):
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, _, e1, _ = two_clients
    r1, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    container.doc_requests.delete_request(r1.id)
    all_reqs = container.doc_requests.list_all()
    assert r1.id not in {r.id for r in all_reqs}


def test_attachments_service_list_all(container, tmp_path, two_clients):
    from taxops.services.attachments import UploadAttachmentInput
    _, _, e1, e2 = two_clients
    f1 = tmp_path / "a1.txt"
    f1.write_text("aaa")
    f2 = tmp_path / "a2.txt"
    f2.write_text("bbb")
    att1 = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=e1.id, request_id=None, source_path=f1, uploaded_by="tester",
    ))
    att2 = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=e2.id, request_id=None, source_path=f2, uploaded_by="tester",
    ))
    all_atts = container.attachments.list_all()
    ids = {a.id for a in all_atts}
    assert att1.id in ids
    assert att2.id in ids


def test_attachments_list_all_excludes_archived(container, tmp_path, two_clients):
    from taxops.services.attachments import UploadAttachmentInput
    _, _, e1, _ = two_clients
    f1 = tmp_path / "a1.txt"
    f1.write_text("aaa")
    att1 = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=e1.id, request_id=None, source_path=f1, uploaded_by="tester",
    ))
    container.attachments.delete_attachment(att1.id)
    all_atts = container.attachments.list_all()
    assert att1.id not in {a.id for a in all_atts}


# ── page-level tests (require QApp) ───────────────────────────────────────────

@pytest.mark.usefixtures("qapp")
def test_tasks_page_clear_filter_resets_filter_key(container):
    from taxops.ui.pages.tasks_page import TasksPage
    page = TasksPage(container)
    page.set_filter("overdue")
    assert page._filter_key == "overdue"
    page.clear_filter()
    assert page._filter_key == ""


@pytest.mark.usefixtures("qapp")
def test_engagements_page_clear_filter_resets_filter_key(container):
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    page.set_filter("upcoming")
    assert page._filter_key == "upcoming"
    page.clear_filter()
    assert page._filter_key == ""


@pytest.mark.usefixtures("qapp")
def test_folder_bookmarks_page_instantiates(container):
    """Slice 24 / v0.15.1 — review_notes deleted; folder_bookmarks took its slot."""
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage
    page = FolderBookmarksPage(container)
    assert page._table is not None


@pytest.mark.usefixtures("qapp")
def test_clients_page_clear_filter_resets_filter_key(container):
    from taxops.ui.pages.clients_page import ClientsPage
    page = ClientsPage(container)
    page.set_filter("lease_expiring")
    assert page._filter_key == "lease_expiring"
    page.clear_filter()
    assert page._filter_key == ""


@pytest.mark.usefixtures("qapp")
def test_engagements_page_has_all_clients_option(container):
    from taxops.ui.pages.engagements_page import EngagementsPage, _ALL_CLIENTS
    page = EngagementsPage(container)
    found = any(
        page._client_combo.itemData(i) == _ALL_CLIENTS
        for i in range(page._client_combo.count())
    )
    assert found, "client_combo must have a '全部客戶' item"


@pytest.mark.usefixtures("qapp")
def test_engagements_page_all_clients_shows_all_engagements(container, two_clients):
    from taxops.ui.pages.engagements_page import EngagementsPage, _ALL_CLIENTS
    _, _, e1, e2 = two_clients
    page = EngagementsPage(container)
    # index 0 should be 全部客戶
    page._client_combo.setCurrentIndex(0)
    assert page._client_combo.currentData() == _ALL_CLIENTS
    visible_ids = {
        int(page._table.item(r, 0).text())
        for r in range(page._table.rowCount())
    }
    assert e1.id in visible_ids
    assert e2.id in visible_ids


@pytest.mark.usefixtures("qapp")
def test_attachments_page_all_case_loads_attachments(container, tmp_path, two_clients):
    from taxops.services.attachments import UploadAttachmentInput
    from taxops.ui.pages.attachments_page import AttachmentsPage, _ALL
    _, _, e1, e2 = two_clients
    f1 = tmp_path / "a1.txt"
    f1.write_text("aaa")
    f2 = tmp_path / "a2.txt"
    f2.write_text("bbb")
    att1 = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=e1.id, request_id=None, source_path=f1, uploaded_by="tester",
    ))
    att2 = container.attachments.upload_attachment(UploadAttachmentInput(
        engagement_id=e2.id, request_id=None, source_path=f2, uploaded_by="tester",
    ))
    page = AttachmentsPage(container)
    # index 0 must be "全部案件" with data _ALL
    assert page._eng_combo.itemData(0) == _ALL
    page._eng_combo.setCurrentIndex(0)
    visible_ids = {
        int(page._table.item(r, 0).text())
        for r in range(page._table.rowCount())
    }
    assert att1.id in visible_ids
    assert att2.id in visible_ids


@pytest.mark.usefixtures("qapp")
def test_document_requests_page_global_mode_on_refresh(container, two_clients):
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, e1, e2 = two_clients
    r1, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    r2, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e2.id, tax_type="vat", period_name="2024-Q1",
    ))
    page = DocumentRequestsPage(container)
    # No engagement loaded → global mode on refresh_context
    page.refresh_context()
    assert not page._splitter.isHidden()
    assert page._no_engagement_label.isHidden()
    visible_ids = {
        int(page._req_table.item(r, 0).text())
        for r in range(page._req_table.rowCount())
    }
    assert r1.id in visible_ids
    assert r2.id in visible_ids


@pytest.mark.usefixtures("qapp")
def test_main_window_sidebar_nav_clears_tasks_filter(container, two_clients):
    from taxops.ui.main_window import MainWindow
    from taxops.ui.action_registry import PAGE_TASKS, NAV_ORDER
    win = MainWindow(container)
    # Dashboard navigates to tasks with overdue filter
    win.navigate_to(PAGE_TASKS, filter_key="overdue")
    tasks_idx = win._page_indices[PAGE_TASKS]
    tasks_page = win._stack.widget(tasks_idx)
    assert tasks_page._filter_key == "overdue"
    # Navigate away then back via sidebar to trigger _on_nav_changed
    clients_row = NAV_ORDER.index("clients")
    win._nav.setCurrentRow(clients_row)
    tasks_row = NAV_ORDER.index(PAGE_TASKS)
    win._nav.setCurrentRow(tasks_row)
    assert tasks_page._filter_key == ""


@pytest.mark.usefixtures("qapp")
def test_main_window_dashboard_nav_without_filter_clears_current_page_filter(container, two_clients):
    from taxops.ui.main_window import MainWindow
    from taxops.ui.action_registry import PAGE_TASKS

    win = MainWindow(container)
    win.navigate_to(PAGE_TASKS, filter_key="overdue")
    tasks_idx = win._page_indices[PAGE_TASKS]
    tasks_page = win._stack.widget(tasks_idx)
    assert tasks_page._filter_key == "overdue"

    # Slice 25 / v0.16.0: dashboard rows mirror sidebar entries and emit no
    # hidden filter. Clicking the same page again must therefore behave like
    # the sidebar and clear any prior dashboard-specific filter.
    win.navigate_to(PAGE_TASKS)
    assert tasks_page._filter_key == ""
