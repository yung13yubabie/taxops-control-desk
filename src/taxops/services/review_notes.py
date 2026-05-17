"""Service for review notes: creation, status transitions, validation."""

from __future__ import annotations

from dataclasses import dataclass

from ..repositories.engagements import EngagementsRepository
from ..repositories.review_notes import ReviewNoteRow, ReviewNotesRepository
from .audit import AuditService

VALID_SEVERITIES = frozenset({"critical", "major", "minor"})

_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("open", "responded"),
        ("open", "waived"),
        ("responded", "resolved"),
        ("responded", "waived"),
        ("resolved", "reopened"),
        ("waived", "reopened"),
    }
)


class ReviewNoteValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateReviewNoteInput:
    engagement_id: int
    severity: str
    comment: str
    assigned_to: str | None = None
    related_task_id: int | None = None


@dataclass(frozen=True)
class UpdateReviewNoteStatusInput:
    note_id: int
    new_status: str
    response: str | None = None
    waive_reason: str | None = None


class ReviewNotesService:
    def __init__(
        self,
        repo: ReviewNotesRepository,
        engagements_repo: EngagementsRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._engagements_repo = engagements_repo
        self._audit = audit

    def create(self, payload: CreateReviewNoteInput) -> ReviewNoteRow:
        if payload.severity not in VALID_SEVERITIES:
            raise ReviewNoteValidationError("review_note.invalid_severity")
        if not payload.comment.strip():
            raise ReviewNoteValidationError("review_note.comment_required")
        if self._engagements_repo.get(payload.engagement_id) is None:
            raise ReviewNoteValidationError("review_note.engagement_not_found")

        row = self._repo.insert(
            engagement_id=payload.engagement_id,
            severity=payload.severity,
            comment=payload.comment.strip(),
            assigned_to=payload.assigned_to,
            related_task_id=payload.related_task_id,
        )
        self._audit.record(
            action="review_note.create",
            target_type="review_note",
            target_id=str(row.id),
            detail={"engagement_id": payload.engagement_id, "severity": payload.severity},
        )
        return row

    def update_status(self, payload: UpdateReviewNoteStatusInput) -> ReviewNoteRow:
        note = self._repo.get(payload.note_id)
        if note is None:
            raise ReviewNoteValidationError("review_note.not_found")

        if (note.status, payload.new_status) not in _TRANSITIONS:
            raise ReviewNoteValidationError("review_note.invalid_transition")

        if payload.new_status == "waived" and note.severity == "critical":
            raise ReviewNoteValidationError("review_note.critical_cannot_waive")

        if payload.new_status == "waived" and not (payload.waive_reason or "").strip():
            raise ReviewNoteValidationError("review_note.waive_reason_required")

        updated = self._repo.update_status(
            note_id=payload.note_id,
            status=payload.new_status,
            response=payload.response,
            waive_reason=payload.waive_reason,
        )
        self._audit.record(
            action="review_note.status_change",
            target_type="review_note",
            target_id=str(payload.note_id),
            detail={"from": note.status, "to": payload.new_status},
        )
        return updated  # type: ignore[return-value]

    def list_by_engagement(self, engagement_id: int) -> list[ReviewNoteRow]:
        return self._repo.list_by_engagement(engagement_id)

    def list_open_all(self) -> list[ReviewNoteRow]:
        return self._repo.list_open_all()

    def list_high_risk_all(self) -> list[ReviewNoteRow]:
        return self._repo.list_high_risk_all()

    def get(self, note_id: int) -> ReviewNoteRow | None:
        return self._repo.get(note_id)
