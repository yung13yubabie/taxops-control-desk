"""Official-source domain allowlist.

URLs configured in settings must start with one of these prefixes.
Used by the registry/tax cache module (slice 2+).
"""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_OFFICIAL_DOMAINS: tuple[str, ...] = (
    "eip.fia.gov.tw",
    "data.gov.tw",
    "data.gcis.nat.gov.tw",
)


def is_allowed_official_url(url: str) -> bool:
    """Return True if the URL uses HTTPS and an allowlisted host."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_OFFICIAL_DOMAINS
