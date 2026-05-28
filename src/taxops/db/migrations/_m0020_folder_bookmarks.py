"""Migration 0020: folder_bookmarks (Slice 24 / v0.15.1).

Replaces the retired review_notes feature with a lightweight folder
bookmarks page. Stores user-curated shortcuts to local or UNC paths
that the user can open on demand via QDesktopServices.openUrl.

Soft-delete via deleted_at — same pattern as engagements / tasks.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS folder_bookmarks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    category   TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_folder_bookmarks_category
    ON folder_bookmarks(category);
CREATE INDEX IF NOT EXISTS idx_folder_bookmarks_sort
    ON folder_bookmarks(sort_order, id);
"""
