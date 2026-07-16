"""Validation, audit, and transactions for client leases."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.dates import date_range_is_valid, parse_optional_iso_date
from ..core.text import sanitize_user_text
from ..repositories.client_leases import ClientLeaseRow, ClientLeasesRepository
from .audit import AuditService


class ClientLeaseValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LeaseInput:
    lease_name: str
    premises_address: str | None = None
    landlord_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    monthly_rent: int | None = None
    deposit_amount: int | None = None
    reminder_days: int = 60
    notes: str | None = None
    status: str = "active"


_VALID_STATUSES = frozenset({"active", "expired", "terminated"})


class ClientLeasesService:
    def __init__(self, repo: ClientLeasesRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit
        self._conn = repo._conn

    def _validated(self, payload: LeaseInput) -> dict[str, object]:
        lease_name = sanitize_user_text(payload.lease_name, max_length=200)
        if not lease_name:
            raise ClientLeaseValidationError("client_lease.name.required")
        premises_address = sanitize_user_text(payload.premises_address, max_length=500) or None
        landlord_name = sanitize_user_text(payload.landlord_name, max_length=200) or None
        notes = sanitize_user_text(payload.notes, max_length=2000) or None
        start_date = sanitize_user_text(payload.start_date, max_length=10) or None
        end_date = sanitize_user_text(payload.end_date, max_length=10) or None
        try:
            start = parse_optional_iso_date(start_date)
            end = parse_optional_iso_date(end_date)
        except ValueError as exc:
            raise ClientLeaseValidationError("client_lease.date.invalid") from exc
        if not date_range_is_valid(start, end):
            raise ClientLeaseValidationError("client_lease.date_range.invalid")
        for amount in (payload.monthly_rent, payload.deposit_amount):
            if amount is not None and (not isinstance(amount, int) or isinstance(amount, bool) or amount < 0):
                raise ClientLeaseValidationError("client_lease.amount.invalid")
        if (
            not isinstance(payload.reminder_days, int)
            or isinstance(payload.reminder_days, bool)
            or not 0 <= payload.reminder_days <= 3650
        ):
            raise ClientLeaseValidationError("client_lease.reminder_days.invalid")
        status = sanitize_user_text(payload.status, max_length=20).lower()
        if status not in _VALID_STATUSES:
            raise ClientLeaseValidationError("client_lease.status.invalid")
        return {
            "lease_name": lease_name,
            "premises_address": premises_address,
            "landlord_name": landlord_name,
            "start_date": start_date,
            "end_date": end_date,
            "monthly_rent": payload.monthly_rent,
            "deposit_amount": payload.deposit_amount,
            "reminder_days": payload.reminder_days,
            "status": status,
            "notes": notes,
        }

    def _require_active_client(self, client_id: int) -> None:
        if not self._repo.active_client_exists(client_id):
            raise ClientLeaseValidationError("client_lease.client_not_found")

    def create_lease(self, client_id: int, payload: LeaseInput) -> ClientLeaseRow:
        self._require_active_client(client_id)
        values = self._validated(payload)
        with self._conn:
            row = self._repo.insert(client_id, **values)
            self._audit.record(
                action="client.lease.create",
                target_type="client_lease",
                target_id=str(row.id),
                detail={"client_id": client_id, "status": row.status},
            )
        return row

    def create(self, client_id: int, payload: LeaseInput) -> ClientLeaseRow:
        return self.create_lease(client_id, payload)

    def update_lease(self, lease_id: int, payload: LeaseInput) -> ClientLeaseRow:
        existing = self._repo.get(lease_id)
        if existing is None:
            raise ClientLeaseValidationError("client_lease.not_found")
        self._require_active_client(existing.client_id)
        values = self._validated(payload)
        with self._conn:
            row = self._repo.update(lease_id, **values)
            if row is None:
                raise ClientLeaseValidationError("client_lease.not_found")
            self._audit.record(
                action="client.lease.update",
                target_type="client_lease",
                target_id=str(lease_id),
                detail={"client_id": row.client_id, "status": row.status},
            )
        return row

    def update(self, lease_id: int, payload: LeaseInput) -> ClientLeaseRow:
        return self.update_lease(lease_id, payload)

    def archive_lease(self, lease_id: int) -> ClientLeaseRow:
        existing = self._repo.get(lease_id)
        if existing is None:
            raise ClientLeaseValidationError("client_lease.not_found")
        self._require_active_client(existing.client_id)
        with self._conn:
            row = self._repo.archive(lease_id)
            if row is None:
                raise ClientLeaseValidationError("client_lease.not_found")
            self._audit.record(
                action="client.lease.archive",
                target_type="client_lease",
                target_id=str(lease_id),
                detail={"client_id": row.client_id},
            )
        return row

    def archive(self, lease_id: int) -> ClientLeaseRow:
        return self.archive_lease(lease_id)

    def delete_lease(self, lease_id: int) -> ClientLeaseRow:
        """Compatibility name for the soft-delete operation."""
        return self.archive_lease(lease_id)

    def get_lease(self, lease_id: int, *, include_deleted: bool = False) -> ClientLeaseRow | None:
        return self._repo.get(lease_id, include_deleted=include_deleted)

    def get(self, lease_id: int, *, include_deleted: bool = False) -> ClientLeaseRow | None:
        return self.get_lease(lease_id, include_deleted=include_deleted)

    def list_for_client(
        self, client_id: int, *, include_deleted: bool = False
    ) -> list[ClientLeaseRow]:
        return self._repo.list_for_client(client_id, include_deleted=include_deleted)
