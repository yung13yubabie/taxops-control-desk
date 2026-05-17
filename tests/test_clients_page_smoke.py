"""Smoke tests for BulkImportWizard Step 1 format hint and template (Slice 2.5-A)."""
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


def _build_container(conn: sqlite3.Connection):
    import pathlib
    import tempfile

    from taxops.core.paths import resolve_paths
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "TestContainerSmoke")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    return build_container(paths, conn)


def _fresh_conn() -> sqlite3.Connection:
    import pathlib
    import tempfile

    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "TestSmoke")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# BulkImportWizard Step 1 — format hint and template (Slice 2.5-A)
# ---------------------------------------------------------------------------


def test_bulk_import_wizard_shows_multiline_format_hint() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    wizard = BulkImportWizard(container.clients, container.clients_repo)

    from PySide6.QtWidgets import QLabel

    hint_texts = [lbl.text() for lbl in wizard.findChildren(QLabel)]
    joined = "\n".join(hint_texts)

    assert "客戶代號" in joined, "format hint must mention '客戶代號'"
    assert "客戶名稱" in joined, "format hint must mention '客戶名稱'"

    container.close()


def test_bulk_import_template_clipboard_contains_two_data_rows() -> None:
    """_PASTE_TEMPLATE (written to clipboard) must have header + ≥2 data rows.

    We test the constant directly — clicking the button triggers
    QMessageBox.information() which blocks in offscreen mode.
    """
    from taxops.ui.dialogs.bulk_import_wizard import _PASTE_TEMPLATE

    lines = [ln for ln in _PASTE_TEMPLATE.splitlines() if ln.strip()]
    assert len(lines) >= 3, (
        f"_PASTE_TEMPLATE must have header + 2 data rows, got {len(lines)} non-empty lines"
    )
    header_cols = lines[0].split("\t")
    assert "客戶代號" in header_cols, "template header must contain '客戶代號'"
    assert "客戶名稱" in header_cols, "template header must contain '客戶名稱'"
    assert len(lines) - 1 >= 2, "template must have at least 2 data rows"


def test_bulk_import_wizard_has_copy_template_button() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QPushButton

    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    wizard = BulkImportWizard(container.clients, container.clients_repo)
    copy_btn = next(
        (
            btn
            for btn in wizard.findChildren(QPushButton)
            if "複製" in btn.text() and "範本" in btn.text()
        ),
        None,
    )
    assert copy_btn is not None, "複製貼上範本 button not found in BulkImportWizard"
    container.close()
