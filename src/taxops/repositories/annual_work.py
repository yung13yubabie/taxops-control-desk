"""Bounded persistence for annual client-year workspaces and work items."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ..core.compliance import WORK_TYPE_LABELS
from ..core.clock import now_iso
from ..services.compliance_rules import WorkDraft


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
class AnnualWorkOverviewRow:
    item: AnnualWorkItemRow
    workspace_client_id: int
    operation_year: int
    client_code: str
    client_name: str


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
        or not 1 <= limit <= 500
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
    _WORKSPACE_SORT = {
        "id": "aw.id",
        "operation_year": "aw.operation_year",
        "created_at": "aw.created_at",
        "updated_at": "aw.updated_at",
    }
    _OVERVIEW_SORT = {
        "id": "awi.id",
        "operation_year": "aw.operation_year",
        "client_code": "c.client_code",
        "client_name": "c.client_name",
        "due_date": "awi.due_date",
        "work_type": "awi.work_type",
        "work_status": "awi.work_status",
        "updated_at": "awi.updated_at",
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
            "order_by",
            "order_dir",
        }
    )

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

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
        self, workspace_id: int, *, limit: int = 500, offset: int = 0
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

    def search_overview(
        self,
        filters: Mapping[str, object] | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AnnualWorkOverviewRow]:
        limit, offset = _pagination(limit, offset)
        if filters is not None and not isinstance(filters, Mapping):
            raise ValueError("annual_work.filters.invalid")
        values = dict(filters or {})
        unknown = set(values) - self._OVERVIEW_FILTERS
        if unknown:
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
        if "client_id" in values and values["client_id"] is not None:
            clauses.append("aw.client_id = ?")
            params.append(
                _positive_id(values["client_id"], "annual_work.filters.invalid")
            )
        if "operation_year" in values and values["operation_year"] is not None:
            clauses.append("aw.operation_year = ?")
            params.append(_operation_year(values["operation_year"]))
        exact_columns = {
            "work_status": "awi.work_status",
            "filing_status": "awi.filing_status",
            "document_status": "awi.document_status",
            "tax_status": "awi.tax_status",
            "fee_status": "awi.fee_status",
        }
        if "work_type" in values and values["work_type"] is not None:
            work_type = _filter_text(values["work_type"])
            if work_type not in WORK_TYPE_LABELS:
                raise ValueError("annual_work.filters.invalid")
            clauses.append("awi.work_type = ?")
            params.append(work_type)
        for name, column_name in exact_columns.items():
            if name in values and values[name] is not None:
                clauses.append(f"{column_name} = ?")
                params.append(_filter_text(values[name]))
        for name, operator in (("due_from", ">="), ("due_to", "<=")):
            if name in values and values[name] is not None:
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
        params.extend((limit, offset))
        rows = self._conn.execute(
            "SELECT awi.*, aw.client_id AS overview_client_id, "
            "aw.operation_year AS overview_operation_year, "
            "c.client_code AS overview_client_code, "
            "c.client_name AS overview_client_name "
            "FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY {column} {direction}, awi.id ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [
            AnnualWorkOverviewRow(
                item=_item_row(row),
                workspace_client_id=int(row["overview_client_id"]),
                operation_year=int(row["overview_operation_year"]),
                client_code=str(row["overview_client_code"]),
                client_name=str(row["overview_client_name"]),
            )
            for row in rows
        ]
