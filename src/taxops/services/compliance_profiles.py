"""Validated, atomic persistence for client compliance profiles."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from ..core.text import sanitize_user_text
from ..repositories.compliance_profiles import (
    ComplianceProfileItemRow,
    ComplianceProfileRow,
    ComplianceProfilesRepository,
)
from .audit import AuditService
from .compliance_rules import (
    ComplianceRuleError,
    validate_work_frequency,
    work_type_sort_key,
)


class ComplianceProfileValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ComplianceProfileItemInput:
    work_type: str
    frequency: str
    enabled: bool = True
    notes: str | None = None


@dataclass(frozen=True)
class ComplianceProfileSaveResult:
    profile: ComplianceProfileRow
    items: tuple[ComplianceProfileItemRow, ...]


@dataclass(frozen=True)
class _PreparedItem:
    work_type: str
    frequency: str
    enabled: bool
    notes: str | None


def _is_busy_error(exc: sqlite3.OperationalError) -> bool:
    return getattr(exc, "sqlite_errorcode", None) in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    } or "locked" in str(exc).lower()


@contextmanager
def _immediate_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        raise ComplianceProfileValidationError(
            "compliance_profile.transaction.already_active"
        )
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            conn.rollback()
        if _is_busy_error(exc):
            raise ComplianceProfileValidationError(
                "compliance_profile.transaction.busy"
            ) from exc
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _validate_client_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ComplianceProfileValidationError(
            "compliance_profile.client_id.invalid"
        )
    return value


def _validate_fiscal_month(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 12
    ):
        raise ComplianceProfileValidationError(
            "compliance_profile.fiscal_start_month.invalid"
        )
    return value


def _prepare_items(value: object) -> tuple[_PreparedItem, ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or any(not isinstance(item, ComplianceProfileItemInput) for item in value)
    ):
        raise ComplianceProfileValidationError("compliance_profile.items.invalid")

    prepared: list[_PreparedItem] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item.work_type, str):
            raise ComplianceProfileValidationError(
                "compliance_profile.work_type.invalid"
            )
        if not isinstance(item.frequency, str):
            raise ComplianceProfileValidationError(
                "compliance_profile.frequency.invalid"
            )
        try:
            work_type, frequency = validate_work_frequency(
                item.work_type, item.frequency
            )
        except ComplianceRuleError as exc:
            suffix = exc.code.removeprefix("compliance_rules.")
            raise ComplianceProfileValidationError(
                f"compliance_profile.{suffix}"
            ) from exc
        if work_type in seen:
            raise ComplianceProfileValidationError(
                "compliance_profile.work_type.duplicate"
            )
        seen.add(work_type)
        if not isinstance(item.enabled, bool):
            raise ComplianceProfileValidationError(
                "compliance_profile.enabled.invalid"
            )
        if item.notes is not None and not isinstance(item.notes, str):
            raise ComplianceProfileValidationError(
                "compliance_profile.notes.invalid"
            )
        notes = sanitize_user_text(item.notes, max_length=2001)
        if len(notes) > 2000:
            raise ComplianceProfileValidationError(
                "compliance_profile.notes.too_long"
            )
        prepared.append(
            _PreparedItem(
                work_type=work_type,
                frequency=frequency,
                enabled=item.enabled,
                notes=notes or None,
            )
        )
    prepared.sort(key=lambda item: work_type_sort_key(item.work_type))
    return tuple(prepared)


class ComplianceProfilesService:
    """Partial-upsert profile rows without deleting omitted or disabled rows."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repository: ComplianceProfilesRepository,
        audit: AuditService,
    ) -> None:
        mismatched = [
            name
            for name, candidate in (
                ("repository", repository.connection),
                ("audit", audit.connection),
            )
            if candidate is not conn
        ]
        if mismatched:
            raise ValueError(
                "compliance_profile.connection.mismatch: " + ", ".join(mismatched)
            )
        self._conn = conn
        self._repo = repository
        self._audit = audit

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def repository(self) -> ComplianceProfilesRepository:
        return self._repo

    def get_for_client(self, client_id: int) -> ComplianceProfileSaveResult | None:
        client_id = _validate_client_id(client_id)
        profile = self._repo.get_for_client(client_id)
        if profile is None:
            return None
        return ComplianceProfileSaveResult(
            profile=profile,
            items=tuple(self._repo.list_items(profile.id)),
        )

    def upsert_profile(
        self,
        client_id: int,
        fiscal_year_start_month: int,
        items: Sequence[ComplianceProfileItemInput],
    ) -> ComplianceProfileSaveResult:
        client_id = _validate_client_id(client_id)
        fiscal_month = _validate_fiscal_month(fiscal_year_start_month)
        prepared_items = _prepare_items(items)

        with _immediate_transaction(self._conn):
            if not self._repo.active_client_exists(client_id):
                raise ComplianceProfileValidationError(
                    "compliance_profile.client_not_found"
                )
            existing_profile = self._repo.get_for_client(client_id)
            existing_items = {
                row.work_type: row
                for row in (
                    self._repo.list_items(existing_profile.id)
                    if existing_profile is not None
                    else ()
                )
            }
            profile_changed = (
                existing_profile is None
                or existing_profile.fiscal_year_start_month != fiscal_month
            )
            changed_items = [
                item
                for item in prepared_items
                if not self._same_item(existing_items.get(item.work_type), item)
            ]

            if not profile_changed and not changed_items:
                assert existing_profile is not None
                return ComplianceProfileSaveResult(
                    profile=existing_profile,
                    items=tuple(self._repo.list_items(existing_profile.id)),
                )

            profile = self._repo.upsert_profile(client_id, fiscal_month)
            for item in changed_items:
                self._repo.upsert_item(
                    profile.id,
                    item.work_type,
                    item.frequency,
                    item.enabled,
                    item.notes,
                )
            rows = tuple(self._repo.list_items(profile.id))
            self._audit.record(
                action="compliance_profile.update",
                target_type="compliance_profile",
                target_id=str(profile.id),
                detail={
                    "client_id": client_id,
                    "fiscal_year_start_month": fiscal_month,
                    # These describe this partial-upsert payload, not private notes.
                    "item_count": len(prepared_items),
                    "items": [
                        {
                            "work_type": item.work_type,
                            "frequency": item.frequency,
                            "enabled": item.enabled,
                        }
                        for item in prepared_items
                    ],
                },
            )
        return ComplianceProfileSaveResult(profile=profile, items=rows)

    @staticmethod
    def _same_item(
        existing: ComplianceProfileItemRow | None, prepared: _PreparedItem
    ) -> bool:
        return existing is not None and (
            existing.frequency,
            existing.enabled,
            existing.notes,
        ) == (prepared.frequency, prepared.enabled, prepared.notes)
