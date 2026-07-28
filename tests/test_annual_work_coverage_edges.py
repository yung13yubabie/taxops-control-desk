from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from taxops.repositories.annual_work import AnnualWorkItemVersionConflict
from taxops.services.annual_work import (
    AnnualWorkError,
    AnnualWorkService,
    AnnualWorkValidationError,
    UpdateAnnualWorkItemInput,
    _next_item_updated_at,
    _prepare_drafts,
    _valid_optional_date,
)
from taxops.services.compliance_rules import WorkDraft


class _Connection:
    """Minimal transaction double that makes rollback behavior observable."""

    def __init__(self) -> None:
        self.in_transaction = False
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def execute(self, _sql: str) -> None:
        self.in_transaction = True

    def commit(self) -> None:
        self.commit_count += 1
        self.in_transaction = False

    def rollback(self) -> None:
        self.rollback_count += 1
        self.in_transaction = False

    def close(self) -> None:
        self.closed = True
        self.in_transaction = False


def _raise(exc: Exception) -> Callable[..., Any]:
    def raising(*_args: object, **_kwargs: object) -> Any:
        raise exc

    return raising


def _service(
    *,
    conn: _Connection | None = None,
    repo: object | None = None,
    profiles: object | None = None,
    audit: object | None = None,
    engagements: object | None = None,
    documents: object | None = None,
    tasks: object | None = None,
) -> AnnualWorkService:
    connection = conn or _Connection()
    repository = repo or SimpleNamespace(connection=connection)
    profile_repo = profiles or SimpleNamespace(connection=connection)
    audit_service = audit or SimpleNamespace(
        connection=connection,
        record=lambda **_kwargs: None,
    )
    return AnnualWorkService(
        connection,  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        profile_repo,  # type: ignore[arg-type]
        audit_service,  # type: ignore[arg-type]
        engagements=engagements,  # type: ignore[arg-type]
        document_requests=documents,  # type: ignore[arg-type]
        tasks=tasks,  # type: ignore[arg-type]
    )


def _draft() -> WorkDraft:
    return WorkDraft(
        item_key="vat:2026:01-02",
        operation_year=2026,
        work_type="vat",
        title="01-02 月營業稅",
        tax_year=2026,
        period_code="01-02",
        suggested_due_date="2026-03-15",
    )


def _update_payload() -> UpdateAnnualWorkItemInput:
    return UpdateAnnualWorkItemInput(
        title="年度工作",
        tax_year=2026,
        period_code="年度",
        due_date="2027-05-31",
        notes="保留換行\n與完整說明",
        work_status="not_started",
        filing_status="not_filed",
        document_status="not_requested",
        tax_status="unconfirmed",
        fee_status="not_billed",
        expected_updated_at="2026-07-28T00:00:00.000000+00:00",
    )


def _invoke_failure_path(service: AnnualWorkService, operation: str) -> object:
    if operation == "request":
        return service.create_linked_request(
            1, request_name="應備文件", item_names=("發票",)
        )
    if operation == "link":
        return service.link_existing_engagement(1, 2)
    if operation == "unlink":
        return service.unlink_engagement(1)
    if operation == "task":
        return service.create_linked_task(1, title="追蹤缺件")
    if operation == "update":
        return service.update_item_details(1, _update_payload())
    if operation == "status":
        return service.set_filing_status(1, "filed")
    if operation == "complete":
        return service.complete_item(1)
    if operation == "cancel":
        return service.cancel_item(1, "客戶停業")
    if operation == "restore":
        return service.restore_item(1)
    if operation == "delete":
        return service.delete_item(1)
    if operation == "confirm":
        draft = _draft()
        return service.confirm_preview(1, 2026, (draft,))
    raise AssertionError(f"unknown operation: {operation}")


_FAILURE_CODES = {
    "request": "annual_work.request.create_failed",
    "link": "annual_work.engagement.link_failed",
    "unlink": "annual_work.engagement.unlink_failed",
    "task": "annual_work.task.create_failed",
    "update": "annual_work.item_details.update_failed",
    "status": "annual_work.status.update_failed",
    "complete": "annual_work.complete.failed",
    "cancel": "annual_work.cancel.failed",
    "restore": "annual_work.restore.failed",
    "delete": "annual_work.delete.failed",
    "confirm": "annual_work.confirm.failed",
}


