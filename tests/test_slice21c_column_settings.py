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
def test_install_clamps_tiny_saved_widths(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings
    widths = json.dumps({"id": 1, "name": 1, "status": 1})
    container.settings.set_setting("ui.engagements.column_widths", widths)
    table = _make_table(qapp)
    cs = ColumnSettings(table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings)
    cs.install()

    assert table.columnWidth(_TEST_COLS.index("id")) >= 56
    assert table.columnWidth(_TEST_COLS.index("name")) >= 120
    assert table.columnWidth(_TEST_COLS.index("status")) >= 120


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


@pytest.mark.usefixtures("qapp")
def test_clients_page_keeps_core_identity_columns_visible(container):
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    page = ClientsPage(container)
    page._hidden_cols.update({"client_code", "client_name"})
    page._apply_column_visibility()

    assert not page._table.isColumnHidden(_COLUMN_ORDER.index("client_code"))
    assert not page._table.isColumnHidden(_COLUMN_ORDER.index("client_name"))


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    "raw",
    ["not-json", "[]", '{"id": "bad", "owner": 0}'],
)
def test_invalid_width_settings_are_ignored_without_breaking_table(
    qapp, container, raw
):
    from taxops.ui.widgets.column_settings import ColumnSettings

    container.settings.set_setting("ui.engagements.column_widths", raw)
    table = _make_table(qapp)
    original = [table.columnWidth(i) for i in range(table.columnCount())]
    settings = ColumnSettings(
        table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings
    )

    settings.install()

    assert [table.columnWidth(i) for i in range(table.columnCount())] == original


@pytest.mark.usefixtures("qapp")
def test_resize_and_auto_resize_persist_only_visible_columns(qapp, container):
    from taxops.ui.widgets.column_settings import ColumnSettings

    table = _make_table(qapp)
    settings = ColumnSettings(
        table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings
    )
    settings.install()
    table.setColumnHidden(_TEST_COLS.index("owner"), True)
    table.setColumnWidth(_TEST_COLS.index("id"), 155)
    settings._save_widths()
    settings._on_auto_resize_all()

    stored = json.loads(container.settings.get("ui.engagements.column_widths"))
    assert "owner" not in stored
    assert stored["id"] > 0


@pytest.mark.usefixtures("qapp")
def test_persistence_failures_are_contained_and_do_not_change_ui(
    qapp, container, monkeypatch, caplog
):
    from taxops.ui.widgets.column_settings import ColumnSettings

    table = _make_table(qapp)
    settings = ColumnSettings(
        table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings
    )
    settings.install()
    monkeypatch.setattr(
        container.settings,
        "set_setting",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("settings locked")),
    )

    settings._on_toggle_col(_TEST_COLS.index("owner"), False)
    settings._on_reset()

    assert not table.isColumnHidden(_TEST_COLS.index("owner"))
    assert "failed to persist hidden cols" in caplog.text
    assert "failed to persist widths" in caplog.text
    assert "failed to clear presets" in caplog.text


@pytest.mark.usefixtures("qapp")
def test_suspended_save_does_not_write_settings(qapp, container, monkeypatch):
    from taxops.ui.widgets.column_settings import ColumnSettings

    table = _make_table(qapp)
    settings = ColumnSettings(
        table, "engagements", _TEST_COLS, _TEST_CORE, _TEST_HEADERS, container.settings
    )
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        container.settings,
        "set_setting",
        lambda key, value: writes.append((key, value)),
    )
    settings._suspend_save = True

    settings._save_hidden()
    settings._save_widths()

    assert writes == []


@pytest.mark.usefixtures("qapp")
def test_oversized_width_payload_is_not_persisted(qapp, container, monkeypatch, caplog):
    from taxops.ui.widgets.column_settings import ColumnSettings

    columns = tuple(f"very_long_column_name_{index:03d}" for index in range(40))
    table = QTableWidget(0, len(columns))
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        container.settings,
        "set_setting",
        lambda key, value: writes.append((key, value)),
    )
    settings = ColumnSettings(
        table,
        "oversized",
        columns,
        frozenset(),
        {column: column for column in columns},
        container.settings,
    )

    settings._save_widths()

    assert writes == []
    assert "widths JSON too long" in caplog.text
