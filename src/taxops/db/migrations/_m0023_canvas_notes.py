"""Migration 0023: A4 canvas notes for Work Records."""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS canvas_notes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    scene_json       TEXT    NOT NULL,
    client_id        INTEGER REFERENCES clients(id),
    engagement_id    INTEGER REFERENCES engagements(id),
    context_snapshot TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    deleted_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_canvas_notes_context
    ON canvas_notes(client_id, engagement_id);
"""
