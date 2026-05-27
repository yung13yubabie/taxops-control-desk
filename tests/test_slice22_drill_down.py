"""Slice 22 / v0.14.3: 案件→索件→文件 three-layer drill-down."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seeded(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.services.engagements import CreateEngagementInput

    c = container.clients.create_client(CreateClientInput(
        client_code="C22", client_name="22客戶",
    ))
    e = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c.id, engagement_name="22案件",
        tax_type="vat", period_name="2026-Q1",
    ))
    req_row, _items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("發票", "進銷項"),
    ))
    return c, e, req_row


@pytest.mark.usefixtures("qapp")
def test_page_has_three_layer_stack(container):
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    assert page._stack.count() == 3
    assert page._stack.currentIndex() == 0


@pytest.mark.usefixtures("qapp")
def test_breadcrumb_root_button_exists(container):
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    assert "案件管理" in page._bc_root_btn.text()
    assert page._bc_engagement_btn.isHidden()
    assert page._bc_request_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_drill_to_engagement_switches_page_and_updates_breadcrumb(container, seeded):
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e, _ = seeded
    page = EngagementsPage(container)
    page.refresh_context()
    page._drill_to_engagement(e.id)
    assert page._stack.currentIndex() == 1
    assert page._current_engagement_id == e.id
    assert page._bc_engagement_btn.text() == e.engagement_name
    assert not page._bc_engagement_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_drill_to_items_switches_page_and_loads_items(container, seeded):
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e, r = seeded
    page = EngagementsPage(container)
    page.refresh_context()
    page._drill_to_engagement(e.id)
    page._on_drill_to_items(r.id)
    assert page._stack.currentIndex() == 2
    assert page._current_request_id == r.id
    assert page._items_page._item_table.rowCount() == 2
    assert page._bc_request_btn.text() == "2026-Q1"


@pytest.mark.usefixtures("qapp")
def test_breadcrumb_root_click_returns_to_master(container, seeded):
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e, r = seeded
    page = EngagementsPage(container)
    page.refresh_context()
    page._drill_to_engagement(e.id)
    page._on_drill_to_items(r.id)
    page._show_master()
    assert page._stack.currentIndex() == 0
    assert page._bc_engagement_btn.isHidden()
    assert page._bc_request_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_breadcrumb_engagement_click_returns_to_requests(container, seeded):
    from taxops.ui.pages.engagements_page import EngagementsPage
    _, e, r = seeded
    page = EngagementsPage(container)
    page.refresh_context()
    page._drill_to_engagement(e.id)
    page._on_drill_to_items(r.id)
    page._show_requests()
    assert page._stack.currentIndex() == 1
    assert not page._bc_engagement_btn.isHidden()
    assert page._bc_request_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_requests_only_mode_hides_item_buttons(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container, embedded=True, view_mode="requests_only")
    assert not page._req_table.isHidden()
    assert page._add_item_btn.isHidden()
    assert page._edit_item_btn.isHidden()


@pytest.mark.usefixtures("qapp")
def test_items_only_mode_hides_request_buttons(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    assert page._new_req_btn.isHidden()
    assert page._delete_req_btn.isHidden()
    assert page._context_banner.isHidden()


@pytest.mark.usefixtures("qapp")
def test_items_only_mode_load_request_items_populates(container, seeded):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, r = seeded
    page = DocumentRequestsPage(container, embedded=True, view_mode="items_only")
    page.load_request_items(r.id)
    assert page._items_only_request_id == r.id
    assert page._item_table.rowCount() == 2
    assert page._add_item_btn.isEnabled()


def test_invalid_view_mode_raises():
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage

    class _Stub:
        pass
    with pytest.raises(ValueError):
        DocumentRequestsPage(_Stub(), view_mode="bogus")


@pytest.mark.usefixtures("qapp")
def test_drill_to_items_signal_fires_on_double_click(container, seeded):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, e, r = seeded
    page = DocumentRequestsPage(container, embedded=True, view_mode="requests_only")
    page.load_engagement(e.id)
    received: list[int] = []
    page.drill_to_items.connect(lambda rid: received.append(rid))
    page._req_table.selectRow(0)
    page._on_req_row_double_clicked(None)
    assert received == [r.id]
