"""Migration 0017: workflow_tasks.client_id.

Adds a nullable ``client_id`` column on ``workflow_tasks`` so tasks can be
bound to a client without requiring an engagement (e.g. recurring client-level
reminders). Backfills the column for existing rows where ``engagement_id`` is
set so legacy data shows up under client-scoped filters immediately.

ALTER TABLE ADD COLUMN is used (no full table recreate) since SQLite supports
adding nullable columns in place.
"""

from __future__ import annotations

SQL = """
ALTER TABLE workflow_tasks
    ADD COLUMN client_id INTEGER REFERENCES clients(id);

UPDATE workflow_tasks
   SET client_id = (
           SELECT engagements.client_id
             FROM engagements
            WHERE engagements.id = workflow_tasks.engagement_id
       )
 WHERE engagement_id IS NOT NULL
   AND client_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_workflow_tasks_client
    ON workflow_tasks(client_id);
"""
