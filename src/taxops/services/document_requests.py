"""Document requests service: VAT template, item status, audit log."""

from __future__ import annotations

import sqlite3
import unicodedata
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

MAX_ITEMS_PER_REQUEST = 1_000
MAX_ITEM_NAMES_TOTAL_LENGTH = 100_000
MAX_BULK_RAW_TEXT_LENGTH = 100_000


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


@dataclass(frozen=True)
class DocumentItemsMutationResult:
    """Committed item rows plus exact parent request rows from one transaction."""

    requests_after: tuple[DocumentRequestRow, ...]
    affected_items: tuple[DocumentRequestItemRow, ...] = ()
    deleted_items: tuple[DocumentRequestItemRow, ...] = ()


@dataclass(frozen=True)
class DocumentRequestSnapshot:
    request: DocumentRequestRow
    items: tuple[DocumentRequestItemRow, ...]


def default_request_name(*, period_name: str, tax_type: str) -> str:
    period = sanitize_user_text(period_name, max_length=80) or "未命名期間"
    tax = sanitize_user_text(tax_type, max_length=40) or "一般"
    return f"{period} {tax} request"


def _has_disallowed_control(value: str) -> bool:
    return any(
        unicodedata.category(char).startswith("C")
        for char in value
        if char not in {"\n", "\t"}
    )


def _prepare_item_names(
    values: object, *, source: str
) -> tuple[str, ...]:
    """Boundedly consume and validate item names from tuples or generators."""
    if isinstance(values, (str, bytes, dict)):
        raise DocumentRequestValidationError(f"{source}.invalid")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise DocumentRequestValidationError(f"{source}.invalid") from exc
    clean_names: list[str] = []
    total_length = 0
    for index, value in enumerate(iterator):
        if index >= MAX_ITEMS_PER_REQUEST:
            raise DocumentRequestValidationError(f"{source}.too_many")
        if (
            not isinstance(value, str)
            or len(value) > 200
            or _has_disallowed_control(value)
        ):
            raise DocumentRequestValidationError(
                "doc_request_item.name.invalid"
            )
        clean = sanitize_user_text(value, max_length=200)
        if not clean:
            raise DocumentRequestValidationError(
                "doc_request_item.name.required"
            )
        total_length += len(clean)
        if total_length > MAX_ITEM_NAMES_TOTAL_LENGTH:
            raise DocumentRequestValidationError(f"{source}.too_large")
        clean_names.append(clean)
    return tuple(clean_names)


def validate_bulk_item_text(raw_text: object) -> tuple[str, ...]:
    """Validate a pasted batch without writing or truncating its source text."""
    if not isinstance(raw_text, str):
        raise DocumentRequestValidationError(
            "doc_request_item.bulk.invalid"
        )
    if len(raw_text) > MAX_BULK_RAW_TEXT_LENGTH:
        raise DocumentRequestValidationError(
            "doc_request_item.bulk.too_large"
        )
    names = (
        line.strip() for line in raw_text.splitlines() if line.strip()
    )
    prepared = _prepare_item_names(
        names, source="doc_request_item.bulk"
    )
    if not prepared:
        raise DocumentRequestValidationError(
            "doc_request_item.bulk.empty"
        )
    return prepared


