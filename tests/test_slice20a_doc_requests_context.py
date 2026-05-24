"""Slice 20A regression tests: DocumentRequestsPage self-contained context.

Covers:
- Engagement combo presence + label format ("客戶名 — 案件名 — 期別")
- Combo switching loads matching requests
- _on_new_request in global mode prompts engagement picker (no silent return)
- Item operations (edit / set_status / delete) refresh request table
- Selection preservation across refresh
- clear_filter resets to global mode (sidebar nav scenario)
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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


# ── combo presence / format ────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_doc_requests_page_has_engagement_combo(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    assert hasattr(page, "_engagement_combo")


@pytest.mark.usefixtures("qapp")
def test_engagement_combo_first_item_is_all(container):
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _ALL_ENGAGEMENTS,
    )
    page = DocumentRequestsPage(container)
    page.refresh_context()
    assert page._engagement_combo.itemData(0) == _ALL_ENGAGEMENTS


@pytest.mark.usefixtures("qapp")
def test_engagement_combo_includes_all_engagements(container, two_clients):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, e1, e2 = two_clients
    page = DocumentRequestsPage(container)
    page.refresh_context()
    eng_ids = {
        page._engagement_combo.itemData(i)
        for i in range(page._engagement_combo.count())
    }
    assert e1.id in eng_ids
    assert e2.id in eng_ids


@pytest.mark.usefixtures("qapp")
def test_engagement_combo_label_includes_client_name_and_period(container, two_clients):
    """Label format: 客戶名 — 案件名 — 期別."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    c1, _, e1, _ = two_clients
    page = DocumentRequestsPage(container)
    page.refresh_context()
    for i in range(page._engagement_combo.count()):
        if page._engagement_combo.itemData(i) == e1.id:
            label = page._engagement_combo.itemText(i)
            assert c1.client_name in label
            assert e1.engagement_name in label
            assert e1.period_name in label
            return
    pytest.fail("engagement e1 not found in combo")


# ── combo switching ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_combo_switch_to_engagement_loads_its_requests(container, two_clients):
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
    page.refresh_context()
    idx = page._engagement_combo.findData(e1.id)
    assert idx >= 1
    page._engagement_combo.setCurrentIndex(idx)
    visible_ids = {
        int(page._req_table.item(r, 0).text())
        for r in range(page._req_table.rowCount())
    }
    assert r1.id in visible_ids
    assert r2.id not in visible_ids


@pytest.mark.usefixtures("qapp")
def test_combo_switch_back_to_all_shows_all_requests(container, two_clients):
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _ALL_ENGAGEMENTS,
    )
    _, _, e1, e2 = two_clients
    r1, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    r2, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e2.id, tax_type="vat", period_name="2024-Q1",
    ))
    page = DocumentRequestsPage(container)
    page.refresh_context()
    idx_e1 = page._engagement_combo.findData(e1.id)
    page._engagement_combo.setCurrentIndex(idx_e1)
    idx_all = page._engagement_combo.findData(_ALL_ENGAGEMENTS)
    page._engagement_combo.setCurrentIndex(idx_all)
    visible_ids = {
        int(page._req_table.item(r, 0).text())
        for r in range(page._req_table.rowCount())
    }
    assert r1.id in visible_ids
    assert r2.id in visible_ids


# ── _on_new_request global mode ────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_new_request_global_mode_opens_picker_not_silent(container, two_clients):
    """In ALL mode, clicking 新增 must open the engagement picker — never silently return."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    page.refresh_context()
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=("", False),
    ) as picker:
        page._on_new_request()
        picker.assert_called_once()


@pytest.mark.usefixtures("qapp")
def test_new_request_global_mode_creates_request_after_picking(container, two_clients):
    """When user picks an engagement, a doc request is created under that engagement."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, e1, _ = two_clients
    page = DocumentRequestsPage(container)
    page.refresh_context()
    label = None
    for i in range(page._engagement_combo.count()):
        if page._engagement_combo.itemData(i) == e1.id:
            label = page._engagement_combo.itemText(i)
            break
    assert label is not None
    initial_count = len(container.doc_requests.list_by_engagement(e1.id))
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=(label, True),
    ):
        page._on_new_request()
    new_count = len(container.doc_requests.list_by_engagement(e1.id))
    assert new_count == initial_count + 1


