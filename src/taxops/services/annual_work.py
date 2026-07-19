"""Preview and idempotent confirmation of annual compliance work."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..core.compliance import WORK_TYPE_LABELS
from ..repositories.annual_work import (
    AnnualWorkItemRow,
    AnnualWorkRepository,
    AnnualWorkspaceRow,
)
from ..repositories.compliance_profiles import ComplianceProfilesRepository
from .audit import AuditService
from .compliance_rules import ComplianceRuleError, WorkDraft, build_standard_drafts


class AnnualWorkError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AnnualWorkValidationError(AnnualWorkError):
    """A caller-supplied value or current client profile cannot be used."""


@dataclass(frozen=True)
class AnnualWorkspaceResult:
    workspace: AnnualWorkspaceRow
    items: tuple[AnnualWorkItemRow, ...]
    created_workspace: bool
    inserted_item_count: int

    @property
    def unchanged(self) -> bool:
        return not self.created_workspace and self.inserted_item_count == 0


def _validate_client_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AnnualWorkValidationError("annual_work.client_id.invalid")
    return value


def _validate_operation_year(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1912 <= value <= 9999
    ):
        raise AnnualWorkValidationError("annual_work.operation_year.invalid")
    return value


def _valid_optional_date(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _prepare_drafts(
    value: object, operation_year: int
) -> tuple[WorkDraft, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AnnualWorkValidationError("annual_work.drafts.invalid")
    if not value:
        raise AnnualWorkValidationError("annual_work.drafts.empty")
    prepared: list[WorkDraft] = []
    seen: set[str] = set()
    for draft in value:
        if type(draft) is not WorkDraft:
            raise AnnualWorkValidationError("annual_work.draft.invalid")
        if (
            type(draft.operation_year) is not int
            or draft.operation_year != operation_year
        ):
            raise AnnualWorkValidationError(
                "annual_work.draft.operation_year.mismatch"
            )
        if (
            not isinstance(draft.item_key, str)
            or not draft.item_key.strip()
            or len(draft.item_key) > 255
            or not isinstance(draft.work_type, str)
            or draft.work_type not in WORK_TYPE_LABELS
            or not isinstance(draft.title, str)
            or not draft.title.strip()
            or len(draft.title) > 500
            or (
                draft.tax_year is not None
                and (
                    type(draft.tax_year) is not int
                    or not 1912 <= draft.tax_year <= 9999
                )
            )
            or (
                draft.period_code is not None
                and (
                    not isinstance(draft.period_code, str)
                    or not draft.period_code.strip()
                    or len(draft.period_code) > 50
                )
            )
            or not _valid_optional_date(draft.suggested_due_date)
        ):
            raise AnnualWorkValidationError("annual_work.draft.invalid")
        if draft.item_key in seen:
            raise AnnualWorkValidationError("annual_work.draft.item_key.duplicate")
        seen.add(draft.item_key)
        prepared.append(draft)
    return tuple(prepared)


class AnnualWorkService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repository: AnnualWorkRepository,
        profiles: ComplianceProfilesRepository,
        audit: AuditService,
    ) -> None:
        mismatched = [
            name
            for name, candidate in (
                ("repository", repository.connection),
                ("profiles", profiles.connection),
                ("audit", audit.connection),
            )
            if candidate is not conn
        ]
        if mismatched:
            raise ValueError("annual_work.connection.mismatch: " + ", ".join(mismatched))
        self._conn = conn
        self._repo = repository
        self._profiles = profiles
        self._audit = audit

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def repository(self) -> AnnualWorkRepository:
        return self._repo

    def preview(self, client_id: int, operation_year: int) -> tuple[WorkDraft, ...]:
        client_id = _validate_client_id(client_id)
        operation_year = _validate_operation_year(operation_year)
        if not self._profiles.active_client_exists(client_id):
            raise AnnualWorkValidationError("annual_work.client_not_found")
        profile = self._profiles.get_for_client(client_id)
        if profile is None:
            raise AnnualWorkValidationError("annual_work.profile_not_found")
        enabled = {
            row.work_type: row.frequency
            for row in self._profiles.list_items(profile.id)
            if row.enabled
        }
        if not enabled:
            raise AnnualWorkValidationError("annual_work.enabled_items.empty")
        try:
            drafts = build_standard_drafts(
                operation_year,
                fiscal_start_month=profile.fiscal_year_start_month,
                enabled=enabled,
            )
        except ComplianceRuleError as exc:
            suffix = exc.code.removeprefix("compliance_rules.")
            raise AnnualWorkValidationError(f"annual_work.{suffix}") from exc
        if not drafts:
            raise AnnualWorkValidationError("annual_work.preview.empty")
        return drafts

    def confirm_preview(
        self,
        client_id: int,
        operation_year: int,
        drafts: Sequence[WorkDraft],
    ) -> AnnualWorkspaceResult:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        client_id = _validate_client_id(client_id)
        operation_year = _validate_operation_year(operation_year)
        prepared = _prepare_drafts(drafts, operation_year)

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            expected = self.preview(client_id, operation_year)
            if prepared != expected:
                raise AnnualWorkValidationError(
                    "annual_work.drafts.profile_mismatch"
                )
            profile = self._profiles.get_for_client(client_id)
            if profile is None:
                raise AnnualWorkValidationError("annual_work.profile_not_found")

            workspace = self._repo.find_workspace(client_id, operation_year)
            created_workspace = False
            if workspace is None:
                try:
                    workspace = self._repo.insert_workspace(
                        client_id,
                        operation_year,
                        profile.fiscal_year_start_month,
                    )
                    created_workspace = True
                except sqlite3.IntegrityError as exc:
                    if (
                        getattr(exc, "sqlite_errorcode", None)
                        != sqlite3.SQLITE_CONSTRAINT_UNIQUE
                    ):
                        raise
                    workspace = self._repo.find_workspace(
                        client_id, operation_year
                    )
                    if workspace is None:
                        raise

            inserted_count = 0
            for draft in prepared:
                result = self._repo.insert_item_if_missing(workspace.id, draft)
                inserted_count += int(result.inserted)
            items = tuple(self._repo.list_items(workspace.id))
            self._audit.record(
                action="annual_workspace.confirm",
                target_type="annual_workspace",
                target_id=str(workspace.id),
                detail={
                    "client_id": client_id,
                    "operation_year": operation_year,
                    "created_workspace": created_workspace,
                    "inserted_item_count": inserted_count,
                    "item_count": len(items),
                    "unchanged": not created_workspace and inserted_count == 0,
                },
            )
            self._conn.commit()
            return AnnualWorkspaceResult(
                workspace=workspace,
                items=items,
                created_workspace=created_workspace,
                inserted_item_count=inserted_count,
            )
        except AnnualWorkError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            code = getattr(exc, "sqlite_errorcode", None)
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(
                exc
            ).lower():
                raise AnnualWorkError("annual_work.transaction.busy") from exc
            raise AnnualWorkError("annual_work.confirm.failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.confirm.failed") from exc
