"""Clients service: validation, persistence, and audit log."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.dates import date_range_is_valid, parse_optional_iso_date
from ..core.text import sanitize_user_text
from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.search import SearchRepository
from .audit import AuditService


class _AddressUnset:
    pass


_ADDRESS_UNSET = _AddressUnset()
AddressInput = str | None | _AddressUnset

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
    # ``address`` is accepted only as a v0.30 compatibility input.
    address: AddressInput = _ADDRESS_UNSET
    registered_address: AddressInput = _ADDRESS_UNSET
    contact_address: AddressInput = _ADDRESS_UNSET
    contact_address_same: bool | _AddressUnset = _ADDRESS_UNSET
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
    # ``address`` is accepted only as a v0.30 compatibility input.
    address: AddressInput = _ADDRESS_UNSET
    registered_address: AddressInput = _ADDRESS_UNSET
    contact_address: AddressInput = _ADDRESS_UNSET
    contact_address_same: bool | _AddressUnset = _ADDRESS_UNSET
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


def _normalize_address(value: str | None) -> str | None:
    # Avoid sanitize_user_text's normal resource-limit truncation: an address
    # over the domain limit is invalid and must never be silently shortened.
    cleaned = sanitize_user_text(value, max_length=max(501, len(value or "") + 1))
    if len(cleaned) > 500:
        raise ClientValidationError("client.address.too_long")
    return cleaned or None


def _resolve_registered_address(
    *,
    legacy: AddressInput,
    canonical: AddressInput,
    existing: str | None = None,
) -> str | None:
    legacy_provided = legacy is not _ADDRESS_UNSET
    canonical_provided = canonical is not _ADDRESS_UNSET
    legacy_clean = _normalize_address(legacy) if legacy_provided else None  # type: ignore[arg-type]
    canonical_clean = (
        _normalize_address(canonical) if canonical_provided else None  # type: ignore[arg-type]
    )
    if (
        legacy_provided
        and canonical_provided
        and legacy_clean
        and canonical_clean
        and legacy_clean != canonical_clean
    ):
        raise ClientValidationError("client.address.conflict")
    if canonical_provided:
        return canonical_clean
    if legacy_provided:
        return legacy_clean
    return existing


def _resolve_address_state(
    payload: CreateClientInput | UpdateClientInput,
    existing: ClientRow | None = None,
) -> tuple[str | None, str | None, bool]:
    registered = _resolve_registered_address(
        legacy=payload.address,
        canonical=payload.registered_address,
        existing=existing.registered_address if existing is not None else None,
    )
    contact_input = payload.contact_address
    contact_provided = contact_input is not _ADDRESS_UNSET
    contact = (
        _normalize_address(contact_input) if contact_provided else None  # type: ignore[arg-type]
    )
    same_input = payload.contact_address_same
    if same_input is _ADDRESS_UNSET:
        same = (
            False
            if contact_provided
            else (existing.contact_address_same if existing is not None else True)
        )
    elif not isinstance(same_input, bool):
        raise ClientValidationError("client.contact_address_same.invalid")
    else:
        same = same_input

    if same:
        contact = registered
    elif not contact_provided and existing is not None:
        contact = existing.contact_address
    return registered, contact, same


def prepare_client_create(
    payload: CreateClientInput,
    repo: ClientsRepository,
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate a create payload without opening or committing a transaction."""
    client_code = sanitize_user_text(payload.client_code, max_length=50)
    if not client_code:
        raise ClientValidationError("client.client_code.required")

    client_name = sanitize_user_text(payload.client_name, max_length=200)
    if not client_name:
        raise ClientValidationError("client.client_name.required")

    tax_id = _normalize_tax_id(payload.tax_id)
    registered_address, contact_address, contact_address_same = (
        _resolve_address_state(payload)
    )
    if repo.find_by_code(client_code) is not None:
        raise ClientValidationError("client.client_code.duplicate")

    lease_start = sanitize_user_text(payload.lease_start, max_length=10) or None
    lease_end = sanitize_user_text(payload.lease_end, max_length=10) or None
    try:
        parsed_start = parse_optional_iso_date(lease_start)
        parsed_end = parse_optional_iso_date(lease_end)
    except ValueError as exc:
        raise ClientValidationError("client.lease_date.invalid") from exc
    if not date_range_is_valid(parsed_start, parsed_end):
        raise ClientValidationError("client.lease_range.invalid")

    values: dict[str, object] = {
        "client_code": client_code,
        "client_name": client_name,
        "tax_id": tax_id,
        "short_name": sanitize_user_text(payload.short_name, max_length=100) or None,
        "contact_name": sanitize_user_text(payload.contact_name, max_length=100) or None,
        "contact_phone": sanitize_user_text(payload.contact_phone, max_length=50) or None,
        "contact_email": sanitize_user_text(payload.contact_email, max_length=200) or None,
        "registered_address": registered_address,
        "contact_address": contact_address,
        "contact_address_same": contact_address_same,
        "note": sanitize_user_text(payload.note, max_length=2000) or None,
        "lease_start": lease_start,
        "lease_end": lease_end,
    }
    audit_detail: dict[str, object] = {
        "client_code": client_code,
        "client_name": client_name,
        "tax_id": tax_id,
    }
    if payload.registry_source_tax_id:
        audit_detail.update(
            {
                "registry_prefill_used": True,
                "source_tax_id": payload.registry_source_tax_id,
                "cache_version": payload.registry_cache_version or "",
                "prefill_time_note": (
                    "source_tax_id/cache_version recorded at fill time; "
                    "user may have edited fields before saving"
                ),
            }
        )
    return values, audit_detail


