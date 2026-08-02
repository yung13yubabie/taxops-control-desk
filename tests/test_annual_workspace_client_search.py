from __future__ import annotations

import time
import threading

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QDialog

from taxops.services.clients import CreateClientInput
from taxops.ui.dialogs.annual_workspace_dialog import AnnualWorkspaceDialog
from taxops.ui.dialogs import annual_workspace_dialog
from taxops.ui.workers import annual_client_search


def _insert_active_clients(container, count: int) -> list[object]:
    rows = [
        container.clients_repo.insert(
            client_code=f"BOUND-{index:04d}",
            client_name=f"效能測試客戶 {index:04d}",
        )
        for index in range(1, count + 1)
    ]
    container.conn.commit()
    return rows


def _wait_for_search(qtbot, dialog: AnnualWorkspaceDialog) -> None:
    qtbot.waitUntil(lambda: not dialog._search_workers, timeout=2000)


def test_client_search_is_bounded_warns_and_can_find_client_501(
    qtbot, container
) -> None:
    clients = _insert_active_clients(container, 501)
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    _wait_for_search(qtbot, dialog)

    assert dialog.client_combo.count() == 101
    assert dialog.feedback_label.text() == (
        "結果超過 100 筆，僅顯示前 100 筆，請輸入更精確關鍵字。"
    )
    assert dialog.client_combo.findData(clients[500].id) < 0

    dialog.client_search_input.setText("BOUND-0501")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)
    _wait_for_search(qtbot, dialog)

    assert dialog.client_combo.count() == 2
    assert dialog.client_combo.itemData(1) == clients[500].id
    dialog.client_combo.setCurrentIndex(1)
    assert dialog.client_combo.currentData() == clients[500].id

    dialog.client_search_input.setText("BOUND-0500")
    qtbot.keyClick(dialog.client_search_input, Qt.Key.Key_Return)
    _wait_for_search(qtbot, dialog)
    assert dialog.client_combo.itemData(1) == clients[499].id


def test_constructor_does_not_block_qt_event_loop_on_client_query(
    qtbot, container, monkeypatch
) -> None:
    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.2)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    timer_fired: list[bool] = []
    QTimer.singleShot(10, lambda: timer_fired.append(True))

    started = time.monotonic()
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    elapsed = time.monotonic() - started
    qtbot.addWidget(dialog)

    assert elapsed < 0.1
    assert dialog._search_workers
    qtbot.waitUntil(lambda: timer_fired == [True], timeout=1000)
    _wait_for_search(qtbot, dialog)


def test_editing_query_without_search_discards_delayed_old_result(
    qtbot, container, monkeypatch
) -> None:
    old = container.clients_repo.insert(
        client_code="ONLY-OLD", client_name="只屬於舊查詢"
    )
    container.conn.commit()

    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.15)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    dialog.client_search_input.setText("ONLY-OLD")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)
    dialog.client_search_input.setText("尚未按搜尋的新條件")

    _wait_for_search(qtbot, dialog)

    assert dialog.client_search_input.text() == "尚未按搜尋的新條件"
    assert dialog.client_combo.findData(old.id) < 0
    assert "重新搜尋" in dialog.feedback_label.text()


def test_rapid_search_clicks_keep_at_most_one_live_worker(
    qtbot, container, monkeypatch
) -> None:
    counter_lock = threading.Lock()
    active = 0
    maximum = 0

    class CountedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.1)
                super().run()
            finally:
                with counter_lock:
                    active -= 1

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", CountedWorker
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    for index in range(8):
        dialog.client_search_input.setText(f"連點-{index}")
        qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)

    _wait_for_search(qtbot, dialog)

    assert maximum == 1
    assert dialog.client_search_input.text() == "連點-7"


