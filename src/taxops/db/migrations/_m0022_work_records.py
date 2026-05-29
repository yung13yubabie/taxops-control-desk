"""Migration 0022: work records workflow templates/runs and error reviews."""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS workflow_templates_v2 (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    stages_json      TEXT    NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    client_id        INTEGER REFERENCES clients(id),
    engagement_id    INTEGER REFERENCES engagements(id),
    context_snapshot TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    deleted_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflow_templates_v2_context
    ON workflow_templates_v2(client_id, engagement_id);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id      INTEGER REFERENCES workflow_templates_v2(id),
    name             TEXT    NOT NULL,
    stages_json      TEXT    NOT NULL,
    client_id        INTEGER REFERENCES clients(id),
    engagement_id    INTEGER REFERENCES engagements(id),
    context_snapshot TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    deleted_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_template
    ON workflow_runs(template_id);

CREATE TABLE IF NOT EXISTS error_reviews (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT    NOT NULL,
    phenomenon           TEXT    NOT NULL,
    root_cause           TEXT    NOT NULL,
    short_term_fix       TEXT,
    long_term_guard      TEXT,
    severity             TEXT    NOT NULL,
    workflow_template_id INTEGER REFERENCES workflow_templates_v2(id),
    guard_stage_id       TEXT,
    guard_step_text      TEXT,
    client_id            INTEGER REFERENCES clients(id),
    engagement_id        INTEGER REFERENCES engagements(id),
    context_snapshot     TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL,
    deleted_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_error_reviews_template
    ON error_reviews(workflow_template_id);
"""
