"""Migration 0004: engagements + document_requests + document_request_items.

3 tables, 7 indexes:
- ``engagements`` — one per client per tax-type per period
- ``document_requests`` — one per engagement per indexed batch
- ``document_request_items`` — line items within a request batch
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS engagements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    engagement_name TEXT    NOT NULL,
    tax_type        TEXT    NOT NULL,
    period_name     TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'draft',
    owner           TEXT,
    due_date        TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    deleted_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_engagements_client   ON engagements(client_id);
CREATE INDEX IF NOT EXISTS idx_engagements_status   ON engagements(status);
CREATE INDEX IF NOT EXISTS idx_engagements_due_date ON engagements(due_date);

CREATE TABLE IF NOT EXISTS document_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id   INTEGER NOT NULL REFERENCES engagements(id),
    tax_type        TEXT    NOT NULL,
    period_name     TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'not_requested',
    due_date        TEXT,
    requested_at    TEXT,
    follow_up_count INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    deleted_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_requests_engagement ON document_requests(engagement_id);
CREATE INDEX IF NOT EXISTS idx_doc_requests_status     ON document_requests(status);
CREATE INDEX IF NOT EXISTS idx_doc_requests_due_date   ON document_requests(due_date);

CREATE TABLE IF NOT EXISTS document_request_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL REFERENCES document_requests(id),
    item_name   TEXT    NOT NULL,
    item_status TEXT    NOT NULL DEFAULT 'missing',
    notes       TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_doc_request_items_request ON document_request_items(request_id);
"""
