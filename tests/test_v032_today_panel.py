"""Due reminders use complete, read-only real-service snapshots and honest states."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from taxops.services.clients import CreateClientInput
from taxops.services.document_requests import CreateDocumentRequestInput
from taxops.services.engagements import CreateEngagementInput
from taxops.services.tasks import CreateTaskInput
from taxops.ui import tokens
from taxops.ui.action_registry import PAGE_ENGAGEMENTS, PAGE_TASKS
from taxops.ui.today_queue import TodayQueueValidationError
from taxops.ui.widgets.today_work_panel import (
    TodayWorkPanel, all_document_requests, all_engagements,
)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(container, app, monkeypatch):
    monkeypatch.setattr("taxops.ui.widgets.today_work_panel.today_iso", lambda: "2026-10-12")
    widget = TodayWorkPanel(container)
    widget.resize(420, 560)
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
    app.processEvents()


def client(container, code="A001", name="甲公司"):
    return container.clients.create_client(CreateClientInput(client_code=code, client_name=name))


def case(container, owner=None):
    owner = owner or client(container)
    return container.engagements.create_engagement(CreateEngagementInput(
        client_id=owner.id, engagement_name="十月申報案件", tax_type="vat", period_name="2026-10",
    ))


def task(container, *, title="核對申報", client_id=None, engagement_id=None, due_date="2026-10-12"):
    return container.tasks.create_task(CreateTaskInput(
        title=title, client_id=client_id, engagement_id=engagement_id, due_date=due_date,
    ))


def request(container, engagement_id, *, title="十月補件", due_date="2026-10-10"):
    return container.doc_requests.create_request(CreateDocumentRequestInput(
        engagement_id=engagement_id, tax_type="vat", period_name="2026-10",
        request_name=title, due_date=due_date,
    ))[0]


def fail(*_args, **_kwargs):
    raise RuntimeError("private diagnostic: database unavailable")


def test_empty_is_distinct_from_first_failure_and_retry_recovers(panel, container, monkeypatch):
    seen = []
    panel.summary_changed.connect(seen.append)
    assert panel.compact_summary == "提醒未載入"
    assert panel.due_count is None
    original = container.doc_requests.count_all
    monkeypatch.setattr(container.doc_requests, "count_all", fail)
    panel.refresh()
    assert panel.state_kind == "error"
    assert panel.compact_summary == "提醒載入失敗"
    assert panel.due_count is None
    assert panel._list.count() == 0 and panel._list.isHidden()
    assert not panel._retry_btn.isHidden()
    assert "沒有" not in panel._message.text()
    assert "private diagnostic" not in panel._message.text()
    monkeypatch.setattr(container.doc_requests, "count_all", original)
    panel._retry_btn.click()
    assert panel.state_kind == "empty"
    assert panel.compact_summary == "提醒 0"
    assert panel.due_count == 0
    assert "目前沒有" in panel._message.text()
    assert panel._retry_btn.isHidden()
    assert seen == ["提醒載入失敗", "提醒 0"]


def test_real_rows_have_sources_identity_dates_and_no_business_writes(panel, container):
    owner = client(container)
    engagement = case(container, owner)
    task_row = task(container, client_id=owner.id, engagement_id=engagement.id)
    request_row = request(container, engagement.id)
    before = container.conn.total_changes
    panel.refresh()
    assert container.conn.total_changes == before
    assert panel.state_kind == "success"
    assert panel.due_count == 2 and panel.earliest_due_date == "2026-10-10"
    assert panel.compact_summary == "提醒 2 · 最早10/10"
    rows = [panel._list.item(i) for i in range(panel._list.count())]
    assert rows[0].data(Qt.ItemDataRole.UserRole).request_id == request_row.id
    assert rows[1].data(Qt.ItemDataRole.UserRole).task_id == task_row.id
    assert "逾期 2 天" in rows[0].text() and "今天到期" in rows[1].text()
    assert "索件" in rows[0].text() and "待辦" in rows[1].text()
    assert "索件批次" in rows[0].toolTip()
    assert all("A001" in row.text() and "甲公司" in row.text() for row in rows)
    assert all("十月申報案件" in row.toolTip() for row in rows)
    assert all(row.data(Qt.ItemDataRole.AccessibleTextRole) for row in rows)
    assert panel._title.text() == "待辦與索件提醒"
    assert panel._message.isHidden()


def test_client_only_same_title_tasks_are_distinguishable(panel, container):
    first = client(container, "A001", "甲公司")
    second = client(container, "B002", "乙公司")
    a = task(container, client_id=first.id)
    b = task(container, client_id=second.id)
    panel.refresh()
    texts = {panel._list.item(i).data(Qt.ItemDataRole.UserRole).task_id: panel._list.item(i).text()
             for i in range(panel._list.count())}
    assert "A001 · 甲公司" in texts[a.id]
    assert "B002 · 乙公司" in texts[b.id]
    assert all("未關聯案件" in text for text in texts.values())


def test_selection_survives_reordering_and_repeated_refresh_without_duplicate_signals(panel, container):
    chosen = task(container)
    panel.refresh()
    panel._list.setCurrentRow(0)
    task(container, title="較早的期限", due_date="2026-10-09")
    navigations = []
    panel.navigate_requested.connect(navigations.append)
    before = container.conn.total_changes
    for _ in range(3):
        panel.refresh()
        assert panel._list.currentItem().data(Qt.ItemDataRole.UserRole).task_id == chosen.id
        assert panel._list.count() == 2
    panel._open_btn.click()
    assert container.conn.total_changes == before
    assert len(navigations) == 1 and navigations[0].task_id == chosen.id
    assert navigations[0].page_id == PAGE_TASKS
    assert navigations[0].attachment_id is None and navigations[0].request_id is None


def test_enter_activates_exact_request_navigation(panel, container, app):
    engagement = case(container)
    row = request(container, engagement.id)
    panel.refresh()
    panel._list.setCurrentRow(0)
    panel._list.setFocus()
    app.processEvents()
    targets = []
    panel.navigate_requested.connect(targets.append)
    QTest.keyClick(panel._list, Qt.Key.Key_Return)
    assert len(targets) == 1
    assert targets[0].page_id == PAGE_ENGAGEMENTS
    assert targets[0].engagement_id == engagement.id and targets[0].request_id == row.id
    assert targets[0].task_id is None and targets[0].attachment_id is None


def test_refresh_failure_retains_selected_stale_snapshot(panel, container, monkeypatch):
    chosen = task(container, due_date="2026-10-10")
    panel.refresh()
    panel._list.setCurrentRow(0)
    row_text = panel._list.item(0).text()
    monkeypatch.setattr(container.tasks, "list_overdue", fail)
    before = container.conn.total_changes
    panel.refresh()
    panel.refresh()
    assert container.conn.total_changes == before
    assert panel.state_kind == "stale"
    assert panel.compact_summary == "提醒 1 · 最早10/10 · 未更新"
    assert panel.due_count == 1 and panel.earliest_due_date == "2026-10-10"
    assert panel._list.currentItem().data(Qt.ItemDataRole.UserRole).task_id == chosen.id
    assert panel._list.item(0).text() == row_text
    assert "更新失敗" in panel._message.text() and "的資料" in panel._message.text()
    assert not panel._retry_btn.isHidden()


def test_last_successful_zero_is_marked_stale_on_failure(panel, container, monkeypatch):
    panel.refresh()
    monkeypatch.setattr(container.doc_requests, "count_all", fail)
    panel.refresh()
    assert panel.state_kind == "stale"
    assert panel.compact_summary == "提醒 0 · 未更新"
    assert "目前沒有" not in panel._message.text()


def test_complete_real_request_pagination_includes_record_201(panel, container, monkeypatch):
    engagement = case(container)
    for index in range(201):
        request(container, engagement.id, title=f"索件{index + 1}", due_date="2026-10-10" if index == 200 else "2026-11-01")
    calls = []
    original = container.doc_requests.list_all
    def tracked(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(container.doc_requests, "list_all", tracked)
    panel.refresh()
    assert calls == [{"limit": 200, "offset": 0}, {"limit": 200, "offset": 200}]
    assert panel.due_count == 1
    assert "索件201" in panel._list.item(0).text()


def test_case_501_not_lost_and_only_due_reference_loaded(panel, container, monkeypatch):
    owner = client(container)
    container.conn.executemany(
        "INSERT INTO engagements(client_id,engagement_name,tax_type,period_name,status,created_at,updated_at) "
        "VALUES (?,?,'vat','2026-10','todo','2026-10-12','2026-10-12')",
        [(owner.id, f"案件{i}") for i in range(1, 502)],
    )
    container.conn.commit()
    cases = all_engagements(container)
    assert len(cases) == 501 and cases[-1].engagement_name == "案件501"
    request(container, cases[-1].id)
    calls = []
    original = container.engagements.get_engagement
    def tracked(record_id):
        calls.append(record_id)
        return original(record_id)
    monkeypatch.setattr(container.engagements, "get_engagement", tracked)
    monkeypatch.setattr(container.engagements, "list_all", fail)
    panel.refresh()
    assert panel.state_kind == "success" and panel.due_count == 1
    assert calls == [cases[-1].id]
    assert "案件501" in panel._list.item(0).text()


@pytest.mark.parametrize("kind", ["incomplete", "duplicate", "none", "changed"])
def test_request_snapshot_failure_is_visible_not_partial(panel, container, monkeypatch, kind):
    engagement = case(container)
    row = request(container, engagement.id)
    monkeypatch.setattr(container.doc_requests, "count_all", lambda: 2)
    if kind == "incomplete":
        monkeypatch.setattr(container.doc_requests, "list_all", lambda **_: [row])
    elif kind == "duplicate":
        monkeypatch.setattr(container.doc_requests, "list_all", lambda **_: [row, row])
    elif kind == "none":
        monkeypatch.setattr(container.doc_requests, "list_all", lambda **_: None)
    else:
        counts = iter([1, 2])
        monkeypatch.setattr(container.doc_requests, "count_all", lambda: next(counts))
    panel.refresh()
    assert panel.state_kind == "error" and panel.due_count is None
    assert panel._list.count() == 0 and not panel._retry_btn.isHidden()


def test_invalid_or_missing_client_is_failure_not_ambiguous_identity(panel, container, monkeypatch):
    owner = client(container)
    task(container, client_id=owner.id)
    monkeypatch.setattr(container.clients, "get_client", lambda _id: None)
    panel.refresh()
    assert panel.state_kind == "error" and panel.due_count is None
    assert "載入" in panel._message.text()


def test_actions_are_contextual_and_all_use_nonprimary_roles(panel, container):
    assert panel._open_btn.isHidden()
    assert panel.font().pixelSize() >= 14
    assert panel._list.accessibleName() and panel._retry_btn.accessibleName()
    for button in panel.findChildren(QPushButton):
        assert button.property("role") in tokens.BUTTON_ROLES
        assert button.property("role") != tokens.ROLE_PRIMARY
    task(container)
    panel.refresh()
    assert panel._open_btn.isHidden()
    panel._list.setCurrentRow(0)
    assert not panel._open_btn.isHidden()
    panel._list.setCurrentRow(-1)
    assert panel._open_btn.isHidden()


def test_case_pagination_repeated_page_raises_instead_of_looping(container, monkeypatch):
    engagement = case(container)
    duplicate_page = [replace(engagement, id=index + 1) for index in range(500)]
    monkeypatch.setattr(container.engagements, "list_all", lambda **_: duplicate_page)
    with pytest.raises(TodayQueueValidationError, match="duplicate_id"):
        all_engagements(container)


@pytest.mark.parametrize("count", [None, -1, True, "0"])
def test_invalid_request_count_is_not_zero(count):
    fake = SimpleNamespace(doc_requests=SimpleNamespace(count_all=lambda: count))
    with pytest.raises(TodayQueueValidationError, match="invalid_count"):
        all_document_requests(fake)


def test_real_soft_deleted_owners_and_tasks_are_absent(panel, container):
    owner = client(container)
    engagement = case(container, owner)
    row = task(container, client_id=owner.id, engagement_id=engagement.id)
    request(container, engagement.id)
    container.tasks.delete_task(row.id)
    container.conn.execute("UPDATE clients SET deleted_at = '2026-10-12' WHERE id = ?", (owner.id,))
    container.conn.commit()
    panel.refresh()
    assert panel.state_kind == "empty" and panel.due_count == 0


def test_multiline_task_title_stays_concise_but_full_details_accessible(panel, container):
    row = task(container, title="核對申報\n備註全文\n再核對")
    panel.refresh()
    item = panel._list.item(0)
    assert item.text().count("\n") == 2
    assert row.title in item.toolTip()
    assert row.title in item.data(Qt.ItemDataRole.AccessibleTextRole)


def test_state_seam_never_allows_error_rows_or_unlabeled_stale():
    from taxops.ui.widgets.today_work_panel import _QueueState
    with pytest.raises(ValueError, match="non-data"):
        _QueueState("error", rows=(object(),), error="讀取失敗")
    with pytest.raises(ValueError, match="snapshot"):
        _QueueState("stale", error="讀取失敗")


def test_invalid_final_count_cannot_verify_empty_snapshot():
    counts = iter([0, False])
    fake = SimpleNamespace(doc_requests=SimpleNamespace(count_all=lambda: next(counts)))
    with pytest.raises(TodayQueueValidationError, match="changed_snapshot"):
        all_document_requests(fake)


def test_empty_state_has_live_navigation_and_cleared_selection_has_no_action(panel, container):
    panel.refresh()
    assert not panel._browse_btn.isHidden()
    targets = []
    panel.navigate_requested.connect(targets.append)
    panel._browse_btn.click()
    assert targets[0].page_id == PAGE_TASKS and targets[0].task_id is None
    task(container)
    panel.refresh()
    assert panel._browse_btn.isHidden()
    panel._list.setCurrentRow(0)
    panel._list.clearSelection()
    assert panel._open_btn.isHidden()
    panel.open_current()
    assert len(targets) == 1


def test_schema_invalid_title_is_first_error_not_fabricated_stale(panel, container, monkeypatch):
    row = task(container)
    monkeypatch.setattr(container.tasks, "list_due_today", lambda _: [replace(row, title=None)])
    panel.refresh()
    assert panel.state_kind == "error" and panel.due_count is None
    assert panel._list.count() == 0
