"""Migration 0012: FTS5 full-text search virtual tables."""

SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_clients USING fts5(
    client_code,
    client_name,
    tax_id,
    short_name,
    contact_name,
    note,
    tokenize='trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_engagements USING fts5(
    engagement_name,
    tokenize='trigram'
);
"""