def _failing_service(operation: str, exc: Exception) -> tuple[AnnualWorkService, _Connection]:
    conn = _Connection()
    failure = _raise(exc)
    repo = SimpleNamespace(
        connection=conn,
        get_item_context=failure,
        get_item=failure,
    )
    profiles = SimpleNamespace(connection=conn)
    engagements = SimpleNamespace(connection=conn)
    documents = SimpleNamespace(connection=conn)
    tasks = SimpleNamespace(connection=conn)
    service = _service(
        conn=conn,
        repo=repo,
        profiles=profiles,
        engagements=engagements,
        documents=documents,
        tasks=tasks,
    )
    if operation == "confirm":
        service.preview = failure  # type: ignore[method-assign]
    return service, conn


@pytest.mark.parametrize("operation", tuple(_FAILURE_CODES))
def test_mutation_unexpected_failure_rolls_back_and_returns_stable_error(
    operation: str,
) -> None:
    service, conn = _failing_service(
        operation, RuntimeError("private database implementation detail")
    )

    with pytest.raises(AnnualWorkError) as caught:
        _invoke_failure_path(service, operation)

    assert caught.value.code == _FAILURE_CODES[operation]
    assert "private database implementation detail" not in str(caught.value)
    assert conn.rollback_count == 1
    assert conn.in_transaction is False


@pytest.mark.parametrize("operation", tuple(_FAILURE_CODES))
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("database table is locked", "annual_work.transaction.busy"),
        ("disk I/O error", None),
    ],
)
def test_mutation_sqlite_failures_roll_back_and_distinguish_contention(
    operation: str,
    message: str,
    expected: str | None,
) -> None:
    service, conn = _failing_service(operation, sqlite3.OperationalError(message))

    with pytest.raises(AnnualWorkError) as caught:
        _invoke_failure_path(service, operation)

    assert caught.value.code == (expected or _FAILURE_CODES[operation])
    assert conn.rollback_count == 1
    assert conn.in_transaction is False


@pytest.mark.parametrize(
    "operation",
    [
        "request",
        "link",
        "unlink",
        "task",
        "update",
        "status",
        "complete",
        "cancel",
        "restore",
        "delete",
        "confirm",
    ],
)
def test_mutations_reject_caller_owned_transaction_before_any_write(
    operation: str,
) -> None:
    conn = _Connection()
    conn.in_transaction = True
    collaborator = SimpleNamespace(connection=conn)
    service = _service(
        conn=conn,
        repo=collaborator,
        profiles=collaborator,
        engagements=collaborator,
        documents=collaborator,
        tasks=collaborator,
    )

    with pytest.raises(
        AnnualWorkValidationError,
        match="^annual_work.transaction.already_active$",
    ):
        _invoke_failure_path(service, operation)

    assert conn.in_transaction is True
    assert conn.commit_count == 0
    assert conn.rollback_count == 0


class _BrokenLength(Sequence[WorkDraft]):
    def __getitem__(self, _index: int) -> WorkDraft:
        return _draft()

    def __len__(self) -> int:
        raise RuntimeError("hostile length")


class _BrokenIterator(Sequence[WorkDraft]):
    def __getitem__(self, _index: int) -> WorkDraft:
        raise IndexError

    def __len__(self) -> int:
        return 1

    def __iter__(self) -> Iterator[WorkDraft]:
        raise RuntimeError("hostile iterator")


class _FailsDuringIteration(Sequence[WorkDraft]):
    def __getitem__(self, _index: int) -> WorkDraft:
        raise IndexError

    def __len__(self) -> int:
        return 2

    def __iter__(self) -> Iterator[WorkDraft]:
        yield _draft()
        raise RuntimeError("hostile next")


class _LengthMismatch(Sequence[WorkDraft]):
    def __init__(self, *, reported: int, values: tuple[WorkDraft, ...]) -> None:
        self._reported = reported
        self._values = values

    def __getitem__(self, index: int) -> WorkDraft:
        return self._values[index]

    def __len__(self) -> int:
        return self._reported

    def __iter__(self) -> Iterator[WorkDraft]:
        return iter(self._values)


