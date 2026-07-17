"""Atomic client-profile persistence across clients, FTS, audit, and leases."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal

from ..repositories.client_leases import ClientLeaseRow, ClientLeasesRepository
from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.search import SearchRepository
from .audit import AuditService
from .client_leases import LeaseInput, validate_lease_input
from .clients import (
    ClientValidationError,
    CreateClientInput,
    UpdateClientInput,
    prepare_client_create,
    prepare_client_update,
)


@dataclass(frozen=True)
class ClientProfileSaveResult:
    client: ClientRow
    leases: tuple[ClientLeaseRow, ...]


@dataclass(frozen=True)
class LeaseChange:
    operation: Literal["create", "update", "archive"]
    lease_id: int | None = None
    payload: LeaseInput | None = None


class ClientProfileValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_busy_error(exc: sqlite3.OperationalError) -> bool:
    return getattr(exc, "sqlite_errorcode", None) in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    } or "locked" in str(exc).lower()


def _require_typed_sequence(
    value: object,
    element_type: type[object],
    code: str,
) -> None:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or any(not isinstance(item, element_type) for item in value)
    ):
        raise ClientProfileValidationError(code)


@contextmanager
def _immediate_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        raise ClientProfileValidationError(
            "client_profile.transaction.already_active"
        )
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            conn.rollback()
        if _is_busy_error(exc):
            raise ClientProfileValidationError(
                "client_profile.transaction.busy"
            ) from exc
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


class ClientProfilesService:
    """Coordinates profile mutations under one explicit SQLite transaction."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clients_repo: ClientsRepository,
        leases_repo: ClientLeasesRepository,
        audit: AuditService,
        search_repo: SearchRepository,
    ) -> None:
        connections = {
            "clients_repo": clients_repo.connection,
            "leases_repo": leases_repo.connection,
            "audit_repo": audit.connection,
            "search_repo": search_repo.connection,
        }
        mismatched = [
            name
            for name, repository_conn in connections.items()
            if repository_conn is not conn
        ]
        if mismatched:
            raise ValueError(
                "client_profile.connection.mismatch: " + ", ".join(mismatched)
            )
        self._conn = conn
        self._clients_repo = clients_repo
        self._leases_repo = leases_repo
        self._audit = audit
        self._search_repo = search_repo

    def create_client_with_leases(
        self,
        client_payload: CreateClientInput,
        lease_inputs: Sequence[LeaseInput],
    ) -> ClientProfileSaveResult:
        _require_typed_sequence(
            lease_inputs, LeaseInput, "client_profile.lease_inputs.invalid"
        )
        try:
            with _immediate_transaction(self._conn):
                client_values, client_audit = prepare_client_create(
                    client_payload, self._clients_repo
                )
                lease_values = [
                    validate_lease_input(payload) for payload in lease_inputs
                ]
                client = self._clients_repo.insert(**client_values)
                self._search_repo.add_client(
                    client.id,
                    client_code=client.client_code,
                    client_name=client.client_name,
                    tax_id=client.tax_id,
                    short_name=client.short_name,
                    contact_name=client.contact_name,
                    note=client.note,
                )
                self._audit.record(
                    action="client.create",
                    target_type="client",
                    target_id=str(client.id),
                    detail=client_audit,
                )
                leases: list[ClientLeaseRow] = []
                for values in lease_values:
                    lease = self._leases_repo.insert(client.id, **values)
                    self._audit.record(
                        action="client.lease.create",
                        target_type="client_lease",
                        target_id=str(lease.id),
                        detail={"client_id": client.id, "status": lease.status},
                    )
                    leases.append(lease)
        except sqlite3.IntegrityError as exc:
            if "clients.client_code" in str(exc):
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise
        return ClientProfileSaveResult(client=client, leases=tuple(leases))

    def update_client_with_lease_changes(
        self,
        client_id: int,
        client_payload: UpdateClientInput,
        lease_changes: Sequence[LeaseChange],
    ) -> ClientProfileSaveResult:
        _require_typed_sequence(
            lease_changes, LeaseChange, "client_profile.lease_changes.invalid"
        )
        try:
            with _immediate_transaction(self._conn):
                client_values, client_audit = prepare_client_update(
                    client_id, client_payload, self._clients_repo
                )
                prepared_changes = self._prepare_lease_changes(
                    client_id, lease_changes
                )
                client = self._clients_repo.update(client_id, **client_values)
                if client is None:
                    raise ClientValidationError("client.not_found")
                self._search_repo.update_client(
                    client.id,
                    client_code=client.client_code,
                    client_name=client.client_name,
                    tax_id=client.tax_id,
                    short_name=client.short_name,
                    contact_name=client.contact_name,
                    note=client.note,
                )
                self._audit.record(
                    action="client.update",
                    target_type="client",
                    target_id=str(client.id),
                    detail=client_audit,
                )
                for change, values in prepared_changes:
                    if change.operation == "create":
                        lease = self._leases_repo.insert(client_id, **values)
                    elif change.operation == "update":
                        lease = self._leases_repo.update_for_client(
                            change.lease_id, client_id, **values
                        )
                        if lease is None:
                            raise ClientProfileValidationError(
                                "client_profile.lease_change.not_found"
                            )
                    else:
                        lease = self._leases_repo.archive_for_client(
                            change.lease_id, client_id
                        )
                        if lease is None:
                            raise ClientProfileValidationError(
                                "client_profile.lease_change.not_found"
                            )
                    self._audit_lease_change(change.operation, client_id, lease)
                leases = tuple(self._leases_repo.list_for_client(client_id))
        except sqlite3.IntegrityError as exc:
            if "clients.client_code" in str(exc):
                raise ClientValidationError("client.client_code.duplicate") from exc
            raise
        return ClientProfileSaveResult(client=client, leases=leases)

    def _prepare_lease_changes(
        self,
        client_id: int,
        lease_changes: Sequence[LeaseChange],
    ) -> list[tuple[LeaseChange, dict[str, object]]]:
        seen_ids: set[int] = set()
        prepared: list[tuple[LeaseChange, dict[str, object]]] = []
        for change in lease_changes:
            if change.operation not in {"create", "update", "archive"}:
                raise ClientProfileValidationError(
                    "client_profile.lease_change.operation.invalid"
                )
            if change.operation == "create":
                if change.lease_id is not None or change.payload is None:
                    raise ClientProfileValidationError(
                        "client_profile.lease_change.invalid"
                    )
                prepared.append((change, validate_lease_input(change.payload)))
                continue

            if (
                not isinstance(change.lease_id, int)
                or isinstance(change.lease_id, bool)
                or change.lease_id <= 0
                or (change.operation == "update" and change.payload is None)
                or (change.operation == "archive" and change.payload is not None)
            ):
                raise ClientProfileValidationError(
                    "client_profile.lease_change.invalid"
                )
            if change.lease_id in seen_ids:
                raise ClientProfileValidationError(
                    "client_profile.lease_change.duplicate_id"
                )
            seen_ids.add(change.lease_id)
            existing = self._leases_repo.get(change.lease_id, include_deleted=True)
            if existing is None:
                raise ClientProfileValidationError(
                    "client_profile.lease_change.not_found"
                )
            if existing.client_id != client_id:
                raise ClientProfileValidationError(
                    "client_profile.lease_change.foreign_client"
                )
            if existing.deleted_at is not None:
                raise ClientProfileValidationError(
                    "client_profile.lease_change.not_found"
                )
            values = (
                validate_lease_input(change.payload)
                if change.operation == "update" and change.payload is not None
                else {}
            )
            prepared.append((change, values))
        return prepared

    def _audit_lease_change(
        self, operation: str, client_id: int, lease: ClientLeaseRow
    ) -> None:
        detail: dict[str, object] = {"client_id": client_id}
        if operation != "archive":
            detail["status"] = lease.status
        self._audit.record(
            action=f"client.lease.{operation}",
            target_type="client_lease",
            target_id=str(lease.id),
            detail=detail,
        )
