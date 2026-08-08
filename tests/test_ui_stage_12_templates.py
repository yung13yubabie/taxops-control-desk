"""Stage 12 acceptance: message templates page and template editor dialog.

Each test states one condition from the stage's audit row:

  Message templates — "Keep master-detail; contextual actions; EmptyState"
  New/edit template — "Collapsible notes, searchable field list, live preview"

Plus the object-model correctness point: a pending fixed-billing record is an
issuance awaiting confirmation, never money the client owes.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QScrollArea,
    QTextEdit,
)

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.i18n import error_message
from taxops.i18n.status_labels import UNKNOWN_STATUS_TEXT
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.templates import TemplateRow, TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.templates import (
    ALLOWED_VARIABLES,
    CreateTemplateInput,
    TemplatesService,
    VARIABLE_INFO,
    VARIABLE_LABELS,
)
from taxops.ui import tokens
from taxops.ui.dialogs.template_form_dialog import (
    TemplateFormDialog,
    UnknownVariableSource,
    insertion_text,
)
from taxops.ui.pages.templates_page import TemplatesPage
from taxops.ui.widgets.page_shell import MAX_VISIBLE_ACTIONS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeContainer:
    def __init__(self, conn):
        audit_repo = AuditLogRepository(conn)
        self.audit_repo = audit_repo
        repo = TemplatesRepository(conn)
        self.templates = TemplatesService(repo, AuditService(audit_repo, actor="stage12"))
        client = SimpleNamespace(
            id=1, client_code="UI001", client_name="王小明會計師事務所"
        )
        self.clients = SimpleNamespace(
            search_clients=lambda *_a, **_k: [client]
        )
        self.gen_messages = SimpleNamespace(
            build_client_example_variables=lambda _cid: {
                key: "" for key in ALLOWED_VARIABLES
            }
            | {"client_name": client.client_name}
        )
        self.logged: list[tuple[str, dict]] = []
        self.system_log = SimpleNamespace(
            warn=lambda message, detail=None: self.logged.append(
                (message, detail or {})
            )
        )


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "stage12.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


@pytest.fixture()
def page(qapp, container):
    widget = TemplatesPage(container)
    widget.show()
    return widget


def _select(page: TemplatesPage, template_id: int) -> None:
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(template_id):
            page._table.selectRow(row)
            return
    raise AssertionError(f"template {template_id} is not in the list")


def _custom_template(container) -> int:
    return container.templates.create_template(
        CreateTemplateInput(name="自訂測試模板", body="您好 【客戶名稱】")
    ).id


def _builtin_id(container) -> int:
    builtins = [row for row in container.templates.list_all() if row.is_builtin]
    assert builtins, "migrations are expected to seed built-in templates"
    return builtins[0].id


# ── Page: one primary, contextual actions ──────────────────────────────────────

def test_new_template_is_the_pages_only_primary_action(page):
    assert page._new_btn.property("role") == tokens.ROLE_PRIMARY
    assert page._header.actions_visible() == 1


def test_edit_and_trial_live_in_the_inspector_not_the_toolbar(page):
    # The third entry is the icon-only 更多 button, which carries no label.
    assert page._inspector.action_texts() == ("編輯模板", "試用模板", "")
    for button in (page._edit_btn, page._trial_btn, page._more_btn):
        assert page._inspector.isAncestorOf(button)
        assert button.property("role") != tokens.ROLE_PRIMARY


def test_delete_is_reachable_only_through_the_overflow_menu(page):
    menu_texts = tuple(action.text() for action in page._more_menu.actions())
    bar_texts = tuple(
        button.text() for button in page._action_bar.visible_actions()
    )

    assert "刪除模板" in menu_texts
    assert "刪除模板" not in bar_texts
    assert "刪除模板" not in page._inspector.action_texts()
    assert page._delete_btn.property("role") == tokens.ROLE_DANGER


def test_overflow_menu_entry_and_delete_button_share_one_path(
    page, container, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    template_id = _custom_template(container)
    page._refresh()
    _select(page, template_id)
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )

    page._delete_action.trigger()

    assert container.templates.get_template(template_id) is None


def test_refresh_is_a_quiet_icon_and_the_bar_holds_nothing_else(page):
    assert page._refresh_btn.text() == ""
    assert page._refresh_btn.accessibleName() == "重新整理模板清單"
    assert page._refresh_btn.toolTip() == "重新整理模板清單"
    assert page._action_bar.visible_action_count() == 1
    assert page._action_bar.visible_action_count() <= MAX_VISIBLE_ACTIONS


def test_page_entry_reloads_the_list_without_the_user_pressing_refresh(
    page, container
):
    template_id = _custom_template(container)
    assert template_id not in [
        int(page._table.item(r, 0).text()) for r in range(page._table.rowCount())
    ]

    page.refresh_context()

    assert template_id in [
        int(page._table.item(r, 0).text()) for r in range(page._table.rowCount())
    ]


# ── Page: nothing selected explains itself ─────────────────────────────────────

def test_no_selection_shows_an_explanation_instead_of_an_empty_preview_box(page):
    page._table.clearSelection()

    assert page._inspector.is_showing_placeholder()
    assert not page._preview_panel.isVisible()
    assert not page._inspector.actions_are_exposed()


def test_selecting_a_template_reveals_the_preview_and_its_actions(page, container):
    template_id = _custom_template(container)
    page._refresh()

    _select(page, template_id)

    assert not page._inspector.is_showing_placeholder()
    assert page._preview_panel.isVisible()
    assert page._inspector.actions_are_exposed()
    assert "【客戶名稱】" in page._preview.toPlainText()


# ── Page: metadata columns lose their weight ───────────────────────────────────

def test_metadata_columns_are_hidden_and_the_name_column_is_visible(page):
    hidden = {
        page._table.horizontalHeaderItem(idx).text()
        for idx in range(page._table.columnCount())
        if page._table.isColumnHidden(idx)
    }
    shown = {
        page._table.horizontalHeaderItem(idx).text()
        for idx in range(page._table.columnCount())
        if not page._table.isColumnHidden(idx)
    }
    assert hidden == {"編號", "內建", "更新時間"}
    assert shown == {"名稱", "類型"}


def test_hidden_metadata_reappears_in_the_inspector(page, container):
    template_id = _custom_template(container)
    page._refresh()
    _select(page, template_id)

    values = page._inspector.field_values()

    assert values["編號"] == str(template_id)
    assert values["類型"] == "自訂"
    assert values["來源"] == "自訂模板"
    assert values["更新時間"]


# ── Page: built-in templates say what may be done to them ──────────────────────

def test_builtin_template_states_that_it_cannot_be_edited_or_deleted(page, container):
    _select(page, _builtin_id(container))

    values = page._inspector.field_values()

    assert values["編輯"] == "不可編輯（內建模板）"
    assert values["刪除"] == "不可刪除（內建模板）"
    assert not page._edit_btn.isEnabled()
    assert not page._delete_btn.isEnabled()
    assert not page._delete_action.isEnabled()
    assert page._edit_btn.toolTip() == error_message("template.builtin.readonly")


def test_custom_template_states_that_it_can_be_edited_and_deleted(page, container):
    template_id = _custom_template(container)
    page._refresh()

    _select(page, template_id)

    values = page._inspector.field_values()
    assert values["編輯"] == "可以編輯"
    assert values["刪除"] == "可以刪除"
    assert page._edit_btn.isEnabled()
    assert page._delete_btn.isEnabled()
    assert page._delete_action.isEnabled()


def test_double_clicking_a_builtin_row_explains_instead_of_opening_a_dead_form(
    page, container, monkeypatch
):
    shown: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.QMessageBox.information",
        lambda _parent, _title, body: shown.append(body),
    )
    opened: list[bool] = []
    monkeypatch.setattr(
        "taxops.ui.pages.templates_page.TemplateFormDialog",
        lambda *_a, **_k: opened.append(True),
    )
    _select(page, _builtin_id(container))

    page._on_edit_template()

    assert shown == [error_message("template.builtin.readonly")]
    assert opened == []


def test_trial_stays_available_for_a_builtin_template(page, container):
    _select(page, _builtin_id(container))

    assert page._trial_btn.isEnabled()


# ── Page: loud on an unmapped template type ────────────────────────────────────

def test_unknown_template_type_renders_the_unknown_status_line_and_logs(
    page, container, conn
):
    template_id = _custom_template(container)
    conn.execute(
        "UPDATE message_templates SET template_type = 'not_a_type' WHERE id = ?",
        (template_id,),
    )
    conn.commit()

    page._refresh()

    _select(page, template_id)
    assert page._inspector.field_values()["類型"] == UNKNOWN_STATUS_TEXT
    assert any(
        detail.get("template_type") == "not_a_type"
        for _message, detail in container.logged
    )


# ── Page: empty state replaces the body ────────────────────────────────────────

def test_empty_state_replaces_the_master_detail_body(page, container, monkeypatch):
    monkeypatch.setattr(container.templates, "list_all", lambda: [])

    page._refresh()

    assert page._empty_state.isVisible()
    assert page._split.isHidden()
    assert page._empty_state.action_button is not None
    assert page._empty_state.action_button.property("role") == tokens.ROLE_SECONDARY


# ── Dialog: the explanation collapses ──────────────────────────────────────────

def test_field_source_explanation_is_collapsed_and_below_the_editor(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    assert dialog.disclosure_states() == {"真實資料預覽": False, "欄位來源說明": False}
    assert not dialog._variable_help.isVisibleTo(dialog)
    assert dialog._body.isVisibleTo(dialog)


def test_expanding_the_explanation_shows_the_same_text(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    dialog._help_toggle.setChecked(True)

    assert dialog._variable_help.isVisibleTo(dialog)
    assert "不是在此輸入資料" in dialog._variable_help.text()


# ── Dialog: one vertical scroll region ─────────────────────────────────────────

def test_dialog_has_one_scrolling_text_region_by_default(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    visible_text_areas = [
        widget
        for widget in dialog.findChildren(QTextEdit)
        if widget.isVisibleTo(dialog)
    ]

    assert visible_text_areas == [dialog._body]
    assert dialog.findChildren(QScrollArea) == []
    assert len(dialog.findChildren(QListWidget)) == 1


# ── Dialog: categories and search ──────────────────────────────────────────────

def test_field_list_groups_fields_under_source_categories(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    entries = dialog.variable_list_entries()
    headers = [text for text, key in entries if key is None]

    assert "客戶資料" in headers
    assert "索件批次" in headers
    assert "年度工作臺" in headers
    # Every field row sits after a header row.
    assert entries[0][1] is None
    for text, key in entries:
        if key is not None:
            assert VARIABLE_LABELS[key] == text


def test_category_headers_cannot_be_selected_or_inserted(container, qapp):
    from PySide6.QtCore import Qt

    dialog = TemplateFormDialog(container.templates)
    header = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).data(Qt.ItemDataRole.UserRole) is None
    )

    dialog._on_insert_variable(header)

    assert dialog._body.toPlainText() == ""
    assert not header.flags() & Qt.ItemFlag.ItemIsSelectable
    assert not header.flags() & Qt.ItemFlag.ItemIsEnabled


def test_search_box_narrows_the_field_list(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    dialog._var_search.setText("截止")

    labels = [text for text, key in dialog.variable_list_entries() if key is not None]
    assert labels == ["截止日"]
    assert "客戶名稱" not in labels


def test_search_box_matches_a_source_category(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    dialog._var_search.setText("年度工作臺")

    keys = [key for _text, key in dialog.variable_list_entries() if key is not None]
    assert keys
    assert all(VARIABLE_INFO[key].source == "年度工作臺" for key in keys)


def test_search_with_no_match_says_so_instead_of_showing_an_empty_list(
    container, qapp
):
    dialog = TemplateFormDialog(container.templates)

    dialog._var_search.setText("zzz不存在")

    assert dialog.variable_list_entries() == ()
    assert "沒有符合" in dialog._var_detail.text()
    assert dialog._insert_format.text() == "插入格式：—"


def test_a_variable_source_outside_the_category_list_raises(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    from taxops.services import templates as templates_module

    original = templates_module.VARIABLE_INFO["client_name"]
    try:
        templates_module.VARIABLE_INFO["client_name"] = type(original)(
            "無此分類", original.description, original.empty_behavior
        )
        with pytest.raises(UnknownVariableSource):
            dialog._refresh_variable_list()
    finally:
        templates_module.VARIABLE_INFO["client_name"] = original


# ── Dialog: insertion format is explicit ───────────────────────────────────────

def test_selecting_a_field_shows_the_exact_inserted_text(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    item = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).text() == "客戶名稱"
    )

    dialog._var_list.setCurrentItem(item)

    assert dialog._insert_format.text() == "插入格式：【客戶名稱】"
    assert item.toolTip().startswith("插入格式：【客戶名稱】")


def test_double_click_inserts_exactly_the_advertised_text(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    item = next(
        dialog._var_list.item(i)
        for i in range(dialog._var_list.count())
        if dialog._var_list.item(i).text() == "截止日"
    )

    dialog._on_insert_variable(item)

    assert dialog._body.toPlainText() == insertion_text("截止日")


# ── Dialog: footer roles ───────────────────────────────────────────────────────

def test_save_is_the_only_primary_and_cancel_is_secondary(container, qapp):
    from PySide6.QtWidgets import QDialogButtonBox

    dialog = TemplateFormDialog(container.templates)
    box = dialog.findChild(QDialogButtonBox)
    roles = {button.text(): button.property("role") for button in box.buttons()}

    assert roles["新增模板"] == tokens.ROLE_PRIMARY
    assert roles["取消"] == tokens.ROLE_SECONDARY
    assert sum(1 for role in roles.values() if role == tokens.ROLE_PRIMARY) == 1


def test_editing_an_existing_template_keeps_one_primary(container, qapp):
    template_id = _custom_template(container)
    existing = container.templates.get_template(template_id)

    dialog = TemplateFormDialog(container.templates, existing=existing)

    assert dialog._save_btn.property("role") == tokens.ROLE_PRIMARY
    assert dialog._save_btn.isEnabled()


# ── Dialog: built-in templates ─────────────────────────────────────────────────

def test_builtin_template_dialog_is_readonly_and_says_why(container, qapp):
    builtin = container.templates.get_template(_builtin_id(container))

    dialog = TemplateFormDialog(container.templates, existing=builtin)

    assert dialog.windowTitle() == "內建模板（唯讀）"
    assert dialog._builtin_note.isVisibleTo(dialog)
    assert dialog._builtin_note.text() == error_message("template.builtin.readonly")
    assert not dialog._save_btn.isEnabled()
    assert not dialog._body.isEnabled()
    assert not dialog._var_search.isEnabled()


def test_custom_template_dialog_hides_the_builtin_note(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    assert not dialog._builtin_note.isVisibleTo(dialog)


# ── Dialog: real-client preview ────────────────────────────────────────────────

def test_choosing_a_test_client_previews_against_real_data(container, qapp):
    dialog = TemplateFormDialog(container.templates, container=container)
    dialog._example_toggle.setChecked(True)
    dialog._body.setPlainText("您好【客戶名稱】")

    index = dialog._example_client.findData(1)
    dialog._example_client.setCurrentIndex(index)
    dialog._refresh_example_preview()

    assert dialog._example_preview.isVisibleTo(dialog)
    assert "王小明會計師事務所" in dialog._example_preview.toPlainText()


def test_preview_without_a_container_says_the_entry_point_offers_none(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    assert not dialog._example_client.isEnabled()
    assert dialog._example_client.currentText() == "此入口未提供客戶預覽"


# ── Object model: pending fixed billing is not a receivable ────────────────────

def test_fixed_billing_fields_are_described_as_issuance_schedules(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    dialog._type.setCurrentIndex(dialog._type.findData("payment_follow_up"))

    for label in ("全部待開立總額", "逾期待開立總額", "逾期待開立明細"):
        item = next(
            dialog._var_list.item(i)
            for i in range(dialog._var_list.count())
            if dialog._var_list.item(i).text() == label
        )
        dialog._var_list.setCurrentItem(item)
        detail = dialog._var_detail.text()
        assert "固定開立" in detail
        assert "不代表客戶欠款" in detail
        for forbidden in ("應收帳款", "欠款帳本", "未收款"):
            assert forbidden not in detail


def test_field_source_help_does_not_call_pending_billing_money_owed(container, qapp):
    dialog = TemplateFormDialog(container.templates)

    help_text = dialog._variable_help.text()

    assert "待開立排程" in help_text
    assert "不是收款或欠款帳本" in help_text
    assert "應收帳款" not in help_text


def test_fixed_billing_fields_group_under_the_fixed_billing_category(container, qapp):
    dialog = TemplateFormDialog(container.templates)
    dialog._type.setCurrentIndex(dialog._type.findData("payment_follow_up"))

    entries = dialog.variable_list_entries()
    headers = [text for text, key in entries if key is None]

    assert "固定開立" in headers
    assert "應收帳款" not in headers


# ── Legacy placeholder compatibility ───────────────────────────────────────────

def test_legacy_label_still_opens_in_the_editor_and_still_renders(container, qapp):
    """A body written with the pre-rename label keeps working.

    `【未收款總額】` was the old label for `outstanding_amount`. Bodies stored with it
    must still open in the editor and still render, which is what
    `_LEGACY_LABEL_TO_VARIABLE` in the service exists for.
    """
    created = container.templates.create_template(
        CreateTemplateInput(
            name="舊版佔位符",
            template_type="payment_follow_up",
            body="待開立：【未收款總額】",
        )
    )
    existing: TemplateRow = container.templates.get_template(created.id)

    dialog = TemplateFormDialog(container.templates, existing=existing)

    assert "【未收款總額】" in dialog._body.toPlainText()
    assert (
        container.templates.render_template(created.id, {"outstanding_amount": "1,200"})
        == "待開立：1,200"
    )


def test_engineering_placeholders_open_as_the_current_label(container, qapp):
    """Bodies holding the raw `{{ key }}` form become the current Chinese label."""
    row = TemplateRow(
        id=0,
        name="工程佔位符",
        template_type="payment_follow_up",
        body="待開立：{{ outstanding_amount }}",
        is_builtin=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )

    dialog = TemplateFormDialog(container.templates, existing=row)

    assert "【全部待開立總額】" in dialog._body.toPlainText()
    assert "{{" not in dialog._body.toPlainText()
