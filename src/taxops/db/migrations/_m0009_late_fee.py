"""Migration 0009: late_fee_records.

Stores late-fee calculation snapshots per document request.
penalty_percent is 0 for labor_health tax type (needs_manual_review=1).
Formula: units = (overdue_days - 1) // 3; penalty_percent = min(units, 10);
no penalty when overdue_days <= 3.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS late_fee_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id          INTEGER NOT NULL REFERENCES document_requests(id),
    overdue_days        INTEGER NOT NULL,
    penalty_percent     REAL    NOT NULL,
    base_amount         REAL    NOT NULL,
    penalty_amount      REAL    NOT NULL,
    tax_type            TEXT    NOT NULL,
    needs_manual_review INTEGER NOT NULL DEFAULT 0,
    calc_at             TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_late_fee_records_request ON late_fee_records(request_id);
"""
