"""Migration 0025: late_fee_records period + payment-date + breakdown columns.

Adds nullable columns so a late-fee calculation can record which 營業稅 period it
belongs to, the last/actual payment dates that drove the result, and the full
penalty-band breakdown JSON for traceability. All columns are NULLable so existing
rows remain valid; no table recreate is needed (SQLite ADD COLUMN in place).
"""

from __future__ import annotations

SQL = """
ALTER TABLE late_fee_records ADD COLUMN period_year INTEGER;
ALTER TABLE late_fee_records ADD COLUMN period_code TEXT;
ALTER TABLE late_fee_records ADD COLUMN last_payment_date TEXT;
ALTER TABLE late_fee_records ADD COLUMN actual_payment_date TEXT;
ALTER TABLE late_fee_records ADD COLUMN penalty_breakdown_json TEXT;
"""
