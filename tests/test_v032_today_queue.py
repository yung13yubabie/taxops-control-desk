"""Pure today's-queue projection; no Qt application or database required."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime

import pytest

from taxops.repositories.document_requests import DocumentRequestRow
from taxops.repositories.engagements import EngagementRow
from taxops.repositories.tasks import TaskRow
from taxops.services.document_requests import VALID_REQUEST_STATUSES
from taxops.services.tasks import VALID_TASK_STATUSES
from taxops.ui.today_queue import TodayQueueValidationError, build_today_queue


TODAY = date(2026, 10, 12)
TASK = TaskRow(
    id=1, engagement_id=None, client_id=None, parent_task_id=None,
    title="核對申報資料", assignee=None, due_date="2026-10-12",
    priority="normal", status="todo", next_step=None, notes=None,
    completed_at=None, created_at="", updated_at="",
)
REQUEST = DocumentRequestRow(
    id=1, engagement_id=10, request_name="十月補件", tax_type="vat",
    period_name="2026-10", status="requested", due_date="2026-10-12",
    requested_at=None, follow_up_count=0, notes=None, created_at="", updated_at="",
)
ENGAGEMENT = EngagementRow(
    id=10, client_id=20, engagement_name="申報", tax_type="vat",
    period_name="2026-10", status="in_progress", owner=None,
    due_date="2026-10-10", notes=None, created_at="", updated_at="",
)


def test_combines_overdue_and_today_with_stable_identity_and_date_order():
    tasks = [replace(TASK, id=8), replace(TASK, id=2, due_date="2026-10-10")]
    requests = [replace(REQUEST, id=8), replace(REQUEST, id=3, due_date="2026-10-11")]
    result = build_today_queue(tasks, requests, [ENGAGEMENT], TODAY)
    assert [item.key for item in result] == [
        ("task", 2), ("document_request", 3), ("document_request", 8), ("task", 8)
    ]
    assert result == build_today_queue(reversed(tasks), reversed(requests), [ENGAGEMENT], TODAY)
    assert result[2].request_id == 8 and result[2].task_id is None
    assert result[3].task_id == 8 and result[3].request_id is None
    assert result[2].title == "十月補件"
    assert result[2].source_label == "索件批次"
    assert result[2].status_label == "已發出索件"
    assert result[3].source_label == "待辦事項"
    assert result[3].status_label == "待處理"


@pytest.mark.parametrize("status", sorted(VALID_TASK_STATUSES))
def test_task_terminal_status_semantics(status):
    result = build_today_queue([replace(TASK, status=status)], [], [], TODAY)
    assert bool(result) == (status not in {"done", "cancelled"})


@pytest.mark.parametrize("status", sorted(VALID_REQUEST_STATUSES))
def test_only_accepted_request_is_finished(status):
    result = build_today_queue([], [replace(REQUEST, status=status)], [ENGAGEMENT], TODAY)
    assert bool(result) == (status != "accepted")


@pytest.mark.parametrize("due_date", [None, "", "  ", "2026-10-13"])
def test_missing_or_future_due_dates_do_not_borrow_engagement_deadline(due_date):
    task = replace(TASK, engagement_id=10, due_date=due_date)
    request = replace(REQUEST, due_date=due_date)
    assert build_today_queue([task], [request], [ENGAGEMENT], TODAY) == []


def test_deleted_records_are_excluded():
    assert build_today_queue(
        [replace(TASK, deleted_at="2026-10-11")],
        [replace(REQUEST, deleted_at="2026-10-11")], [], TODAY,
    ) == []


def test_context_comes_from_explicit_ids_without_inventing_links():
    tasks = [TASK, replace(TASK, id=2, client_id=30), replace(TASK, id=3, engagement_id=10)]
    items = {item.key: item for item in build_today_queue(tasks, [REQUEST], [ENGAGEMENT], TODAY)}
    unlinked = items[("task", 1)]
    assert unlinked.engagement_id is None and unlinked.client_id is None
    client_only = items[("task", 2)]
    assert client_only.engagement_id is None and client_only.client_id == 30
    linked = items[("task", 3)]
    assert linked.engagement_id == 10 and linked.client_id == 20
    assert linked.request_id is None
    request = items[("document_request", 1)]
    assert request.engagement_id == 10 and request.client_id == 20
    assert request.task_id is None


def test_child_task_keeps_its_own_context_and_deadline():
    child = replace(TASK, id=2, parent_task_id=1, due_date="2026-10-11")
    assert build_today_queue([child], [], [], TODAY)[0].client_id is None


@pytest.mark.parametrize("kind", ["task", "document_request"])
@pytest.mark.parametrize("value", ["2026-02-30", "invalid", "2026-1", 0])
def test_bad_due_dates_raise_typed_error_instead_of_empty_result(kind, value):
    tasks = [replace(TASK, due_date=value)] if kind == "task" else []
    requests = [replace(REQUEST, due_date=value)] if kind == "document_request" else []
    with pytest.raises(TodayQueueValidationError) as exc:
        build_today_queue(tasks, requests, [ENGAGEMENT], TODAY)
    assert (exc.value.code, exc.value.kind, exc.value.record_id) == ("invalid_due_date", kind, 1)


@pytest.mark.parametrize("today", [None, "", "2026-02-30", datetime(2026, 10, 12)])
def test_invalid_today_is_not_an_empty_queue(today):
    with pytest.raises(TodayQueueValidationError, match="invalid_today"):
        build_today_queue([], [], [], today)


@pytest.mark.parametrize("kind", ["task", "document_request", "engagement"])
def test_duplicate_ids_rejected_per_source(kind):
    tasks = [TASK, TASK] if kind == "task" else []
    requests = [REQUEST, REQUEST] if kind == "document_request" else []
    engagements = [ENGAGEMENT, ENGAGEMENT] if kind == "engagement" else [ENGAGEMENT]
    with pytest.raises(TodayQueueValidationError) as exc:
        build_today_queue(tasks, requests, engagements, TODAY)
    assert exc.value.code == "duplicate_id" and exc.value.kind == kind


@pytest.mark.parametrize("kind", ["task", "document_request"])
@pytest.mark.parametrize("engagements", [[], [replace(ENGAGEMENT, deleted_at="2026-10-11")]])
def test_dangling_reference_is_distinct_from_unlinked_task(kind, engagements):
    tasks = [replace(TASK, engagement_id=10)] if kind == "task" else []
    requests = [REQUEST] if kind == "document_request" else []
    with pytest.raises(TodayQueueValidationError, match="engagement_not_found"):
        build_today_queue(tasks, requests, engagements, TODAY)


def test_request_without_required_engagement_raises():
    with pytest.raises(TodayQueueValidationError, match="engagement_not_found"):
        build_today_queue([], [replace(REQUEST, engagement_id=None)], [], TODAY)


def test_conflicting_client_context_raises():
    with pytest.raises(TodayQueueValidationError, match="client_mismatch"):
        build_today_queue([replace(TASK, engagement_id=10, client_id=99)], [], [ENGAGEMENT], TODAY)


@pytest.mark.parametrize("kind", ["task", "document_request"])
def test_unknown_status_never_silently_disappears(kind):
    tasks = [replace(TASK, status="unknown")] if kind == "task" else []
    requests = [replace(REQUEST, status="cancelled")] if kind == "document_request" else []
    with pytest.raises(TodayQueueValidationError, match="invalid_status"):
        build_today_queue(tasks, requests, [ENGAGEMENT], TODAY)


@pytest.mark.parametrize("record_id", [0, -1, True, "1"])
def test_invalid_stable_ids_raise(record_id):
    with pytest.raises(TodayQueueValidationError, match="invalid_id"):
        build_today_queue([replace(TASK, id=record_id)], [], [], TODAY)


def test_input_failure_propagates_without_partial_success():
    def broken_tasks():
        yield TASK
        raise RuntimeError("snapshot unavailable")

    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        build_today_queue(broken_tasks(), [], [], TODAY)


def test_items_are_frozen_and_input_snapshots_unchanged():
    tasks, requests, engagements = [TASK], [REQUEST], [ENGAGEMENT]
    result = build_today_queue(tasks, requests, engagements, TODAY.isoformat())
    assert tasks == [TASK] and requests == [REQUEST] and engagements == [ENGAGEMENT]
    with pytest.raises(FrozenInstanceError):
        result[0].title = "改名"


def test_date_normalization_and_leap_day():
    result = build_today_queue([replace(TASK, due_date=" 2024-02-29 ")], [], [], TODAY)
    assert result[0].due_date == "2024-02-29"


def test_empty_success_is_distinct_from_errors():
    assert build_today_queue([], [], [], TODAY) == []


def test_due_summary_is_derived_from_full_sorted_result():
    from taxops.ui.today_queue import summarize_today_queue
    rows = build_today_queue(
        [TASK, replace(TASK, id=2, due_date="2026-10-10")], [REQUEST], [ENGAGEMENT], TODAY,
    )
    summary = summarize_today_queue(reversed(rows))
    assert summary.count == 3
    assert summary.earliest_due_date == "2026-10-10"
    assert summary.compact == "提醒 3 · 最早10/10"
    empty = summarize_today_queue([])
    assert empty.count == 0 and empty.earliest_due_date is None
    assert empty.compact == "提醒 0"


def test_only_due_context_is_required_and_no_annual_deadlines_are_inferred():
    from taxops.ui.today_queue import due_engagement_ids
    future = replace(REQUEST, id=2, engagement_id=200, due_date="2026-11-01")
    done = replace(REQUEST, id=3, engagement_id=300, status="accepted")
    tasks = [TASK, replace(TASK, id=2, engagement_id=10)]
    assert due_engagement_ids(tasks, [REQUEST, future, done], TODAY) == frozenset({10})
    rows = build_today_queue(tasks, [REQUEST, future, done], [ENGAGEMENT], TODAY)
    assert len(rows) == 3
    assert all(not hasattr(row, "attachment_id") for row in rows)
    # An annual-linked task still owns its own deadline. No annual service is read.
    annual_task = replace(TASK, annual_work_item_id=999, due_date=None)
    assert build_today_queue([annual_task], [], [], TODAY) == []


@pytest.mark.parametrize("title", [None, 42, "", "  "])
@pytest.mark.parametrize("kind", ["task", "document_request"])
def test_invalid_title_is_not_rendered_as_valid_work(title, kind):
    tasks = [replace(TASK, title=title)] if kind == "task" else []
    requests = [replace(REQUEST, request_name=title)] if kind == "document_request" else []
    with pytest.raises(TodayQueueValidationError, match="invalid_title"):
        build_today_queue(tasks, requests, [ENGAGEMENT], TODAY)