class DocumentRequestsService:
    def __init__(
        self,
        repo: DocumentRequestsRepository,
        audit: AuditService,
    ) -> None:
        if audit.connection is not repo._conn:
            raise ValueError("doc_request.connection.mismatch")
        self._repo = repo
        self._audit = audit
        self._conn = repo._conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def create_request(
        self, payload: CreateDocumentRequestInput
    ) -> tuple[DocumentRequestRow, list[DocumentRequestItemRow]]:
        """Create a document request, optionally seeding the VAT template items.

        Request + items are inserted atomically — any failure rolls back both.
        Returns (request_row, items).
        """
        with self._conn:
            return self._create_request_uncommitted(payload)

    def _create_request_uncommitted(
        self, payload: CreateDocumentRequestInput
    ) -> tuple[DocumentRequestRow, list[DocumentRequestItemRow]]:
        """Validate and create without committing or rolling back a caller transaction."""
        if not self._repo.engagement_exists(payload.engagement_id):
            raise DocumentRequestValidationError("doc_request.engagement_not_found")

        if (
            not isinstance(payload.tax_type, str)
            or not payload.tax_type.strip()
            or len(payload.tax_type) > 40
            or _has_disallowed_control(payload.tax_type)
        ):
            raise DocumentRequestValidationError("doc_request.tax_type.invalid")
        if (
            not isinstance(payload.period_name, str)
            or not payload.period_name.strip()
            or len(payload.period_name) > 80
            or _has_disallowed_control(payload.period_name)
        ):
            raise DocumentRequestValidationError("doc_request.period_name.invalid")
        if payload.request_name is not None and (
            not isinstance(payload.request_name, str) or len(payload.request_name) > 120
            or _has_disallowed_control(payload.request_name)
        ):
            raise DocumentRequestValidationError("doc_request.name.invalid")
        if payload.due_date is not None and (
            not isinstance(payload.due_date, str) or len(payload.due_date) > 20
            or _has_disallowed_control(payload.due_date)
        ):
            raise DocumentRequestValidationError("doc_request.due_date.invalid")
        if payload.notes is not None and (
            not isinstance(payload.notes, str) or len(payload.notes) > 2000
            or _has_disallowed_control(payload.notes)
        ):
            raise DocumentRequestValidationError("doc_request.notes.invalid")
        clean_item_names = _prepare_item_names(
            payload.item_names, source="doc_request.items"
        )

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

        request, items = self._repo.insert_request_with_items_uncommitted(
            engagement_id=payload.engagement_id,
            request_name=request_name,
            tax_type=payload.tax_type,
            period_name=payload.period_name,
            due_date=due_date,
            notes=notes,
            item_names=clean_item_names,
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
        with self._conn:
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
        with self._conn:
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
        with self._conn:
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
        with self._conn:
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
        with self._conn:
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

    def add_item(
        self,
        request_id: int,
        item_name: str,
        *,
        with_request: bool = False,
    ) -> DocumentRequestItemRow | DocumentItemsMutationResult:
        result = self._add_item_result(request_id, item_name)
        return result if with_request else result.affected_items[0]

    def _add_item_result(
        self, request_id: int, item_name: str
    ) -> DocumentItemsMutationResult:
        name = _prepare_item_names(
            (item_name,), source="doc_request_item.bulk"
        )[0]
        try:
            with self._conn:
                if self._repo.get_request(request_id) is None:
                    raise DocumentRequestValidationError(
                        "doc_request.not_found"
                    )
                existing_count, existing_chars = self._repo.item_totals(
                    request_id
                )
                if existing_count + 1 > MAX_ITEMS_PER_REQUEST:
                    raise DocumentRequestValidationError(
                        "doc_request_item.bulk.too_many"
                    )
                if existing_chars + len(name) > MAX_ITEM_NAMES_TOTAL_LENGTH:
                    raise DocumentRequestValidationError(
                        "doc_request_item.bulk.too_large"
                )
                item = self._repo.insert_item(request_id=request_id, item_name=name)
                new_req_status = self._recompute_request_status(request_id)
                request_after = self._repo.update_request_status(
                    request_id, status=new_req_status
                )
                if request_after is None:
                    raise DocumentRequestValidationError(
                        "doc_request.not_found"
                    )
                self._audit.record(
                    action="doc_request_item.create",
                    target_type="document_request_item",
                    target_id=str(item.id),
                    detail={"request_id": request_id, "item_name": name},
                )
        except sqlite3.IntegrityError as exc:
            if "FOREIGN KEY" in str(exc).upper():
                raise DocumentRequestValidationError("doc_request.not_found") from exc
            raise
        return DocumentItemsMutationResult(
            requests_after=(request_after,),
            affected_items=(item,),
        )

    def add_items_bulk(
        self,
        request_id: int,
        raw_text: str,
        *,
        with_request: bool = False,
    ) -> list[DocumentRequestItemRow] | DocumentItemsMutationResult:
        result = self._add_items_bulk_result(request_id, raw_text)
        return result if with_request else list(result.affected_items)

    def _add_items_bulk_result(
        self, request_id: int, raw_text: str
    ) -> DocumentItemsMutationResult:
        """Validate the full batch, then insert it atomically."""
        names = validate_bulk_item_text(raw_text)
        try:
            with self._conn:
                if self._repo.get_request(request_id) is None:
                    raise DocumentRequestValidationError(
                        "doc_request.not_found"
                    )
                existing_count, existing_chars = self._repo.item_totals(
                    request_id
                )
                if existing_count + len(names) > MAX_ITEMS_PER_REQUEST:
                    raise DocumentRequestValidationError(
                        "doc_request_item.bulk.too_many"
                    )
                if (
                    existing_chars + sum(len(name) for name in names)
                    > MAX_ITEM_NAMES_TOTAL_LENGTH
                ):
                    raise DocumentRequestValidationError(
                        "doc_request_item.bulk.too_large"
                    )
                items = [
                    self._repo.insert_item(
                        request_id=request_id, item_name=name
                    )
                    for name in names
                ]
                new_req_status = self._recompute_request_status(request_id)
                request_after = self._repo.update_request_status(
                    request_id, status=new_req_status
                )
                if request_after is None:
                    raise DocumentRequestValidationError(
                        "doc_request.not_found"
                    )
                for item in items:
                    self._audit.record(
                        action="doc_request_item.create",
                        target_type="document_request_item",
                        target_id=str(item.id),
                        detail={
                            "request_id": request_id,
                            "item_name": item.item_name,
                        },
                    )
                return DocumentItemsMutationResult(
                    requests_after=(request_after,),
                    affected_items=tuple(items),
                )
        except sqlite3.IntegrityError as exc:
            if "FOREIGN KEY" in str(exc).upper():
                raise DocumentRequestValidationError(
                    "doc_request.not_found"
                ) from exc
            raise

    def update_item(
        self,
        item_id: int,
        item_name: str,
        notes: str | None = None,
        *,
        with_request: bool = False,
    ) -> DocumentRequestItemRow | DocumentItemsMutationResult:
        result = self._update_item_result(item_id, item_name, notes)
        return result if with_request else result.affected_items[0]

    def _update_item_result(
        self, item_id: int, item_name: str, notes: str | None = None
    ) -> DocumentItemsMutationResult:
        name = sanitize_user_text(item_name, max_length=200)
        if not name:
            raise DocumentRequestValidationError("doc_request_item.name.required")
        notes_clean = sanitize_user_text(notes, max_length=500) or None
        with self._conn:
            item = self._repo.update_item_name(item_id, item_name=name, notes=notes_clean)
            if item is None:
                raise DocumentRequestValidationError("doc_request_item.not_found")
            request_after = self._repo.get_request(item.request_id)
            if request_after is None:
                raise DocumentRequestValidationError(
                    "doc_request.not_found"
                )
            self._audit.record(
                action="doc_request_item.update",
                target_type="document_request_item",
                target_id=str(item_id),
                detail={"item_name": name},
            )
        return DocumentItemsMutationResult(
            requests_after=(request_after,),
            affected_items=(item,),
        )

    def delete_items_bulk(
        self,
        item_ids: list[int],
        *,
        with_request: bool = False,
    ) -> int | DocumentItemsMutationResult:
        result = self._delete_items_bulk_result(item_ids)
        return result if with_request else len(result.deleted_items)

    def _delete_items_bulk_result(
        self, item_ids: list[int]
    ) -> DocumentItemsMutationResult:
        """Delete multiple items by id; silently skip nonexistent ids.

        Recomputes the parent request status for each affected request once
        per request (not once per item) and records a single audit entry with
        the list of ids and final deleted count.
        """
        if not item_ids:
            return DocumentItemsMutationResult(requests_after=())
        affected_request_ids: set[int] = set()
        deleted_rows: list[DocumentRequestItemRow] = []
        requests_after: list[DocumentRequestRow] = []
        with self._conn:
            for item_id in item_ids:
                existing = self._repo.get_item(item_id)
                if existing is None:
                    continue
                self._repo.delete_item(item_id)
                affected_request_ids.add(existing.request_id)
                deleted_rows.append(existing)
            for req_id in sorted(affected_request_ids):
                new_status = self._recompute_request_status(req_id)
                request_after = self._repo.update_request_status(
                    req_id, status=new_status
                )
                if request_after is None:
                    raise DocumentRequestValidationError(
                        "doc_request.not_found"
                    )
                requests_after.append(request_after)
            if deleted_rows:
                deleted_ids = [row.id for row in deleted_rows]
                self._audit.record(
                    action="doc_request_item.bulk_delete",
                    target_type="document_request_item",
                    target_id=",".join(str(i) for i in deleted_ids),
                    detail={
                        "item_ids": deleted_ids,
                        "deleted_count": len(deleted_ids),
                    },
                )
        return DocumentItemsMutationResult(
            requests_after=tuple(requests_after),
            deleted_items=tuple(deleted_rows),
        )

    def delete_item(
        self, item_id: int, *, with_request: bool = False
    ) -> None | DocumentItemsMutationResult:
        result = self._delete_item_result(item_id)
        return result if with_request else None

    def _delete_item_result(
        self, item_id: int
    ) -> DocumentItemsMutationResult:
        existing = self._repo.get_item(item_id)
        if existing is None:
            raise DocumentRequestValidationError("doc_request_item.not_found")
        with self._conn:
            self._repo.delete_item(item_id)
            new_req_status = self._recompute_request_status(existing.request_id)
            request_after = self._repo.update_request_status(
                existing.request_id, status=new_req_status
            )
            if request_after is None:
                raise DocumentRequestValidationError(
                    "doc_request.not_found"
                )
            self._audit.record(
                action="doc_request_item.delete",
                target_type="document_request_item",
                target_id=str(item_id),
                detail={"item_name": existing.item_name, "request_id": existing.request_id},
            )
        return DocumentItemsMutationResult(
            requests_after=(request_after,),
            deleted_items=(existing,),
        )

    def set_item_status(
        self,
        item_id: int,
        *,
        item_status: str,
        notes: str | None = None,
        with_request: bool = False,
    ) -> DocumentRequestItemRow | DocumentItemsMutationResult:
        result = self._set_item_status_result(
            item_id, item_status=item_status, notes=notes
        )
        return result if with_request else result.affected_items[0]

    def _set_item_status_result(
        self,
        item_id: int,
        *,
        item_status: str,
        notes: str | None = None,
    ) -> DocumentItemsMutationResult:
        if item_status not in VALID_ITEM_STATUSES:
            raise DocumentRequestValidationError("doc_request_item.status.invalid")
        notes_clean = sanitize_user_text(notes, max_length=500) or None
        with self._conn:
            item = self._repo.update_item_status(item_id, item_status=item_status, notes=notes_clean)
            if item is None:
                raise DocumentRequestValidationError("doc_request_item.not_found")
            new_req_status = self._recompute_request_status(item.request_id)
            request_after = self._repo.update_request_status(
                item.request_id, status=new_req_status
            )
            if request_after is None:
                raise DocumentRequestValidationError(
                    "doc_request.not_found"
                )
            self._audit.record(
                action="doc_request_item.status_change",
                target_type="document_request_item",
                target_id=str(item_id),
                detail={"item_status": item_status, "request_status": new_req_status},
            )
        return DocumentItemsMutationResult(
            requests_after=(request_after,),
            affected_items=(item,),
        )

    def _recompute_request_status(self, request_id: int) -> str:
        items = self._repo.list_items(request_id)
        statuses = frozenset(i.item_status for i in items)
        return _derive_request_status(statuses)

    def get_request(self, request_id: int) -> DocumentRequestRow | None:
        return self._repo.get_request(request_id)

    def read_request_snapshot(
        self, request_id: int
    ) -> DocumentRequestSnapshot:
        request = self._repo.get_request(request_id)
        if request is None:
            raise DocumentRequestValidationError("doc_request.not_found")
        total = self._repo.item_totals(request_id)[0]
        if total > MAX_ITEMS_PER_REQUEST:
            raise DocumentRequestValidationError(
                "doc_request.items.too_many"
            )
        rows: list[DocumentRequestItemRow] = []
        for offset in range(0, total, 200):
            rows.extend(
                self._repo.list_items_page(
                    request_id, limit=200, offset=offset
                )
            )
        if len(rows) != total:
            raise RuntimeError("doc_request_item.readback.incomplete")
        return DocumentRequestSnapshot(request=request, items=tuple(rows))

    def get_item(
        self, item_id: int
    ) -> DocumentRequestItemRow | None:
        return self._repo.get_item(item_id)

    def list_all(
        self, *, limit: int = 200, offset: int = 0
    ) -> list[DocumentRequestRow]:
        self._validate_pagination(limit, offset)
        return self._repo.list_all(limit=limit, offset=offset)

    def count_all(self) -> int:
        return self._repo.count_all()

    def list_by_engagement(
        self,
        engagement_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[DocumentRequestRow]:
        self._validate_pagination(limit, offset)
        return self._repo.list_by_engagement(
            engagement_id, limit=limit, offset=offset
        )

    @staticmethod
    def _validate_pagination(limit: object, offset: object) -> None:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 500
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= 1_000_000
        ):
            raise DocumentRequestValidationError(
                "doc_request.pagination.invalid"
            )

    def count_by_engagement(self, engagement_id: int) -> int:
        return self._repo.count_by_engagement(engagement_id)

    def request_position(
        self, request_id: int, *, engagement_id: int | None
    ) -> int | None:
        return self._repo.request_position(
            request_id, engagement_id=engagement_id
        )

    def list_items(
        self,
        request_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[DocumentRequestItemRow]:
        self._validate_pagination(limit, offset)
        return self._repo.list_items_page(
            request_id, limit=limit, offset=offset
        )

    def count_items(self, request_id: int) -> int:
        return self._repo.item_totals(request_id)[0]

    def item_position(self, request_id: int, item_id: int) -> int | None:
        return self._repo.item_position(request_id, item_id)
