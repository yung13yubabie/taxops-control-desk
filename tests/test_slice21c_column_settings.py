"""Slice 21C: column visibility + width persistence (ColumnSettings helper).

Tests the helper itself and verifies it is installed on the four major
tables: engagements list, doc-request batches, doc-request items, tasks.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


_TEST_COLS = ("id", "name", "status", "owner", "due_date")
_TEST_HEADERS = {
    "id": "編號",
    "name": "名稱",
    "status": "狀態",
    "owner": "負責人",
    "due_date": "截止日",
}
_TEST_CORE = frozenset({"name", "status"})


def _make_table(qapp) -> QTableWidget:
    t = QTableWidget(0, len(_TEST_COLS))
    t.setHorizontalHeaderLabels([_TEST_HEADERS[c] for c in _TEST_COLS])
    return t


def _add_test_key(container, table_id: str) -> None:
    """Add the per-table settings keys to ALLOWED_KEYS so set_setting works
    in helper unit tests. We patch the underlying repository directly to
    bypass the whitelist for ad-hoc test table_ids that aren't shipped in
    DEFAULT_SETTINGS."""
    # The settings service whitelists keys via ALLOWED_KEYS. For unit tests
    # we use repo.upsert directly, which has no whitelist.
    container.settings._repo.upsert(f"ui.{table_id}.columns_hidden", "")
    container.settings._repo.upsert(f"ui.{table_id}.column_widths", "")


@pytest.mark.usefixtures("qapp")
def test_install_restores_no_hidden_when_settings_empty(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    for i in range(table.columnCount()):
        assert not table.isColumnHidden(i)


@pytest.mark.usefixtures("qapp")
def test_install_restores_hidden_cols_from_settings(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    container.settings.set_setting("ui.engagements.columns_hidden", "owner,due_date")
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    assert table.isColumnHidden(_TEST_COLS.index("owner"))
    assert table.isColumnHidden(_TEST_COLS.index("due_date"))
    assert not table.isColumnHidden(_TEST_COLS.index("id"))


@pytest.mark.usefixtures("qapp")
def test_install_restores_widths_from_settings(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    widths = json.dumps({"id": 120, "name": 240})
    container.settings.set_setting("ui.engagements.column_widths", widths)
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    assert table.columnWidth(_TEST_COLS.index("id")) == 120
    assert table.columnWidth(_TEST_COLS.index("name")) == 240


@pytest.mark.usefixtures("qapp")
def test_toggle_col_persists_hidden(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    cs._on_toggle_col(_TEST_COLS.index("owner"), False)
    stored = container.settings.get("ui.engagements.columns_hidden")
    assert "owner" in stored


@pytest.mark.usefixtures("qapp")
def test_core_cols_cannot_be_hidden_even_if_in_settings(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    container.settings.set_setting("ui.engagements.columns_hidden", "name,owner")
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    assert not table.isColumnHidden(_TEST_COLS.index("name"))
    assert table.isColumnHidden(_TEST_COLS.index("owner"))


@pytest.mark.usefixtures("qapp")
def test_reset_clears_settings(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    container.settings.set_setting("ui.engagements.columns_hidden", "owner")
    container.settings.set_setting("ui.engagements.column_widths", '{"id": 100}')
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()
    cs._on_reset()
    assert container.settings.get("ui.engagements.columns_hidden") == ""
    assert container.settings.get("ui.engagements.column_widths") == ""
    for i in range(table.columnCount()):
        assert not table.isColumnHidden(i)


# ── Page integration ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("qapp")
def test_engagements_page_installs_column_settings(container):
    from taxops.ui.pages.engagements_page import EngagementsPage
    page = EngagementsPage(container)
    assert hasattr(page, "_col_settings")
    assert page._col_settings.hidden_key == "ui.engagements.columns_hidden"


@pytest.mark.usefixtures("qapp")
def test_doc_requests_page_installs_two_column_settings(container):
    from taxops.ui.pages.document_requests_page import DocumentRequestsPage
    page = DocumentRequestsPage(container)
    assert hasattr(page, "_req_col_settings")
    assert hasattr(page, "_item_col_settings")
    assert page._req_col_settings.hidden_key == "ui.doc_requests.columns_hidden"
    assert page._item_col_settings.hidden_key == "ui.doc_items.columns_hidden"


@pytest.mark.usefixtures("qapp")
def test_tasks_page_installs_column_settings(container):
    from taxops.ui.pages.tasks_page import TasksPage
    page = TasksPage(container)
    assert hasattr(page, "_col_settings")
    assert page._col_settings.hidden_key == "ui.tasks.columns_hidden"
