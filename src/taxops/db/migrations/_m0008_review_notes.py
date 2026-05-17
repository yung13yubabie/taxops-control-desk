"""Migration 0008: review_notes.

Stores internal review comments per engagement. State machine:
open → responded / waived; responded → resolved / waived;
resolved / waived → reopened. Critical notes cannot be waived.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS review_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id   INTEGER NOT NULL REFERENCES engagements(id),
    severity        TEXT    NOT NULL,
    comment         TEXT    NOT NULL,
    assigned_to     TEXT,
    related_task_id INTEGER REFERENCES workflow_tasks(id),
    status          TEXT    NOT NULL DEFAULT 'open',
    response        TEXT,
    waive_reason    TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_notes_engagement ON review_notes(engagement_id);
CREATE INDEX IF NOT EXISTS idx_review_notes_status     ON review_notes(status);
"""
