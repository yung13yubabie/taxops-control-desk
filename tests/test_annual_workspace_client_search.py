from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from taxops.services.clients import CreateClientInput
from taxops.ui.dialogs.annual_workspace_dialog import AnnualWorkspaceDialog


def _insert_active_clients(container, count: int) -> list[object]:
    rows = [
        container.clients_repo.insert(
            client_code=f"BOUND-{index:04d}",
            client_name=f"邊界測試客戶 {index:04d}",
        )
        for index in range(1, count + 1)
    ]
    container.conn.commit()
    return rows


def test_client_search_is_bounded_warns_and_can_find_client_501(
    qtbot, container
) -> None:
    clients = _insert_active_clients(container, 501)
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)

    assert dialog.client_combo.count() == 101
    assert dialog.feedback_label.text() == (
        "找到 501 位客戶，目前顯示前 100 位，請輸入更完整的代號或名稱。"
    )
    assert dialog.client_combo.findData(clients[500].id) < 0

    dialog.client_search_input.setText("BOUND-0501")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)

    assert dialog.client_combo.count() == 2
    assert dialog.client_combo.itemData(1) == clients[500].id
    dialog.client_combo.setCurrentIndex(1)
    assert dialog.client_combo.currentData() == clients[500].id

    dialog.client_search_input.setText("BOUND-0500")
    qtbot.keyClick(dialog.client_search_input, Qt.Key.Key_Return)
    assert dialog.client_combo.itemData(1) == clients[499].id


def test_preselected_active_client_is_fetched_exactly_beyond_first_page(
    qtbot, container, monkeypatch
) -> None:
    clients = _insert_active_clients(container, 101)
    real_get = container.clients.get_client
    fetched: list[int] = []

    def get_exact(client_id: int):
        fetched.append(client_id)
        return real_get(client_id)

    monkeypatch.setattr(container.clients, "get_client", get_exact)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=clients[100].id, operation_year=2026
    )
    qtbot.addWidget(dialog)

    assert fetched == [clients[100].id]
    assert dialog.client_combo.currentData() == clients[100].id
    assert dialog.client_combo.findData(clients[100].id) >= 0


def test_deleted_client_is_never_visible_in_search_or_preselection(
    qtbot, container
) -> None:
    deleted = container.clients.create_client(
        CreateClientInput(client_code="DELETED-ONLY", client_name="已刪除客戶")
    )
    container.clients.delete_client(deleted.id)
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=deleted.id, operation_year=2026
    )
    qtbot.addWidget(dialog)
    dialog.client_search_input.setText("DELETED-ONLY")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)

    assert dialog.client_combo.findData(deleted.id) < 0
    assert dialog.client_combo.count() == 1
    assert dialog.feedback_label.text() == "找到 0 位客戶。"


def test_initial_and_interactive_client_search_failures_are_visible_and_safe(
    qtbot, container, monkeypatch
) -> None:
    real_count = container.clients.count_clients
    monkeypatch.setattr(
        container.clients,
        "count_clients",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW INITIAL CLIENT SECRET")
        ),
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.client_combo.count() == 0
    assert dialog.feedback_label.text() == "載入客戶失敗，請稍後再試。"
    assert "SECRET" not in dialog.feedback_label.text()
    assert dialog.client_search_button.isEnabled()

    monkeypatch.setattr(container.clients, "count_clients", real_count)
    second = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(second)
    second.client_search_input.setText("保留的搜尋文字")
    monkeypatch.setattr(
        container.clients,
        "search_clients",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW SEARCH CLIENT SECRET")
        ),
    )
    qtbot.mouseClick(second.client_search_button, Qt.MouseButton.LeftButton)

    assert second.result() != QDialog.DialogCode.Accepted
    assert second.client_combo.count() == 0
    assert second.client_search_input.text() == "保留的搜尋文字"
    assert second.feedback_label.text() == "載入客戶失敗，請稍後再試。"
    assert "SECRET" not in second.feedback_label.text()
    assert second.client_search_button.isEnabled()
