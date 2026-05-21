"""Shared ISO date parsing and validation.

All dates stored in the system use YYYY-MM-DD.  These helpers centralise
the parse/validate logic so every service layer rejects bad dates at the
boundary rather than letting them corrupt SQL string-comparison queries.
"""

from __future__ import annotations

import datetime


def parse_optional_iso_date(value: str | None) -> datetime.date | None:
    """Parse a YYYY-MM-DD string; return None for empty/None input.

    Raises ``ValueError`` on any input that is present but not a valid
    calendar date (e.g. '2026-99-99', 'abc', '2026-2').
    """
    if not value or not value.strip():
        return None
    return datetime.date.fromisoformat(value.strip())


def date_range_is_valid(start: datetime.date | None, end: datetime.date | None) -> bool:
    """Return True when start <= end, or when either bound is absent."""
    if start is None or end is None:
        return True
    return start <= end
