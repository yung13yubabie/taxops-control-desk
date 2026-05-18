"""Time utilities. ISO 8601 UTC timestamps for stored data."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string (seconds precision)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    """Return today's date in the local OS timezone as ``YYYY-MM-DD``.

    Uses local time so due-date comparisons match the user's calendar,
    not UTC (which differs from Asia/Taipei by +8 hours).
    """
    return datetime.now().strftime("%Y-%m-%d")
