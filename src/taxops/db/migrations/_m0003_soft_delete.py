"""Slice 2.5: soft-delete support for clients.

Adds ``deleted_at`` (ISO-8601 timestamp or NULL) to the ``clients`` table.
NULL means active; a timestamp means soft-deleted.

Hard DELETE is never issued against ``clients`` after this migration.
"""

from __future__ import annotations

SQL = """
ALTER TABLE clients ADD COLUMN deleted_at TEXT;
"""
