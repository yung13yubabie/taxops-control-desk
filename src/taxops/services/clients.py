"""Clients service: validation, persistence, and audit log."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from ..core.dates import date_range_is_valid, parse_optional_iso_date
from ..core.text import sanitize_user_text
from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.search import SearchRepository
from .audit import AuditService

_log = logging.getLogger(__name__)


class ClientValidationError(Exception):
    """Raised when client input fails business validation.

    The ``code`` attribute is a stable error code mapped to a Chinese label
    via :mod:`taxops.i18n.errors`.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateClientInput:
    client_code: str
    client_name: str
    tax_id: str | None = None
    short_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    address: str | None = None
    note: str | None = None
    lease_start: str | None = None
    lease_end: str | None = None
    registry_source_tax_id: str | None = None
    registry_cache_version: str | None = None


@dataclass(frozen=True)
class UpdateClientInput:
    client_code: str
    client_name: str
    tax_id: str | None = None
    short_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    address: str | None = None
    note: str | None = None
    lease_start: str | None = None
    lease_end: str | None = None


def _normalize_tax_id(value: str | None) -> str | None:
    """Trim Taiwan unified business number; allow blank, validate when present."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) != 8 or not cleaned.isdigit():
        raise ClientValidationError("client.tax_id.invalid")
    return cleaned


class ClientsService:
    def __init__(
        self,
        repo: ClientsRepository,
        audit: AuditService,
        search_repo: SearchRepository | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._search_repo = search_repo

    def _fts_add(self, row: ClientRow) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.add_client(
                row.id,
                client_code=row.client_code,
                client_name=row.client_name,
                tax_id=row.tax_id,
                short_name=row.short_name,
                contact_name=row.contact_name,
                note=row.note,
            )
        except Exception:
            _log.warning("client FTS add failed", exc_info=True)

    def _fts_update(self, row: ClientRow) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.update_client(
                row.id,
                client_code=row.client_code,
                client_name=row.client_name,
                tax_id=row.tax_id,
                short_name=row.short_name,
                contact_name=row.contact_name,
                note=row.note,
            )
        except Exception:
            _log.warning("client FTS update failed", exc_info=True)

    def _fts_delete(self, client_id: int) -> None:
        if self._search_repo is None:
            return
        try:
            self._search_repo.delete_client(client_id)
        except Exception:
            _log.warning("client FTS delete failed", exc_info=True)

    def create_client(self, payload: CreateClientInput) -> ClientRow:
        client_code = sanitize_user_text(payload.client_code, max_length=50)
        if not client_code:
            raise ClientValidationError("client.client_code.required")

        client_name = sanitize_user_text(payload.client_name, max_length=200)
        if not client_name:
            raise ClientValidationError("client.client_name.required")

        tax_id = _normalize_tax_id(payload.tax_id)
        short_name = sanitize_user_text(payload.short_name, max_length=100) or None
        contact_name = sanitize_user_text(payload.contact_name, max_length=100) or None
        contact_phone = sanitize_user_text(payload.contact_phone, max_length=50) or None
        contact_email = sanitize_user_text(payload.contact_email, max_length=200) or None
        address = sanitize_user_text(payload.address, max_length=500) or None
        note = sanitize_user_text(payload.note, max_length=2000) or None

        if self._repo.find_by_code(client_code) is not None:
            raise ClientValidationError("client.client_code.duplicate")

        lease_start = sanitize_user_text(payload.lease_start, max_length=10) or None
        lease_end = sanitize_user_text(payload.lease_end, max_length=10) or None
        try:
            ls = parse_optional_iso_date(lease_start)
            le = parse_optional_iso_date(lease_end)
        except ValueError:
            raise ClientValidationError("client.lease_date.invalid")
        if not date_range_is_valid(ls, le):
            raise ClientValidationError("client.lease_range.invalid")

        try:
            row = self._repo.insert(
                client_code=client_code,
                client_name=client_name,
                tax_id=tax_id,
                short_name=short_name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                address=address,
                note=note,
                lease_start=lease_start,
                lease_end=lease_end,
            )
        except sqlite3.IntegrityError as exc:
            # Backstop in case the pre-check raced with another writer.
            if "client_code" in str(exc) or "UNIQUE" in str(exc).upper():
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise

        audit_detail: dict = {
            "client_code": row.client_code,
            "client_name": row.client_name,
            "tax_id": row.tax_id,
        }
        if payload.registry_source_tax_id:
            audit_detail["registry_prefill_used"] = True
            audit_detail["source_tax_id"] = payload.registry_source_tax_id
            audit_detail["cache_version"] = payload.registry_cache_version or ""
            audit_detail["prefill_time_note"] = (
                "source_tax_id/cache_version recorded at fill time; "
                "user may have edited fields before saving"
            )
        self._audit.record(
            action="client.create",
            target_type="client",
            target_id=str(row.id),
            detail=audit_detail,
        )
        self._fts_add(row)
        return row

    def update_client(self, client_id: int, payload: UpdateClientInput) -> ClientRow:
        client_code = sanitize_user_text(payload.client_code, max_length=50)
        if not client_code:
            raise ClientValidationError("client.client_code.required")

        client_name = sanitize_user_text(payload.client_name, max_length=200)
        if not client_name:
            raise ClientValidationError("client.client_name.required")

        tax_id = _normalize_tax_id(payload.tax_id)
        short_name = sanitize_user_text(payload.short_name, max_length=100) or None
        contact_name = sanitize_user_text(payload.contact_name, max_length=100) or None
        contact_phone = sanitize_user_text(payload.contact_phone, max_length=50) or None
        contact_email = sanitize_user_text(payload.contact_email, max_length=200) or None
        address = sanitize_user_text(payload.address, max_length=500) or None
        note = sanitize_user_text(payload.note, max_length=2000) or None
        lease_start_u = sanitize_user_text(payload.lease_start, max_length=10) or None
        lease_end_u = sanitize_user_text(payload.lease_end, max_length=10) or None
        try:
            ls_u = parse_optional_iso_date(lease_start_u)
            le_u = parse_optional_iso_date(lease_end_u)
        except ValueError:
            raise ClientValidationError("client.lease_date.invalid")
        if not date_range_is_valid(ls_u, le_u):
            raise ClientValidationError("client.lease_range.invalid")

        existing = self._repo.find_by_code(client_code)
        if existing is not None and existing.id != client_id:
            raise ClientValidationError("client.client_code.duplicate")

        try:
            row = self._repo.update(
                client_id,
                client_code=client_code,
                client_name=client_name,
                tax_id=tax_id,
                short_name=short_name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                address=address,
                note=note,
                lease_start=lease_start_u,
                lease_end=lease_end_u,
            )
        except sqlite3.IntegrityError as exc:
            if "client_code" in str(exc) or "UNIQUE" in str(exc).upper():
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise

        if row is None:
            raise ClientValidationError("client.not_found")

        self._audit.record(
            action="client.update",
            target_type="client",
            target_id=str(client_id),
            detail={
                "client_code": row.client_code,
                "client_name": row.client_name,
                "tax_id": row.tax_id,
            },
        )
        self._fts_update(row)
        return row

    def delete_client(self, client_id: int) -> None:
        existing = self._repo.get(client_id)
        if existing is None:
            raise ClientValidationError("client.not_found")
        self._repo.delete(client_id)
        self._fts_delete(client_id)
        self._audit.record(
            action="client.delete",
            target_type="client",
            target_id=str(client_id),
            detail={
                "client_code": existing.client_code,
                "client_name": existing.client_name,
            },
        )

    def restore_client(self, client_id: int) -> None:
        """Undo a soft-delete. Raises client.not_found if id is unknown or already active."""
        restored = self._repo.restore(client_id)
        if not restored:
            raise ClientValidationError("client.not_found")
        row = self._repo.get(client_id)
        if row is not None:
            self._fts_add(row)
        self._audit.record(
            action="client.restore",
            target_type="client",
            target_id=str(client_id),
            detail={
                "client_code": row.client_code if row else "",
                "client_name": row.client_name if row else "",
            },
        )

    def purge_client(self, client_id: int) -> None:
        """Permanently delete a soft-deleted client with no engagement refs."""
        existing = self._repo.get_any(client_id)
        if existing is None:
            raise ClientValidationError("client.not_found")
        if existing.deleted_at is None:
            raise ClientValidationError("client.purge.requires_deleted")
        if self._repo.count_engagement_refs(client_id) > 0:
            raise ClientValidationError("client.purge.has_engagements")

        purged = self._repo.purge(client_id)
        if not purged:
            raise ClientValidationError("client.not_found")
        self._fts_delete(client_id)
        self._audit.record(
            action="client.purge",
            target_type="client",
            target_id=str(client_id),
            detail={
                "client_code": existing.client_code,
                "client_name": existing.client_name,
                "deleted_at": existing.deleted_at,
            },
        )

    def list_clients(self, *, limit: int = 500, offset: int = 0) -> list[ClientRow]:
        return self._repo.list_clients(limit=limit, offset=offset)

    def search_clients(
        self,
        query: str = "",
        *,
        order_by: str = "client_code",
        order_dir: str = "ASC",
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[ClientRow]:
        return self._repo.search_clients(
            query,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
        )

    def count_clients(self, query: str = "", *, include_deleted: bool = False) -> int:
        return self._repo.count_clients(query, include_deleted=include_deleted)

    def get_client(self, client_id: int) -> ClientRow | None:
        return self._repo.get(client_id)

    def find_by_code(self, client_code: str) -> ClientRow | None:
        return self._repo.find_by_code(client_code)

    def count(self) -> int:
        return self._repo.count()

    def list_lease_expiring_soon(self, today: str, until: str) -> list[ClientRow]:
        return self._repo.list_lease_expiring_soon(today, until)
