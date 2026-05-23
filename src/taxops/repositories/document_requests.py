"""Document requests + items repository.

Parameterized SQL only. No business validation here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class DocumentRequestRow:
    id: int
    engagement_id: int
    tax_type: str
    period_name: str
    status: str
    due_date: str | None
    requested_at: str | None
    follow_up_count: int
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


@dataclass(frozen=True)
class DocumentRequestItemRow:
    id: int
    request_id: int
    item_name: str
    item_status: str
    notes: str | None
    created_at: str
    updated_at: str


def _row_to_request(row: sqlite3.Row) -> DocumentRequestRow:
    keys = row.keys()
    return DocumentRequestRow(
        id=row["id"],
        engagement_id=row["engagement_id"],
        tax_type=row["tax_type"],
        period_name=row["period_name"],
        status=row["status"],
        due_date=row["due_date"],
        requested_at=row["requested_at"],
        follow_up_count=row["follow_up_count"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"] if "deleted_at" in keys else None,
    )


def _row_to_item(row: sqlite3.Row) -> DocumentRequestItemRow:
    return DocumentRequestItemRow(
        id=row["id"],
        request_id=row["request_id"],
        item_name=row["item_name"],
        item_status=row["item_status"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class DocumentRequestsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- document_requests ---

    def insert_request(
        self,
        *,
        engagement_id: int,
        tax_type: str,
        period_name: str,
        status: str = "not_requested",
        due_date: str | None = None,
        notes: str | None = None,
    ) -> DocumentRequestRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO document_requests("
            "engagement_id, tax_type, period_name, status,"
            " due_date, requested_at, follow_up_count, notes, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?, ?)",
            (engagement_id, tax_type, period_name, status, due_date, notes, ts, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("document_requests.insert: lastrowid missing")
        got = self.get_request(new_id)
        if got is None:
            raise RuntimeError("document_requests.insert: row missing after insert")
        return got

    def get_request(self, request_id: int) -> DocumentRequestRow | None:
        row = self._conn.execute(
            "SELECT * FROM document_requests WHERE id = ? AND deleted_at IS NULL",
            (request_id,),
        ).fetchone()
        return _row_to_request(row) if row else None

    def list_all(self) -> list[DocumentRequestRow]:
        rows = self._conn.execute(
            "SELECT * FROM document_requests WHERE deleted_at IS NULL ORDER BY created_at ASC"
        ).fetchall()
        return [_row_to_request(r) for r in rows]

    def list_by_engagement(self, engagement_id: int) -> list[DocumentRequestRow]:
        rows = self._conn.execute(
            "SELECT * FROM document_requests"
            " WHERE engagement_id = ? AND deleted_at IS NULL"
            " ORDER BY created_at ASC",
            (engagement_id,),
        ).fetchall()
        return [_row_to_request(r) for r in rows]

    def update_request_status(
        self,
        request_id: int,
        *,
        status: str,
        requested_at: str | None = None,
    ) -> DocumentRequestRow | None:
        ts = now_iso()
        if requested_at is not None:
            self._conn.execute(
                "UPDATE document_requests SET status = ?, requested_at = ?, updated_at = ?"
                " WHERE id = ? AND deleted_at IS NULL",
                (status, requested_at, ts, request_id),
            )
        else:
            self._conn.execute(
                "UPDATE document_requests SET status = ?, updated_at = ?"
                " WHERE id = ? AND deleted_at IS NULL",
                (status, ts, request_id),
            )
        self._conn.commit()
        return self.get_request(request_id)

    def increment_follow_up(self, request_id: int) -> DocumentRequestRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE document_requests"
            " SET follow_up_count = follow_up_count + 1, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (ts, request_id),
        )
        self._conn.commit()
        return self.get_request(request_id)

    def delete_request(self, request_id: int) -> bool:
        ts = now_iso()
        cur = self._conn.execute(
            "UPDATE document_requests SET deleted_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (ts, request_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # --- document_request_items ---

    def insert_item(
        self,
        *,
        request_id: int,
        item_name: str,
        item_status: str = "missing",
        notes: str | None = None,
    ) -> DocumentRequestItemRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO document_request_items("
            "request_id, item_name, item_status, notes, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (request_id, item_name, item_status, notes, ts, ts),
        )
        self._conn.commit()
        new_id = cur.lastrowid
        if new_id is None:
            raise RuntimeError("document_request_items.insert: lastrowid missing")
        got = self.get_item(new_id)
        if got is None:
            raise RuntimeError("document_request_items.insert: row missing after insert")
        return got

    def get_item(self, item_id: int) -> DocumentRequestItemRow | None:
        row = self._conn.execute(
            "SELECT * FROM document_request_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        return _row_to_item(row) if row else None

    def list_items(self, request_id: int) -> list[DocumentRequestItemRow]:
        rows = self._conn.execute(
            "SELECT * FROM document_request_items WHERE request_id = ? ORDER BY id ASC",
            (request_id,),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def update_item_status(
        self,
        item_id: int,
        *,
        item_status: str,
        notes: str | None = None,
    ) -> DocumentRequestItemRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE document_request_items SET item_status = ?, notes = ?, updated_at = ?"
            " WHERE id = ?",
            (item_status, notes, ts, item_id),
        )
        self._conn.commit()
        return self.get_item(item_id)

    # --- atomic batch insert ---

    def insert_request_with_items(
        self,
        *,
        engagement_id: int,
        tax_type: str,
        period_name: str,
        status: str = "not_requested",
        due_date: str | None = None,
        notes: str | None = None,
        item_names: tuple[str, ...] = (),
    ) -> tuple[DocumentRequestRow, list[DocumentRequestItemRow]]:
        """Insert request + items in a single transaction.

        On any failure the entire batch is rolled back.
        """
        ts = now_iso()
        try:
            cur = self._conn.execute(
                "INSERT INTO document_requests("
                "engagement_id, tax_type, period_name, status,"
                " due_date, requested_at, follow_up_count, notes, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?, ?)",
                (engagement_id, tax_type, period_name, status, due_date, notes, ts, ts),
            )
            request_id = cur.lastrowid
            item_ids: list[int] = []
            for name in item_names:
                ic = self._conn.execute(
                    "INSERT INTO document_request_items("
                    "request_id, item_name, item_status, notes, created_at, updated_at"
                    ") VALUES (?, ?, 'missing', NULL, ?, ?)",
                    (request_id, name, ts, ts),
                )
                if ic.lastrowid is None:
                    raise RuntimeError("insert_request_with_items: item lastrowid missing")
                item_ids.append(ic.lastrowid)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        request = self.get_request(request_id)
        if request is None:
            raise RuntimeError("insert_request_with_items: request missing after commit")
        items = [self.get_item(iid) for iid in item_ids]
        return request, [i for i in items if i is not None]

    # --- export query ---

    def list_missing_items_for_export(
        self,
        engagement_id: int | None = None,
    ) -> list[dict]:
        """Return missing-item rows joined with request/engagement/client data.

        Filters to items with status in (missing, incomplete, invalid, pending_confirm).
        When *engagement_id* is given, scope to that engagement only.
        Returns plain dicts so the service layer can pass them to openpyxl without
        importing repository types.
        """
        _MISSING_STATUSES = ("missing", "incomplete", "invalid", "pending_confirm")
        placeholders = ",".join("?" * len(_MISSING_STATUSES))
        params: list = list(_MISSING_STATUSES)

        where_extra = ""
        if engagement_id is not None:
            where_extra = " AND e.id = ?"
            params.append(engagement_id)

        sql = (
            "SELECT"
            "  c.client_code,"
            "  c.client_name,"
            "  COALESCE(c.tax_id, '') AS tax_id,"
            "  e.engagement_name,"
            "  dr.tax_type,"
            "  dr.period_name,"
            "  dri.item_name,"
            "  dri.item_status,"
            "  COALESCE(e.owner, '') AS owner,"
            "  COALESCE(dr.due_date, '') AS due_date,"
            "  COALESCE(dr.requested_at, '') AS requested_at,"
            "  dr.follow_up_count,"
            "  COALESCE(dri.notes, '') AS notes"
            " FROM document_request_items dri"
            " JOIN document_requests dr ON dr.id = dri.request_id"
            " JOIN engagements e ON e.id = dr.engagement_id"
            " JOIN clients c ON c.id = e.client_id"
            f" WHERE dri.item_status IN ({placeholders})"
            "  AND dr.deleted_at IS NULL"
            "  AND e.deleted_at IS NULL"
            f"{where_extra}"
            " ORDER BY c.client_code, e.engagement_name, dr.id, dri.id"
            " LIMIT 100000"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- FK existence checks ---

    def engagement_exists(self, engagement_id: int) -> bool:
        row = self._conn.execute(
            "SELECT id FROM engagements WHERE id = ? AND deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return row is not None