@pytest.mark.parametrize(
    "drafts",
    [
        _BrokenLength(),
        _BrokenIterator(),
        _FailsDuringIteration(),
        _LengthMismatch(reported=1, values=(_draft(), _draft())),
        _LengthMismatch(reported=2, values=(_draft(),)),
    ],
)
def test_draft_validation_rejects_hostile_or_inconsistent_sequences(
    drafts: Sequence[WorkDraft],
) -> None:
    with pytest.raises(
        AnnualWorkValidationError, match="^annual_work.drafts.invalid$"
    ):
        _prepare_drafts(drafts, 2026)


@pytest.mark.parametrize(
    "draft",
    [
        WorkDraft("", 2026, "vat", "營業稅", 2026, "01-02", "2026-03-15"),
        WorkDraft("key", 2026, "unknown", "營業稅", 2026, "01-02", "2026-03-15"),
        WorkDraft("key", 2026, "vat", "營業\u200b稅", 2026, "01-02", "2026-03-15"),
        WorkDraft("key", 2026, "vat", "營業稅", True, "01-02", "2026-03-15"),
        WorkDraft("key", 2026, "vat", "營業稅", 1911, "01-02", "2026-03-15"),
        WorkDraft("key", 2026, "vat", "營業稅", 2026, " ", "2026-03-15"),
        WorkDraft("key", 2026, "vat", "營業稅", 2026, "01-02", 123),  # type: ignore[arg-type]
    ],
)
def test_draft_validation_rejects_ambiguous_or_cross_type_fields(
    draft: WorkDraft,
) -> None:
    with pytest.raises(
        AnnualWorkValidationError, match="^annual_work.draft.invalid$"
    ):
        _prepare_drafts((draft,), 2026)


def test_date_and_version_helpers_reject_noncanonical_persistence_values() -> None:
    assert _valid_optional_date(None) is True
    assert _valid_optional_date(20260728) is False
    assert _valid_optional_date("2026-7-28") is False

    with pytest.raises(
        AnnualWorkError, match="^annual_work.item.updated_at.invalid$"
    ):
        _next_item_updated_at("not-an-iso-version")


def test_connection_identity_guard_names_every_mismatched_collaborator() -> None:
    expected = _Connection()
    wrong = _Connection()
    correct = SimpleNamespace(connection=expected)
    mismatched = SimpleNamespace(connection=wrong)

    with pytest.raises(ValueError) as caught:
        AnnualWorkService(
            expected,  # type: ignore[arg-type]
            mismatched,  # type: ignore[arg-type]
            correct,  # type: ignore[arg-type]
            mismatched,  # type: ignore[arg-type]
            engagements=mismatched,  # type: ignore[arg-type]
            document_requests=correct,  # type: ignore[arg-type]
            tasks=mismatched,  # type: ignore[arg-type]
        )

    assert str(caught.value) == (
        "annual_work.connection.mismatch: repository, audit, engagements, tasks"
    )


def test_linked_overview_degrades_to_item_only_when_optional_services_absent() -> None:
    conn = _Connection()
    item = SimpleNamespace(id=7, engagement_id=99)
    repo = SimpleNamespace(
        connection=conn,
        get_item_context=lambda _item_id: SimpleNamespace(
            item=item, client_id=3, operation_year=2026
        ),
    )
    service = _service(conn=conn, repo=repo)

    overview = service.linked_overview(7)

    assert overview.item is item
    assert overview.engagement is None
    assert overview.requests == ()
    assert overview.tasks == ()


def test_linked_overview_does_not_query_requests_for_deleted_engagement() -> None:
    conn = _Connection()
    item = SimpleNamespace(id=7, engagement_id=99)
    repo = SimpleNamespace(
        connection=conn,
        get_item_context=lambda _item_id: SimpleNamespace(
            item=item, client_id=3, operation_year=2026
        ),
    )
    engagements = SimpleNamespace(
        connection=conn,
        get_engagement=lambda _engagement_id: None,
    )
    documents = SimpleNamespace(
        connection=conn,
        list_by_engagement=_raise(AssertionError("must not query orphan request")),
    )
    service = _service(
        conn=conn,
        repo=repo,
        engagements=engagements,
        documents=documents,
    )

    overview = service.linked_overview(7)

    assert overview.engagement is None
    assert overview.requests == ()


