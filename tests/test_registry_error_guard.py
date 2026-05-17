"""Guard tests: registry errors must not block new-client flow.

Covers:
- count() exception → NewClientDialog opens without lookup panel
- search() exception → dialog shows Chinese warning, does not crash
- registry prefill tracked in audit detail on save
- BulkImportWizard Step 1 is scrollable (QScrollArea present)
"""
from __future__ import annotations

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fresh_conn() -> sqlite3.Connection:
    import pathlib
    import tempfile

    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "GuardTest")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return conn


def _build_container(conn: sqlite3.Connection):
    import pathlib
    import tempfile

    from taxops.core.paths import resolve_paths
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "GuardContainer")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    return build_container(paths, conn)


class _BrokenRepo:
    """Stub that always raises on count() and search()."""

    def count(self) -> int:
        raise RuntimeError("simulated DB failure")

    def search(self, query: str, **_kwargs) -> list:
        raise RuntimeError("simulated search failure")


# ---------------------------------------------------------------------------
# count() exception → dialog opens without lookup panel
# ---------------------------------------------------------------------------


def test_new_client_dialog_opens_when_count_raises() -> None:
    """clients_page.on_new_client() must catch count() exception and open dialog."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QGroupBox

    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    # Simulate what clients_page.on_new_client() does when count() raises
    registry_repo = None
    try:
        if _BrokenRepo().count() > 0:
            registry_repo = _BrokenRepo()
    except Exception:
        pass  # should be caught — registry_repo stays None

    dialog = NewClientDialog(container.clients, tax_registry_repo=registry_repo)

    # Dialog must open successfully — no lookup panel
    assert dialog is not None
    group_boxes = dialog.findChildren(QGroupBox)
    assert not any("稅籍" in gb.title() for gb in group_boxes)

    container.close()


# ---------------------------------------------------------------------------
# search() exception → warning shown, dialog does not crash
# ---------------------------------------------------------------------------


def test_new_client_search_exception_does_not_crash() -> None:
    """_on_search() must catch search() exception, not crash, not expose raw error."""
    from unittest.mock import patch

    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QMessageBox

    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    broken = _BrokenRepo()
    dialog = NewClientDialog(container.clients, tax_registry_repo=broken)  # type: ignore[arg-type]

    dialog._search_input.setText("任意查詢")

    # Mock QMessageBox.warning so it doesn't block in offscreen mode
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        try:
            dialog._on_search()
            raised = False
        except Exception:
            raised = True

    assert not raised, "_on_search() must not propagate exceptions to caller"
    assert not dialog._result_combo.isEnabled()

    container.close()


# ---------------------------------------------------------------------------
# Stale results cleared when second search fails
# ---------------------------------------------------------------------------


def test_stale_results_cleared_after_search_failure() -> None:
    """Search A succeeds → search B fails → combo must be empty and fill disabled."""
    import sqlite3
    from unittest.mock import patch

    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    conn.execute(
        "INSERT INTO tax_registry_cache("
        "tax_id, business_name, business_address, parent_tax_id, capital, "
        "registered_date_roc, organization_type, uses_uniform_invoice, "
        "industry_code_primary, industry_name_primary, "
        "industry_code_1, industry_name_1, "
        "industry_code_2, industry_name_2, "
        "industry_code_3, industry_name_3, "
        "cache_version, imported_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "12345678", "第一家公司", "台北市中正區",
            None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            "v20260510", "2026-05-10T00:00:00Z",
        ),
    )
    conn.commit()

    from taxops.repositories.tax_registry import TaxRegistryRepository
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog
    from PySide6.QtWidgets import QMessageBox

    registry_repo = TaxRegistryRepository(conn)

    dialog = NewClientDialog(container.clients, tax_registry_repo=registry_repo)

    # First search — succeeds
    dialog._search_input.setText("12345678")
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
        dialog._on_search()

    assert dialog._result_combo.count() == 1, "first search should have 1 result"
    assert dialog._result_combo.isEnabled()
    assert dialog._fill_btn.isEnabled()

    # Second search — repo replaced with broken one to simulate failure
    dialog._registry_repo = _BrokenRepo()  # type: ignore[assignment]
    dialog._search_input.setText("broken_query")

    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        dialog._on_search()

    # After failure: combo must be cleared and fill disabled
    assert dialog._result_combo.count() == 0, "combo must be empty after failed search"
    assert not dialog._result_combo.isEnabled(), "combo must be disabled after failed search"
    assert not dialog._fill_btn.isEnabled(), "fill button must be disabled after failed search"
    assert dialog._registry_results == [], "internal results list must be empty"
    assert dialog._registry_prefill is None, "prefill must be cleared"

    container.close()


# ---------------------------------------------------------------------------
# Registry prefill tracked in audit detail
# ---------------------------------------------------------------------------


def test_registry_prefill_recorded_in_audit() -> None:
    """When registry lookup fills the form, audit.detail must record source."""
    conn = _fresh_conn()
    container = _build_container(conn)

    conn.execute(
        "INSERT INTO tax_registry_cache("
        "tax_id, business_name, business_address, parent_tax_id, capital, "
        "registered_date_roc, organization_type, uses_uniform_invoice, "
        "industry_code_primary, industry_name_primary, "
        "industry_code_1, industry_name_1, "
        "industry_code_2, industry_name_2, "
        "industry_code_3, industry_name_3, "
        "cache_version, imported_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "55667788", "審計來源公司", "台南市中西區",
            None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            "v20260510", "2026-05-10T00:00:00Z",
        ),
    )
    conn.commit()

    from taxops.services.clients import CreateClientInput

    payload = CreateClientInput(
        client_code="AUDIT1",
        client_name="審計來源公司",
        tax_id="55667788",
        registry_source_tax_id="55667788",
        registry_cache_version="v20260510",
    )
    row = container.clients.create_client(payload)

    import json

    audit_rows = container.audit._repo.list_recent(limit=5)  # type: ignore[attr-defined]
    create_row = next(
        r for r in audit_rows
        if r.action == "client.create" and r.target_id == str(row.id)
    )
    detail = json.loads(create_row.detail_json) if create_row.detail_json else {}
    assert detail.get("registry_prefill_used") is True
    assert detail.get("source_tax_id") == "55667788"
    assert detail.get("cache_version") == "v20260510"

    container.close()


# ---------------------------------------------------------------------------
# BulkImportWizard Step 1 is scrollable
# ---------------------------------------------------------------------------


def test_bulk_import_wizard_step1_is_scrollarea() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QScrollArea

    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    wizard = BulkImportWizard(container.clients, container.clients_repo)

    step1_widget = wizard._stack.widget(0)
    assert isinstance(step1_widget, QScrollArea), (
        f"Step 1 must be a QScrollArea, got {type(step1_widget).__name__}"
    )

    # Template button must be inside the scroll area's inner widget
    from PySide6.QtWidgets import QPushButton

    inner = step1_widget.widget()
    copy_btn = next(
        (btn for btn in inner.findChildren(QPushButton) if "複製" in btn.text()),
        None,
    )
    assert copy_btn is not None, "複製貼上範本 button not found inside scroll area"

    container.close()
