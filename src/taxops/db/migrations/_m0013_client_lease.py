"""Migration 0013: add lease_start and lease_end to clients.

Both columns are ISO-8601 date strings (TEXT), nullable.
"""

from __future__ import annotations

SQL = """
ALTER TABLE clients ADD COLUMN lease_start TEXT;
ALTER TABLE clients ADD COLUMN lease_end TEXT;
"""
