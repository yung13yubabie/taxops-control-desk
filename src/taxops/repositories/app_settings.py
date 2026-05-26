"""App settings repository (key/value)."""

from __future__ import annotations

import sqlite3

from ..core.clock import now_iso

# Default settings seeded on first run. Tax cache URLs come from
# docs/registry_cache_workflow.md and decisions in .ai/DECISIONS.md.
DEFAULT_SETTINGS: tuple[tuple[str, str], ...] = (
    ("display.local_user_name", "local_user"),
    ("tax_cache.query_mode", "local_only"),
    ("tax_cache.dataset_url", "https://data.gov.tw/dataset/9400"),
    ("tax_cache.download_url", "https://eip.fia.gov.tw/data/BGMOPEN1.zip"),
    (
        "tax_cache.gcis_swagger_url",
        "https://data.gcis.nat.gov.tw/resources/swagger/swagger.json",
    ),
    ("ui.sidebar_collapsed", "0"),
    ("ui.doc_request_template.vat", ""),
    # Slice 21C: column visibility (CSV of hidden col keys) + width
    # presets (JSON {col_key: pixels}) per major table.
    ("ui.engagements.columns_hidden", ""),
    ("ui.engagements.column_widths", ""),
    ("ui.doc_requests.columns_hidden", ""),
    ("ui.doc_requests.column_widths", ""),
    ("ui.doc_items.columns_hidden", ""),
    ("ui.doc_items.column_widths", ""),
    ("ui.tasks.columns_hidden", ""),
    ("ui.tasks.column_widths", ""),
)

VALID_QUERY_MODES = ("local_only", "allow_online")


class AppSettingsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seed_defaults(self) -> None:
        """Insert default rows for missing keys. Idempotent."""
        cur = self._conn.cursor()
        for key, value in DEFAULT_SETTINGS:
            cur.execute(
                "INSERT OR IGNORE INTO app_settings(key, value, updated_at) "
                "VALUES (?, ?, ?)",
                (key, value, now_iso()),
            )
        self._conn.commit()

    def get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_all(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT key, value FROM app_settings"
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def upsert(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, now_iso()),
        )
        self._conn.commit()
