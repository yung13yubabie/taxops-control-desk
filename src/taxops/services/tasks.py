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

_BULK_UPDATE_FIELDS = frozenset({
    "status",
    "priority",
    "assignee",
    "due_date",
    "next_step",
    "notes",
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


@dataclass(frozen=True)
class BulkTaskTemplate:
    """Common fields applied to every task in a bulk-create operation."""
    title: str
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
        # Slice 21D: forbid deleting a parent that still has live children.
        if self._repo.count_children(task_id) > 0:
            raise TaskValidationError("task.delete.has_children")
        self._repo.delete(task_id)
        self._audit.record(
            action="task.delete",
            target_type="task",
            target_id=str(task_id),
            detail={"title": existing.title},
        )

    # ── Slice 21D: parent/child + bulk CRUD ──────────────────────────

    def convert_to_child(self, task_id: int, parent_task_id: int) -> TaskRow:
        """Mark ``task_id`` as a child of ``parent_task_id``.

        Enforces 2-level depth: the chosen parent must itself be a root
        (parent_task_id IS NULL). Also rejects self-reference. The child
        inherits nothing automatically here — caller can update the child's
        client_id/engagement_id separately if desired.
        """
        if task_id == parent_task_id:
            raise TaskValidationError("task.parent.self_reference")
        child = self._repo.get(task_id)
        if child is None:
            raise TaskValidationError("task.not_found")
        parent = self._repo.get(parent_task_id)
        if parent is None:
            raise TaskValidationError("task.parent.not_found")
        if (
            child.client_id != parent.client_id
            or child.engagement_id != parent.engagement_id
        ):
            raise TaskValidationError("task.parent.context_mismatch")
        # 2-level cap: parent must be a root (no grandparent).
        if parent.parent_task_id is not None:
            raise TaskValidationError("task.parent.depth_exceeded")
        # Also reject if the child already has its own children — converting
        # it would make a grandchild and exceed depth.
        if self._repo.count_children(task_id) > 0:
            raise TaskValidationError("task.parent.depth_exceeded")
        row = self._repo.update_parent(task_id, parent_task_id)
        if row is None:
            raise TaskValidationError("task.not_found")
        self._audit.record(
            action="task.convert_to_child",
            target_type="task",
            target_id=str(task_id),
            detail={"parent_task_id": parent_task_id},
        )
        return row

    def create_child_task(self, parent_task_id: int, title: str) -> TaskRow:
        parent = self._repo.get(parent_task_id)
        if parent is None:
            raise TaskValidationError("task.parent.not_found")
        if parent.parent_task_id is not None:
            raise TaskValidationError("task.parent.depth_exceeded")
        clean_title = sanitize_user_text(title, max_length=200)
        if not clean_title:
            raise TaskValidationError("task.title.required")
        row = self._repo.insert(
            engagement_id=parent.engagement_id,
            client_id=parent.client_id,
            parent_task_id=parent.id,
            title=clean_title,
            assignee=parent.assignee,
            due_date=None,
            priority=parent.priority,
            status="todo",
            next_step=None,
            notes=None,
        )
        self._audit.record(
            action="task.create_child",
            target_type="task",
            target_id=str(row.id),
            detail={
                "parent_task_id": parent.id,
                "client_id": parent.client_id,
                "engagement_id": parent.engagement_id,
                "title": row.title,
            },
        )
        return row

    def create_tasks_bulk(
        self,
        client_ids: list[int],
        template: BulkTaskTemplate,
    ) -> list[TaskRow]:
        """Create one task per ``client_id`` from a shared template.

        Each task is created with ``client_id`` set and ``engagement_id``
        left NULL — bulk operations are client-scoped, never tied to a
        specific case. Invalid client_ids are silently skipped (per-row
        validation; caller can compare returned len vs input len). A single
        ``task.bulk_create`` audit entry records the operation; per-task
        ``task.create`` audits also fire (one per row).
        """
        created: list[TaskRow] = []
        for cid in client_ids:
            try:
                row = self.create_task(CreateTaskInput(
                    engagement_id=None,
                    client_id=cid,
                    title=template.title,
                    assignee=template.assignee,
                    due_date=template.due_date,
                    priority=template.priority,
                    next_step=template.next_step,
                    notes=template.notes,
                ))
                created.append(row)
            except TaskValidationError:
                # Skip invalid clients (e.g. nonexistent id) and continue.
                continue
        if created:
            self._audit.record(
                action="task.bulk_create",
                target_type="task",
                target_id=",".join(str(t.id) for t in created),
                detail={
                    "task_count": len(created),
                    "title": template.title,
                    "client_ids": client_ids,
                },
            )
        return created

    def update_tasks_bulk(
        self,
        task_ids: list[int],
        fields: dict,
    ) -> int:
        """Apply the same set of field updates to every listed task.

        Supported fields: ``status``, ``priority``, ``assignee``, ``due_date``.
        Status changes still respect the per-task transition rules; tasks
        whose transition would be invalid are silently skipped (partial
        success allowed). Returns the count of successfully updated tasks.
        """
        if not task_ids or not fields:
            return 0
        normalized_fields = self._normalize_bulk_update_fields(fields)
        updated = 0
        for tid in task_ids:
            existing = self._repo.get(tid)
            if existing is None:
                continue
            try:
                if "status" in normalized_fields:
                    self.set_status(tid, normalized_fields["status"])
                if any(k in normalized_fields for k in ("priority", "assignee", "due_date", "next_step", "notes")):
                    refreshed = self._repo.get(tid) or existing
                    self._repo.update(
                        tid,
                        title=refreshed.title,
                        assignee=normalized_fields.get("assignee", refreshed.assignee),
                        due_date=normalized_fields.get("due_date", refreshed.due_date),
                        priority=normalized_fields.get("priority", refreshed.priority),
                        next_step=normalized_fields.get("next_step", refreshed.next_step),
                        notes=normalized_fields.get("notes", refreshed.notes),
                    )
                updated += 1
            except TaskValidationError:
                continue
        if updated:
            self._audit.record(
                action="task.bulk_update",
                target_type="task",
                target_id=",".join(str(i) for i in task_ids),
                detail={
                    "updated_count": updated,
                    "skipped_count": len(task_ids) - updated,
                    "fields": list(normalized_fields.keys()),
                },
            )
        return updated

    def _normalize_bulk_update_fields(self, fields: dict) -> dict:
        unknown_fields = set(fields) - _BULK_UPDATE_FIELDS
        if unknown_fields:
            raise TaskValidationError("task.bulk.update.invalid_field")

        normalized: dict = {}
        if "status" in fields:
            status = fields["status"]
            if status not in VALID_TASK_STATUSES:
                raise TaskValidationError("task.status.invalid")
            normalized["status"] = status

        if "priority" in fields:
            priority = fields["priority"]
            if priority not in VALID_PRIORITIES:
                raise TaskValidationError("task.priority.invalid")
            normalized["priority"] = priority

        if "assignee" in fields:
            normalized["assignee"] = sanitize_user_text(
                fields["assignee"], max_length=100
            ) or None

        if "due_date" in fields:
            due_date = sanitize_user_text(fields["due_date"], max_length=20) or None
            if due_date is not None:
                try:
                    datetime.date.fromisoformat(due_date)
                except ValueError:
                    raise TaskValidationError("task.due_date.invalid")
            normalized["due_date"] = due_date

        if "next_step" in fields:
            normalized["next_step"] = sanitize_user_text(
                fields["next_step"], max_length=500
            ) or None

        if "notes" in fields:
            normalized["notes"] = sanitize_user_text(
                fields["notes"], max_length=2000
            ) or None

        return normalized

    def delete_tasks_bulk(self, task_ids: list[int]) -> int:
        """Soft-delete each listed task; skip parents that still have
        children (same protection as single delete). Returns deleted count.
        """
        deleted = 0
        for tid in task_ids:
            try:
                self.delete_task(tid)
                deleted += 1
            except TaskValidationError:
                continue
        if deleted:
            self._audit.record(
                action="task.bulk_delete",
                target_type="task",
                target_id=",".join(str(i) for i in task_ids),
                detail={
                    "deleted_count": deleted,
                    "skipped_count": len(task_ids) - deleted,
                },
            )
        return deleted

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
