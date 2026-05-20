"""Migration 0014: make workflow_tasks.engagement_id nullable.

Allows creating standalone tasks not yet tied to an engagement.
Table is recreated because SQLite does not support removing NOT NULL
from an existing column via ALTER TABLE.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS workflow_tasks_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id   INTEGER REFERENCES engagements(id),
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

INSERT INTO workflow_tasks_v2
    SELECT id, engagement_id, title, assignee, due_date, priority, status,
           next_step, notes, completed_at, created_at, updated_at, deleted_at
    FROM workflow_tasks;

DROP TABLE workflow_tasks;

ALTER TABLE workflow_tasks_v2 RENAME TO workflow_tasks;

CREATE INDEX IF NOT EXISTS idx_workflow_tasks_engagement ON workflow_tasks(engagement_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_status     ON workflow_tasks(status);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_due_date   ON workflow_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_assignee   ON workflow_tasks(assignee);
"""
