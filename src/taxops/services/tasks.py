"""Tasks service: validation, persistence, and audit log."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from ..core.text import sanitize_user_text
from ..repositories.tasks import TaskRow, TasksRepository
from .audit import AuditService

VALID_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})

VALID_TASK_STATUSES = frozenset({
    "todo",
    "doing",
    "waiting_client",
    "waiting_internal_review",
    "done",
    "cancelled",
})

_ALLOWED_TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "todo": frozenset({"todo", "doing", "waiting_client", "waiting_internal_review", "cancelled"}),
    "doing": frozenset({"doing", "todo", "waiting_client", "waiting_internal_review", "done", "cancelled"}),
    "waiting_client": frozenset({"waiting_client", "doing", "done", "cancelled"}),
    "waiting_internal_review": frozenset({"waiting_internal_review", "doing", "done", "cancelled"}),
    "done": frozenset({"done"}),
    "cancelled": frozenset({"cancelled"}),
}


class TaskValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateTaskInput:
    engagement_id: int | None
    title: str
    client_id: int | None = None
    assignee: str | None = None
    due_date: str | None = None
    priority: str = "normal"
    next_step: str | None = None
    notes: str | None = None


class TasksService:
    def __init__(self, repo: TasksRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit

    def create_task(self, payload: CreateTaskInput) -> TaskRow:
        if payload.engagement_id is not None:
            if not self._repo.engagement_exists(payload.engagement_id):
                raise TaskValidationError("task.engagement_not_found")
            # Engagement is the source of truth — overrides any caller-supplied
            # client_id so tasks always agree with their parent engagement.
            effective_client_id: int | None = self._repo.get_engagement_client_id(
                payload.engagement_id
            )
        else:
            effective_client_id = payload.client_id
            if effective_client_id is not None and not self._repo.client_exists(
                effective_client_id
            ):
                raise TaskValidationError("task.client_not_found")

        title = sanitize_user_text(payload.title, max_length=200)
        if not title:
            raise TaskValidationError("task.title.required")

        if payload.priority not in VALID_PRIORITIES:
            raise TaskValidationError("task.priority.invalid")

        assignee = sanitize_user_text(payload.assignee, max_length=100) or None
        due_date = sanitize_user_text(payload.due_date, max_length=20) or None
        if due_date is not None:
            try:
                datetime.date.fromisoformat(due_date)
            except ValueError:
                raise TaskValidationError("task.due_date.invalid")
        next_step = sanitize_user_text(payload.next_step, max_length=500) or None
        notes = sanitize_user_text(payload.notes, max_length=2000) or None

        row = self._repo.insert(
            engagement_id=payload.engagement_id,
            client_id=effective_client_id,
            title=title,
            assignee=assignee,
            due_date=due_date,
            priority=payload.priority,
            status="todo",
            next_step=next_step,
            notes=notes,
        )
        self._audit.record(
            action="task.create",
            target_type="task",
            target_id=str(row.id),
            detail={
                "engagement_id": payload.engagement_id,
                "client_id": effective_client_id,
                "title": row.title,
                "priority": row.priority,
                "due_date": row.due_date,
            },
        )
        return row

    def complete_task(self, task_id: int, *, completion_note: str | None = None) -> TaskRow:
        existing = self._repo.get(task_id)
        if existing is None:
            raise TaskValidationError("task.not_found")
        if existing.status == "done":
            raise TaskValidationError("task.already_done")
        if existing.status == "cancelled":
            raise TaskValidationError("task.status.transition_invalid")

        row = self._repo.complete(task_id)
        if row is None:
            raise TaskValidationError("task.not_found")
        self._audit.record(
            action="task.complete",
            target_type="task",
            target_id=str(task_id),
            detail={
                "title": existing.title,
                "completion_note": sanitize_user_text(completion_note, max_length=500) or None,
            },
        )
        return row

    def set_status(self, task_id: int, status: str) -> TaskRow:
        if status not in VALID_TASK_STATUSES:
            raise TaskValidationError("task.status.invalid")
        existing = self._repo.get(task_id)
        if existing is None:
            raise TaskValidationError("task.not_found")
        allowed = _ALLOWED_TASK_TRANSITIONS.get(existing.status, frozenset())
        if status not in allowed:
            raise TaskValidationError("task.status.transition_invalid")
        row = self._repo.update_status(task_id, status)
        if row is None:
            raise TaskValidationError("task.not_found")
        self._audit.record(
            action="task.status_change",
            target_type="task",
            target_id=str(task_id),
            detail={"status": status, "previous_status": existing.status},
        )
        return row

    def delete_task(self, task_id: int) -> None:
        existing = self._repo.get(task_id)
        if existing is None:
            raise TaskValidationError("task.not_found")
        self._repo.delete(task_id)
        self._audit.record(
            action="task.delete",
            target_type="task",
            target_id=str(task_id),
            detail={"title": existing.title},
        )

    def get_task(self, task_id: int) -> TaskRow | None:
        return self._repo.get(task_id)

    def list_by_engagement(
        self,
        engagement_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[TaskRow]:
        return self._repo.list_by_engagement(
            engagement_id,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
        )

    def list_all(
        self,
        *,
        order_by: str = "due_date",
        order_dir: str = "ASC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[TaskRow]:
        return self._repo.list_all(order_by=order_by, order_dir=order_dir, limit=limit, offset=offset)

    def list_overdue(self, today: str) -> list[TaskRow]:
        return self._repo.list_overdue(today)

    def list_due_today(self, today: str) -> list[TaskRow]:
        return self._repo.list_due_today(today)

    def list_by_client(
        self,
        client_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[TaskRow]:
        return self._repo.list_by_client(
            client_id,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
        )
