"""Migration 0027: expand client master data and attachment ownership for v0.30."""

from __future__ import annotations

SQL = """
ALTER TABLE clients ADD COLUMN registered_address TEXT;
ALTER TABLE clients ADD COLUMN contact_address TEXT;
ALTER TABLE clients ADD COLUMN contact_address_same INTEGER NOT NULL DEFAULT 1
    CHECK(contact_address_same IN (0, 1));

UPDATE clients
   SET registered_address = address,
       contact_address = address
 WHERE address IS NOT NULL;

CREATE TABLE client_leases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    lease_name TEXT NOT NULL,
    premises_address TEXT,
    landlord_name TEXT,
    start_date TEXT,
    end_date TEXT,
    monthly_rent INTEGER CHECK(monthly_rent IS NULL OR monthly_rent >= 0),
    deposit_amount INTEGER CHECK(deposit_amount IS NULL OR deposit_amount >= 0),
    reminder_days INTEGER NOT NULL DEFAULT 60
        CHECK(reminder_days BETWEEN 0 AND 3650),
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(id, client_id)
);

CREATE INDEX idx_client_leases_client ON client_leases(client_id);
CREATE INDEX idx_client_leases_end_date ON client_leases(end_date);

INSERT INTO client_leases(
    client_id, lease_name, start_date, end_date, status, created_at, updated_at
)
SELECT id, '既有租約', lease_start, lease_end, 'active',
       COALESCE(created_at, updated_at, datetime('now')),
       COALESCE(updated_at, created_at, datetime('now'))
 FROM clients
 WHERE lease_start IS NOT NULL OR lease_end IS NOT NULL;

CREATE TABLE client_industries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    industry_code TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    source_version TEXT,
    applied_at TEXT NOT NULL,
    UNIQUE(client_id, industry_code)
);

CREATE INDEX idx_client_industries_client
    ON client_industries(client_id, sort_order);

CREATE TEMP TABLE _m0027_sequence_high_water (
    name TEXT PRIMARY KEY,
    seq INTEGER NOT NULL
);

INSERT INTO _m0027_sequence_high_water(name, seq)
SELECT 'attachments', MAX(
    COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'attachments'), 0),
    COALESCE((SELECT MAX(id) FROM attachments), 0)
);

INSERT INTO _m0027_sequence_high_water(name, seq)
SELECT 'attachment_versions', MAX(
    COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'attachment_versions'), 0),
    COALESCE((SELECT MAX(id) FROM attachment_versions), 0)
);

CREATE TABLE attachments_v030_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id INTEGER REFERENCES engagements(id),
    request_id INTEGER REFERENCES document_requests(id),
    client_id INTEGER REFERENCES clients(id),
    lease_id INTEGER,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_hash_sha256 TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    uploaded_by TEXT NOT NULL DEFAULT 'local_user',
    uploaded_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'uploaded',
    notes TEXT,
    accepted_by TEXT,
    accepted_at TEXT,
    FOREIGN KEY(lease_id, client_id) REFERENCES client_leases(id, client_id),
    CHECK(
        (engagement_id IS NOT NULL AND client_id IS NULL AND lease_id IS NULL)
        OR
        (engagement_id IS NULL AND request_id IS NULL
         AND client_id IS NOT NULL AND lease_id IS NOT NULL)
    )
);

INSERT INTO attachments_v030_new(
    id, engagement_id, request_id, original_filename, stored_filename,
    file_hash_sha256, file_size, mime_type, extension, uploaded_by,
    uploaded_at, source, status, notes, accepted_by, accepted_at
)
SELECT id, engagement_id, request_id, original_filename, stored_filename,
       file_hash_sha256, file_size, mime_type, extension, uploaded_by,
       uploaded_at, source, status, notes, accepted_by, accepted_at
  FROM attachments;

CREATE TABLE attachment_versions_v030_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attachment_id INTEGER NOT NULL REFERENCES attachments_v030_new(id),
    supersedes_id INTEGER REFERENCES attachments_v030_new(id),
    created_at TEXT NOT NULL
);

INSERT INTO attachment_versions_v030_new(
    id, attachment_id, supersedes_id, created_at
)
SELECT id, attachment_id, supersedes_id, created_at
  FROM attachment_versions;

DROP TABLE attachment_versions;
DROP TABLE attachments;
ALTER TABLE attachments_v030_new RENAME TO attachments;
ALTER TABLE attachment_versions_v030_new RENAME TO attachment_versions;

DELETE FROM sqlite_sequence
 WHERE name IN ('attachments', 'attachment_versions');
INSERT INTO sqlite_sequence(name, seq)
SELECT name, seq FROM _m0027_sequence_high_water;
DROP TABLE _m0027_sequence_high_water;

CREATE INDEX idx_attachments_engagement ON attachments(engagement_id);
CREATE INDEX idx_attachments_request ON attachments(request_id);
CREATE INDEX idx_attachments_client ON attachments(client_id);
CREATE INDEX idx_attachments_lease ON attachments(lease_id);
CREATE INDEX idx_attachments_status ON attachments(status);
CREATE INDEX idx_attachment_versions_attachment
    ON attachment_versions(attachment_id);
"""
