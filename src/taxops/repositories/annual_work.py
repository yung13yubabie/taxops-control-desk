"""Bounded persistence for annual client-year workspaces and work items."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ..core.compliance import WORK_TYPE_LABELS
from ..core.clock import now_iso
from ..core.annual_status import STATUS_SETS, WORK_STATUSES
from ..services.compliance_rules import WorkDraft
from .annual_transactions import (
    ANNUAL_OVERVIEW_RISKS,
    AnnualBalance,
    decode_annual_exact_decimal,
    register_annual_exact_sqlite_functions,
)


MAX_WORKSPACE_ITEMS = 500


@dataclass(frozen=True)
class AnnualWorkspaceRow:
    id: int
    client_id: int
    operation_year: int
    fiscal_year_start_month_snapshot: int
    status: str
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class AnnualWorkItemRow:
    id: int
    workspace_id: int
    item_key: str
    work_type: str
    title: str
    tax_year: int | None
    period_code: str | None
    suggested_due_date: str | None
    due_date: str | None
    work_status: str
    filing_status: str
    document_status: str
    tax_status: str
    fee_status: str
    engagement_id: int | None
    exception_reason: str | None
    notes: str | None
    completed_at: str | None
    cancelled_at: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class AnnualWorkItemInsertResult:
    row: AnnualWorkItemRow
    inserted: bool


@dataclass(frozen=True)
class AnnualWorkDependencies:
    has_transactions: bool
    engagement_id: int | None
    has_tasks: bool

    @property
    def has_history(self) -> bool:
        return (
            self.has_transactions
            or self.engagement_id is not None
            or self.has_tasks
        )


@dataclass(frozen=True)
class AnnualWorkOverviewRow:
    item: AnnualWorkItemRow
    workspace_client_id: int
    operation_year: int
    client_code: str
    client_name: str
    balance: AnnualBalance


@dataclass(frozen=True)
class AnnualOverviewMetrics:
    item_count: int = 0
    client_count: int = 0
    exception_count: int = 0
    document_risk_count: int = 0
    collection_shortfall_total: int = 0
    unpaid_tax_total: int = 0
    outstanding_fee_total: int = 0
    overage_count: int = 0


@dataclass(frozen=True)
class AnnualWorkItemContext:
    item: AnnualWorkItemRow
    client_id: int
    operation_year: int


@dataclass(frozen=True)
class AnnualDocumentSummaryRow:
    request_count: int = 0
    total: int = 0
    missing: int = 0
    received: int = 0
    incomplete: int = 0
    invalid: int = 0
    accepted: int = 0
    pending_confirm: int = 0
    not_applicable: int = 0
    client_said_none: int = 0
    attachment_count: int = 0


def _workspace_row(row: sqlite3.Row) -> AnnualWorkspaceRow:
    return AnnualWorkspaceRow(
        id=int(row["id"]),
        client_id=int(row["client_id"]),
        operation_year=int(row["operation_year"]),
        fiscal_year_start_month_snapshot=int(
            row["fiscal_year_start_month_snapshot"]
        ),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=row["deleted_at"],
    )


def _item_row(row: sqlite3.Row) -> AnnualWorkItemRow:
    return AnnualWorkItemRow(
        id=int(row["id"]),
        workspace_id=int(row["workspace_id"]),
        item_key=str(row["item_key"]),
        work_type=str(row["work_type"]),
        title=str(row["title"]),
        tax_year=int(row["tax_year"]) if row["tax_year"] is not None else None,
        period_code=row["period_code"],
        suggested_due_date=row["suggested_due_date"],
        due_date=row["due_date"],
        work_status=str(row["work_status"]),
        filing_status=str(row["filing_status"]),
        document_status=str(row["document_status"]),
        tax_status=str(row["tax_status"]),
        fee_status=str(row["fee_status"]),
        engagement_id=(
            int(row["engagement_id"]) if row["engagement_id"] is not None else None
        ),
        exception_reason=row["exception_reason"],
        notes=row["notes"],
        completed_at=row["completed_at"],
        cancelled_at=row["cancelled_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=row["deleted_at"],
    )


def _pagination(limit: object, offset: object) -> tuple[int, int]:
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_WORKSPACE_ITEMS
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= 1_000_000
    ):
        raise ValueError("annual_work.pagination.invalid")
    return limit, offset


def _positive_id(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(code)
    return value


def _operation_year(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1912 <= value <= 9999
    ):
        raise ValueError("annual_work.filters.invalid")
    return value


def _filter_text(value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("annual_work.filters.invalid")
    if not allow_empty and not value.strip():
        raise ValueError("annual_work.filters.invalid")
    return value


def _filter_date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("annual_work.filters.invalid")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError("annual_work.filters.invalid") from exc
    return value


def _sort(
    order_by: object, order_dir: object, columns: Mapping[str, str]
) -> tuple[str, str]:
    if (
        not isinstance(order_by, str)
        or order_by not in columns
        or not isinstance(order_dir, str)
        or order_dir.upper() not in {"ASC", "DESC"}
    ):
        raise ValueError("annual_work.sort.invalid")
    return columns[order_by], order_dir.upper()


def _literal_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AnnualWorkRepository:
    _STATUS_COLUMNS = {
        "work_status": "work_status",
        "filing_status": "filing_status",
        "document_status": "document_status",
        "tax_status": "tax_status",
        "fee_status": "fee_status",
    }
    _WORKSPACE_SORT = {
        "id": "aw.id",
        "operation_year": "aw.operation_year",
        "created_at": "aw.created_at",
        "updated_at": "aw.updated_at",
    }
    _OVERVIEW_SORT = {
        "id": "id",
        "operation_year": "overview_operation_year",
        "client_code": "overview_client_code",
        "client_name": "overview_client_name",
        "due_date": "due_date",
        "work_type": "work_type",
        "work_status": "work_status",
        "updated_at": "updated_at",
    }
    _OVERVIEW_FILTERS = frozenset(
        {
            "client_id",
            "operation_year",
            "work_type",
            "work_status",
            "filing_status",
            "document_status",
            "tax_status",
            "fee_status",
            "due_from",
            "due_to",
            "query",
            "risk",
            "order_by",
            "order_dir",
        }
    )

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        register_annual_exact_sqlite_functions(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def get_item(self, item_id: int) -> AnnualWorkItemRow | None:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        row = self._conn.execute(
            "SELECT awi.* FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id "
            "WHERE awi.id = ? AND awi.deleted_at IS NULL "
            "AND aw.deleted_at IS NULL AND c.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        return _item_row(row) if row else None

    def get_item_context(self, item_id: int) -> AnnualWorkItemContext | None:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        row = self._conn.execute(
            "SELECT awi.*, aw.client_id AS context_client_id, "
            "aw.operation_year AS context_operation_year "
            "FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id "
            "WHERE awi.id = ? AND awi.deleted_at IS NULL "
            "AND aw.deleted_at IS NULL AND c.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return AnnualWorkItemContext(
            item=_item_row(row),
            client_id=int(row["context_client_id"]),
            operation_year=int(row["context_operation_year"]),
        )

    def active_item_record_exists(self, item_id: int) -> bool:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        row = self._conn.execute(
            "SELECT 1 FROM annual_work_items awi"
            " JOIN annual_workspaces aw ON aw.id = awi.workspace_id"
            " WHERE awi.id = ? AND awi.deleted_at IS NULL AND aw.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        return row is not None

    def set_engagement_link(
        self, item_id: int, engagement_id: int | None
    ) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        if engagement_id is not None:
            engagement_id = _positive_id(
                engagement_id, "annual_work.engagement_id.invalid"
            )
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET engagement_id = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (engagement_id, now_iso(), item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def linked_engagement_has_history(
        self, item_id: int, engagement_id: int
    ) -> bool:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        engagement_id = _positive_id(
            engagement_id, "annual_work.engagement_id.invalid"
        )
        row = self._conn.execute(
            "SELECT "
            "EXISTS(SELECT 1 FROM document_requests dr "
            " WHERE dr.engagement_id = ?) "
            "OR EXISTS(SELECT 1 FROM workflow_tasks wt "
            " WHERE wt.annual_work_item_id = ? OR wt.engagement_id = ?) "
            "OR EXISTS(SELECT 1 FROM attachments a "
            " WHERE a.engagement_id = ? OR a.request_id IN "
            " (SELECT dr.id FROM document_requests dr WHERE dr.engagement_id = ?)) "
            "AS has_history",
            (engagement_id, item_id, engagement_id, engagement_id, engagement_id),
        ).fetchone()
        return bool(row["has_history"]) if row else False

    def document_summary(self, item_id: int) -> AnnualDocumentSummaryRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        row = self._conn.execute(
            "WITH linked AS ("
            " SELECT awi.engagement_id FROM annual_work_items awi"
            " JOIN annual_workspaces aw ON aw.id = awi.workspace_id"
            " JOIN clients c ON c.id = aw.client_id AND c.deleted_at IS NULL"
            " JOIN engagements e ON e.id = awi.engagement_id"
            "  AND e.client_id = aw.client_id AND e.deleted_at IS NULL"
            " WHERE awi.id = ? AND awi.deleted_at IS NULL AND aw.deleted_at IS NULL"
            "), active_requests AS ("
            " SELECT dr.id FROM document_requests dr JOIN linked l"
            "  ON l.engagement_id = dr.engagement_id WHERE dr.deleted_at IS NULL"
            "), item_counts AS ("
            " SELECT COUNT(*) AS total,"
            " SUM(dri.item_status = 'missing') AS missing,"
            " SUM(dri.item_status = 'received') AS received,"
            " SUM(dri.item_status = 'incomplete') AS incomplete,"
            " SUM(dri.item_status = 'invalid') AS invalid,"
            " SUM(dri.item_status = 'accepted') AS accepted,"
            " SUM(dri.item_status = 'pending_confirm') AS pending_confirm,"
            " SUM(dri.item_status = 'not_applicable') AS not_applicable,"
            " SUM(dri.item_status = 'client_said_none') AS client_said_none"
            " FROM document_request_items dri JOIN active_requests ar"
            "  ON ar.id = dri.request_id"
            ") SELECT"
            " (SELECT COUNT(*) FROM active_requests) AS request_count,"
            " COALESCE(ic.total, 0) AS total, COALESCE(ic.missing, 0) AS missing,"
            " COALESCE(ic.received, 0) AS received,"
            " COALESCE(ic.incomplete, 0) AS incomplete,"
            " COALESCE(ic.invalid, 0) AS invalid,"
            " COALESCE(ic.accepted, 0) AS accepted,"
            " COALESCE(ic.pending_confirm, 0) AS pending_confirm,"
            " COALESCE(ic.not_applicable, 0) AS not_applicable,"
            " COALESCE(ic.client_said_none, 0) AS client_said_none,"
            " (SELECT COUNT(*) FROM attachments a WHERE a.status != 'archived'"
            "   AND ((a.request_id IS NULL"
            "         AND a.engagement_id = (SELECT engagement_id FROM linked))"
            "        OR a.request_id IN (SELECT id FROM active_requests)))"
            " AS attachment_count FROM item_counts ic",
            (item_id,),
        ).fetchone()
        if row is None:
            return AnnualDocumentSummaryRow()
        return AnnualDocumentSummaryRow(
            **{
                field: int(row[field] or 0)
                for field in AnnualDocumentSummaryRow.__dataclass_fields__
            }
        )

    def update_status(
        self, item_id: int, dimension: str, status: str
    ) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        column = self._STATUS_COLUMNS.get(dimension)
        if column is None:
            raise ValueError("annual_work.status_dimension.invalid")
        if not isinstance(status, str) or status not in STATUS_SETS[dimension]:
            raise ValueError("annual_work.status.invalid")
        timestamp = now_iso()
        cursor = self._conn.execute(
            f"UPDATE annual_work_items SET {column} = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (status, timestamp, item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def update_item_details(
        self,
        item_id: int,
        *,
        title: str,
        tax_year: int | None,
        period_code: str | None,
        due_date: str | None,
        notes: str | None,
        work_status: str,
        filing_status: str,
        document_status: str,
        tax_status: str,
        fee_status: str,
        expected_updated_at: str,
        updated_at: str,
    ) -> AnnualWorkItemRow:
        """Replace user-editable detail fields using one optimistic write."""
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET title = ?, tax_year = ?, "
            "period_code = ?, due_date = ?, notes = ?, work_status = ?, "
            "filing_status = ?, document_status = ?, tax_status = ?, "
            "fee_status = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL AND updated_at = ?",
            (
                title,
                tax_year,
                period_code,
                due_date,
                notes,
                work_status,
                filing_status,
                document_status,
                tax_status,
                fee_status,
                updated_at,
                item_id,
                expected_updated_at,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_update_stale")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def complete_item(
        self, item_id: int, status: str, exception_reason: str | None
    ) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        if status not in {"completed", "completed_with_exception"}:
            raise ValueError("annual_work.completion_status.invalid")
        timestamp = now_iso()
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET work_status = ?, exception_reason = ?, "
            "completed_at = ?, cancelled_at = NULL, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (status, exception_reason, timestamp, timestamp, item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def reopen_item(self, item_id: int, status: str) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        if status not in WORK_STATUSES - {
            "completed",
            "completed_with_exception",
            "cancelled",
        }:
            raise ValueError("annual_work.work_status.invalid")
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET work_status = ?, completed_at = NULL, "
            "exception_reason = NULL, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (status, now_iso(), item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def cancel_item(self, item_id: int, reason: str) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        timestamp = now_iso()
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET work_status = 'cancelled', "
            "exception_reason = ?, completed_at = NULL, "
            "cancelled_at = COALESCE(cancelled_at, ?), updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (reason, timestamp, timestamp, item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def restore_item(self, item_id: int) -> AnnualWorkItemRow:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        cursor = self._conn.execute(
            "UPDATE annual_work_items SET work_status = 'not_started', "
            "cancelled_at = NULL, completed_at = NULL, exception_reason = NULL, "
            "updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now_iso(), item_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_work.item_not_found")
        row = self.get_item(item_id)
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return row

    def probe_dependencies(self, item_id: int) -> AnnualWorkDependencies:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        row = self._conn.execute(
            "SELECT awi.engagement_id, "
            "EXISTS(SELECT 1 FROM annual_work_transactions tx WHERE tx.work_item_id = awi.id) "
            "AS has_transactions, "
            "EXISTS(SELECT 1 FROM workflow_tasks wt WHERE wt.annual_work_item_id = awi.id) "
            "AS has_tasks FROM annual_work_items awi "
            "WHERE awi.id = ? AND awi.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("annual_work.item_not_found")
        return AnnualWorkDependencies(
            has_transactions=bool(row["has_transactions"]),
            engagement_id=(
                int(row["engagement_id"])
                if row["engagement_id"] is not None
                else None
            ),
            has_tasks=bool(row["has_tasks"]),
        )

    def hard_delete_item(self, item_id: int) -> bool:
        item_id = _positive_id(item_id, "annual_work.item_id.invalid")
        cursor = self._conn.execute(
            "DELETE FROM annual_work_items WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        )
        return cursor.rowcount == 1

    def find_workspace(
        self, client_id: int, operation_year: int
    ) -> AnnualWorkspaceRow | None:
        row = self._conn.execute(
            "SELECT * FROM annual_workspaces "
            "WHERE client_id = ? AND operation_year = ? AND deleted_at IS NULL",
            (client_id, operation_year),
        ).fetchone()
        return _workspace_row(row) if row else None

    def list_workspaces(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "operation_year",
        order_dir: str = "DESC",
    ) -> list[AnnualWorkspaceRow]:
        limit, offset = _pagination(limit, offset)
        column, direction = _sort(order_by, order_dir, self._WORKSPACE_SORT)
        rows = self._conn.execute(
            "SELECT aw.* FROM annual_workspaces aw "
            "JOIN clients c ON c.id = aw.client_id "
            "WHERE aw.deleted_at IS NULL AND c.deleted_at IS NULL "
            f"ORDER BY {column} {direction}, aw.id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_workspace_row(row) for row in rows]

    def insert_workspace(
        self,
        client_id: int,
        operation_year: int,
        fiscal_year_start_month_snapshot: int,
    ) -> AnnualWorkspaceRow:
        timestamp = now_iso()
        cursor = self._conn.execute(
            "INSERT INTO annual_workspaces("
            "client_id, operation_year, fiscal_year_start_month_snapshot, "
            "status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (
                client_id,
                operation_year,
                fiscal_year_start_month_snapshot,
                timestamp,
                timestamp,
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM annual_workspaces WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        if row is None:
            raise RuntimeError("annual_work.insert_workspace.missing")
        return _workspace_row(row)

    def insert_item_if_missing(
        self, workspace_id: int, draft: WorkDraft
    ) -> AnnualWorkItemInsertResult:
        timestamp = now_iso()
        cursor = self._conn.execute(
            "INSERT INTO annual_work_items("
            "workspace_id, item_key, work_type, title, tax_year, period_code, "
            "suggested_due_date, due_date, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(workspace_id, item_key) WHERE deleted_at IS NULL "
            "DO NOTHING RETURNING *",
            (
                workspace_id,
                draft.item_key,
                draft.work_type,
                draft.title,
                draft.tax_year,
                draft.period_code,
                draft.suggested_due_date,
                draft.suggested_due_date,
                timestamp,
                timestamp,
            ),
        )
        row = cursor.fetchone()
        inserted = row is not None
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM annual_work_items "
                "WHERE workspace_id = ? AND item_key = ? AND deleted_at IS NULL",
                (workspace_id, draft.item_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("annual_work.insert_item.missing")
        return AnnualWorkItemInsertResult(row=_item_row(row), inserted=inserted)

    def list_items(
        self,
        workspace_id: int,
        *,
        limit: int = MAX_WORKSPACE_ITEMS,
        offset: int = 0,
    ) -> list[AnnualWorkItemRow]:
        limit, offset = _pagination(limit, offset)
        workspace_id = _positive_id(
            workspace_id, "annual_work.workspace_id.invalid"
        )
        rows = self._conn.execute(
            "SELECT * FROM annual_work_items "
            "WHERE workspace_id = ? AND deleted_at IS NULL "
            "ORDER BY id LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        ).fetchall()
        return [_item_row(row) for row in rows]

    def list_items_for_snapshot(
        self, workspace_id: int
    ) -> list[AnnualWorkItemRow]:
        """Read at most one row beyond the service snapshot bound."""
        workspace_id = _positive_id(
            workspace_id, "annual_work.workspace_id.invalid"
        )
        rows = self._conn.execute(
            "SELECT * FROM annual_work_items "
            "WHERE workspace_id = ? AND deleted_at IS NULL "
            "ORDER BY id LIMIT ?",
            (workspace_id, MAX_WORKSPACE_ITEMS + 1),
        ).fetchall()
        return [_item_row(row) for row in rows]

    def _overview_filter_parts(
        self, filters: Mapping[str, object] | None
    ) -> tuple[list[str], list[object], str | None, str, str]:
        if filters is not None and not isinstance(filters, Mapping):
            raise ValueError("annual_work.filters.invalid")
        values = dict(filters or {})
        if set(values) - self._OVERVIEW_FILTERS:
            raise ValueError("annual_work.filters.invalid")
        order_by = values.pop("order_by", "due_date")
        order_dir = values.pop("order_dir", "ASC")
        column, direction = _sort(order_by, order_dir, self._OVERVIEW_SORT)
        clauses = [
            "aw.deleted_at IS NULL",
            "awi.deleted_at IS NULL",
            "c.deleted_at IS NULL",
        ]
        params: list[object] = []
        if values.get("client_id") is not None:
            clauses.append("aw.client_id = ?")
            params.append(
                _positive_id(values["client_id"], "annual_work.filters.invalid")
            )
        if values.get("operation_year") is not None:
            clauses.append("aw.operation_year = ?")
            params.append(_operation_year(values["operation_year"]))
        if values.get("work_type") is not None:
            work_type = _filter_text(values["work_type"])
            if work_type not in WORK_TYPE_LABELS:
                raise ValueError("annual_work.filters.invalid")
            clauses.append("awi.work_type = ?")
            params.append(work_type)
        exact_columns = {
            "work_status": "awi.work_status",
            "filing_status": "awi.filing_status",
            "document_status": "awi.document_status",
            "tax_status": "awi.tax_status",
            "fee_status": "awi.fee_status",
        }
        for name, column_name in exact_columns.items():
            if values.get(name) is not None:
                if (
                    not isinstance(values[name], str)
                    or values[name] not in STATUS_SETS[name]
                ):
                    raise ValueError("annual_work.filters.invalid")
                clauses.append(f"{column_name} = ?")
                params.append(_filter_text(values[name]))
        risk: str | None = None
        if values.get("risk") is not None:
            if (
                not isinstance(values["risk"], str)
                or values["risk"] not in ANNUAL_OVERVIEW_RISKS
            ):
                raise ValueError("annual_work.filters.invalid")
            risk = values["risk"]
        for name, operator in (("due_from", ">="), ("due_to", "<=")):
            if values.get(name) is not None:
                clauses.append(f"awi.due_date {operator} ?")
                params.append(_filter_date(values[name]))
        if (
            values.get("due_from") is not None
            and values.get("due_to") is not None
            and values["due_from"] > values["due_to"]
        ):
            raise ValueError("annual_work.filters.invalid")
        if values.get("query") is not None:
            query = _filter_text(values["query"], allow_empty=True)
            if query.strip():
                pattern = f"%{_literal_like(query.strip())}%"
                clauses.append(
                    "(c.client_code LIKE ? ESCAPE '\\' "
                    "OR c.client_name LIKE ? ESCAPE '\\' "
                    "OR awi.title LIKE ? ESCAPE '\\' "
                    "OR awi.item_key LIKE ? ESCAPE '\\')"
                )
                params.extend((pattern, pattern, pattern, pattern))
        return clauses, params, risk, column, direction

    def search_overview(
        self,
        filters: Mapping[str, object] | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AnnualWorkOverviewRow]:
        limit, offset = _pagination(limit, offset)
        clauses, params, risk, column, direction = self._overview_filter_parts(
            filters
        )
        outer_clause = ""
        if risk is not None:
            outer_clause = (
                " WHERE annual_exact_balance_risk(?, work_status, document_status, "
                "overview_tax_liability, overview_client_tax_collection, "
                "overview_tax_payment, overview_tax_credit_or_refund, "
                "overview_fee_receivable, overview_fee_receipt) = 1"
            )
            params.append(risk)
        params.extend((limit, offset))
        rows = self._conn.execute(
            "WITH overview AS (SELECT awi.*, aw.client_id AS overview_client_id, "
            "aw.operation_year AS overview_operation_year, "
            "c.client_code AS overview_client_code, "
            "c.client_name AS overview_client_name, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_liability' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_liability, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'client_tax_collection' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_client_tax_collection, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_payment' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_payment, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_credit_or_refund' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_credit_or_refund, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'fee_receivable' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_fee_receivable, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'fee_receipt' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_fee_receipt "
            "FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id "
            "LEFT JOIN annual_work_transactions awt "
            " ON awt.work_item_id = awi.id AND awt.deleted_at IS NULL WHERE "
            + " AND ".join(clauses)
            + " GROUP BY awi.id) SELECT * FROM overview"
            + outer_clause
            + f" ORDER BY {column} {direction}, id ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [
            AnnualWorkOverviewRow(
                item=_item_row(row),
                workspace_client_id=int(row["overview_client_id"]),
                operation_year=int(row["overview_operation_year"]),
                client_code=str(row["overview_client_code"]),
                client_name=str(row["overview_client_name"]),
                balance=AnnualBalance.from_totals(
                    tax_liability=decode_annual_exact_decimal(
                        row["overview_tax_liability"]
                    ),
                    client_tax_collection=decode_annual_exact_decimal(
                        row["overview_client_tax_collection"]
                    ),
                    tax_payment=decode_annual_exact_decimal(
                        row["overview_tax_payment"]
                    ),
                    tax_credit_or_refund=decode_annual_exact_decimal(
                        row["overview_tax_credit_or_refund"]
                    ),
                    fee_receivable=decode_annual_exact_decimal(
                        row["overview_fee_receivable"]
                    ),
                    fee_receipt=decode_annual_exact_decimal(
                        row["overview_fee_receipt"]
                    ),
                ),
            )
            for row in rows
        ]

    def overview_metrics(
        self, filters: Mapping[str, object] | None = None
    ) -> AnnualOverviewMetrics:
        clauses, params, risk, _column, _direction = self._overview_filter_parts(
            filters
        )
        matched_where = ""
        if risk is not None:
            matched_where = (
                " WHERE annual_exact_balance_risk(?, work_status, document_status, "
                "overview_tax_liability, overview_client_tax_collection, "
                "overview_tax_payment, overview_tax_credit_or_refund, "
                "overview_fee_receivable, overview_fee_receipt) = 1"
            )
            params.append(risk)
        row = self._conn.execute(
            "WITH overview AS (SELECT awi.*, aw.client_id AS overview_client_id, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_liability' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_liability, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'client_tax_collection' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_client_tax_collection, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_payment' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_payment, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'tax_credit_or_refund' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_tax_credit_or_refund, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'fee_receivable' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_fee_receivable, "
            "COALESCE(annual_exact_int_sum(CASE "
            " WHEN awt.category = 'fee_receipt' THEN awt.amount ELSE 0 END), '0') "
            " AS overview_fee_receipt FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id "
            "LEFT JOIN annual_work_transactions awt "
            " ON awt.work_item_id = awi.id AND awt.deleted_at IS NULL WHERE "
            + " AND ".join(clauses)
            + " GROUP BY awi.id), matched AS (SELECT * FROM overview"
            + matched_where
            + "), per_item AS (SELECT *, "
            "annual_exact_balance_value('collection_shortfall', "
            "overview_tax_liability, overview_client_tax_collection, "
            "overview_tax_payment, overview_tax_credit_or_refund, "
            "overview_fee_receivable, overview_fee_receipt) AS collection_shortfall, "
            "annual_exact_balance_value('unpaid_tax', "
            "overview_tax_liability, overview_client_tax_collection, "
            "overview_tax_payment, overview_tax_credit_or_refund, "
            "overview_fee_receivable, overview_fee_receipt) AS unpaid_tax, "
            "annual_exact_balance_value('outstanding_fee', "
            "overview_tax_liability, overview_client_tax_collection, "
            "overview_tax_payment, overview_tax_credit_or_refund, "
            "overview_fee_receivable, overview_fee_receipt) AS outstanding_fee "
            "FROM matched) SELECT COUNT(*) AS item_count, "
            "COUNT(DISTINCT overview_client_id) AS client_count, "
            "COALESCE(SUM(work_status IN ('exception', 'completed_with_exception')), 0) "
            " AS exception_count, "
            "COALESCE(SUM(document_status IN ('missing', 'partially_received')), 0) "
            " AS document_risk_count, "
            "COALESCE(annual_exact_decimal_sum(collection_shortfall), '0') "
            " AS collection_shortfall_total, "
            "COALESCE(annual_exact_decimal_sum(unpaid_tax), '0') AS unpaid_tax_total, "
            "COALESCE(annual_exact_decimal_sum(outstanding_fee), '0') "
            " AS outstanding_fee_total, "
            "COALESCE(SUM(annual_exact_balance_risk('overage', work_status, "
            "document_status, overview_tax_liability, "
            "overview_client_tax_collection, overview_tax_payment, "
            "overview_tax_credit_or_refund, overview_fee_receivable, "
            "overview_fee_receipt)), 0) AS overage_count FROM per_item",
            params,
        ).fetchone()
        if row is None:
            return AnnualOverviewMetrics()
        return AnnualOverviewMetrics(
            item_count=int(row["item_count"]),
            client_count=int(row["client_count"]),
            exception_count=int(row["exception_count"]),
            document_risk_count=int(row["document_risk_count"]),
            collection_shortfall_total=decode_annual_exact_decimal(
                row["collection_shortfall_total"]
            ),
            unpaid_tax_total=decode_annual_exact_decimal(
                row["unpaid_tax_total"]
            ),
            outstanding_fee_total=decode_annual_exact_decimal(
                row["outstanding_fee_total"]
            ),
            overage_count=int(row["overage_count"]),
        )
