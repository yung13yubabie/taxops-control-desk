"""Cache status + verification helpers (read-only)."""

from __future__ import annotations

from dataclasses import dataclass

from ...repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from ..audit import AuditService


@dataclass(frozen=True)
class CacheStatus:
    has_cache: bool
    cache_version: str | None
    row_count: int
    metadata_row_count: int | None
    last_import_source: str | None
    imported_at: str | None
    data_freshness_iso: str | None
    source_sha256: str | None
    bundle_sha256_of_data: str | None


@dataclass(frozen=True)
class CacheVerification:
    cache_version: str | None
    metadata_row_count: int | None
    actual_row_count: int
    row_count_matches: bool
    last_import_source: str | None
    data_freshness_iso: str | None
    source_sha256: str | None
    bundle_sha256_of_data: str | None


def _opt_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_cache_status(
    registry_repo: TaxRegistryRepository,
    metadata_repo: TaxCacheMetadataRepository,
) -> CacheStatus:
    meta = metadata_repo.get_all()
    actual = registry_repo.count()
    return CacheStatus(
        has_cache=actual > 0,
        cache_version=meta.get("cache_version") or None,
        row_count=actual,
        metadata_row_count=_opt_int(meta.get("row_count")),
        last_import_source=meta.get("last_import_source") or None,
        imported_at=meta.get("imported_at") or None,
        data_freshness_iso=meta.get("data_freshness_iso") or None,
        source_sha256=meta.get("source_sha256") or None,
        bundle_sha256_of_data=meta.get("bundle_sha256_of_data") or None,
    )


def verify_cache(
    registry_repo: TaxRegistryRepository,
    metadata_repo: TaxCacheMetadataRepository,
    audit: AuditService,
) -> CacheVerification:
    """Read-only consistency check: metadata.row_count vs actual cache count.

    Writes an audit log row recording the verification outcome.
    """
    status = get_cache_status(registry_repo, metadata_repo)
    matches = (
        status.metadata_row_count is not None
        and status.metadata_row_count == status.row_count
    )
    audit.record(
        action="tax_cache.verify",
        target_type="tax_cache",
        target_id=status.cache_version,
        detail={
            "metadata_row_count": status.metadata_row_count,
            "actual_row_count": status.row_count,
            "row_count_matches": matches,
            "cache_version": status.cache_version,
        },
    )
    return CacheVerification(
        cache_version=status.cache_version,
        metadata_row_count=status.metadata_row_count,
        actual_row_count=status.row_count,
        row_count_matches=matches,
        last_import_source=status.last_import_source,
        data_freshness_iso=status.data_freshness_iso,
        source_sha256=status.source_sha256,
        bundle_sha256_of_data=status.bundle_sha256_of_data,
    )
