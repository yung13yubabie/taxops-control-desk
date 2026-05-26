"""Migration 0018: workflow_tasks.parent_task_id (Slice 21D parent/child).

Self-referential FK supporting a 2-level hierarchy (task → subtask). Depth
is enforced at the service layer, not the schema.
"""

from __future__ import annotations

SQL = """
ALTER TABLE workflow_tasks
    ADD COLUMN parent_task_id INTEGER REFERENCES workflow_tasks(id);

CREATE INDEX IF NOT EXISTS idx_workflow_tasks_parent
    ON workflow_tasks(parent_task_id);
"""
