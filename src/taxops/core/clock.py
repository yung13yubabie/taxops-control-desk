"""Time utilities. ISO 8601 UTC timestamps for stored data."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string (seconds precision)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    """Return current UTC date as ISO 8601 ``YYYY-MM-DD`` string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
