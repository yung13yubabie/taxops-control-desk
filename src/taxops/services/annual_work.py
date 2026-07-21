"""Preview and idempotent confirmation of annual compliance work."""

from __future__ import annotations

import sqlite3
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..core.compliance import WORK_TYPE_LABELS
from ..core.annual_status import (
    DOCUMENT_STATUSES,
    FEE_STATUSES,
    FILING_STATUSES,
    TAX_STATUSES,
    WORK_STATUSES,
)
from ..i18n.status_labels import (
    ANNUAL_DOCUMENT_STATUS_LABELS,
    ANNUAL_FEE_STATUS_LABELS,
    ANNUAL_FILING_STATUS_LABELS,
    ANNUAL_TAX_STATUS_LABELS,
    ANNUAL_WORK_STATUS_LABELS,
    UNKNOWN_STATUS_TEXT,
)
from ..repositories.annual_work import (
    AnnualOverviewMetrics,
    AnnualDocumentSummaryRow,
    AnnualWorkItemRow,
    AnnualWorkOverviewRow,
    AnnualWorkRepository,
    AnnualWorkspaceRow,
)
from ..repositories.document_requests import DocumentRequestItemRow, DocumentRequestRow
from ..repositories.engagements import EngagementRow
from ..repositories.tasks import TaskRow
from ..repositories.compliance_profiles import ComplianceProfilesRepository
from .audit import AuditService
from .compliance_rules import ComplianceRuleError, WorkDraft, build_standard_drafts
from .system_log import SystemLogService
from .document_requests import (
    CreateDocumentRequestInput,
    DocumentRequestsService,
    DocumentRequestValidationError,
)
from .engagements import (
    CreateEngagementInput,
    EngagementsService,
    EngagementValidationError,
)
from .tasks import CreateTaskInput, TasksService, TaskValidationError


MAX_REASON_LENGTH = 4000

_COMPLETION_RISKS = {
    "filing_status": frozenset({"filing_failed", "correction_required"}),
    "document_status": frozenset({"missing", "partially_received"}),
    "tax_status": frozenset(
        {"unconfirmed", "awaiting_collection", "partially_collected", "unpaid"}
    ),
    "fee_status": frozenset({"awaiting_payment", "partially_paid"}),
}


class AnnualWorkError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AnnualWorkValidationError(AnnualWorkError, ValueError):
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


@dataclass(frozen=True)
class AnnualWorkspaceSnapshot:
    workspace: AnnualWorkspaceRow
    items: tuple[AnnualWorkItemRow, ...]


@dataclass(frozen=True)
class AnnualWorkStatusPresentation:
    work_status_label: str
    filing_status_label: str
    document_status_label: str
    tax_status_label: str
    fee_status_label: str


@dataclass(frozen=True)
class LinkedDocumentRequestResult:
    item: AnnualWorkItemRow
    engagement: EngagementRow
    request: DocumentRequestRow
    items: tuple[DocumentRequestItemRow, ...]


@dataclass(frozen=True)
class AnnualLinkedOverview:
    item: AnnualWorkItemRow
    engagement: EngagementRow | None
    requests: tuple[DocumentRequestRow, ...]
    tasks: tuple[TaskRow, ...]


AnnualDocumentSummary = AnnualDocumentSummaryRow


