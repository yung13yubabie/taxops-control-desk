"""Migration 0021: document_requests.request_name.

Adds a user-facing batch name for document request batches. Existing rows are
backfilled from period and tax type so legacy data remains readable.
"""

from __future__ import annotations

SQL = """
ALTER TABLE document_requests
    ADD COLUMN request_name TEXT;

UPDATE document_requests
   SET request_name = TRIM(period_name || ' ' || tax_type || ' request')
 WHERE request_name IS NULL
    OR TRIM(request_name) = '';

CREATE INDEX IF NOT EXISTS idx_doc_requests_request_name
    ON document_requests(request_name);
"""
