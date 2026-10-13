"""Cache status + verification helpers (cache reads and verification audit)."""

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
    """Check metadata.row_count vs actual cache count and audit the outcome.

    Repositories share the audit connection, as wired by the service container.
    Own the transaction when called on an idle connection; otherwise isolate
    this operation in a savepoint and leave commit/rollback to the caller.
    """
    conn = audit.connection
    owns_transaction = not conn.in_transaction
    savepoint = "taxops_verify_cache"
    if owns_transaction:
        # Reserve the audit write before reading so a concurrent import cannot
        # change the cache between the metadata/count reads and the audit row.
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f"SAVEPOINT {savepoint}")
    try:
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
        result = CacheVerification(
            cache_version=status.cache_version,
            metadata_row_count=status.metadata_row_count,
            actual_row_count=status.row_count,
            row_count_matches=matches,
            last_import_source=status.last_import_source,
            data_freshness_iso=status.data_freshness_iso,
            source_sha256=status.source_sha256,
            bundle_sha256_of_data=status.bundle_sha256_of_data,
        )
        if owns_transaction:
            conn.commit()
        else:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException as exc:
        try:
            if owns_transaction:
                conn.rollback()
            else:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except BaseException as cleanup_error:
            exc.add_note(f"Cache verification rollback also failed: {cleanup_error!r}")
        raise
    return result
