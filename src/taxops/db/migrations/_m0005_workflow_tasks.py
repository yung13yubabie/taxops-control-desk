"""Migration 0005: workflow_tasks.

One task per engagement with priority, status, assignee, due_date, and
optional next_step note. Soft-deleted via deleted_at.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS workflow_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id   INTEGER NOT NULL REFERENCES engagements(id),
    title           TEXT    NOT NULL,
    assignee        TEXT,
    due_date        TEXT,
    priority        TEXT    NOT NULL DEFAULT 'normal',
    status          TEXT    NOT NULL DEFAULT 'todo',
    next_step       TEXT,
    notes           TEXT,
    completed_at    TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    deleted_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflow_tasks_engagement ON workflow_tasks(engagement_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_status     ON workflow_tasks(status);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_due_date   ON workflow_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_assignee   ON workflow_tasks(assignee);
"""
