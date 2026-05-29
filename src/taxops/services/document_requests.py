"""Document requests service: VAT template, item status, audit log."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso
from ..core.dates import parse_optional_iso_date
from ..core.text import sanitize_user_text
from ..repositories.document_requests import (
    DocumentRequestItemRow,
    DocumentRequestRow,
    DocumentRequestsRepository,
)
from .audit import AuditService

VAT_ITEMS = (
    "銷項發票明細",
    "進項憑證",
    "折讓單",
    "銀行交易資料",
    "租金憑證",
    "薪資資料",
    "電商平台報表",
    "海關進口資料",
    "其他收據",
)

VALID_REQUEST_STATUSES = frozenset({
    "not_requested",
    "requested",
    "partially_received",
    "under_validation",
    "pending_confirm",
    "accepted",
})

VALID_ITEM_STATUSES = frozenset({
    "missing",
    "received",
    "incomplete",
    "invalid",
    "accepted",
    "not_applicable",
    "client_said_none",
    "pending_confirm",
})


_RESOLVED = frozenset({"accepted", "not_applicable", "client_said_none"})
_RECEIVED = frozenset({"received", "not_applicable", "client_said_none"})


def _derive_request_status(statuses: frozenset[str]) -> str:
    """Derive request-level status from the set of item statuses."""
    if not statuses:
        return "requested"
    if statuses.issubset(_RESOLVED):
        return "accepted"
    if "pending_confirm" in statuses:
        return "pending_confirm"
    if "invalid" in statuses or "incomplete" in statuses:
        return "under_validation"
    if statuses & _RECEIVED:
        return "partially_received"
    return "requested"


class DocumentRequestValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateDocumentRequestInput:
    engagement_id: int
    tax_type: str
    period_name: str
    request_name: str | None = None
    due_date: str | None = None
    notes: str | None = None
    item_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateDocumentRequestInput:
    request_name: str
    due_date: str | None = None
    notes: str | None = None


def default_request_name(*, period_name: str, tax_type: str) -> str:
    period = sanitize_user_text(period_name, max_length=80) or "未命名期間"
    tax = sanitize_user_text(tax_type, max_length=40) or "一般"
    return f"{period} {tax} request"


class DocumentRequestsService:
    def __init__(
        self,
        repo: DocumentRequestsRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._audit = audit

    def create_request(
        self, payload: CreateDocumentRequestInput
    ) -> tuple[DocumentRequestRow, list[DocumentRequestItemRow]]:
        """Create a document request, optionally seeding the VAT template items.

        Request + items are inserted atomically — any failure rolls back both.
        Returns (request_row, items).
        """
        if not self._repo.engagement_exists(payload.engagement_id):
            raise DocumentRequestValidationError("doc_request.engagement_not_found")

        due_date = sanitize_user_text(payload.due_date, max_length=20) or None
        try:
            parse_optional_iso_date(due_date)
        except ValueError:
            raise DocumentRequestValidationError("doc_request.due_date.invalid")
        notes = sanitize_user_text(payload.notes, max_length=2000) or None
        request_name = sanitize_user_text(payload.request_name, max_length=120)
        if not request_name:
            request_name = default_request_name(
                period_name=payload.period_name,
                tax_type=payload.tax_type,
            )

        request, items = self._repo.insert_request_with_items(
            engagement_id=payload.engagement_id,
            request_name=request_name,
            tax_type=payload.tax_type,
            period_name=payload.period_name,
            due_date=due_date,
            notes=notes,
            item_names=payload.item_names,
        )
        self._audit.record(
            action="doc_request.create",
            target_type="document_request",
            target_id=str(request.id),
            detail={
                "engagement_id": payload.engagement_id,
                "tax_type": payload.tax_type,
                "period_name": payload.period_name,
                "request_name": request.request_name,
                "item_count": len(items),
            },
        )
        return request, items

    def update_request(
        self,
        request_id: int,
        payload: UpdateDocumentRequestInput,
    ) -> DocumentRequestRow:
        request_name = sanitize_user_text(payload.request_name, max_length=120)
        if not request_name:
            raise DocumentRequestValidationError("doc_request.name.required")
        due_date = sanitize_user_text(payload.due_date, max_length=20) or None
        try:
            parse_optional_iso_date(due_date)
        except ValueError:
            raise DocumentRequestValidationError("doc_request.due_date.invalid")
        notes = sanitize_user_text(payload.notes, max_length=2000) or None
        row = self._repo.update_request_metadata(
            request_id,
            request_name=request_name,
            due_date=due_date,
            notes=notes,
        )
        if row is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        self._audit.record(
            action="doc_request.update",
            target_type="document_request",
            target_id=str(request_id),
            detail={"request_name": row.request_name},
        )
        return row

    def mark_requested(self, request_id: int) -> DocumentRequestRow:
        row = self._repo.update_request_status(
            request_id,
            status="requested",
            requested_at=now_iso(),
        )
        if row is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        self._audit.record(
            action="doc_request.mark_requested",
            target_type="document_request",
            target_id=str(request_id),
            detail={"status": "requested"},
        )
        return row

    def set_request_status(self, request_id: int, status: str) -> DocumentRequestRow:
        if status not in VALID_REQUEST_STATUSES:
            raise DocumentRequestValidationError("doc_request.status.invalid")
        row = self._repo.update_request_status(request_id, status=status)
        if row is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        self._audit.record(
            action="doc_request.status_change",
            target_type="document_request",
            target_id=str(request_id),
            detail={"status": status},
        )
        return row

    def add_follow_up(self, request_id: int) -> DocumentRequestRow:
        row = self._repo.increment_follow_up(request_id)
        if row is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        self._audit.record(
            action="doc_request.follow_up",
            target_type="document_request",
            target_id=str(request_id),
            detail={"follow_up_count": row.follow_up_count},
        )
        return row

    def delete_request(self, request_id: int) -> None:
        existing = self._repo.get_request(request_id)
        if existing is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        self._repo.delete_request(request_id)
        self._audit.record(
            action="doc_request.delete",
            target_type="document_request",
            target_id=str(request_id),
            detail={
                "tax_type": existing.tax_type,
                "period_name": existing.period_name,
            },
        )

    def add_item(self, request_id: int, item_name: str) -> DocumentRequestItemRow:
        name = sanitize_user_text(item_name, max_length=200)
        if not name:
            raise DocumentRequestValidationError("doc_request_item.name.required")
        try:
            item = self._repo.insert_item(request_id=request_id, item_name=name)
        except sqlite3.IntegrityError as exc:
            if "FOREIGN KEY" in str(exc).upper():
                raise DocumentRequestValidationError("doc_request.not_found") from exc
            raise
        new_req_status = self._recompute_request_status(request_id)
        self._repo.update_request_status(request_id, status=new_req_status)
        self._audit.record(
            action="doc_request_item.create",
            target_type="document_request_item",
            target_id=str(item.id),
            detail={"request_id": request_id, "item_name": name},
        )
        return item

    def add_items_bulk(
        self, request_id: int, raw_text: str
    ) -> list[DocumentRequestItemRow]:
        """Add one item per non-empty line in raw_text."""
        names = [line.strip() for line in raw_text.splitlines()]
        names = [n for n in names if n]
        if not names:
            raise DocumentRequestValidationError("doc_request_item.bulk.empty")
        items: list[DocumentRequestItemRow] = []
        for name in names:
            items.append(self.add_item(request_id, name))
        return items

    def update_item(
        self, item_id: int, item_name: str, notes: str | None = None
    ) -> DocumentRequestItemRow:
        name = sanitize_user_text(item_name, max_length=200)
        if not name:
            raise DocumentRequestValidationError("doc_request_item.name.required")
        notes_clean = sanitize_user_text(notes, max_length=500) or None
        item = self._repo.update_item_name(item_id, item_name=name, notes=notes_clean)
        if item is None:
            raise DocumentRequestValidationError("doc_request_item.not_found")
        self._audit.record(
            action="doc_request_item.update",
            target_type="document_request_item",
            target_id=str(item_id),
            detail={"item_name": name},
        )
        return item

    def delete_items_bulk(self, item_ids: list[int]) -> int:
        """Delete multiple items by id; silently skip nonexistent ids.

        Recomputes the parent request status for each affected request once
        per request (not once per item) and records a single audit entry with
        the list of ids and final deleted count.
        """
        if not item_ids:
            return 0
        affected_request_ids: set[int] = set()
        deleted: list[int] = []
        for item_id in item_ids:
            existing = self._repo.get_item(item_id)
            if existing is None:
                continue
            self._repo.delete_item(item_id)
            affected_request_ids.add(existing.request_id)
            deleted.append(item_id)
        for req_id in affected_request_ids:
            new_status = self._recompute_request_status(req_id)
            self._repo.update_request_status(req_id, status=new_status)
        if deleted:
            self._audit.record(
                action="doc_request_item.bulk_delete",
                target_type="document_request_item",
                target_id=",".join(str(i) for i in deleted),
                detail={"item_ids": deleted, "deleted_count": len(deleted)},
            )
        return len(deleted)

    def delete_item(self, item_id: int) -> None:
        existing = self._repo.get_item(item_id)
        if existing is None:
            raise DocumentRequestValidationError("doc_request_item.not_found")
        self._repo.delete_item(item_id)
        new_req_status = self._recompute_request_status(existing.request_id)
        self._repo.update_request_status(existing.request_id, status=new_req_status)
        self._audit.record(
            action="doc_request_item.delete",
            target_type="document_request_item",
            target_id=str(item_id),
            detail={"item_name": existing.item_name, "request_id": existing.request_id},
        )

    def set_item_status(
        self,
        item_id: int,
        *,
        item_status: str,
        notes: str | None = None,
    ) -> DocumentRequestItemRow:
        if item_status not in VALID_ITEM_STATUSES:
            raise DocumentRequestValidationError("doc_request_item.status.invalid")
        notes_clean = sanitize_user_text(notes, max_length=500) or None
        item = self._repo.update_item_status(item_id, item_status=item_status, notes=notes_clean)
        if item is None:
            raise DocumentRequestValidationError("doc_request_item.not_found")
        new_req_status = self._recompute_request_status(item.request_id)
        self._repo.update_request_status(item.request_id, status=new_req_status)
        self._audit.record(
            action="doc_request_item.status_change",
            target_type="document_request_item",
            target_id=str(item_id),
            detail={"item_status": item_status, "request_status": new_req_status},
        )
        return item

    def _recompute_request_status(self, request_id: int) -> str:
        items = self._repo.list_items(request_id)
        statuses = frozenset(i.item_status for i in items)
        return _derive_request_status(statuses)

    def get_request(self, request_id: int) -> DocumentRequestRow | None:
        return self._repo.get_request(request_id)

    def list_all(self) -> list[DocumentRequestRow]:
        return self._repo.list_all()

    def list_by_engagement(self, engagement_id: int) -> list[DocumentRequestRow]:
        return self._repo.list_by_engagement(engagement_id)

    def list_items(self, request_id: int) -> list[DocumentRequestItemRow]:
        return self._repo.list_items(request_id)