_WORK_TYPE_TAX_TYPES = {
    "vat": "vat",
    "corporate_income_tax": "cit",
    "undistributed_earnings": "cit",
    "provisional_tax": "cit",
    "monthly_withholding_payment": "iit",
    "annual_withholding_statements": "iit",
}


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
    WORK_STATUSES = WORK_STATUSES
    FILING_STATUSES = FILING_STATUSES
    DOCUMENT_STATUSES = DOCUMENT_STATUSES
    TAX_STATUSES = TAX_STATUSES
    FEE_STATUSES = FEE_STATUSES

    def __init__(
        self,
        conn: sqlite3.Connection,
        repository: AnnualWorkRepository,
        profiles: ComplianceProfilesRepository,
        audit: AuditService,
        system_log: SystemLogService | None = None,
        engagements: EngagementsService | None = None,
        document_requests: DocumentRequestsService | None = None,
        tasks: TasksService | None = None,
    ) -> None:
        collaborators = [
            ("repository", repository.connection),
            ("profiles", profiles.connection),
            ("audit", audit.connection),
        ]
        if system_log is not None:
            collaborators.append(("system_log", system_log.connection))
        if engagements is not None:
            collaborators.append(("engagements", engagements.connection))
        if document_requests is not None:
            collaborators.append(("document_requests", document_requests.connection))
        if tasks is not None:
            collaborators.append(("tasks", tasks.connection))
        mismatched = [
            name
            for name, candidate in collaborators
            if candidate is not conn
        ]
        if mismatched:
            raise ValueError("annual_work.connection.mismatch: " + ", ".join(mismatched))
        self._conn = conn
        self._repo = repository
        self._profiles = profiles
        self._audit = audit
        self._system_log = system_log
        self._engagements = engagements
        self._document_requests = document_requests
        self._tasks = tasks

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def repository(self) -> AnnualWorkRepository:
        return self._repo

    def _require_workflow_services(
        self,
    ) -> tuple[EngagementsService, DocumentRequestsService]:
        if self._engagements is None or self._document_requests is None:
            raise AnnualWorkError("annual_work.workflow.unavailable")
        return self._engagements, self._document_requests

    def create_linked_request(
        self,
        item_id: int,
        *,
        request_name: str,
        item_names: tuple[str, ...],
        due_date: str | None = None,
        notes: str | None = None,
    ) -> LinkedDocumentRequestResult:
        """Create a new request business event in one immediate transaction.

        A future UI must disable its submit control while this call is in flight.
        The transaction prevents a partial double-click, but repeated completed
        calls intentionally create distinct document requests.
        """
        if self._conn.in_transaction:
            raise AnnualWorkValidationError("annual_work.transaction.already_active")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if not isinstance(request_name, str) or not request_name.strip():
            raise AnnualWorkValidationError("doc_request.name.required")
        engagements, documents = self._require_workflow_services()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            context = self._repo.get_item_context(item_id)
            if context is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            item = context.item
            engagement: EngagementRow | None = None
            if item.engagement_id is not None:
                engagement = engagements.get_engagement(item.engagement_id)
                if engagement is None:
                    raise AnnualWorkValidationError("annual_work.engagement_not_found")
                if engagement.client_id != context.client_id:
                    raise AnnualWorkValidationError("annual_work.engagement.client_mismatch")
            else:
                engagement_name = item.title
                period_name = item.period_code or str(
                    item.tax_year or context.operation_year
                )
                if len(engagement_name) > 200 or len(period_name) > 50:
                    raise AnnualWorkValidationError(
                        "annual_work.engagement_fields.invalid"
                    )
                engagement = engagements._create_engagement_uncommitted(
                    CreateEngagementInput(
                        client_id=context.client_id,
                        engagement_name=engagement_name,
                        tax_type=_WORK_TYPE_TAX_TYPES.get(item.work_type, "other"),
                        period_name=period_name,
                        due_date=item.due_date,
                        notes=item.notes,
                    )
                )
                item = self._repo.set_engagement_link(item.id, engagement.id)

            request, created_items = documents._create_request_uncommitted(
                CreateDocumentRequestInput(
                    engagement_id=engagement.id,
                    tax_type=engagement.tax_type,
                    period_name=engagement.period_name,
                    request_name=request_name,
                    due_date=due_date,
                    notes=notes,
                    item_names=item_names,
                )
            )
            self._audit.record(
                action="annual_work.request.create",
                target_type="annual_work_item",
                target_id=str(item.id),
                detail={
                    "engagement_id": engagement.id,
                    "request_id": request.id,
                    "item_count": len(created_items),
                },
            )
            self._conn.commit()
            return LinkedDocumentRequestResult(
                item=item,
                engagement=engagement,
                request=request,
                items=tuple(created_items),
            )
        except AnnualWorkError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except (EngagementValidationError, DocumentRequestValidationError) as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkValidationError(exc.code) from exc
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            code = getattr(exc, "sqlite_errorcode", None)
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(exc).lower():
                raise AnnualWorkError("annual_work.transaction.busy") from exc
            raise AnnualWorkError("annual_work.request.create_failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.request.create_failed") from exc

    def document_summary(self, item_id: int) -> AnnualDocumentSummary:
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if not self._repo.active_item_record_exists(item_id):
            raise AnnualWorkValidationError("annual_work.item_not_found")
        return self._repo.document_summary(item_id)

    def link_existing_engagement(
        self, item_id: int, engagement_id: int
    ) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError("annual_work.transaction.already_active")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if (
            not isinstance(engagement_id, int)
            or isinstance(engagement_id, bool)
            or engagement_id <= 0
        ):
            raise AnnualWorkValidationError("annual_work.engagement_id.invalid")
        engagements, _documents = self._require_workflow_services()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            context = self._repo.get_item_context(item_id)
            if context is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            engagement = engagements.get_engagement(engagement_id)
            if engagement is None:
                raise AnnualWorkValidationError("annual_work.engagement_not_found")
            if engagement.client_id != context.client_id:
                raise AnnualWorkValidationError(
                    "annual_work.engagement.client_mismatch"
                )
            previous = context.item.engagement_id
            if previous == engagement_id:
                self._conn.commit()
                return context.item
            if previous is not None and self._repo.linked_engagement_has_history(
                item_id, previous
            ):
                raise AnnualWorkValidationError(
                    "annual_work.engagement.relink_has_history"
                )
            updated = self._repo.set_engagement_link(item_id, engagement_id)
            self._audit.record(
                action=(
                    "annual_work.engagement.relink"
                    if previous is not None
                    else "annual_work.engagement.link"
                ),
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={
                    "previous_engagement_id": previous,
                    "engagement_id": engagement_id,
                },
            )
            self._conn.commit()
            return updated
        except AnnualWorkError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            code = getattr(exc, "sqlite_errorcode", None)
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(exc).lower():
                raise AnnualWorkError("annual_work.transaction.busy") from exc
            raise AnnualWorkError("annual_work.engagement.link_failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.engagement.link_failed") from exc

    def unlink_engagement(self, item_id: int) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError("annual_work.transaction.already_active")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            context = self._repo.get_item_context(item_id)
            if context is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            previous = context.item.engagement_id
            if previous is None:
                self._conn.commit()
                return context.item
            if self._repo.linked_engagement_has_history(item_id, previous):
                raise AnnualWorkValidationError(
                    "annual_work.engagement.unlink_has_history"
                )
            updated = self._repo.set_engagement_link(item_id, None)
            self._audit.record(
                action="annual_work.engagement.unlink",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={"previous_engagement_id": previous},
            )
            self._conn.commit()
            return updated
        except AnnualWorkError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            code = getattr(exc, "sqlite_errorcode", None)
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(exc).lower():
                raise AnnualWorkError("annual_work.transaction.busy") from exc
            raise AnnualWorkError("annual_work.engagement.unlink_failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.engagement.unlink_failed") from exc

    def create_linked_task(
        self,
        item_id: int,
        *,
        title: str,
        assignee: str | None = None,
        due_date: str | None = None,
        priority: str = "normal",
        next_step: str | None = None,
        notes: str | None = None,
    ) -> TaskRow:
        """Create one existing workflow task linked bidirectionally to an item."""
        if self._conn.in_transaction:
            raise AnnualWorkValidationError("annual_work.transaction.already_active")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if self._engagements is None or self._tasks is None:
            raise AnnualWorkError("annual_work.workflow.unavailable")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            context = self._repo.get_item_context(item_id)
            if context is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            item = context.item
            engagement: EngagementRow | None = None
            if item.engagement_id is not None:
                engagement = self._engagements.get_engagement(item.engagement_id)
                if engagement is None:
                    raise AnnualWorkValidationError("annual_work.engagement_not_found")
                if engagement.client_id != context.client_id:
                    raise AnnualWorkValidationError(
                        "annual_work.engagement.client_mismatch"
                    )
            else:
                engagement_name = item.title
                period_name = item.period_code or str(
                    item.tax_year or context.operation_year
                )
                if len(engagement_name) > 200 or len(period_name) > 50:
                    raise AnnualWorkValidationError(
                        "annual_work.engagement_fields.invalid"
                    )
                engagement = self._engagements._create_engagement_uncommitted(
                    CreateEngagementInput(
                        client_id=context.client_id,
                        engagement_name=engagement_name,
                        tax_type=_WORK_TYPE_TAX_TYPES.get(item.work_type, "other"),
                        period_name=period_name,
                        due_date=item.due_date,
                        notes=item.notes,
                    )
                )
                item = self._repo.set_engagement_link(item.id, engagement.id)
            task = self._tasks._create_task_uncommitted(
                CreateTaskInput(
                    engagement_id=engagement.id,
                    client_id=context.client_id,
                    title=title,
                    assignee=assignee,
                    due_date=due_date,
                    priority=priority,
                    next_step=next_step,
                    notes=notes,
                    annual_work_item_id=item.id,
                )
            )
            self._audit.record(
                action="annual_work.task.create",
                target_type="annual_work_item",
                target_id=str(item.id),
                detail={"engagement_id": engagement.id, "task_id": task.id},
            )
            self._conn.commit()
            return task
        except AnnualWorkError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except (EngagementValidationError, TaskValidationError) as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkValidationError(exc.code) from exc
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            code = getattr(exc, "sqlite_errorcode", None)
            if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(exc).lower():
                raise AnnualWorkError("annual_work.transaction.busy") from exc
            raise AnnualWorkError("annual_work.task.create_failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.task.create_failed") from exc

    def linked_overview(
        self,
        item_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> AnnualLinkedOverview:
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 500
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= 1_000_000
        ):
            raise AnnualWorkValidationError(
                "annual_work.linked_requests.pagination.invalid"
            )
        context = self._repo.get_item_context(item_id)
        if context is None:
            raise AnnualWorkValidationError("annual_work.item_not_found")
        engagement: EngagementRow | None = None
        requests: tuple[DocumentRequestRow, ...] = ()
        if context.item.engagement_id is not None and self._engagements is not None:
            engagement = self._engagements.get_engagement(
                context.item.engagement_id
            )
            if engagement is not None and self._document_requests is not None:
                requests = tuple(
                    self._document_requests.list_by_engagement(
                        engagement.id, limit=limit, offset=offset
                    )
                )
        tasks: tuple[TaskRow, ...] = ()
        if self._tasks is not None:
            tasks = tuple(self._tasks.list_by_annual_work_item(item_id))
        return AnnualLinkedOverview(
            item=context.item,
            engagement=engagement,
            requests=requests,
            tasks=tasks,
        )

    def list_linked_requests(
        self,
        item_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[DocumentRequestRow, ...]:
        return self.linked_overview(
            item_id, limit=limit, offset=offset
        ).requests

    def list_linked_tasks(self, item_id: int) -> tuple[TaskRow, ...]:
        return self.linked_overview(item_id).tasks

    def get_status_presentation(self, item_id: int) -> AnnualWorkStatusPresentation:
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        item = self._repo.get_item(item_id)
        if item is None:
            raise AnnualWorkValidationError("annual_work.item_not_found")
        return self.present_statuses(item)

    def present_statuses(
        self, item: AnnualWorkItemRow
    ) -> AnnualWorkStatusPresentation:
        """Present an already-loaded item without another repository read."""
        mappings = {
            "work_status": ANNUAL_WORK_STATUS_LABELS,
            "filing_status": ANNUAL_FILING_STATUS_LABELS,
            "document_status": ANNUAL_DOCUMENT_STATUS_LABELS,
            "tax_status": ANNUAL_TAX_STATUS_LABELS,
            "fee_status": ANNUAL_FEE_STATUS_LABELS,
        }
        labels: dict[str, str] = {}
        for dimension, mapping in mappings.items():
            raw = getattr(item, dimension)
            known = isinstance(raw, str) and raw in mapping
            labels[dimension] = mapping[raw] if known else UNKNOWN_STATUS_TEXT
            if not known and self._system_log is not None:
                raw_text = raw if isinstance(raw, str) else f"<{type(raw).__name__}>"
                sanitized = "".join(
                    char
                    if unicodedata.category(char) not in {"Cc", "Cf"}
                    else "�"
                    for char in raw_text
                )[:120]
                caller_transaction = self._conn.in_transaction
                try:
                    self._system_log.warn(
                        "annual_work.unknown_status",
                        detail={
                            "dimension": dimension,
                            "item_id": item.id,
                            "raw_code": sanitized,
                        },
                        commit=not caller_transaction,
                    )
                except Exception:
                    # Presentation must remain available when diagnostic storage
                    # is locked or unavailable. Never alter a caller-owned
                    # transaction; only clean up a transaction started by this
                    # best-effort log attempt.
                    if not caller_transaction and self._conn.in_transaction:
                        try:
                            self._conn.rollback()
                        except sqlite3.Error:
                            pass
        return AnnualWorkStatusPresentation(
            work_status_label=labels["work_status"],
            filing_status_label=labels["filing_status"],
            document_status_label=labels["document_status"],
            tax_status_label=labels["tax_status"],
            fee_status_label=labels["fee_status"],
        )

    def search_overview(
        self,
        filters: Mapping[str, object] | None = None,
        *,
        risk: object = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AnnualWorkOverviewRow]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise AnnualWorkValidationError("annual_work.pagination.invalid")
        if filters is not None and not isinstance(filters, Mapping):
            raise AnnualWorkValidationError("annual_work.filters.invalid")
        values = dict(filters or {})
        if risk is not None:
            if "risk" in values:
                raise AnnualWorkValidationError("annual_work.filters.invalid")
            values["risk"] = risk
        try:
            return self._repo.search_overview(values, limit=limit, offset=offset)
        except ValueError as exc:
            raise AnnualWorkValidationError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise AnnualWorkError("annual_work.overview.failed") from exc

    def overview_metrics(
        self, filters: Mapping[str, object] | None = None
    ) -> AnnualOverviewMetrics:
        try:
            return self._repo.overview_metrics(filters)
        except ValueError as exc:
            raise AnnualWorkValidationError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise AnnualWorkError("annual_work.overview.failed") from exc

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

    def get_workspace_snapshot(
        self, client_id: int, operation_year: int
    ) -> AnnualWorkspaceSnapshot | None:
        """Return one complete bounded workspace snapshot for presentation."""
        client_id = _validate_client_id(client_id)
        operation_year = _validate_operation_year(operation_year)
        try:
            workspace = self._repo.find_workspace(client_id, operation_year)
            if workspace is None:
                return None
            items = tuple(self._repo.list_items_for_snapshot(workspace.id))
            if len(items) > 500:
                raise AnnualWorkError("annual_work.snapshot.too_many_items")
            return AnnualWorkspaceSnapshot(
                workspace=workspace,
                items=items,
            )
        except AnnualWorkError:
            raise
        except (sqlite3.Error, RuntimeError, ValueError) as exc:
            raise AnnualWorkError("annual_work.snapshot.failed") from exc

    def _set_status(
        self,
        item_id: int,
        status: object,
        *,
        dimension: str,
        allowed: frozenset[str],
    ) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if not isinstance(status, str) or status not in allowed:
            raise AnnualWorkValidationError(f"annual_work.{dimension}.invalid")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self._repo.get_item(item_id)
            if current is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            if current.work_status == "cancelled":
                raise AnnualWorkValidationError("annual_work.item.cancelled")
            if dimension != "work_status" and current.work_status in {
                "completed",
                "completed_with_exception",
            }:
                raise AnnualWorkValidationError("annual_work.item.completed")
            previous = getattr(current, dimension)
            if previous == status:
                self._conn.commit()
                return current
            reopened = dimension == "work_status" and current.work_status in {
                "completed",
                "completed_with_exception",
            }
            if reopened:
                updated = self._repo.reopen_item(item_id, status)
            else:
                updated = self._repo.update_status(item_id, dimension, status)
            detail = {
                "from_status": previous,
                "to_status": status,
            }
            if reopened:
                detail["reopened"] = True
            self._audit.record(
                action=f"annual_work.{dimension}.update",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail=detail,
            )
            self._conn.commit()
            return updated
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
            raise AnnualWorkError("annual_work.status.update_failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.status.update_failed") from exc

    def set_work_status(self, item_id: int, status: object) -> AnnualWorkItemRow:
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if isinstance(status, str) and status in {
            "completed",
            "completed_with_exception",
            "cancelled",
        }:
            raise AnnualWorkValidationError(
                "annual_work.work_status.transition_required"
            )
        return self._set_status(
            item_id, status, dimension="work_status", allowed=self.WORK_STATUSES
        )

    def set_filing_status(self, item_id: int, status: object) -> AnnualWorkItemRow:
        return self._set_status(
            item_id, status, dimension="filing_status", allowed=self.FILING_STATUSES
        )

    def set_document_status(self, item_id: int, status: object) -> AnnualWorkItemRow:
        return self._set_status(
            item_id,
            status,
            dimension="document_status",
            allowed=self.DOCUMENT_STATUSES,
        )

    def set_tax_status(self, item_id: int, status: object) -> AnnualWorkItemRow:
        return self._set_status(
            item_id, status, dimension="tax_status", allowed=self.TAX_STATUSES
        )

    def set_fee_status(self, item_id: int, status: object) -> AnnualWorkItemRow:
        return self._set_status(
            item_id, status, dimension="fee_status", allowed=self.FEE_STATUSES
        )

    def complete_item(
        self, item_id: int, *, exception_reason: object = None
    ) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if exception_reason is not None and (
            not isinstance(exception_reason, str)
            or len(exception_reason) > MAX_REASON_LENGTH
        ):
            raise AnnualWorkValidationError("annual_work.exception_reason.invalid")
        reason = exception_reason
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self._repo.get_item(item_id)
            if current is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            if current.work_status == "cancelled":
                raise AnnualWorkValidationError("annual_work.item.cancelled")
            if current.work_status in {"completed", "completed_with_exception"}:
                raise AnnualWorkValidationError(
                    "annual_work.item.already_completed"
                )
            risks = tuple(
                dimension
                for dimension, statuses in _COMPLETION_RISKS.items()
                if getattr(current, dimension) in statuses
            )
            if risks and (reason is None or not reason.strip()):
                raise AnnualWorkValidationError(
                    "annual_work.exception_reason.required"
                )
            target = "completed_with_exception" if risks else "completed"
            updated = self._repo.complete_item(item_id, target, reason)
            self._audit.record(
                action="annual_work.complete",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={
                    "from_status": current.work_status,
                    "to_status": target,
                    "open_risk_dimensions": list(risks),
                    "exception_reason": reason,
                },
            )
            self._conn.commit()
            return updated
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
            raise AnnualWorkError("annual_work.complete.failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.complete.failed") from exc

    def cancel_item(self, item_id: int, reason: object) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        if not isinstance(reason, str) or len(reason) > MAX_REASON_LENGTH:
            raise AnnualWorkValidationError("annual_work.cancel_reason.invalid")
        if not reason.strip():
            raise AnnualWorkValidationError("annual_work.cancel_reason.required")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self._repo.get_item(item_id)
            if current is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            if current.work_status == "cancelled" and current.exception_reason == reason:
                self._conn.commit()
                return current
            updated = self._repo.cancel_item(item_id, reason)
            self._audit.record(
                action="annual_work.cancel",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={
                    "from_status": current.work_status,
                    "to_status": "cancelled",
                    "reason": reason,
                    "reason_changed": current.work_status == "cancelled",
                },
            )
            self._conn.commit()
            return updated
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
            raise AnnualWorkError("annual_work.cancel.failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.cancel.failed") from exc

    def restore_item(self, item_id: int) -> AnnualWorkItemRow:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self._repo.get_item(item_id)
            if current is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            if current.work_status != "cancelled":
                raise AnnualWorkValidationError("annual_work.item.not_cancelled")
            updated = self._repo.restore_item(item_id)
            self._audit.record(
                action="annual_work.restore",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={
                    "from_status": "cancelled",
                    "to_status": "not_started",
                    "cancel_reason": current.exception_reason,
                },
            )
            self._conn.commit()
            return updated
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
            raise AnnualWorkError("annual_work.restore.failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.restore.failed") from exc

    def delete_item(self, item_id: int) -> None:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise AnnualWorkValidationError("annual_work.item_id.invalid")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self._repo.get_item(item_id)
            if current is None:
                raise AnnualWorkValidationError("annual_work.item_not_found")
            if current.work_status == "cancelled":
                raise AnnualWorkValidationError("annual_work.item.cancelled")
            dependencies = self._repo.probe_dependencies(item_id)
            if dependencies.has_history:
                raise AnnualWorkValidationError("annual_work.delete.has_history")
            if not self._repo.hard_delete_item(item_id):
                raise AnnualWorkValidationError("annual_work.item_not_found")
            self._audit.record(
                action="annual_work.delete",
                target_type="annual_work_item",
                target_id=str(item_id),
                detail={"item_key": current.item_key, "work_type": current.work_type},
            )
            self._conn.commit()
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
            raise AnnualWorkError("annual_work.delete.failed") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualWorkError("annual_work.delete.failed") from exc

    def confirm_preview(
        self,
        client_id: int,
        operation_year: int,
        drafts: Sequence[WorkDraft],
    ) -> AnnualWorkspaceResult:
        return self._confirm_preview_selection(
            client_id,
            operation_year,
            expected_drafts=drafts,
            selected_drafts=drafts,
            include_selection_audit=False,
        )

    def confirm_preview_selection(
        self,
        client_id: int,
        operation_year: int,
        *,
        expected_drafts: Sequence[WorkDraft],
        selected_drafts: Sequence[WorkDraft],
    ) -> AnnualWorkspaceResult:
        """Atomically confirm a stale-guarded subset of standard/custom drafts."""
        return self._confirm_preview_selection(
            client_id,
            operation_year,
            expected_drafts=expected_drafts,
            selected_drafts=selected_drafts,
            include_selection_audit=True,
        )

    def _confirm_preview_selection(
        self,
        client_id: int,
        operation_year: int,
        *,
        expected_drafts: Sequence[WorkDraft],
        selected_drafts: Sequence[WorkDraft],
        include_selection_audit: bool,
    ) -> AnnualWorkspaceResult:
        if self._conn.in_transaction:
            raise AnnualWorkValidationError(
                "annual_work.transaction.already_active"
            )
        client_id = _validate_client_id(client_id)
        operation_year = _validate_operation_year(operation_year)
        prepared_expected = _prepare_drafts(expected_drafts, operation_year)
        prepared_selected = _prepare_drafts(selected_drafts, operation_year)

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            fresh = self.preview(client_id, operation_year)
            if prepared_expected != fresh:
                raise AnnualWorkValidationError(
                    "annual_work.drafts.profile_mismatch"
                )
            standard_by_key = {draft.item_key: draft for draft in fresh}
            custom_count = 0
            for draft in prepared_selected:
                standard = standard_by_key.get(draft.item_key)
                if standard is not None:
                    if draft.work_type != standard.work_type:
                        raise AnnualWorkValidationError(
                            "annual_work.draft.standard_mismatch"
                        )
                    continue
                if not draft.item_key.startswith("custom:"):
                    raise AnnualWorkValidationError(
                        "annual_work.draft.item_key.fabricated"
                    )
                raw_uuid = draft.item_key.removeprefix("custom:")
                try:
                    canonical_uuid = str(uuid.UUID(raw_uuid))
                except (ValueError, AttributeError) as exc:
                    raise AnnualWorkValidationError(
                        "annual_work.draft.custom_key.invalid"
                    ) from exc
                if raw_uuid != canonical_uuid:
                    raise AnnualWorkValidationError(
                        "annual_work.draft.custom_key.invalid"
                    )
                custom_count += 1
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
            for draft in prepared_selected:
                result = self._repo.insert_item_if_missing(workspace.id, draft)
                inserted_count += int(result.inserted)
            items = tuple(self._repo.list_items(workspace.id))
            unchanged = not created_workspace and inserted_count == 0
            audit_detail = {
                "client_id": client_id,
                "operation_year": operation_year,
                "created_workspace": created_workspace,
                "inserted_item_count": inserted_count,
                "item_count": len(items),
                "unchanged": unchanged,
            }
            if include_selection_audit:
                audit_detail.update(
                    {
                        "selected_count": len(prepared_selected),
                        "custom_count": custom_count,
                    }
                )
            self._audit.record(
                action="annual_workspace.confirm",
                target_type="annual_workspace",
                target_id=str(workspace.id),
                detail=audit_detail,
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
