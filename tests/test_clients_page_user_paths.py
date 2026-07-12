from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.usefixtures("qapp")
def test_search_sort_and_pagination_buttons_follow_real_rows(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    for index in range(105):
        container.clients.create_client(
            CreateClientInput(
                client_code=f"PAGE-{index:03d}",
                client_name=f"分頁客戶 {index:03d}",
            )
        )
    page = ClientsPage(container)
    assert page._table.rowCount() == 50
    assert page._next_btn.isEnabled()

    page._next_btn.click()
    assert page._page == 1
    assert page._table.rowCount() == 50
    assert page._next_btn.isEnabled()

    page._next_btn.click()
    assert page._page == 2
    assert page._table.rowCount() == 5
    assert page._prev_btn.isEnabled()

    page._prev_btn.click()
    assert page._page == 1
    page._prev_btn.click()
    assert page._page == 0
    name_col = _COLUMN_ORDER.index("client_name")
    page._on_header_clicked(name_col)
    assert page._sort_col == "client_name"
    page._on_header_clicked(name_col)
    assert page._sort_dir == "DESC"

    page._search_input.setText("分頁客戶 104")
    page._search_btn.click()
    assert page._table.rowCount() == 1
    assert "104" in page._table.item(0, name_col).text()

    page._clear_btn.click()
    assert page._search_input.text() == ""
    assert page._table.rowCount() == 50


@pytest.mark.usefixtures("qapp")
def test_client_notes_are_visible_by_default_and_preserve_newlines(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    note = "每月 5 日前要報表\n只接受 Email，不要 LINE"
    client = container.clients.create_client(
        CreateClientInput(
            client_code="NOTE-VISIBLE",
            client_name="有特殊要求客戶",
            note=note,
        )
    )
    page = ClientsPage(container)
    note_col = _COLUMN_ORDER.index("note")

    assert "note" not in page._hidden_cols
    assert not page._table.isColumnHidden(note_col)
    item = page._table.item(0, note_col)
    assert "每月 5 日前要報表" in item.text()
    assert item.toolTip() == note
    assert container.clients.get_client(client.id).note == note


@pytest.mark.usefixtures("qapp")
def test_special_requirements_overview_filters_and_shows_full_multiline_note(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    note = "每月 5 日前提供報表\n只接受 Email\n發票寄總公司"
    noted = container.clients.create_client(
        CreateClientInput(
            client_code="NOTE-ONLY",
            client_name="特殊要求客戶",
            note=note,
        )
    )
    container.clients.create_client(
        CreateClientInput(client_code="NO-NOTE", client_name="一般客戶")
    )
    page = ClientsPage(container)

    page._notes_only_check.setChecked(True)

    assert page._table.rowCount() == 1
    assert int(page._table.item(0, _COLUMN_ORDER.index("id")).text()) == noted.id
    page._table.selectRow(0)
    assert page._note_detail.toPlainText() == note
    assert page._note_detail.isVisibleTo(page)


@pytest.mark.usefixtures("qapp")
def test_delete_restore_and_purge_buttons_cover_client_lifecycle(
    container, monkeypatch
):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage

    client = container.clients.create_client(
        CreateClientInput(client_code="LIFECYCLE", client_name="生命週期客戶")
    )
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = ClientsPage(container)
    page._table.selectRow(0)
    page._delete_btn.click()
    assert container.clients.get_client(client.id) is None

    page._show_deleted_check.setChecked(True)
    page._table.selectRow(0)
    assert page._restore_btn.isEnabled()
    page._restore_btn.click()
    assert container.clients.get_client(client.id) is not None

    page._table.selectRow(0)
    page._delete_btn.click()
    page._table.selectRow(0)
    assert page._purge_btn.isEnabled()
    page._purge_btn.click()
    assert container.conn.execute(
        "SELECT COUNT(*) FROM clients WHERE id = ?", (client.id,)
    ).fetchone()[0] == 0


@pytest.mark.usefixtures("qapp")
def test_new_and_edit_buttons_submit_real_dialog_widgets(container, monkeypatch):
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog as RealEditDialog
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog as RealNewDialog
    from taxops.ui.pages.clients_page import ClientsPage, _COLUMN_ORDER

    class NewDialog(RealNewDialog):
        def exec(self):
            self._client_code.setText("DIALOG")
            self._client_name.setText("對話框新增")
            self._note.setPlainText("由真實表單儲存")
            self._save_btn.click()
            return self.result()

    class EditDialog(RealEditDialog):
        def exec(self):
            self._client_name.setText("對話框編輯")
            self._note.setPlainText("編輯亦走真實 Save")
            self._save_btn.click()
            return self.result()

    monkeypatch.setattr("taxops.ui.pages.clients_page.NewClientDialog", NewDialog)
    monkeypatch.setattr("taxops.ui.pages.clients_page.EditClientDialog", EditDialog)
    page = ClientsPage(container)

    page._new_btn.click()
    assert page._new_btn.isEnabled()
    assert page._table.rowCount() == 1

    page._table.selectRow(0)
    page._edit_btn.click()
    name_col = _COLUMN_ORDER.index("client_name")
    assert page._table.item(0, name_col).text() == "對話框編輯"
    saved = container.clients.list_clients()[0]
    assert saved.note == "編輯亦走真實 Save"
    actions = {
        row[0]
        for row in container.conn.execute(
            "SELECT action FROM audit_logs WHERE target_type = 'client'"
        ).fetchall()
    }
    assert {"client.create", "client.update"} <= actions


@pytest.mark.usefixtures("qapp")
def test_refresh_failure_keeps_page_alive_and_shows_warning(
    container, monkeypatch
):
    from taxops.ui.pages.clients_page import ClientsPage

    page = ClientsPage(container)
    warnings = []
    monkeypatch.setattr(
        container.clients,
        "count_clients",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("locked")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._refresh_btn.click()

    assert len(warnings) == 1


@pytest.mark.usefixtures("qapp")
def test_new_client_registry_failure_is_visible_but_manual_dialog_still_opens(
    container, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog as RealDialog
    from taxops.ui.pages.clients_page import ClientsPage

    class CancelDialog(RealDialog):
        opened = False

        def exec(self):
            type(self).opened = True
            assert self._registry_repo is None
            self.reject()
            return self.result()

    warnings: list[str] = []
    monkeypatch.setattr(
        container.tax_registry_repo,
        "count",
        lambda: (_ for _ in ()).throw(RuntimeError("cache locked")),
    )
    monkeypatch.setattr("taxops.ui.pages.clients_page.NewClientDialog", CancelDialog)
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    page = ClientsPage(container)

    page._new_btn.click()

    assert CancelDialog.opened
    assert len(warnings) == 1
    assert "可繼續手動填寫" in warnings[0]
    assert page._new_btn.isEnabled()


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    "operation,unexpected",
    [
        ("delete", False),
        ("delete", True),
        ("restore", False),
        ("restore", True),
        ("purge", False),
        ("purge", True),
    ],
)
def test_client_lifecycle_buttons_keep_service_failures_visible(
    container, monkeypatch, operation, unexpected
):
    from taxops.services.clients import ClientValidationError, CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage

    client = container.clients.create_client(
        CreateClientInput(
            client_code=f"FAIL-{operation}-{int(unexpected)}",
            client_name=f"{operation} 失敗客戶",
        )
    )
    if operation in {"restore", "purge"}:
        container.clients.delete_client(client.id)
    page = ClientsPage(container)
    if operation in {"restore", "purge"}:
        page._show_deleted_check.setChecked(True)
    page._table.selectRow(0)
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    error = RuntimeError("secret lifecycle detail") if unexpected else ClientValidationError(
        "client.not_found"
    )
    method, button = {
        "delete": ("delete_client", page._delete_btn),
        "restore": ("restore_client", page._restore_btn),
        "purge": ("purge_client", page._purge_btn),
    }[operation]
    monkeypatch.setattr(
        container.clients,
        method,
        lambda *_args: (_ for _ in ()).throw(error),
    )

    button.click()

    assert len(warnings) == 1
    assert "secret lifecycle detail" not in warnings[0]
    assert container.conn.execute(
        "SELECT COUNT(*) FROM clients WHERE id = ?", (client.id,)
    ).fetchone()[0] == 1


@pytest.mark.usefixtures("qapp")
def test_edit_missing_client_refreshes_and_warns(container, monkeypatch):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.pages.clients_page import ClientsPage

    container.clients.create_client(
        CreateClientInput(client_code="EDIT-MISSING", client_name="編輯時消失")
    )
    page = ClientsPage(container)
    page._table.selectRow(0)
    warnings: list[str] = []
    monkeypatch.setattr(container.clients, "get_client", lambda _client_id: None)
    monkeypatch.setattr(
        "taxops.ui.pages.clients_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._edit_btn.click()

    assert len(warnings) == 1
    assert warnings[0].strip()
