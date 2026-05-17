"""Migration 0010: attachments + attachment_versions tables."""

SQL = """
CREATE TABLE IF NOT EXISTS attachments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id     INTEGER NOT NULL REFERENCES engagements(id),
    request_id        INTEGER REFERENCES document_requests(id),
    original_filename TEXT    NOT NULL,
    stored_filename   TEXT    NOT NULL,
    file_hash_sha256  TEXT    NOT NULL,
    file_size         INTEGER NOT NULL,
    mime_type         TEXT    NOT NULL,
    extension         TEXT    NOT NULL,
    uploaded_by       TEXT    NOT NULL DEFAULT 'local_user',
    uploaded_at       TEXT    NOT NULL,
    source            TEXT    NOT NULL DEFAULT 'manual',
    status            TEXT    NOT NULL DEFAULT 'uploaded',
    notes             TEXT,
    accepted_by       TEXT,
    accepted_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachments_engagement
    ON attachments(engagement_id);
CREATE INDEX IF NOT EXISTS idx_attachments_request
    ON attachments(request_id);
CREATE INDEX IF NOT EXISTS idx_attachments_status
    ON attachments(status);

CREATE TABLE IF NOT EXISTS attachment_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attachment_id INTEGER NOT NULL REFERENCES attachments(id),
    supersedes_id INTEGER REFERENCES attachments(id),
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachment_versions_attachment
    ON attachment_versions(attachment_id);
"""