def test_delayed_old_search_keeps_ui_responsive_and_cannot_replace_new_result(
    qtbot, container, monkeypatch
) -> None:
    old = container.clients_repo.insert(
        client_code="STALE-OLD", client_name="舊搜尋結果"
    )
    new = container.clients_repo.insert(
        client_code="STALE-NEW", client_name="新搜尋結果"
    )
    container.conn.commit()
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    _wait_for_search(qtbot, dialog)

    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.2 if self._query == "STALE-OLD" else 0.01)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    heartbeat: list[bool] = []
    dialog.client_search_input.setText("STALE-OLD")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)
    QTimer.singleShot(10, lambda: dialog.client_search_input.setText("STALE-NEW"))
    QTimer.singleShot(
        15,
        lambda: qtbot.mouseClick(
            dialog.client_search_button, Qt.MouseButton.LeftButton
        ),
    )
    QTimer.singleShot(20, lambda: heartbeat.append(True))

    qtbot.waitUntil(lambda: heartbeat == [True], timeout=500)
    _wait_for_search(qtbot, dialog)

    assert dialog.client_combo.findData(new.id) >= 0
    assert dialog.client_combo.findData(old.id) < 0
    assert dialog.feedback_label.text() == "找到 1 筆客戶。"


def test_cancel_waits_for_search_worker_before_rejecting_dialog(
    qtbot, container, monkeypatch
) -> None:
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    _wait_for_search(qtbot, dialog)

    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.2)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    rejected = QSignalSpy(dialog.rejected)
    dialog.show()
    dialog.client_search_input.setText("停止中的搜尋")
    qtbot.mouseClick(dialog.client_search_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)

    assert dialog._close_after_search is True
    assert dialog._search_workers
    assert rejected.count() == 0
    _wait_for_search(qtbot, dialog)
    qtbot.waitUntil(lambda: rejected.count() == 1, timeout=1000)
    assert not dialog._search_workers


def test_reject_after_native_finish_does_not_launch_pending_search(
    qtbot, container, monkeypatch
) -> None:
    created: list[annual_client_search.AnnualClientSearchWorker] = []

    class ObservedWorker(annual_client_search.AnnualClientSearchWorker):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", ObservedWorker
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    dialog.client_search_input.setText("關閉前的待執行搜尋")
    dialog._search_clients()
    assert dialog._pending_search is not None
    first = created[0]
    assert first.wait(2000)
    assert first.isFinished()
    assert dialog._search_workers

    dialog.reject()
    qtbot.wait(50)

    assert len(created) == 1
    assert dialog._pending_search is None
    assert not dialog._search_workers
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_dialog_can_be_deleted_while_delayed_worker_finishes_safely(
    qtbot, container, monkeypatch
) -> None:
    class DelayedWorker(annual_client_search.AnnualClientSearchWorker):
        def run(self) -> None:
            time.sleep(0.15)
            super().run()

    monkeypatch.setattr(
        annual_workspace_dialog, "AnnualClientSearchWorker", DelayedWorker
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    worker = next(iter(dialog._search_workers.values()))
    finished = QSignalSpy(worker.finished)
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(
        None, QEvent.Type.DeferredDelete
    )

    qtbot.waitUntil(lambda: finished.count() == 1, timeout=1000)


def test_cancel_tolerates_connection_closing_after_reference_was_read(
    qtbot, container, monkeypatch
) -> None:
    query_started = threading.Event()
    allow_query_finish = threading.Event()
    close_started = threading.Event()
    cancel_errors: list[BaseException] = []

    class Cursor:
        def fetchall(self):
            query_started.set()
            assert allow_query_finish.wait(1)
            return []

        def fetchone(self):
            return None

    class RacingConnection:
        row_factory = None
        in_transaction = False
        closed = False

        def execute(self, sql, _params=()):
            if sql == "BEGIN":
                self.in_transaction = True
            if sql.startswith("SELECT id, client_code"):
                return Cursor()
            return Cursor()

        def set_progress_handler(self, *_args):
            return None

        def rollback(self):
            self.in_transaction = False

        def close(self):
            self.closed = True
            close_started.set()

        def interrupt(self):
            assert close_started.wait(1)
            if self.closed:
                raise annual_client_search.sqlite3.ProgrammingError(
                    "Cannot operate on a closed database."
                )

    connection = RacingConnection()
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: connection,
    )
    worker = annual_client_search.AnnualClientSearchWorker(
        str(container.paths.db_path), "race", 1
    )
    worker.start()
    assert query_started.wait(1)

    def cancel_worker() -> None:
        try:
            worker.cancel()
        except BaseException as exc:  # pragma: no branch - asserted below
            cancel_errors.append(exc)

    cancel_thread = threading.Thread(target=cancel_worker)
    cancel_thread.start()
    allow_query_finish.set()
    cancel_thread.join(2)
    assert not cancel_thread.is_alive()
    qtbot.waitUntil(worker.isFinished, timeout=1000)
    assert cancel_errors == []


