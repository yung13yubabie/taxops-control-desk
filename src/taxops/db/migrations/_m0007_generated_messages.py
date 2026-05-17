"""Migration 0007: generated_messages.

Stores the rendered body of each message generated from a template +
document request. Append-only (no soft-delete, no update).
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS generated_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      INTEGER NOT NULL REFERENCES document_requests(id),
    template_id     INTEGER NOT NULL REFERENCES message_templates(id),
    body            TEXT    NOT NULL,
    generated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generated_messages_request
    ON generated_messages(request_id);
"""
