"""Slice 2 schema: tax registry cache, cache metadata, registry match results.

Field shape for ``tax_registry_cache`` mirrors the actual MOF
``BGMOPEN1.csv`` 16 columns (verified against the real file on 2026-05-09).
``registered_date_roc`` keeps the raw 民國 ``YYYMMDD`` string so callers can
choose how to render it.

``registry_match_results.differences_json`` stores a difference summary only
— it must never be used to overwrite ``clients`` rows.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS tax_registry_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_id TEXT NOT NULL,
    business_name TEXT,
    business_address TEXT,
    parent_tax_id TEXT,
    capital INTEGER,
    registered_date_roc TEXT,
    organization_type TEXT,
    uses_uniform_invoice TEXT,
    industry_code_primary TEXT,
    industry_name_primary TEXT,
    industry_code_1 TEXT,
    industry_name_1 TEXT,
    industry_code_2 TEXT,
    industry_name_2 TEXT,
    industry_code_3 TEXT,
    industry_name_3 TEXT,
    cache_version TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tax_registry_cache_tax_id ON tax_registry_cache(tax_id);
CREATE INDEX IF NOT EXISTS idx_tax_registry_cache_cache_version ON tax_registry_cache(cache_version);

CREATE TABLE IF NOT EXISTS tax_cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registry_match_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    tax_id TEXT,
    registry_source TEXT NOT NULL,
    cache_version TEXT,
    match_status TEXT NOT NULL,
    matched_name TEXT,
    matched_address TEXT,
    matched_business_status TEXT,
    differences_json TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    generated_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_match_results_client ON registry_match_results(client_id);
CREATE INDEX IF NOT EXISTS idx_match_results_tax_id ON registry_match_results(tax_id);
CREATE INDEX IF NOT EXISTS idx_match_results_status ON registry_match_results(match_status);
"""