def test_shutdown_coordinator_cancels_all_before_one_aggregate_wait_deadline(
    qtbot,
) -> None:
    events: list[tuple[str, object]] = []
    cancelled: set[str] = set()

    class ObservedWorker(annual_client_search.AnnualClientSearchWorker):
        def __init__(self, name: str) -> None:
            super().__init__("unused.sqlite", "", 1)
            self.name = name

        def run(self) -> None:
            while not self.isInterruptionRequested():
                time.sleep(0.005)

        def cancel(self) -> None:
            cancelled.add(self.name)
            events.append(("cancel", self.name))
            super().cancel()

        def wait(self, timeout=...):
            events.append(("wait", frozenset(cancelled)))
            return super().wait(timeout)

    coordinator = annual_client_search.AnnualClientSearchCoordinator()
    workers = (ObservedWorker("A"), ObservedWorker("B"))
    for worker in workers:
        coordinator.register(worker)
        worker.start()

    assert coordinator.cancel_and_wait(1000) is True

    first_wait = next(index for index, event in enumerate(events) if event[0] == "wait")
    assert {event[1] for event in events[:first_wait]} == {"A", "B"}
    assert all(event[1] == frozenset({"A", "B"}) for event in events[first_wait:])
    qtbot.waitUntil(lambda: coordinator.active_count == 0, timeout=1000)


def test_application_uses_one_shared_annual_search_coordinator() -> None:
    first = annual_client_search.annual_client_search_coordinator()
    second = annual_client_search.annual_client_search_coordinator()

    assert first is second


def test_preselected_active_client_is_fetched_exactly_beyond_first_page(
    qtbot, container, monkeypatch
) -> None:
    clients = _insert_active_clients(container, 101)
    service_calls: list[int] = []
    monkeypatch.setattr(
        container.clients,
        "get_client",
        lambda client_id: service_calls.append(client_id),
    )
    dialog = AnnualWorkspaceDialog(
        container, preselected_client_id=clients[100].id, operation_year=2026
    )
    qtbot.addWidget(dialog)
    _wait_for_search(qtbot, dialog)

    assert service_calls == []
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
    _wait_for_search(qtbot, dialog)

    assert dialog.client_combo.findData(deleted.id) < 0
    assert dialog.client_combo.count() == 1
    assert dialog.feedback_label.text() == "找到 0 筆客戶。"


def test_initial_and_interactive_client_search_failures_are_visible_and_safe(
    qtbot, container, monkeypatch
) -> None:
    real_connect = annual_client_search.sqlite3.connect
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW INITIAL CLIENT SECRET")
        ),
    )
    dialog = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(dialog)
    _wait_for_search(qtbot, dialog)

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.client_combo.count() == 0
    assert dialog.feedback_label.text() == "載入客戶失敗，請稍後再試。"
    assert "SECRET" not in dialog.feedback_label.text()
    assert dialog.client_search_button.isEnabled()

    monkeypatch.setattr(annual_client_search.sqlite3, "connect", real_connect)
    second = AnnualWorkspaceDialog(container, operation_year=2026)
    qtbot.addWidget(second)
    _wait_for_search(qtbot, second)
    second.client_search_input.setText("測試不存在名稱")
    monkeypatch.setattr(
        annual_client_search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("RAW SEARCH CLIENT SECRET")
        ),
    )
    qtbot.mouseClick(second.client_search_button, Qt.MouseButton.LeftButton)
    _wait_for_search(qtbot, second)

    assert second.result() != QDialog.DialogCode.Accepted
    assert second.client_combo.count() == 0
    assert second.client_search_input.text() == "測試不存在名稱"
    assert second.feedback_label.text() == "載入客戶失敗，請稍後再試。"
    assert "SECRET" not in second.feedback_label.text()
    assert second.client_search_button.isEnabled()
