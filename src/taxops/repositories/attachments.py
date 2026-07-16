"""Repository for attachments and attachment_versions tables."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso

_ATTACHMENT_COLUMNS = (
    "id, engagement_id, request_id, client_id, lease_id, original_filename, "
    "stored_filename, file_hash_sha256, file_size, mime_type, extension, "
    "uploaded_by, uploaded_at, source, status, notes, accepted_by, accepted_at"
)

_ACTIVE_ATTACHMENT_OWNER_SQL = (
    "((attachments.engagement_id IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM engagements e"
    " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
    " WHERE e.id = attachments.engagement_id AND e.deleted_at IS NULL))"
    " OR (attachments.lease_id IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM client_leases l"
    " JOIN clients c ON c.id = l.client_id AND c.deleted_at IS NULL"
    " WHERE l.id = attachments.lease_id"
    " AND l.client_id = attachments.client_id)))"
)


@dataclass(frozen=True)
class AttachmentRow:
    id: int
    engagement_id: int | None
    request_id: int | None
    original_filename: str
    stored_filename: str
    file_hash_sha256: str
    file_size: int
    mime_type: str
    extension: str
    uploaded_by: str
    uploaded_at: str
    source: str
    status: str
    notes: str | None
    accepted_by: str | None
    accepted_at: str | None
    client_id: int | None = None
    lease_id: int | None = None


@dataclass(frozen=True)
class AttachmentVersionRow:
    id: int
    attachment_id: int
    supersedes_id: int | None
    created_at: str


def _row(r: sqlite3.Row) -> AttachmentRow:
    return AttachmentRow(
        id=r["id"],
        engagement_id=r["engagement_id"],
        request_id=r["request_id"],
        client_id=r["client_id"],
        lease_id=r["lease_id"],
        original_filename=r["original_filename"],
        stored_filename=r["stored_filename"],
        file_hash_sha256=r["file_hash_sha256"],
        file_size=r["file_size"],
        mime_type=r["mime_type"],
        extension=r["extension"],
        uploaded_by=r["uploaded_by"],
        uploaded_at=r["uploaded_at"],
        source=r["source"],
        status=r["status"],
        notes=r["notes"],
        accepted_by=r["accepted_by"],
        accepted_at=r["accepted_at"],
    )


class AttachmentsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        engagement_id: int,
        request_id: int | None,
        original_filename: str,
        stored_filename: str,
        file_hash_sha256: str,
        file_size: int,
        mime_type: str,
        extension: str,
        uploaded_by: str = "local_user",
        source: str = "manual",
        notes: str | None = None,
    ) -> AttachmentRow:
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO attachments
                (engagement_id, request_id, original_filename, stored_filename,
                 file_hash_sha256, file_size, mime_type, extension,
                 uploaded_by, uploaded_at, source, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
            """,
            (
                engagement_id, request_id, original_filename, stored_filename,
                file_hash_sha256, file_size, mime_type, extension,
                uploaded_by, now, source, notes,
            ),
        )
        attachment_id = cur.lastrowid
        return self.get(attachment_id)  # type: ignore[arg-type]

    def insert_version(
        self,
        attachment_id: int,
        supersedes_id: int | None = None,
    ) -> AttachmentVersionRow:
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO attachment_versions (attachment_id, supersedes_id, created_at)
            VALUES (?, ?, ?)
            """,
            (attachment_id, supersedes_id, now),
        )
        version_id = cur.lastrowid
        r = self._conn.execute(
            "SELECT * FROM attachment_versions WHERE id = ?", (version_id,)
        ).fetchone()
        return AttachmentVersionRow(
            id=r["id"],
            attachment_id=r["attachment_id"],
            supersedes_id=r["supersedes_id"],
            created_at=r["created_at"],
        )

    def insert_with_version(
        self,
        engagement_id: int,
        request_id: int | None,
        original_filename: str,
        stored_filename: str,
        file_hash_sha256: str,
        file_size: int,
        mime_type: str,
        extension: str,
        uploaded_by: str = "local_user",
        source: str = "manual",
        notes: str | None = None,
    ) -> AttachmentRow:
        """Insert attachment and first version in a single transaction."""
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO attachments
                (engagement_id, request_id, original_filename, stored_filename,
                 file_hash_sha256, file_size, mime_type, extension,
                 uploaded_by, uploaded_at, source, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
            """,
            (
                engagement_id, request_id, original_filename, stored_filename,
                file_hash_sha256, file_size, mime_type, extension,
                uploaded_by, now, source, notes,
            ),
        )
        attachment_id = cur.lastrowid
        self._conn.execute(
            "INSERT INTO attachment_versions (attachment_id, supersedes_id, created_at)"
            " VALUES (?, ?, ?)",
            (attachment_id, None, now),
        )
        return self.get(attachment_id)  # type: ignore[return-value]

    def request_belongs_to_engagement(
        self, request_id: int, engagement_id: int
    ) -> bool:
        r = self._conn.execute(
            "SELECT 1 FROM document_requests dr"
            " JOIN engagements e ON e.id = dr.engagement_id AND e.deleted_at IS NULL"
            " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
            " WHERE dr.id = ? AND dr.engagement_id = ? AND dr.deleted_at IS NULL",
            (request_id, engagement_id),
        ).fetchone()
        return r is not None

    def get(self, attachment_id: int) -> AttachmentRow | None:
        r = self._conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE id = ?"
            f" AND {_ACTIVE_ATTACHMENT_OWNER_SQL}",
            (attachment_id,),
        ).fetchone()
        return _row(r) if r else None

    def list_by_engagement(
        self, engagement_id: int, *, include_archived: bool = False
    ) -> list[AttachmentRow]:
        where = (
            "engagement_id = ?"
            if include_archived
            else "engagement_id = ? AND status != 'archived'"
        )
        rows = self._conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE {where}"
            f" AND {_ACTIVE_ATTACHMENT_OWNER_SQL}"
            " ORDER BY uploaded_at DESC",
            (engagement_id,),
        ).fetchall()
        return [_row(r) for r in rows]

    def list_all(self) -> list[AttachmentRow]:
        rows = self._conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE status != 'archived'"
            f" AND {_ACTIVE_ATTACHMENT_OWNER_SQL}"
            " ORDER BY uploaded_at DESC"
        ).fetchall()
        return [_row(r) for r in rows]

    def list_by_request(
        self, request_id: int, *, include_archived: bool = False
    ) -> list[AttachmentRow]:
        where = (
            "request_id = ?"
            if include_archived
            else "request_id = ? AND status != 'archived'"
        )
        rows = self._conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE {where}"
            f" AND {_ACTIVE_ATTACHMENT_OWNER_SQL}"
            " ORDER BY uploaded_at DESC",
            (request_id,),
        ).fetchall()
        return [_row(r) for r in rows]

    def update_status(
        self,
        attachment_id: int,
        status: str,
        accepted_by: str | None = None,
        accepted_at: str | None = None,
    ) -> AttachmentRow | None:
        self._conn.execute(
            """
            UPDATE attachments
               SET status = ?, accepted_by = ?, accepted_at = ?
             WHERE id = ?
            """,
            (status, accepted_by, accepted_at, attachment_id),
        )
        return self.get(attachment_id)

    def engagement_exists(self, engagement_id: int) -> bool:
        r = self._conn.execute(
            "SELECT 1 FROM engagements e"
            " JOIN clients c ON c.id = e.client_id AND c.deleted_at IS NULL"
            " WHERE e.id = ? AND e.deleted_at IS NULL",
            (engagement_id,),
        ).fetchone()
        return r is not None

    def lease_belongs_to_active_client(self, client_id: int, lease_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM client_leases l"
            " JOIN clients c ON c.id = l.client_id AND c.deleted_at IS NULL"
            " WHERE l.id = ? AND l.client_id = ? AND l.deleted_at IS NULL",
            (lease_id, client_id),
        ).fetchone()
        return row is not None

    def insert_for_lease(
        self,
        *,
        client_id: int,
        lease_id: int,
        original_filename: str,
        stored_filename: str,
        file_hash_sha256: str,
        file_size: int,
        mime_type: str,
        extension: str,
        uploaded_by: str = "local_user",
        source: str = "manual",
        notes: str | None = None,
    ) -> AttachmentRow:
        now = now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO attachments(
                engagement_id, request_id, client_id, lease_id,
                original_filename, stored_filename, file_hash_sha256,
                file_size, mime_type, extension, uploaded_by, uploaded_at,
                source, status, notes
            ) VALUES (NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
            """,
            (
                client_id,
                lease_id,
                original_filename,
                stored_filename,
                file_hash_sha256,
                file_size,
                mime_type,
                extension,
                uploaded_by,
                now,
                source,
                notes,
            ),
        )
        attachment_id = int(cur.lastrowid or 0)
        self._conn.execute(
            "INSERT INTO attachment_versions (attachment_id, supersedes_id, created_at)"
            " VALUES (?, NULL, ?)",
            (attachment_id, now),
        )
        row = self.get(attachment_id)
        if row is None:
            raise RuntimeError("attachments.insert_for_lease: row missing after insert")
        return row

    def list_by_lease(
        self, lease_id: int, *, include_archived: bool = False
    ) -> list[AttachmentRow]:
        archived_sql = "" if include_archived else " AND status != 'archived'"
        rows = self._conn.execute(
            f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments"
            f" WHERE lease_id = ?{archived_sql} AND {_ACTIVE_ATTACHMENT_OWNER_SQL}"
            " ORDER BY uploaded_at DESC, id DESC",
            (lease_id,),
        ).fetchall()
        return [_row(row) for row in rows]
