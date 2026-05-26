"""Slice 21B regression tests: EngagementsPage absorbs DocumentRequestsPage.

After 21B the sidebar no longer has a separate "索件管理" entry; the page
is folded into EngagementsPage as a vertical master-detail split (top =
engagement list, bottom = embedded doc-requests widget). Selecting an
engagement in the top table drives the bottom widget.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def client_with_engagements(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    c = container.clients.create_client(CreateClientInput(
        client_code="C21B", client_name="21B客戶",
    ))
    e1 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c.id, engagement_name="21B案件A", tax_type="vat", period_name="2026-Q1",
    ))
    e2 = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c.id, engagement_name="21B案件B", tax_type="cit", period_name="2026",
    ))
    return c, e1, e2


@pytest.mark.usefixtures("qapp")
def test_engagements_page_has_embedded_doc_requests_widget(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    assert hasattr(page, "_doc_requests_widget")
    assert isinstance(page._doc_requests_widget, DocumentRequestsPage)


@pytest.mark.usefixtures("qapp")
def test_embedded_doc_requests_widget_is_in_embedded_mode(container):
    """Embedded mode hides the engagement combo (parent page already picks
    the engagement) and the 「← 返回案件」back button (no separate page to
    return from)."""
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    embedded = page._doc_requests_widget
    assert embedded._engagement_combo.isHidden()
    assert embedded._back_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_standalone_doc_requests_page_still_shows_combo_and_back_btn(container):
    """Constructing DocumentRequestsPage directly (no embedded flag) keeps
    the historical UI intact — both the case combo and back button remain
    visible. Useful for tests that exercise the page in isolation."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    page.show()
    assert not page._engagement_combo.isHidden()
    assert not page._back_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_selecting_engagement_loads_into_embedded_widget(container, client_with_engagements):
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e1, _ = client_with_engagements
    container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B"),
    ))
    page = EngagementsPage(container)
    page.refresh_context()
    target_row = None
    for r in range(page._table.rowCount()):
        if int(page._table.item(r, 0).text()) == e1.id:
            target_row = r
            break
    assert target_row is not None
    page._table.selectRow(target_row)
    assert page._doc_requests_widget._engagement_id == e1.id
    visible = page._doc_requests_widget._req_table.rowCount()
    assert visible == 1


def test_nav_order_no_longer_includes_doc_requests():
    """After 21B, 索件管理 has no sidebar entry of its own."""
    from taxops.ui.action_registry import NAV_ORDER, PAGE_DOC_REQUESTS
    assert PAGE_DOC_REQUESTS not in NAV_ORDER


def test_action_registry_still_describes_doc_request_contracts():
    """Even without a sidebar entry, the action contracts for the embedded
    widget are still registered (they describe handlers on the embedded
    DocumentRequestsPage instance)."""
    from taxops.ui.action_registry import PAGE_DOC_REQUESTS, actions_for_page
    contracts = actions_for_page(PAGE_DOC_REQUESTS)
    assert len(contracts) >= 5


@pytest.mark.usefixtures("qapp")
def test_main_window_does_not_route_to_doc_requests_page(container):
    """Navigating to PAGE_DOC_REQUESTS from the main window is a no-op
    because the page is no longer registered as a sidebar destination —
    main_window._page_indices should not contain the key."""
    from taxops.ui.action_registry import PAGE_DOC_REQUESTS
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    assert PAGE_DOC_REQUESTS not in win._page_indices


@pytest.mark.usefixtures("qapp")
def test_no_engagement_selected_shows_global_doc_requests_view(container, client_with_engagements):
    """When no engagement row is selected, the embedded widget falls back
    to the global ('全部案件') view of all doc requests."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e1, e2 = client_with_engagements
    container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="vat", period_name="2026-Q1",
        item_names=("X",),
    ))
    container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e2.id, tax_type="cit", period_name="2026",
        item_names=("Y",),
    ))
    page = EngagementsPage(container)
    page.refresh_context()
    page._table.clearSelection()
    page._sync_embedded_to_selection()
    assert page._doc_requests_widget._engagement_id is None
    assert page._doc_requests_widget._req_table.rowCount() == 2
