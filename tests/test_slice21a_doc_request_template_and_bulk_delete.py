"""Slice 21A regression tests:
- VAT items checklist dialog (replaces auto-template insertion)
- Bulk delete document items
- CreateDocumentRequestInput API: item_names replaces use_vat_template
- Persist last-selected items per tax_type in app_settings
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def client_and_engagement(container):
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    c = container.clients.create_client(CreateClientInput(
        client_code="C21A", client_name="21A客戶",
    ))
    e = container.engagements.create_engagement(CreateEngagementInput(
        client_id=c.id, engagement_name="21A案件", tax_type="vat", period_name="2026-Q1",
    ))
    return c, e


# ── service: item_names replaces use_vat_template ─────────────────────────


def test_create_request_with_item_names_creates_those_items(container, client_and_engagement):
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    items_to_create = ("發票", "進項憑證", "銀行對帳單")
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=items_to_create,
    ))
    assert len(items) == 3
    assert {i.item_name for i in items} == set(items_to_create)


def test_create_request_with_empty_item_names_creates_no_items(container, client_and_engagement):
    """An empty item_names tuple results in a request with zero items (no auto-fill)."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=(),
    ))
    assert items == []


def test_create_request_default_item_names_is_empty(container, client_and_engagement):
    """Default behaviour is no items — caller must explicitly opt into a template."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
    ))
    assert items == []


def test_use_vat_template_kwarg_no_longer_supported(client_and_engagement):
    """Breaking API change: use_vat_template raises TypeError (no backwards-compat shim)."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    with pytest.raises(TypeError):
        CreateDocumentRequestInput(  # type: ignore[call-arg]
            engagement_id=1, tax_type="vat", period_name="2026",
            use_vat_template=True,
        )


def test_vat_items_module_constant_is_exported(container):
    """UI dialogs need a public template; VAT_ITEMS stays as a module-level constant."""
    from taxops.services import document_requests as mod
    assert hasattr(mod, "VAT_ITEMS")
    assert len(mod.VAT_ITEMS) >= 5
    assert "銷項發票明細" in mod.VAT_ITEMS


# ── service: delete_items_bulk ─────────────────────────────────────────────


def test_delete_items_bulk_removes_all_specified_items(container, client_and_engagement):
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B", "C", "D"),
    ))
    ids_to_delete = [items[0].id, items[2].id]
    count = container.doc_requests.delete_items_bulk(ids_to_delete)
    assert count == 2
    remaining = container.doc_requests.list_items(req.id)
    remaining_names = {i.item_name for i in remaining}
    assert remaining_names == {"B", "D"}


def test_delete_items_bulk_recomputes_request_status(container, client_and_engagement):
    """After deleting all items, parent request status should revert to 'requested'."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B"),
    ))
    for it in items:
        container.doc_requests.set_item_status(it.id, item_status="accepted")
    after_accept = container.doc_requests.get_request(req.id)
    assert after_accept.status == "accepted"
    container.doc_requests.delete_items_bulk([items[0].id, items[1].id])
    after_delete = container.doc_requests.get_request(req.id)
    assert after_delete.status == "requested"


def test_delete_items_bulk_with_invalid_id_continues(container, client_and_engagement):
    """A nonexistent id in the batch is silently skipped — partial success allowed."""
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A",),
    ))
    count = container.doc_requests.delete_items_bulk([items[0].id, 99999])
    assert count == 1
    assert container.doc_requests.list_items(req.id) == []


def test_delete_items_bulk_audit_records_count(container, client_and_engagement):
    from taxops.services.document_requests import CreateDocumentRequestInput
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B", "C"),
    ))
    ids = [items[0].id, items[1].id]
    container.doc_requests.delete_items_bulk(ids)
    rows = container.conn.execute(
        "SELECT detail_json FROM audit_logs WHERE action = ?",
        ("doc_request_item.bulk_delete",),
    ).fetchall()
    assert len(rows) == 1
    detail = rows[0]["detail_json"]
    assert '"deleted_count": 2' in detail


# ── dialog: DocumentItemTemplateDialog ────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_template_dialog_default_state_has_all_vat_items_checked(container):
    """First-time use: all VAT_ITEMS are pre-checked (no persisted preset yet)."""
    from taxops.services.document_requests import VAT_ITEMS
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    selected = dlg.selected_items()
    assert set(selected) == set(VAT_ITEMS)


@pytest.mark.usefixtures("qapp")
def test_template_dialog_remembers_last_selection(container):
    """Persisted preset is restored on next dialog open."""
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    preset = json.dumps({"checked": ["銷項發票明細", "進項憑證"], "custom": []})
    container.settings.set_setting("ui.doc_request_template.vat", preset)
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    selected = set(dlg.selected_items())
    assert selected == {"銷項發票明細", "進項憑證"}


@pytest.mark.usefixtures("qapp")
def test_template_dialog_persists_selection_on_accept(container):
    """Accepting the dialog saves the current selection so next time it's restored."""
    from taxops.services.document_requests import VAT_ITEMS
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    for name, cb in dlg._checkboxes.items():
        cb.setChecked(name == VAT_ITEMS[0])
    dlg.accept()
    stored = container.settings.get("ui.doc_request_template.vat")
    assert stored is not None
    data = json.loads(stored)
    assert data["checked"] == [VAT_ITEMS[0]]


