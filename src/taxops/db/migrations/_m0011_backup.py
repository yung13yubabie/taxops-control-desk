"""Migration 0011: backup_records table."""

SQL = """
CREATE TABLE IF NOT EXISTS backup_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL,
    backup_path TEXT    NOT NULL,
    file_size   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backup_records_created
    ON backup_records(created_at DESC);
"""
