"""Registry lookup panel in NewClientDialog — smoke + unit tests."""
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
    paths = resolve_paths(override_root=tmp / "RegLookupSmoke")
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
    paths = resolve_paths(override_root=tmp / "RegLookupContainer")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    return build_container(paths, conn)


def _seed_registry(conn: sqlite3.Connection) -> None:
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
            "12345678",
            "測試科技股份有限公司",
            "台北市中正區測試路一段1號",
            None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            "test", "2026-01-01T00:00:00Z",
        ),
    )
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
            "87654321",
            "另一測試有限公司",
            "新北市板橋區測試路二段2號",
            None, None, None, None, None,
            None, None, None, None, None, None, None, None,
            "test", "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# TaxRegistryRepository.search() unit tests
# ---------------------------------------------------------------------------


def test_search_by_exact_tax_id() -> None:
    from taxops.repositories.tax_registry import TaxRegistryRepository

    conn = _fresh_conn()
    _seed_registry(conn)
    repo = TaxRegistryRepository(conn)

    results = repo.search("12345678")
    assert len(results) == 1
    assert results[0]["business_name"] == "測試科技股份有限公司"


def test_search_by_name_partial() -> None:
    from taxops.repositories.tax_registry import TaxRegistryRepository

    conn = _fresh_conn()
    _seed_registry(conn)
    repo = TaxRegistryRepository(conn)

    results = repo.search("測試")
    assert len(results) == 2


def test_search_by_name_specific() -> None:
    from taxops.repositories.tax_registry import TaxRegistryRepository

    conn = _fresh_conn()
    _seed_registry(conn)
    repo = TaxRegistryRepository(conn)

    results = repo.search("另一測試")
    assert len(results) == 1
    assert results[0]["tax_id"] == "87654321"


def test_search_empty_query_returns_empty() -> None:
    from taxops.repositories.tax_registry import TaxRegistryRepository

    conn = _fresh_conn()
    _seed_registry(conn)
    repo = TaxRegistryRepository(conn)

    assert repo.search("") == []
    assert repo.search("   ") == []


def test_search_no_match_returns_empty() -> None:
    from taxops.repositories.tax_registry import TaxRegistryRepository

    conn = _fresh_conn()
    _seed_registry(conn)
    repo = TaxRegistryRepository(conn)

    assert repo.search("不存在公司") == []


# ---------------------------------------------------------------------------
# NewClientDialog smoke — registry panel present / absent
# ---------------------------------------------------------------------------


def test_new_client_dialog_has_lookup_panel_when_registry_provided() -> None:
    _make_app()
    conn = _fresh_conn()
    _seed_registry(conn)
    container = _build_container(conn)

    from PySide6.QtWidgets import QGroupBox

    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(
        container.clients,
        tax_registry_repo=container.tax_registry_repo,
    )
    group_boxes = dialog.findChildren(QGroupBox)
    assert any("稅籍" in gb.title() for gb in group_boxes), (
        "lookup QGroupBox not found when registry_repo is provided"
    )
    container.close()


def test_new_client_dialog_no_lookup_panel_without_registry() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QGroupBox

    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dialog = NewClientDialog(container.clients)
    group_boxes = dialog.findChildren(QGroupBox)
    assert not any("稅籍" in gb.title() for gb in group_boxes), (
        "lookup panel should not appear when registry_repo is None"
    )
    container.close()
