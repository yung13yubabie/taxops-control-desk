"""Slice 2.6 tests: client search/sort/pagination + client_id safety + sidebar collapse.

Covers:
- search_clients() + count_clients() repo methods
- sorting by different columns
- pagination offset
- edit/delete after filter still uses correct client_id (not row index)
- sidebar collapse setting persisted and restored
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_conn() -> sqlite3.Connection:
    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "Slice26Test")
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
    paths = resolve_paths(override_root=tmp / "Slice26Container")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    return build_container(paths, conn)


def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _insert_clients(conn: sqlite3.Connection, n: int) -> list[int]:
    """Insert n clients and return their ids."""
    from taxops.core.clock import now_iso

    ids = []
    ts = now_iso()
    for i in range(1, n + 1):
        cur = conn.execute(
            "INSERT INTO clients(client_code, client_name, tax_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"C{i:03d}", f"測試公司{i:03d}", f"1234{i:04d}", ts, ts),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


# ---------------------------------------------------------------------------
# search_clients / count_clients — repo layer
# ---------------------------------------------------------------------------


def test_count_clients_empty_query_counts_all() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 5)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    assert repo.count_clients() == 5
    conn.close()


def test_count_clients_with_query_filters() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 5)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    assert repo.count_clients("C001") == 1
    assert repo.count_clients("ZZZNOMATCH") == 0
    conn.close()


def test_search_clients_default_order_is_client_code_asc() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 5)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    rows = repo.search_clients()
    codes = [r.client_code for r in rows]
    assert codes == sorted(codes), "default order should be client_code ASC"
    conn.close()


def test_search_clients_order_desc() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 5)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    rows = repo.search_clients(order_by="client_code", order_dir="DESC")
    codes = [r.client_code for r in rows]
    assert codes == sorted(codes, reverse=True)
    conn.close()


def test_search_clients_pagination() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 10)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    page0 = repo.search_clients(limit=3, offset=0)
    page1 = repo.search_clients(limit=3, offset=3)
    assert len(page0) == 3
    assert len(page1) == 3
    ids0 = {r.id for r in page0}
    ids1 = {r.id for r in page1}
    assert ids0.isdisjoint(ids1), "pages must not share rows"
    conn.close()


def test_search_clients_query_by_name() -> None:
    conn = _fresh_conn()
    _insert_clients(conn, 3)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    results = repo.search_clients("測試公司002")
    assert len(results) == 1
    assert results[0].client_code == "C002"
    conn.close()


def test_search_clients_invalid_sort_column_falls_back() -> None:
    """Dangerous column name must fall back to client_code, not raise."""
    conn = _fresh_conn()
    _insert_clients(conn, 3)

    from taxops.repositories.clients import ClientsRepository

    repo = ClientsRepository(conn)
    results = repo.search_clients(order_by="1; DROP TABLE clients; --")
    assert len(results) == 3, "fallback sort must still return all rows"
    conn.close()


# ---------------------------------------------------------------------------
# client_id safety: edit/delete after filter operates on correct client
# ---------------------------------------------------------------------------


def test_edit_after_filter_uses_correct_client_id() -> None:
    """After filtering to one client, edit must update only that client by id."""
    conn = _fresh_conn()
    container = _build_container(conn)

    from taxops.services.clients import CreateClientInput, UpdateClientInput

    a = container.clients.create_client(
        CreateClientInput(client_code="AAA", client_name="A公司", tax_id="11112222")
    )
    b = container.clients.create_client(
        CreateClientInput(client_code="BBB", client_name="B公司", tax_id="33334444")
    )

    results = container.clients.search_clients("AAA")
    assert len(results) == 1
    target_id = results[0].id
    assert target_id == a.id

    updated = container.clients.update_client(
        target_id,
        UpdateClientInput(client_code="AAA", client_name="A公司改名"),
    )
    assert updated.client_name == "A公司改名"

    b_fresh = container.clients.get_client(b.id)
    assert b_fresh is not None
    assert b_fresh.client_name == "B公司"
    container.close()


def test_delete_after_sort_uses_correct_client_id() -> None:
    """After sorting DESC, delete must remove the client by id, not by table position."""
    conn = _fresh_conn()
    container = _build_container(conn)

    from taxops.services.clients import CreateClientInput

    a = container.clients.create_client(
        CreateClientInput(client_code="AAA", client_name="A公司")
    )
    b = container.clients.create_client(
        CreateClientInput(client_code="BBB", client_name="B公司")
    )

    results = container.clients.search_clients(order_by="client_code", order_dir="DESC")
    assert results[0].client_code == "BBB"
    first_id = results[0].id  # = b.id

    container.clients.delete_client(first_id)

    assert container.clients.get_client(b.id) is None
    assert container.clients.get_client(a.id) is not None
    container.close()


# ---------------------------------------------------------------------------
# Sidebar collapse: settings persistence
# ---------------------------------------------------------------------------


def test_sidebar_collapsed_setting_seeded_as_zero() -> None:
    conn = _fresh_conn()
    container = _build_container(conn)
    val = container.settings.get("ui.sidebar_collapsed")
    assert val == "0", f"expected '0', got {val!r}"
    container.close()


def test_sidebar_collapse_setting_persists() -> None:
    conn = _fresh_conn()
    container = _build_container(conn)
    container.settings.set_setting("ui.sidebar_collapsed", "1")
    val = container.settings.get("ui.sidebar_collapsed")
    assert val == "1"
    container.close()


def test_sidebar_collapsed_restored_on_window_init() -> None:
    """MainWindow must explicitly hide nav when ui.sidebar_collapsed='1'."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)
    container.settings.set_setting("ui.sidebar_collapsed", "1")

    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    # isHidden() is True when setVisible(False) was called, regardless of show()
    assert window._nav.isHidden(), "nav must be explicitly hidden when sidebar_collapsed=1"
    assert window._collapse_btn.text() == "▶"
    container.close()


