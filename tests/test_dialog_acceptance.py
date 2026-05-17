"""Acceptance tests for EditClientDialog, MismatchReviewDialog, BulkImportWizard.

All tests run headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from taxops.repositories.registry_matches import MatchResultRow, REGISTRY_SOURCE_MOF
from taxops.services.clients import CreateClientInput
from taxops.services.clients_bulk import (
    auto_detect_mapping,
    import_validated,
    parse_clipboard_text,
    validate_rows,
)
from taxops.services.container import ServiceContainer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_match_row(
    client_id: int,
    tax_id: str,
    matched_name: str,
    client_name: str,
    matched_address: str = "",
    client_address: str = "",
) -> MatchResultRow:
    diffs: dict = {}
    if matched_name != client_name:
        diffs["name"] = {"client": client_name, "registry": matched_name}
    if matched_address and client_address and matched_address != client_address:
        diffs["address"] = {"client": client_address, "registry": matched_address}
    return MatchResultRow(
        id=1,
        client_id=client_id,
        tax_id=tax_id,
        registry_source=REGISTRY_SOURCE_MOF,
        cache_version="20260101",
        match_status="mismatch",
        matched_name=matched_name,
        matched_address=matched_address or None,
        matched_business_status=None,
        differences_json=json.dumps(diffs, ensure_ascii=False) if diffs else None,
        review_status="pending",
        generated_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# EditClientDialog
# ---------------------------------------------------------------------------


def test_edit_client_dialog_prefills_all_fields(container: ServiceContainer) -> None:
    _qt_app()
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="ED01", client_name="原始名稱", contact_phone="0912345678")
    )
    dlg = EditClientDialog(container.clients, client)
    assert dlg._client_code.text() == "ED01"
    assert dlg._client_name.text() == "原始名稱"
    assert dlg._contact_phone.text() == "0912345678"
    dlg.destroy()


def test_edit_client_dialog_on_save_persists_to_db(container: ServiceContainer) -> None:
    _qt_app()
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="ED02", client_name="舊名稱")
    )
    dlg = EditClientDialog(container.clients, client)
    dlg._client_name.setText("新名稱")
    dlg.on_save()

    updated = container.clients.get_client(client.id)
    assert updated is not None
    assert updated.client_name == "新名稱"
    dlg.destroy()


def test_edit_client_dialog_empty_name_does_not_write(container: ServiceContainer) -> None:
    _qt_app()
    from unittest.mock import patch
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="ED03", client_name="有效客戶")
    )
    dlg = EditClientDialog(container.clients, client)
    dlg._client_name.setText("")  # required field missing

    with patch("taxops.ui.dialogs.edit_client_dialog.QMessageBox") as mb:
        mb.warning = lambda *a, **kw: None
        dlg.on_save()

    unchanged = container.clients.get_client(client.id)
    assert unchanged.client_name == "有效客戶"
    dlg.destroy()


# ---------------------------------------------------------------------------
# MismatchReviewDialog
# ---------------------------------------------------------------------------


def test_mismatch_dialog_shows_all_rows(container: ServiceContainer) -> None:
    _qt_app()
    from taxops.ui.dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="MR01", client_name="目前名稱", tax_id="12345678")
    )
    match_row = _make_match_row(client.id, "12345678", "財政部名稱", "目前名稱")
    dlg = MismatchReviewDialog([MismatchItem(match_row=match_row, client=client)], container.clients)
    assert dlg._table.rowCount() == 1
    dlg.destroy()


def test_mismatch_dialog_no_selection_calls_accept(container: ServiceContainer) -> None:
    _qt_app()
    from unittest.mock import patch
    from taxops.ui.dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="MR02", client_name="名稱A", tax_id="22222222")
    )
    match_row = _make_match_row(client.id, "22222222", "名稱B", "名稱A")
    dlg = MismatchReviewDialog([MismatchItem(match_row=match_row, client=client)], container.clients)

    with patch.object(dlg, "accept") as mock_accept, \
         patch("taxops.ui.dialogs.mismatch_review_dialog.QMessageBox") as mb:
        mb.information = lambda *a, **kw: None
        dlg._on_apply()
        mock_accept.assert_called_once()
    dlg.destroy()


def test_mismatch_dialog_adopts_registry_name_on_confirm(container: ServiceContainer) -> None:
    _qt_app()
    from unittest.mock import patch
    from taxops.ui.dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="MR03", client_name="舊名", tax_id="33333333")
    )
    match_row = _make_match_row(client.id, "33333333", "財政部新名", "舊名")
    item = MismatchItem(match_row=match_row, client=client)
    dlg = MismatchReviewDialog([item], container.clients)

    name_cb, _ = dlg._checkboxes[0]
    assert name_cb is not None
    name_cb.setChecked(True)

    with patch("taxops.ui.dialogs.mismatch_review_dialog.QMessageBox") as mb:
        mb.information = lambda *a, **kw: None
        dlg._on_apply()

    updated = container.clients.get_client(client.id)
    assert updated is not None
    assert updated.client_name == "財政部新名"
    dlg.destroy()


def test_mismatch_dialog_total_failure_does_not_accept(container: ServiceContainer) -> None:
    _qt_app()
    from unittest.mock import patch
    from taxops.ui.dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog
    from taxops.services.clients import ClientValidationError

    client = container.clients.create_client(
        CreateClientInput(client_code="MR04", client_name="名稱X", tax_id="44444444")
    )
    match_row = _make_match_row(client.id, "44444444", "財政部名稱X", "名稱X")
    dlg = MismatchReviewDialog(
        [MismatchItem(match_row=match_row, client=client)], container.clients
    )

    name_cb, _ = dlg._checkboxes[0]
    if name_cb is not None:
        name_cb.setChecked(True)

    with patch.object(container.clients, "update_client", side_effect=ClientValidationError("client.not_found")), \
         patch.object(dlg, "accept") as mock_accept, \
         patch("taxops.ui.dialogs.mismatch_review_dialog.QMessageBox") as mb:
        mb.warning = lambda *a, **kw: None
        dlg._on_apply()
        mock_accept.assert_not_called()  # KEY: must not accept on total failure
    dlg.destroy()


# ---------------------------------------------------------------------------
# BulkImportWizard navigation correctness
# ---------------------------------------------------------------------------


def test_wizard_back_from_confirm_skips_dup_step_when_no_dups(
    container: ServiceContainer,
) -> None:
    _qt_app()
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    wizard = BulkImportWizard(container.clients, container.clients_repo)

    text = "客戶代號\t客戶名稱\nWIZ01\t測試公司甲\n"
    wizard._headers, wizard._raw_rows = parse_clipboard_text(text)
    wizard._mapping = auto_detect_mapping(wizard._headers)
    wizard._validation = validate_rows(wizard._raw_rows, wizard._mapping, container.clients_repo)

    # Navigate forward, simulating jump-over of dup step (no dups)
    wizard._advance_to(1)
    wizard._advance_to(2)
    wizard._jump_to(4)  # jumps over step 3

    assert wizard._current_step() == 4
    assert 3 not in wizard._step_history

    wizard._go_back()
    assert wizard._current_step() == 2  # must NOT land on step 3
    wizard.destroy()


def test_wizard_back_with_dups_returns_to_dup_step(container: ServiceContainer) -> None:
    _qt_app()
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    container.clients.create_client(CreateClientInput(client_code="DUP99", client_name="已有"))

    wizard = BulkImportWizard(container.clients, container.clients_repo)
    text = "客戶代號\t客戶名稱\nDUP99\t覆蓋嘗試\n"
    wizard._headers, wizard._raw_rows = parse_clipboard_text(text)
    wizard._mapping = auto_detect_mapping(wizard._headers)
    wizard._validation = validate_rows(wizard._raw_rows, wizard._mapping, container.clients_repo)

    wizard._advance_to(1)
    wizard._advance_to(2)
    wizard._advance_to(3)
    wizard._advance_to(4)

    wizard._go_back()
    assert wizard._current_step() == 3  # correctly back to dup policy
    wizard.destroy()


def test_import_validated_toctou_overwrite_skips_when_client_gone(
    container: ServiceContainer,
) -> None:
    container.clients.create_client(CreateClientInput(client_code="TC01", client_name="會消失"))

    text = "客戶代號\t客戶名稱\nTC01\t覆蓋\n"
    headers, raw = parse_clipboard_text(text)
    mapping = auto_detect_mapping(headers)
    vrows = validate_rows(raw, mapping, container.clients_repo)
    assert vrows[0].is_duplicate_code

    existing = container.clients.find_by_code("TC01")
    container.clients.delete_client(existing.id)

    result = import_validated(vrows, container.clients, on_duplicate_code="overwrite")
    assert result.imported == 0
    assert result.overwritten == 0
    assert result.skipped == 1
    assert result.errors[0][1] == "client.not_found"


# ---------------------------------------------------------------------------
# _parse_diffs malformed JSON fallback (Fix 3)
# ---------------------------------------------------------------------------


def test_mismatch_dialog_malformed_diffs_json_returns_empty(
    container: ServiceContainer,
) -> None:
    """_parse_diffs() must return {} and not raise when differences_json is malformed."""
    _qt_app()
    from taxops.ui.dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="MJ01", client_name="名稱甲", tax_id="12345678")
    )
    bad_match = MatchResultRow(
        id=99,
        client_id=client.id,
        tax_id="12345678",
        registry_source=REGISTRY_SOURCE_MOF,
        cache_version="20260101",
        match_status="mismatch",
        matched_name="名稱乙",
        matched_address=None,
        matched_business_status=None,
        differences_json="{bad json{{",
        review_status="pending",
        generated_at="2026-01-01T00:00:00Z",
    )
    item = MismatchItem(client=client, match_row=bad_match)
    dlg = MismatchReviewDialog([item], container.clients)
    diffs = dlg._parse_diffs(item)
    assert diffs == {}
    dlg.destroy()
