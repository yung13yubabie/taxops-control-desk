"""Folder bookmarks repository (Slice 24 / v0.15.1)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FolderBookmarkRow:
    id: int
    name: str
    path: str
    category: str | None
    sort_order: int
    created_at: str
    updated_at: str


def _row_to_bookmark(row: sqlite3.Row) -> FolderBookmarkRow:
    return FolderBookmarkRow(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        category=row["category"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class FolderBookmarksRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_all(self) -> list[FolderBookmarkRow]:
        cur = self._conn.execute(
            "SELECT id, name, path, category, sort_order, created_at, updated_at "
            "FROM folder_bookmarks WHERE deleted_at IS NULL "
            "ORDER BY sort_order, id"
        )
        return [_row_to_bookmark(r) for r in cur.fetchall()]

    def list_by_category(self, category: str | None) -> list[FolderBookmarkRow]:
        if category is None:
            cur = self._conn.execute(
                "SELECT id, name, path, category, sort_order, created_at, updated_at "
                "FROM folder_bookmarks "
                "WHERE deleted_at IS NULL AND category IS NULL "
                "ORDER BY sort_order, id"
            )
        else:
            cur = self._conn.execute(
                "SELECT id, name, path, category, sort_order, created_at, updated_at "
                "FROM folder_bookmarks "
                "WHERE deleted_at IS NULL AND category = ? "
                "ORDER BY sort_order, id",
                (category,),
            )
        return [_row_to_bookmark(r) for r in cur.fetchall()]

    def get(self, bookmark_id: int) -> FolderBookmarkRow | None:
        cur = self._conn.execute(
            "SELECT id, name, path, category, sort_order, created_at, updated_at "
            "FROM folder_bookmarks WHERE id = ? AND deleted_at IS NULL",
            (bookmark_id,),
        )
        row = cur.fetchone()
        return _row_to_bookmark(row) if row else None

    def insert(
        self,
        *,
        name: str,
        path: str,
        category: str | None,
        sort_order: int,
        timestamp: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO folder_bookmarks "
            "(name, path, category, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, path, category, sort_order, timestamp, timestamp),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update(
        self,
        *,
        bookmark_id: int,
        name: str,
        path: str,
        category: str | None,
        sort_order: int,
        timestamp: str,
    ) -> int:
        cur = self._conn.execute(
            "UPDATE folder_bookmarks "
            "SET name = ?, path = ?, category = ?, sort_order = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (name, path, category, sort_order, timestamp, bookmark_id),
        )
        self._conn.commit()
        return cur.rowcount

    def soft_delete(self, bookmark_id: int, timestamp: str) -> int:
        cur = self._conn.execute(
            "UPDATE folder_bookmarks SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (timestamp, bookmark_id),
        )
        self._conn.commit()
        return cur.rowcount

    def list_categories(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT category FROM folder_bookmarks "
            "WHERE deleted_at IS NULL AND category IS NOT NULL "
            "ORDER BY category"
        )
        return [r["category"] for r in cur.fetchall()]
