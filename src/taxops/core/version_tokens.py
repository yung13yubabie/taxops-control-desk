"""Strictly monotonic optimistic-concurrency tokens for second-precision rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .clock import now_iso


def next_updated_at(previous: str) -> str:
    """Return a canonical timestamp token strictly newer than ``previous``."""
    candidate = now_iso()
    if candidate > previous:
        return candidate
    try:
        parsed = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError("version_token.previous.invalid") from exc
    return (parsed + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