@pytest.mark.usefixtures("qapp")
def test_template_dialog_supports_custom_items(container):
    """Custom items added via the input box appear in selected_items() on accept."""
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    dlg._custom_input.setText("特殊項目A")
    dlg._on_add_custom()
    assert "特殊項目A" in dlg.selected_items()
    dlg.accept()
    stored = json.loads(container.settings.get("ui.doc_request_template.vat"))
    assert "特殊項目A" in stored["custom"]


@pytest.mark.usefixtures("qapp")
def test_template_dialog_select_all_button(container):
    from taxops.services.document_requests import VAT_ITEMS
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    for cb in dlg._checkboxes.values():
        cb.setChecked(False)
    dlg._on_select_all()
    assert set(dlg.selected_items()) == set(VAT_ITEMS)


@pytest.mark.usefixtures("qapp")
def test_template_dialog_select_none_button(container):
    from taxops.ui.dialogs.document_item_template_dialog import (
        DocumentItemTemplateDialog,
    )
    dlg = DocumentItemTemplateDialog(container, tax_type="vat")
    dlg._on_select_none()
    assert dlg.selected_items() == ()


# ── DocumentRequestsPage: bulk delete UI integration ──────────────────────


@pytest.mark.usefixtures("qapp")
def test_doc_requests_page_has_bulk_delete_items_button(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    assert hasattr(page, "_bulk_delete_items_btn")


@pytest.mark.usefixtures("qapp")
def test_bulk_delete_items_button_deletes_selected_rows(
    container, client_and_engagement
):
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B", "C"),
    ))
    page = DocumentRequestsPage(container)
    page.load_engagement(e.id)
    page._req_table.selectRow(0)
    page._item_table.clearSelection()
    model = page._item_table.selectionModel()
    sel = QItemSelection()
    cols = page._item_table.columnCount()
    for row in (0, 2):
        top = page._item_table.model().index(row, 0)
        bot = page._item_table.model().index(row, cols - 1)
        sel.select(top, bot)
    model.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "information"):
        page._on_bulk_delete_items()
    remaining = container.doc_requests.list_items(req.id)
    assert {i.item_name for i in remaining} == {"B"}


@pytest.mark.usefixtures("qapp")
def test_bulk_delete_items_button_requires_confirmation(
    container, client_and_engagement
):
    """No-confirmation rejection = no deletion."""
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.document_requests import CreateDocumentRequestInput
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    _, e = client_and_engagement
    req, items = container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=e.id, tax_type="vat", period_name="2026-Q1",
        item_names=("A", "B"),
    ))
    page = DocumentRequestsPage(container)
    page.load_engagement(e.id)
    page._req_table.selectRow(0)
    model = page._item_table.selectionModel()
    sel = QItemSelection()
    cols = page._item_table.columnCount()
    for row in (0, 1):
        top = page._item_table.model().index(row, 0)
        bot = page._item_table.model().index(row, cols - 1)
        sel.select(top, bot)
    model.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        page._on_bulk_delete_items()
    assert len(container.doc_requests.list_items(req.id)) == 2