def prepare_client_update(
    client_id: int,
    payload: UpdateClientInput,
    repo: ClientsRepository,
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate an update payload without opening or committing a transaction."""
    current = repo.get(client_id)
    if current is None:
        raise ClientValidationError("client.not_found")

    client_code = sanitize_user_text(payload.client_code, max_length=50)
    if not client_code:
        raise ClientValidationError("client.client_code.required")
    client_name = sanitize_user_text(payload.client_name, max_length=200)
    if not client_name:
        raise ClientValidationError("client.client_name.required")
    tax_id = _normalize_tax_id(payload.tax_id)
    registered_address, contact_address, contact_address_same = (
        _resolve_address_state(payload, current)
    )
    lease_start = sanitize_user_text(payload.lease_start, max_length=10) or None
    lease_end = sanitize_user_text(payload.lease_end, max_length=10) or None
    try:
        parsed_start = parse_optional_iso_date(lease_start)
        parsed_end = parse_optional_iso_date(lease_end)
    except ValueError as exc:
        raise ClientValidationError("client.lease_date.invalid") from exc
    if not date_range_is_valid(parsed_start, parsed_end):
        raise ClientValidationError("client.lease_range.invalid")

    existing = repo.find_by_code(client_code)
    if existing is not None and existing.id != client_id:
        raise ClientValidationError("client.client_code.duplicate")

    values: dict[str, object] = {
        "client_code": client_code,
        "client_name": client_name,
        "tax_id": tax_id,
        "short_name": sanitize_user_text(payload.short_name, max_length=100) or None,
        "contact_name": sanitize_user_text(payload.contact_name, max_length=100) or None,
        "contact_phone": sanitize_user_text(payload.contact_phone, max_length=50) or None,
        "contact_email": sanitize_user_text(payload.contact_email, max_length=200) or None,
        "registered_address": registered_address,
        "contact_address": contact_address,
        "contact_address_same": contact_address_same,
        "note": sanitize_user_text(payload.note, max_length=2000) or None,
        "lease_start": lease_start,
        "lease_end": lease_end,
    }
    return values, {
        "client_code": client_code,
        "client_name": client_name,
        "tax_id": tax_id,
    }


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
        self._conn = repo._conn

    def _fts_add(self, row: ClientRow) -> None:
        if self._search_repo is None:
            return
        self._search_repo.add_client(
            row.id,
            client_code=row.client_code,
            client_name=row.client_name,
            tax_id=row.tax_id,
            short_name=row.short_name,
            contact_name=row.contact_name,
            note=row.note,
        )

    def _fts_update(self, row: ClientRow) -> None:
        if self._search_repo is None:
            return
        self._search_repo.update_client(
            row.id,
            client_code=row.client_code,
            client_name=row.client_name,
            tax_id=row.tax_id,
            short_name=row.short_name,
            contact_name=row.contact_name,
            note=row.note,
        )

    def _fts_delete(self, client_id: int) -> None:
        if self._search_repo is None:
            return
        self._search_repo.delete_client(client_id)

    def create_client(self, payload: CreateClientInput) -> ClientRow:
        values, audit_detail = prepare_client_create(payload, self._repo)
        try:
            with self._conn:
                row = self._repo.insert(**values)
                self._audit.record(
                    action="client.create",
                    target_type="client",
                    target_id=str(row.id),
                    detail=audit_detail,
                )
                self._fts_add(row)
        except sqlite3.IntegrityError as exc:
            if "clients.client_code" in str(exc):
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise
        return row

    def update_client(self, client_id: int, payload: UpdateClientInput) -> ClientRow:
        values, audit_detail = prepare_client_update(client_id, payload, self._repo)

        try:
            with self._conn:
                row = self._repo.update(client_id, **values)
                if row is None:
                    raise ClientValidationError("client.not_found")
                self._audit.record(
                    action="client.update",
                    target_type="client",
                    target_id=str(client_id),
                    detail=audit_detail,
                )
                self._fts_update(row)
        except sqlite3.IntegrityError as exc:
            if "clients.client_code" in str(exc):
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise
        return row

    def update_registered_address(
        self, client_id: int, new_address: str | None
    ) -> ClientRow:
        existing = self._repo.get(client_id)
        if existing is None:
            raise ClientValidationError("client.not_found")
        registered_address = _normalize_address(new_address)
        contact_address = (
            registered_address
            if existing.contact_address_same
            else existing.contact_address
        )
        with self._conn:
            row = self._repo.update_registered_address(
                client_id,
                registered_address=registered_address,
                contact_address=contact_address,
            )
            if row is None:
                raise ClientValidationError("client.not_found")
            self._audit.record(
                action="client.registered_address.update",
                target_type="client",
                target_id=str(client_id),
                detail={"client_code": row.client_code},
            )
        return row

    def delete_client(self, client_id: int) -> None:
        existing = self._repo.get(client_id)
        if existing is None:
            raise ClientValidationError("client.not_found")
        with self._conn:
            self._repo.delete(client_id)
            self._audit.record(
                action="client.delete",
                target_type="client",
                target_id=str(client_id),
                detail={
                    "client_code": existing.client_code,
                    "client_name": existing.client_name,
                },
            )
            self._fts_delete(client_id)

    def restore_client(self, client_id: int) -> None:
        """Undo a soft-delete. Raises client.not_found if id is unknown or already active."""
        with self._conn:
            restored = self._repo.restore(client_id)
            if not restored:
                raise ClientValidationError("client.not_found")
            row = self._repo.get(client_id)
            self._audit.record(
                action="client.restore",
                target_type="client",
                target_id=str(client_id),
                detail={
                    "client_code": row.client_code if row else "",
                    "client_name": row.client_name if row else "",
                },
            )
            if row is not None:
                self._fts_add(row)

    def purge_client(self, client_id: int) -> None:
        """Permanently delete a soft-deleted client with no engagement refs."""
        existing = self._repo.get_any(client_id)
        if existing is None:
            raise ClientValidationError("client.not_found")
        if existing.deleted_at is None:
            raise ClientValidationError("client.purge.requires_deleted")
        if self._repo.count_engagement_refs(client_id) > 0:
            raise ClientValidationError("client.purge.has_engagements")
        if self._repo.count_purge_blocking_refs(client_id) > 0:
            raise ClientValidationError("client.purge.has_references")

        with self._conn:
            purged = self._repo.purge(client_id)
            if not purged:
                raise ClientValidationError("client.not_found")
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
            self._fts_delete(client_id)

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
        has_note: bool = False,
    ) -> list[ClientRow]:
        return self._repo.search_clients(
            query,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
            has_note=has_note,
        )

    def count_clients(
        self,
        query: str = "",
        *,
        include_deleted: bool = False,
        has_note: bool = False,
    ) -> int:
        return self._repo.count_clients(
            query,
            include_deleted=include_deleted,
            has_note=has_note,
        )

    def get_client(self, client_id: int) -> ClientRow | None:
        return self._repo.get(client_id)

    def find_by_code(self, client_code: str) -> ClientRow | None:
        return self._repo.find_by_code(client_code)

    def count(self) -> int:
        return self._repo.count()

    def list_lease_expiring_soon(self, today: str, until: str) -> list[ClientRow]:
        return self._repo.list_lease_expiring_soon(today, until)
