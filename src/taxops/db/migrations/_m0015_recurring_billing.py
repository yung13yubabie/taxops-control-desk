"""Migration 0015: recurring billing plans, lines, and occurrences."""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS recurring_billing_plans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER NOT NULL REFERENCES clients(id),
    plan_name           TEXT    NOT NULL,
    contract_ref        TEXT,
    frequency           TEXT    NOT NULL DEFAULT 'monthly',
    issue_day           INTEGER NOT NULL DEFAULT 1,
    months_json         TEXT    NOT NULL DEFAULT '[]',
    start_date          TEXT    NOT NULL,
    end_date            TEXT,
    advance_notice_days INTEGER NOT NULL DEFAULT 7,
    status              TEXT    NOT NULL DEFAULT 'active',
    notes               TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    deleted_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_recurring_billing_plans_client
    ON recurring_billing_plans(client_id);
CREATE INDEX IF NOT EXISTS idx_recurring_billing_plans_status
    ON recurring_billing_plans(status);

CREATE TABLE IF NOT EXISTS recurring_billing_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id      INTEGER NOT NULL REFERENCES recurring_billing_plans(id),
    bill_to_name TEXT    NOT NULL,
    description  TEXT,
    amount_cents INTEGER NOT NULL,
    tax_type     TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recurring_billing_lines_plan
    ON recurring_billing_lines(plan_id);

CREATE TABLE IF NOT EXISTS recurring_billing_occurrences (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id                INTEGER NOT NULL REFERENCES recurring_billing_plans(id),
    line_id                INTEGER NOT NULL REFERENCES recurring_billing_lines(id),
    expected_issue_date    TEXT    NOT NULL,
    status                 TEXT    NOT NULL DEFAULT 'pending',
    confirmed_invoice_no   TEXT,
    confirmed_issue_date   TEXT,
    confirmed_amount_cents INTEGER,
    confirmed_at           TEXT,
    skipped_reason         TEXT,
    notes                  TEXT,
    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL,
    UNIQUE(line_id, expected_issue_date)
);

CREATE INDEX IF NOT EXISTS idx_recurring_billing_occurrences_date
    ON recurring_billing_occurrences(expected_issue_date);
CREATE INDEX IF NOT EXISTS idx_recurring_billing_occurrences_status
    ON recurring_billing_occurrences(status);
CREATE INDEX IF NOT EXISTS idx_recurring_billing_occurrences_plan
    ON recurring_billing_occurrences(plan_id);
"""
