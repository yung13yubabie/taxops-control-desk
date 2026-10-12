"""Pure projection of due workflow tasks and document-request batches.

Callers load complete service snapshots and handle load/validation failures.
This module does not read persistence, infer document/attachment links, or
manufacture deadlines for request items (which have no due-date field).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ..core.dates import parse_optional_iso_date
from ..i18n.status_labels import status_to_label
from ..repositories.document_requests import DocumentRequestRow
from ..repositories.engagements import EngagementRow
from ..repositories.tasks import TaskRow
from ..services.document_requests import VALID_REQUEST_STATUSES
from ..services.tasks import VALID_TASK_STATUSES

WorkKind = Literal["task", "document_request"]


@dataclass(frozen=True)
class TodayWorkItem:
    kind: WorkKind
    record_id: int
    title: str
    due_date: str
    engagement_id: int | None
    client_id: int | None
    request_id: int | None
    task_id: int | None
    source_label: str
    status_label: str

    @property
    def key(self) -> tuple[WorkKind, int]:
        """Stable selection identity, independent of row position or title."""
        return self.kind, self.record_id


@dataclass(frozen=True)
class TodayQueueSummary:
    """Derived reminder totals, never annual-work compliance metrics."""

    count: int
    earliest_due_date: str | None

    @property
    def compact(self) -> str:
        if self.earliest_due_date is None:
            return "提醒 0"
        return f"提醒 {self.count} · 最早{self.earliest_due_date[5:].replace('-', '/')}"


def summarize_today_queue(items: Iterable[TodayWorkItem]) -> TodayQueueSummary:
    rows = tuple(items)
    return TodayQueueSummary(
        count=len(rows), earliest_due_date=min((row.due_date for row in rows), default=None)
    )


class TodayQueueValidationError(ValueError):
    """Invalid snapshot; callers must not show this as an empty queue.

    ``code``, ``kind`` and ``record_id`` are diagnostic context, not UI copy.
    A genuinely unlinked task is valid and retains its optional context IDs;
    a non-null reference missing from the engagement snapshot is an error.
    """

    def __init__(
        self, code: str, *, kind: str, record_id: int | None = None
    ) -> None:
        self.code = code
        self.kind = kind
        self.record_id = record_id
        super().__init__(f"today_queue.{code}: {kind} {record_id}")


def _require_id(value: int, *, kind: str, record_id: int | None = None) -> None:
    if type(value) is not int or value <= 0:
        raise TodayQueueValidationError("invalid_id", kind=kind, record_id=record_id)


def _due_date(value: str | None, *, kind: str, record_id: int) -> date | None:
    if value is not None and not isinstance(value, str):
        raise TodayQueueValidationError(
            "invalid_due_date", kind=kind, record_id=record_id
        )
    try:
        return parse_optional_iso_date(value)
    except ValueError as exc:
        raise TodayQueueValidationError(
            "invalid_due_date", kind=kind, record_id=record_id
        ) from exc


def _today_date(today: date | str) -> date:
    # datetime is deliberately not accepted: the caller supplies its local day.
    if type(today) is date:
        return today
    if isinstance(today, str):
        try:
            parsed = parse_optional_iso_date(today)
        except ValueError as exc:
            raise TodayQueueValidationError("invalid_today", kind="today") from exc
        if parsed is not None:
            return parsed
    raise TodayQueueValidationError("invalid_today", kind="today")


def _due_rows(
    tasks: Iterable[TaskRow],
    requests: Iterable[DocumentRequestRow],
    today: date | str,
) -> Iterator[tuple[WorkKind, TaskRow | DocumentRequestRow, date]]:
    """Validate source rows once per projection, before selecting due records."""
    cutoff = _today_date(today)
    sources = (
        ("task", tasks, VALID_TASK_STATUSES),
        ("document_request", requests, VALID_REQUEST_STATUSES),
    )
    for kind, rows, valid_statuses in sources:
        seen: set[int] = set()
        for row in rows:
            _require_id(row.id, kind=kind)
            if row.id in seen:
                raise TodayQueueValidationError("duplicate_id", kind=kind, record_id=row.id)
            seen.add(row.id)
            if row.deleted_at is not None:
                continue
            if row.status not in valid_statuses:
                raise TodayQueueValidationError("invalid_status", kind=kind, record_id=row.id)
            due = _due_date(row.due_date, kind=kind, record_id=row.id)
            terminal = row.status in ({"done", "cancelled"} if kind == "task" else {"accepted"})
            if not terminal and due is not None and due <= cutoff:
                yield kind, row, due


def due_engagement_ids(
    tasks: Iterable[TaskRow], requests: Iterable[DocumentRequestRow], today: date | str
) -> frozenset[int]:
    """Case IDs needed for this reminder snapshot, not every case in the office."""
    result: set[int] = set()
    for kind, row, _due in _due_rows(tasks, requests, today):
        if row.engagement_id is not None:
            _require_id(row.engagement_id, kind=kind, record_id=row.id)
            result.add(row.engagement_id)
    return frozenset(result)


def build_today_queue(
    tasks: Iterable[TaskRow],
    requests: Iterable[DocumentRequestRow],
    engagements: Iterable[EngagementRow],
    today: date | str,
) -> list[TodayWorkItem]:
    """Return unfinished, non-deleted work due on or before ``today``.

    Dates are normalized to YYYY-MM-DD. Missing/blank deadlines are excluded,
    never borrowed from a parent. Tasks finish at ``done``/``cancelled``;
    document requests finish only at ``accepted``. All other current request
    statuses, including ``pending_confirm``, remain actionable.

    Duplicate IDs within a source, unknown statuses, malformed dates and
    dangling/conflicting context raise ``TodayQueueValidationError``. Input
    iterator failures propagate as well; no partial result is returned. The
    same numeric ID in different sources is valid. Inputs are never mutated.
    """
    _today_date(today)
    by_engagement: dict[int, EngagementRow] = {}
    for engagement in engagements:
        _require_id(engagement.id, kind="engagement")
        if engagement.id in by_engagement:
            raise TodayQueueValidationError(
                "duplicate_id", kind="engagement", record_id=engagement.id
            )
        by_engagement[engagement.id] = engagement

    result: list[TodayWorkItem] = []
    for kind, row, due in _due_rows(tasks, requests, today):
        title = row.title if kind == "task" else row.request_name
        if not isinstance(title, str) or not title.strip():
            raise TodayQueueValidationError("invalid_title", kind=kind, record_id=row.id)
        client_id = row.client_id if kind == "task" else None
        if client_id is not None:
            _require_id(client_id, kind=kind, record_id=row.id)
        engagement_id = row.engagement_id
        if engagement_id is not None:
            _require_id(engagement_id, kind=kind, record_id=row.id)
            engagement = by_engagement.get(engagement_id)
            if engagement is None or engagement.deleted_at is not None:
                raise TodayQueueValidationError(
                    "engagement_not_found", kind=kind, record_id=row.id
                )
            _require_id(engagement.client_id, kind="engagement", record_id=engagement.id)
            if not isinstance(engagement.engagement_name, str) or not engagement.engagement_name.strip():
                raise TodayQueueValidationError("invalid_title", kind="engagement", record_id=engagement.id)
            if client_id is not None and client_id != engagement.client_id:
                raise TodayQueueValidationError(
                    "client_mismatch", kind=kind, record_id=row.id
                )
            client_id = engagement.client_id
        elif kind == "document_request":
            raise TodayQueueValidationError(
                "engagement_not_found", kind=kind, record_id=row.id
            )
        result.append(
            TodayWorkItem(
                kind=kind,
                record_id=row.id,
                title=title,
                due_date=due.isoformat(),
                engagement_id=engagement_id,
                client_id=client_id,
                request_id=row.id if kind == "document_request" else None,
                task_id=row.id if kind == "task" else None,
                source_label="待辦事項" if kind == "task" else "索件批次",
                status_label=status_to_label(row.status),
            )
        )
    return sorted(result, key=lambda item: (item.due_date, item.key))