def test_sidebar_expanded_on_window_init_by_default() -> None:
    """Default state must NOT explicitly hide nav (expanded)."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    # isHidden() is False when nav was not explicitly hidden
    assert not window._nav.isHidden(), "nav must not be hidden when sidebar_collapsed=0"
    assert window._collapse_btn.text() == "◀"
    container.close()


# ---------------------------------------------------------------------------
# ClientsPage smoke: search bar + count label + pagination controls present
# ---------------------------------------------------------------------------


def test_clients_page_has_search_and_pagination_widgets() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from PySide6.QtWidgets import QLineEdit

    from taxops.ui.pages.clients_page import ClientsPage

    page = ClientsPage(container)

    assert isinstance(page._search_input, QLineEdit)
    assert hasattr(page, "_prev_btn")
    assert hasattr(page, "_next_btn")
    assert hasattr(page, "_page_label")
    # With no data: page_label shows 共 0 筆, prev/next disabled
    assert page._page_label.text() == "共 0 筆"
    assert not page._prev_btn.isEnabled()
    assert not page._next_btn.isEnabled()
    container.close()


def test_clients_page_count_updates_after_insert() -> None:
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)
    _insert_clients(conn, 3)

    from taxops.ui.pages.clients_page import ClientsPage

    page = ClientsPage(container)
    page.on_refresh()

    # 3 rows, all on page 0 (page_size=50): page_label shows "第 1–3 筆 / 共 3 筆"
    assert "共 3 筆" in page._page_label.text()
    assert "第 1" in page._page_label.text()
    container.close()


def test_page_label_format_combined() -> None:
    """_page_label must show '第 X–Y 筆 / 共 Z 筆' when data exists."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)
    _insert_clients(conn, 5)

    from taxops.ui.pages.clients_page import ClientsPage

    page = ClientsPage(container)
    page.on_refresh()

    label_text = page._page_label.text()
    assert "第 1–5 筆" in label_text, f"expected range in label, got: {label_text!r}"
    assert "共 5 筆" in label_text, f"expected total in label, got: {label_text!r}"
    container.close()


def test_sidebar_save_failure_logs_warning(capsys) -> None:
    """sidebar collapse/expand setting save failure must call system_log.warn, not swallow silently."""
    from unittest.mock import MagicMock, patch

    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)

    # Replace settings with one that always raises on set_setting
    broken_settings = MagicMock()
    broken_settings.get.return_value = "0"
    broken_settings.set_setting.side_effect = RuntimeError("DB locked")
    window._container = MagicMock()
    window._container.settings = broken_settings

    warn_calls = []
    window._container.system_log.warn.side_effect = lambda msg, **kw: warn_calls.append(msg)

    # Trigger collapse save
    window._apply_collapsed(save=True)
    assert any("sidebar" in m for m in warn_calls), (
        f"system_log.warn must be called on save failure; got: {warn_calls}"
    )

    warn_calls.clear()
    # Trigger expand save
    window._apply_expanded(save=True)
    assert any("sidebar" in m for m in warn_calls), (
        f"system_log.warn must be called on expand save failure; got: {warn_calls}"
    )

    container.close()
