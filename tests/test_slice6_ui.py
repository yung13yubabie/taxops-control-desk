"""Slice 6 UI integration tests: TemplatesPage handler → service → DB → audit."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.templates import TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.templates import (
    ALLOWED_VARIABLES,
    CreateTemplateInput,
    TemplatesService,
    UpdateTemplateInput,
)
from taxops.ui.dialogs.template_form_dialog import TemplateFormDialog
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
        client = SimpleNamespace(
            id=1,
            client_code="UI001",
            client_name="王小明會計師事務所",
        )
        self.clients = SimpleNamespace(search_clients=lambda *_args, **_kwargs: [client])
        self.gen_messages = SimpleNamespace(
            build_client_example_variables=lambda _client_id: {
                key: "" for key in ALLOWED_VARIABLES
            }
            | {"client_name": client.client_name}
        )
        self.system_log = SimpleNamespace(warn=lambda *_args, **_kwargs: None)


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


def test_refresh_preserves_selected_template_by_id_after_resort(page, container):
    first = container.templates.create_template(
        CreateTemplateInput(name="Alpha", body="first")
    )
    selected = container.templates.create_template(
        CreateTemplateInput(name="Zulu", body="selected")
    )
    page._refresh()
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(selected.id):
            page._table.selectRow(row)
            break

    container.templates.update_template(
        selected.id,
        UpdateTemplateInput(
            name="Aardvark",
            template_type="custom",
            body="selected",
        ),
    )
    page._refresh()

    assert page._selected_template_id() == selected.id
    assert page._selected_template_id() != first.id


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


def test_template_form_variable_list_uses_plain_language(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    labels = [dialog._var_list.item(i).text() for i in range(dialog._var_list.count())]

    assert "客戶名稱" in labels
    assert "截止日" in labels
    assert all("{{" not in label and "}}" not in label for label in labels)


def test_template_form_insert_variable_uses_plain_language_placeholder(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    item = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).text() == "客戶名稱"
    )

    dialog._on_insert_variable(item)

    body = dialog._body.toPlainText()
    assert body == "【客戶名稱】"
    assert "{{" not in body


def test_template_form_variable_list_tracks_template_type(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    idx = dialog._type.findData("payment_follow_up")
    dialog._type.setCurrentIndex(idx)

    labels = [dialog._var_list.item(i).text() for i in range(dialog._var_list.count())]

    assert "可用欄位：固定開立提醒" in dialog._var_title.text()
    assert "逾期待開立明細" in labels
    assert "全部待開立總額" in labels
    assert "缺少文件" not in labels


def test_template_form_shows_selected_variable_source(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    item = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).text() == "客戶名稱"
    )

    dialog._var_list.setCurrentItem(item)

    detail = dialog._var_detail.text()
    assert "來源：客戶資料" in detail
    assert "所選索件批次" in detail


def test_template_toolbar_click_path_creates_edits_trials_and_deletes(
    page, container, monkeypatch
):
    from PySide6.QtWidgets import QDialog, QMessageBox

    class FormDialog(TemplateFormDialog):
        def exec(self):
            if self._existing is None:
                self._name.setText("Toolbar template")
                self._body.setPlainText("Hello 【客戶名稱】")
            else:
                self._name.setText("Toolbar edited")
                self._body.setPlainText("Edited 【客戶名稱】")
            self._save_btn.click()
            return self.result()

    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.TemplateFormDialog", FormDialog
    )
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    page._new_btn.click()
    created = next(
        row for row in container.templates.list_all() if row.name == "Toolbar template"
    )
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(created.id):
            page._table.selectRow(row)
            break
    page._edit_btn.click()
    edited = container.templates.get_template(created.id)
    assert edited.name == "Toolbar edited"
    assert edited.body == "Edited 【客戶名稱】"
    assert container.templates.render_template(
        created.id, {"client_name": "王小明會計師事務所"}
    ) == "Edited 王小明會計師事務所"

    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(created.id):
            page._table.selectRow(row)
            break
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.DialogCode.Rejected)
    page._trial_btn.click()

    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(created.id):
            page._table.selectRow(row)
            break
    page._delete_btn.click()
    assert container.templates.get_template(created.id) is None


def test_template_form_warns_payment_fields_are_not_receivables(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    dialog._type.setCurrentIndex(dialog._type.findData("payment_follow_up"))
    item = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).text() == "逾期待開立總額"
    )

    dialog._var_list.setCurrentItem(item)

    assert "固定開立" in dialog._var_detail.text()
    assert "不代表客戶欠款" in dialog._var_detail.text()


def test_template_page_load_failure_clears_stale_rows_and_shows_error(
    page, container, monkeypatch
):
    container.system_log = SimpleNamespace(warn=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        container.templates,
        "list_all",
        lambda: (_ for _ in ()).throw(RuntimeError("templates locked")),
    )

    page._refresh_btn.click()

    assert page._table.rowCount() == 0
    assert not page._error_label.isHidden()
    assert page._table.isHidden()
    assert page._empty_state.isHidden()


def test_template_edit_missing_target_warns_and_refreshes(page, container, monkeypatch):
    warnings: list[str] = []
    page._table.selectRow(0)
    monkeypatch.setattr(
        container.templates,
        "get_template",
        lambda _template_id: (_ for _ in ()).throw(RuntimeError("stale id")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._edit_btn.click()

    assert len(warnings) == 1
    assert warnings[0].strip()


@pytest.mark.parametrize("operation,unexpected", [("delete", False), ("delete", True), ("trial", False), ("trial", True)])
def test_template_action_failures_are_visible_and_do_not_mutate(
    page, container, monkeypatch, operation, unexpected
):
    from PySide6.QtWidgets import QMessageBox
    from taxops.services.templates import TemplateValidationError

    custom = container.templates.create_template(
        CreateTemplateInput(name=f"{operation} failure", body="Hello 【客戶名稱】")
    )
    container.system_log = SimpleNamespace(warn=lambda *_args, **_kwargs: None)
    page._refresh()
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(custom.id):
            page._table.selectRow(row)
            break
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    error = RuntimeError("secret template detail") if unexpected else TemplateValidationError(
        "template.not_found"
    )
    method, button = {
        "delete": ("delete_template", page._delete_btn),
        "trial": ("render_template", page._trial_btn),
    }[operation]
    monkeypatch.setattr(
        container.templates,
        method,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    button.click()

    assert len(warnings) == 1
    assert "secret template detail" not in warnings[0]
    assert container.templates.get_template(custom.id) is not None