@pytest.mark.usefixtures("qapp")
def test_new_request_global_mode_no_engagements_shows_info(container):
    """No engagements + global mode + click 新增 → info dialog, not silent fail."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    page.refresh_context()
    with patch.object(QMessageBox, "information") as info:
        page._on_new_request()
        info.assert_called_once()


@pytest.mark.usefixtures("qapp")
def test_new_request_engagement_mode_still_works(container, two_clients):
    """When an engagement is loaded, new request creates without prompting."""
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, e1, _ = two_clients
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    initial = len(container.doc_requests.list_by_engagement(e1.id))
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
    ) as picker:
        page._on_new_request()
        picker.assert_not_called()
    after = len(container.doc_requests.list_by_engagement(e1.id))
    assert after == initial + 1


# ── item operations refresh request table ─────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_set_item_status_refreshes_request_status_in_table(container, two_clients):
    """After set_item_status, the request row's status cell reflects the new derived status."""
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _REQ_COLUMNS,
    )
    _, _, e1, _ = two_clients
    req, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    container.doc_requests.add_item(req.id, "項目A")
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    page._req_table.selectRow(0)
    page._item_table.selectRow(0)
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=(status_to_label("accepted"), True),
    ):
        page._on_set_item_status()
    status_col = _REQ_COLUMNS.index("status")
    cell_text = page._req_table.item(0, status_col).text()
    assert cell_text == status_to_label("accepted")


@pytest.mark.usefixtures("qapp")
def test_delete_item_refreshes_request_table(container, two_clients):
    """After deleting the only accepted item, request status reverts to requested."""
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _REQ_COLUMNS,
    )
    _, _, e1, _ = two_clients
    req, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    item = container.doc_requests.add_item(req.id, "項目A")
    container.doc_requests.set_item_status(item.id, item_status="accepted")
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    page._req_table.selectRow(0)
    page._item_table.selectRow(0)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        page._on_delete_item()
    status_col = _REQ_COLUMNS.index("status")
    cell_text = page._req_table.item(0, status_col).text()
    assert cell_text == status_to_label("requested")


@pytest.mark.usefixtures("qapp")
def test_edit_item_refreshes_item_table(container, two_clients):
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _ITEM_COLUMNS,
    )
    _, _, e1, _ = two_clients
    req, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    container.doc_requests.add_item(req.id, "舊名稱")
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    page._req_table.selectRow(0)
    page._item_table.selectRow(0)
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getText",
        return_value=("新名稱", True),
    ):
        page._on_edit_item()
    name_col = _ITEM_COLUMNS.index("item_name")
    cell_text = page._item_table.item(0, name_col).text()
    assert cell_text == "新名稱"


# ── selection preservation ──────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_preserve_request_selection_after_set_item_status(container, two_clients):
    """The selected request row stays selected after an item-status refresh."""
    from taxops.i18n.status_labels import status_to_label
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, _, e1, _ = two_clients
    req1, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2024",
    ))
    req2, _ = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e1.id, tax_type="cit", period_name="2025",
    ))
    container.doc_requests.add_item(req1.id, "甲")
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    target_row = None
    for r in range(page._req_table.rowCount()):
        if int(page._req_table.item(r, 0).text()) == req1.id:
            target_row = r
            break
    assert target_row is not None
    page._req_table.selectRow(target_row)
    page._item_table.selectRow(0)
    with patch(
        "taxops.ui.pages.document_requests_page.QInputDialog.getItem",
        return_value=(status_to_label("accepted"), True),
    ):
        page._on_set_item_status()
    items = page._req_table.selectedItems()
    assert items, "request selection must be preserved after refresh"
    selected_row = page._req_table.row(items[0])
    selected_id = int(page._req_table.item(selected_row, 0).text())
    assert selected_id == req1.id


# ── clear_filter / sidebar nav fallback ────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_clear_filter_returns_to_global_mode(container, two_clients):
    """Sidebar nav triggers clear_filter → page returns to global ALL mode after refresh."""
    from taxops.ui.pages.document_requests_page import (
        DocumentRequestsPage,
        _ALL_ENGAGEMENTS,
    )
    _, _, e1, _ = two_clients
    page = DocumentRequestsPage(container)
    page.load_engagement(e1.id)
    assert page._engagement_id == e1.id
    page.clear_filter()
    page.refresh_context()
    assert page._engagement_id is None
    assert page._engagement_combo.currentData() == _ALL_ENGAGEMENTS
