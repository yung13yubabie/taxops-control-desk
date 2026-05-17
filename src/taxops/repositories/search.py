"""Search repository: FTS5 index management for clients and engagements."""

from __future__ import annotations

import sqlite3

_MAX_RESULTS = 200


def _fts_quote(text: str) -> str:
    """Wrap user query as an FTS5 phrase literal to prevent syntax errors."""
    cleaned = text.replace('"', "").replace("*", "")
    return f'"{cleaned}"'


class SearchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── clients ─────────────────────────────────────────────────────────────

    def add_client(
        self,
        client_id: int,
        *,
        client_code: str,
        client_name: str,
        tax_id: str | None,
        short_name: str | None,
        contact_name: str | None,
        note: str | None,
    ) -> None:
        """Add a new client to the FTS index."""
        try:
            self._conn.execute(
                "INSERT INTO fts_clients(rowid, client_code, client_name, tax_id,"
                " short_name, contact_name, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    client_id,
                    client_code or "",
                    client_name or "",
                    tax_id or "",
                    short_name or "",
                    contact_name or "",
                    note or "",
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_client(
        self,
        client_id: int,
        *,
        client_code: str,
        client_name: str,
        tax_id: str | None,
        short_name: str | None,
        contact_name: str | None,
        note: str | None,
    ) -> None:
        """Update an existing client in the FTS index."""
        try:
            self._conn.execute(
                "DELETE FROM fts_clients WHERE rowid = ?", (client_id,)
            )
            self._conn.execute(
                "INSERT INTO fts_clients(rowid, client_code, client_name, tax_id,"
                " short_name, contact_name, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    client_id,
                    client_code or "",
                    client_name or "",
                    tax_id or "",
                    short_name or "",
                    contact_name or "",
                    note or "",
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def delete_client(self, client_id: int) -> None:
        try:
            self._conn.execute(
                "DELETE FROM fts_clients WHERE rowid = ?", (client_id,)
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def search_client_ids(self, query: str, *, limit: int = _MAX_RESULTS) -> list[int]:
        q = _fts_quote(query)
        rows = self._conn.execute(
            "SELECT rowid FROM fts_clients WHERE fts_clients MATCH ? ORDER BY rank LIMIT ?",
            (q, limit),
        ).fetchall()
        return [row[0] for row in rows]

    def rebuild_clients(self, client_rows: list) -> None:
        try:
            self._conn.execute("DELETE FROM fts_clients")
            for row in client_rows:
                self._conn.execute(
                    "INSERT INTO fts_clients(rowid, client_code, client_name, tax_id,"
                    " short_name, contact_name, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row.id,
                        row.client_code or "",
                        row.client_name or "",
                        row.tax_id or "",
                        row.short_name or "",
                        row.contact_name or "",
                        row.note or "",
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ── engagements ──────────────────────────────────────────────────────────

    def add_engagement(self, engagement_id: int, *, engagement_name: str) -> None:
        """Add a new engagement to the FTS index."""
        try:
            self._conn.execute(
                "INSERT INTO fts_engagements(rowid, engagement_name) VALUES (?, ?)",
                (engagement_id, engagement_name or ""),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_engagement(self, engagement_id: int, *, engagement_name: str) -> None:
        """Update an existing engagement in the FTS index."""
        try:
            self._conn.execute(
                "DELETE FROM fts_engagements WHERE rowid = ?", (engagement_id,)
            )
            self._conn.execute(
                "INSERT INTO fts_engagements(rowid, engagement_name) VALUES (?, ?)",
                (engagement_id, engagement_name or ""),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def delete_engagement(self, engagement_id: int) -> None:
        try:
            self._conn.execute(
                "DELETE FROM fts_engagements WHERE rowid = ?", (engagement_id,)
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def search_engagement_ids(
        self, query: str, *, limit: int = _MAX_RESULTS
    ) -> list[int]:
        q = _fts_quote(query)
        rows = self._conn.execute(
            "SELECT rowid FROM fts_engagements WHERE fts_engagements MATCH ?"
            " ORDER BY rank LIMIT ?",
            (q, limit),
        ).fetchall()
        return [row[0] for row in rows]

    def rebuild_engagements(self, engagement_rows: list) -> None:
        try:
            self._conn.execute("DELETE FROM fts_engagements")
            for row in engagement_rows:
                self._conn.execute(
                    "INSERT INTO fts_engagements(rowid, engagement_name) VALUES (?, ?)",
                    (row.id, row.engagement_name or ""),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
