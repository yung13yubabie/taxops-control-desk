"""Migration 0019: drop review_notes (Slice 24 / v0.15.1).

Slice 24 retires the 覆核意見 feature entirely (replaced by the new
folder bookmarks page in 0020). Drops the table + its two indexes;
existing review_notes rows are lost on migration apply.
"""

from __future__ import annotations

SQL = """
DROP INDEX IF EXISTS idx_review_notes_engagement;
DROP INDEX IF EXISTS idx_review_notes_status;
DROP TABLE IF EXISTS review_notes;
"""
