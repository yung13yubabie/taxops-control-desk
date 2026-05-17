"""Slice 6 UI integration tests: TemplatesPage handler → service → DB → audit."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.templates import TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.templates import CreateTemplateInput, TemplatesService
from taxops.ui.pages.templates_page import TemplatesPage


# ── QApplication singleton ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ── DB + services fixture ─────────────────────────────────────────────────────

class _FakeContainer:
    """Minimal stand-in for ServiceContainer used by TemplatesPage."""

    def __init__(self, conn):
        self._conn = conn
        audit_repo = AuditLogRepository(conn)
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.audit_repo = audit_repo
        repo = TemplatesRepository(conn)
        self.templates = TemplatesService(repo, self._audit)


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "ui_test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


@pytest.fixture()
def page(qapp, container):
    w = TemplatesPage(container)
    w.show()
    return w


# ── widget smoke ──────────────────────────────────────────────────────────────

def test_templates_page_instantiates(page):
    assert page is not None


def test_new_btn_always_enabled(page):
    assert page._new_btn.isEnabled()


def test_refresh_btn_always_enabled(page):
    assert page._refresh_btn.isEnabled()


def test_edit_delete_disabled_without_selection(page):
    assert not page._edit_btn.isEnabled()
    assert not page._delete_btn.isEnabled()


# ── builtin templates appear on load ─────────────────────────────────────────

def test_builtin_templates_shown_on_load(page):
    assert page._table.rowCount() >= 2
    assert page._table.isVisible()


def test_empty_label_hidden_when_templates_exist(page):
    assert not page._empty_label.isVisible()


# ── custom template create → refresh ─────────────────────────────────────────

def test_table_shows_custom_template_after_service_create(page, container):
    before = page._table.rowCount()
    container.templates.create_template(CreateTemplateInput(name="UI測試模板", body="Hi {{ client_name }}"))
    page._refresh()
    assert page._table.rowCount() == before + 1


# ── _selected_template_id ─────────────────────────────────────────────────────

def test_selected_template_id_returns_none_without_selection(page):
    page._table.clearSelection()
    assert page._selected_template_id() is None


def test_selected_template_id_returns_correct_id(page, container):
    created = container.templates.create_template(
        CreateTemplateInput(name="選取測試", body="hi")
    )
    page._refresh()
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(created.id):
            page._table.selectRow(row)
            break
    assert page._selected_template_id() == created.id


# ── delete → DB → audit ───────────────────────────────────────────────────────

def test_delete_template_removes_from_list_and_audit(page, container, conn):
    created = container.templates.create_template(
        CreateTemplateInput(name="刪除測試", body="bye")
    )
    container.templates.delete_template(created.id)
    page._refresh()

    ids = [int(page._table.item(r, 0).text()) for r in range(page._table.rowCount())]
    assert created.id not in ids

    logs = conn.execute(
        "SELECT action FROM audit_logs WHERE action='template.delete' ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert len(logs) == 1


# ── preview pane ──────────────────────────────────────────────────────────────

def test_preview_updates_on_row_selection(page, container):
    created = container.templates.create_template(
        CreateTemplateInput(name="預覽測試", body="預覽內容 {{ client_name }}")
    )
    page._refresh()
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(created.id):
            page._table.selectRow(row)
            break
    assert "預覽內容" in page._preview.toPlainText()


def test_preview_cleared_on_deselect(page):
    page._table.clearSelection()
    assert page._preview.toPlainText() == ""
