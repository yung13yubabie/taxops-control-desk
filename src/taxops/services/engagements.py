"""Engagements service: validation, persistence, and audit log."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.text import sanitize_user_text
from ..repositories.engagements import EngagementRow, EngagementsRepository
from ..repositories.search import SearchRepository
from .audit import AuditService

_log = logging.getLogger(__name__)

VALID_TAX_TYPES = frozenset({"vat", "cit", "iit", "stamp", "inheritance", "other"})

VALID_STATUSES = frozenset({
    "draft",
    "pending_acceptance",
    "accepted",
    "in_progress",
    "waiting_client",
    "waiting_review",
    "ready_to_file",
    "filed",
    "delivered",
    "closed",
})

# Allowed target statuses keyed by current status.
# Any transition not listed here raises engagement.status.transition_invalid.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({
        "draft", "pending_acceptance", "accepted", "in_progress",
    }),
    "pending_acceptance": frozenset({
        "pending_acceptance", "draft", "accepted",
    }),
    "accepted": frozenset({
        "accepted", "in_progress", "closed",
    }),
    "in_progress": frozenset({
        "in_progress", "waiting_client", "waiting_review", "ready_to_file",
    }),
    "waiting_client": frozenset({
        "waiting_client", "in_progress", "waiting_review",
    }),
    "waiting_review": frozenset({
        "waiting_review", "in_progress", "ready_to_file",
    }),
    "ready_to_file": frozenset({
        "ready_to_file", "filed", "waiting_review", "in_progress",
    }),
    "filed": frozenset({
        "filed", "delivered",
    }),
    "delivered": frozenset({
        "delivered", "closed",
    }),
    "closed": frozenset({
        "closed",
    }),
}


class EngagementValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateEngagementInput:
    client_id: int
    engagement_name: str
    tax_type: str
    period_name: str
    owner: str | None = None
    due_date: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UpdateEngagementInput:
    engagement_name: str
    tax_type: str
    period_name: str
    status: str
    owner: str | None = None
    due_date: str | None = None
    notes: str | None = None


class EngagementsService:
    def __init__(
        self,
        repo: EngagementsRepository,
        audit: AuditService,
        search_repo: SearchRepository | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._search_repo = search_repo

    def _fts_add(self, row: EngagementRow) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.add_engagement(
                row.id, engagement_name=row.engagement_name
            )
        except Exception:
            _log.warning("engagement FTS add failed", exc_info=True)

    def _fts_update(self, row: EngagementRow) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.update_engagement(
                row.id, engagement_name=row.engagement_name
            )
        except Exception:
            _log.warning("engagement FTS update failed", exc_info=True)

    def _fts_delete(self, engagement_id: int) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.delete_engagement(engagement_id)
        except Exception:
            _log.warning("engagement FTS delete failed", exc_info=True)

    def create_engagement(self, payload: CreateEngagementInput) -> EngagementRow:
        if not self._repo.client_exists(payload.client_id):
            raise EngagementValidationError("engagement.client_not_found")

        name = sanitize_user_text(payload.engagement_name, max_length=200)
        if not name:
            raise EngagementValidationError("engagement.name.required")

        if payload.tax_type not in VALID_TAX_TYPES:
            raise EngagementValidationError("engagement.tax_type.invalid")

        period = sanitize_user_text(payload.period_name, max_length=50)
        if not period:
            raise EngagementValidationError("engagement.period_name.required")

        status = "draft"
        owner = sanitize_user_text(payload.owner, max_length=100) or None
        due_date = sanitize_user_text(payload.due_date, max_length=20) or None
        notes = sanitize_user_text(payload.notes, max_length=2000) or None

        row = self._repo.insert(
            client_id=payload.client_id,
            engagement_name=name,
            tax_type=payload.tax_type,
            period_name=period,
            status=status,
            owner=owner,
            due_date=due_date,
            notes=notes,
        )
        self._audit.record(
            action="engagement.create",
            target_type="engagement",
            target_id=str(row.id),
            detail={
                "client_id": payload.client_id,
                "engagement_name": row.engagement_name,
                "tax_type": row.tax_type,
                "period_name": row.period_name,
                "status": row.status,
            },
        )
        self._fts_add(row)
        return row

    def update_engagement(
        self, engagement_id: int, payload: UpdateEngagementInput
    ) -> EngagementRow:
        existing = self._repo.get(engagement_id)
        if existing is None:
            raise EngagementValidationError("engagement.not_found")

        name = sanitize_user_text(payload.engagement_name, max_length=200)
        if not name:
            raise EngagementValidationError("engagement.name.required")

        if payload.tax_type not in VALID_TAX_TYPES:
            raise EngagementValidationError("engagement.tax_type.invalid")

        period = sanitize_user_text(payload.period_name, max_length=50)
        if not period:
            raise EngagementValidationError("engagement.period_name.required")

        if payload.status not in VALID_STATUSES:
            raise EngagementValidationError("engagement.status.invalid")
        allowed = _ALLOWED_TRANSITIONS.get(existing.status, frozenset())
        if payload.status not in allowed:
            raise EngagementValidationError("engagement.status.transition_invalid")

        owner = sanitize_user_text(payload.owner, max_length=100) or None
        due_date = sanitize_user_text(payload.due_date, max_length=20) or None
        notes = sanitize_user_text(payload.notes, max_length=2000) or None

        row = self._repo.update(
            engagement_id,
            engagement_name=name,
            tax_type=payload.tax_type,
            period_name=period,
            status=payload.status,
            owner=owner,
            due_date=due_date,
            notes=notes,
        )
        if row is None:
            raise EngagementValidationError("engagement.not_found")

        self._audit.record(
            action="engagement.update",
            target_type="engagement",
            target_id=str(engagement_id),
            detail={
                "engagement_name": row.engagement_name,
                "status": row.status,
                "tax_type": row.tax_type,
                "period_name": row.period_name,
            },
        )
        self._fts_update(row)
        return row

    def set_status(self, engagement_id: int, status: str) -> EngagementRow:
        if status not in VALID_STATUSES:
            raise EngagementValidationError("engagement.status.invalid")
        existing = self._repo.get(engagement_id)
        if existing is None:
            raise EngagementValidationError("engagement.not_found")
        allowed = _ALLOWED_TRANSITIONS.get(existing.status, frozenset())
        if status not in allowed:
            raise EngagementValidationError("engagement.status.transition_invalid")
        row = self._repo.update_status(engagement_id, status)
        if row is None:
            raise EngagementValidationError("engagement.not_found")
        self._audit.record(
            action="engagement.status_change",
            target_type="engagement",
            target_id=str(engagement_id),
            detail={"status": status},
        )
        return row

    def delete_engagement(self, engagement_id: int) -> None:
        existing = self._repo.get(engagement_id)
        if existing is None:
            raise EngagementValidationError("engagement.not_found")
        self._repo.delete(engagement_id)
        self._fts_delete(engagement_id)
        self._audit.record(
            action="engagement.delete",
            target_type="engagement",
            target_id=str(engagement_id),
            detail={
                "engagement_name": existing.engagement_name,
                "tax_type": existing.tax_type,
                "period_name": existing.period_name,
            },
        )

    def get_engagement(self, engagement_id: int) -> EngagementRow | None:
        return self._repo.get(engagement_id)

    def list_by_client(
        self,
        client_id: int,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[EngagementRow]:
        return self._repo.list_by_client(
            client_id,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
        )

    def count_by_client(self, client_id: int) -> int:
        return self._repo.count_by_client(client_id)

    def list_all(
        self,
        *,
        order_by: str = "updated_at",
        order_dir: str = "DESC",
        limit: int = 500,
        offset: int = 0,
    ) -> list[EngagementRow]:
        return self._repo.list_all(
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
        )

    def list_upcoming(self, today: str, until: str) -> list[EngagementRow]:
        return self._repo.list_upcoming(today, until)

    def list_overdue(self, today: str) -> list[EngagementRow]:
        return self._repo.list_overdue(today)

    def valid_next_statuses(self, engagement_id: int) -> frozenset[str]:
        existing = self._repo.get(engagement_id)
        if existing is None:
            return frozenset()
        return _ALLOWED_TRANSITIONS.get(existing.status, frozenset())
