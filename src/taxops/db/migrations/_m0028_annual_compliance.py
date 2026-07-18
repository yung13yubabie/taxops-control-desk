"""Migration 0028: annual compliance profiles, work, and transaction ledger."""

from __future__ import annotations

SQL = """
CREATE TABLE compliance_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id),
    fiscal_year_start_month INTEGER NOT NULL DEFAULT 1
        CHECK(typeof(fiscal_year_start_month) = 'integer'
              AND fiscal_year_start_month BETWEEN 1 AND 12),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE compliance_profile_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL
        REFERENCES compliance_profiles(id) ON DELETE CASCADE,
    work_type TEXT NOT NULL CHECK(length(trim(work_type)) > 0),
    frequency TEXT NOT NULL CHECK(length(trim(frequency)) > 0),
    enabled INTEGER NOT NULL DEFAULT 1
        CHECK(typeof(enabled) = 'integer' AND enabled IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, work_type)
);

CREATE TABLE annual_workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    operation_year INTEGER NOT NULL
        CHECK(typeof(operation_year) = 'integer'
              AND operation_year BETWEEN 1912 AND 9999),
    fiscal_year_start_month_snapshot INTEGER NOT NULL
        CHECK(typeof(fiscal_year_start_month_snapshot) = 'integer'
              AND fiscal_year_start_month_snapshot BETWEEN 1 AND 12),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX idx_annual_workspaces_client_year
    ON annual_workspaces(client_id, operation_year);

CREATE UNIQUE INDEX ux_annual_workspaces_active
    ON annual_workspaces(client_id, operation_year)
    WHERE deleted_at IS NULL;

CREATE TABLE annual_work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES annual_workspaces(id),
    item_key TEXT NOT NULL CHECK(length(trim(item_key)) > 0),
    work_type TEXT NOT NULL CHECK(length(trim(work_type)) > 0),
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    tax_year INTEGER CHECK(
        tax_year IS NULL OR (
            typeof(tax_year) = 'integer'
            AND tax_year BETWEEN 1912 AND 9999
        )
    ),
    period_code TEXT,
    suggested_due_date TEXT,
    due_date TEXT,
    work_status TEXT NOT NULL DEFAULT 'not_started',
    filing_status TEXT NOT NULL DEFAULT 'not_filed',
    document_status TEXT NOT NULL DEFAULT 'not_requested',
    tax_status TEXT NOT NULL DEFAULT 'unconfirmed',
    fee_status TEXT NOT NULL DEFAULT 'not_billed',
    engagement_id INTEGER REFERENCES engagements(id),
    exception_reason TEXT,
    notes TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX idx_annual_work_items_workspace
    ON annual_work_items(workspace_id);

CREATE INDEX idx_annual_work_items_due_date
    ON annual_work_items(due_date);

CREATE INDEX idx_annual_work_items_engagement
    ON annual_work_items(engagement_id);

CREATE UNIQUE INDEX ux_annual_work_items_active
    ON annual_work_items(workspace_id, item_key)
    WHERE deleted_at IS NULL;

CREATE TABLE annual_work_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES annual_work_items(id),
    category TEXT NOT NULL
        CHECK(category IN (
            'tax_liability', 'client_tax_collection', 'tax_payment',
            'tax_credit_or_refund', 'fee_receivable', 'fee_receipt'
        )),
    amount INTEGER NOT NULL
        CHECK(typeof(amount) = 'integer'
              AND amount BETWEEN 0 AND 9000000000000),
    transaction_date TEXT NOT NULL,
    reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX idx_annual_transactions_work_item
    ON annual_work_transactions(work_item_id);

ALTER TABLE workflow_tasks
    ADD COLUMN annual_work_item_id INTEGER REFERENCES annual_work_items(id);

CREATE INDEX idx_workflow_tasks_annual_item
    ON workflow_tasks(annual_work_item_id);
"""
