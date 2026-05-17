"""Migration registry. Each migration is a (version, sql) tuple."""

from __future__ import annotations

from . import (
    _m0001_initial,
    _m0002_tax_cache,
    _m0003_soft_delete,
    _m0004_engagements,
    _m0005_workflow_tasks,
    _m0006_message_templates,
    _m0007_generated_messages,
    _m0008_review_notes,
    _m0009_late_fee,
    _m0010_attachments,
    _m0011_backup,
    _m0012_fts5,
)

MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("0001_initial", _m0001_initial.SQL),
    ("0002_tax_cache", _m0002_tax_cache.SQL),
    ("0003_soft_delete", _m0003_soft_delete.SQL),
    ("0004_engagements", _m0004_engagements.SQL),
    ("0005_workflow_tasks", _m0005_workflow_tasks.SQL),
    ("0006_message_templates", _m0006_message_templates.SQL),
    ("0007_generated_messages", _m0007_generated_messages.SQL),
    ("0008_review_notes", _m0008_review_notes.SQL),
    ("0009_late_fee", _m0009_late_fee.SQL),
    ("0010_attachments", _m0010_attachments.SQL),
    ("0011_backup", _m0011_backup.SQL),
    ("0012_fts5", _m0012_fts5.SQL),
)