@pytest.mark.parametrize(
    ("method_name", "exception", "expected"),
    [
        (
            "search_overview",
            ValueError("annual_work.filters.risk.invalid"),
            "annual_work.filters.risk.invalid",
        ),
        (
            "search_overview",
            sqlite3.DatabaseError("corrupt"),
            "annual_work.overview.failed",
        ),
        (
            "overview_metrics",
            ValueError("annual_work.filters.year.invalid"),
            "annual_work.filters.year.invalid",
        ),
        (
            "overview_metrics",
            sqlite3.DatabaseError("corrupt"),
            "annual_work.overview.failed",
        ),
    ],
)
def test_overview_repository_errors_are_translated_without_raw_sqlite_detail(
    method_name: str,
    exception: Exception,
    expected: str,
) -> None:
    conn = _Connection()
    repo = SimpleNamespace(
        connection=conn,
        search_overview=_raise(exception),
        overview_metrics=_raise(exception),
    )
    service = _service(conn=conn, repo=repo)

    with pytest.raises(AnnualWorkError) as caught:
        getattr(service, method_name)()

    assert caught.value.code == expected
    assert "corrupt" not in str(caught.value)


@pytest.mark.parametrize(
    ("method_name", "expected"),
    [
        ("create_linked_request", "annual_work.workflow.unavailable"),
        ("link_existing_engagement", "annual_work.workflow.unavailable"),
    ],
)
def test_request_and_engagement_actions_fail_closed_without_workflow_services(
    method_name: str,
    expected: str,
) -> None:
    service = _service()

    with pytest.raises(AnnualWorkError, match=f"^{expected}$"):
        if method_name == "create_linked_request":
            service.create_linked_request(
                1, request_name="缺件通知", item_names=("發票",)
            )
        else:
            service.link_existing_engagement(1, 2)


def test_task_action_fails_closed_without_both_required_services() -> None:
    conn = _Connection()
    engagements = SimpleNamespace(connection=conn)
    service = _service(conn=conn, engagements=engagements)

    with pytest.raises(
        AnnualWorkError, match="^annual_work.workflow.unavailable$"
    ):
        service.create_linked_task(1, title="提醒客戶補件")


@pytest.mark.parametrize(
    "method_name",
    [
        "create_linked_request",
        "link_existing_engagement",
        "unlink_engagement",
        "create_linked_task",
        "document_summary",
        "linked_overview",
        "get_status_presentation",
    ],
)
def test_read_and_link_entry_points_strictly_reject_boolean_item_ids(
    method_name: str,
) -> None:
    service = _service()

    with pytest.raises(
        AnnualWorkValidationError, match="^annual_work.item_id.invalid$"
    ):
        if method_name == "create_linked_request":
            service.create_linked_request(
                True, request_name="缺件", item_names=("發票",)
            )
        elif method_name == "link_existing_engagement":
            service.link_existing_engagement(True, 1)
        elif method_name == "create_linked_task":
            service.create_linked_task(True, title="缺件")
        else:
            getattr(service, method_name)(True)


def test_version_conflict_during_new_request_rolls_back_created_rows() -> None:
    conn = _Connection()
    item = SimpleNamespace(
        id=1,
        engagement_id=None,
        title="營業稅",
        period_code="01-02",
        tax_year=2026,
        due_date="2026-03-15",
        notes=None,
        work_type="vat",
        updated_at="2026-07-28T00:00:00.000000+00:00",
    )
    repo = SimpleNamespace(
        connection=conn,
        get_item_context=lambda _item_id: SimpleNamespace(
            item=item, client_id=3, operation_year=2026
        ),
        set_engagement_link=_raise(AnnualWorkItemVersionConflict()),
    )
    engagement = SimpleNamespace(id=8, tax_type="vat", period_name="01-02")
    engagements = SimpleNamespace(
        connection=conn,
        _create_engagement_uncommitted=lambda _payload: engagement,
    )
    documents = SimpleNamespace(connection=conn)
    service = _service(
        conn=conn,
        repo=repo,
        engagements=engagements,
        documents=documents,
    )

    with pytest.raises(
        AnnualWorkValidationError, match="^annual_work.item_details.stale$"
    ):
        service.create_linked_request(
            1, request_name="缺件清單", item_names=("發票",)
        )

    assert conn.rollback_count == 1
    assert conn.in_transaction is False
