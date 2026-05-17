"""Tax registry cache importer service.

Imports a local ``BGMOPEN1.zip`` file into ``tax_registry_cache`` via the
staging-first repository, captures cache metadata, and writes an audit
trail.

This service does NOT perform any HTTP. It only consumes a local file
path. Slice 3 will add the HTTP download path under the URL allowlist
defined in ``taxops.security.domains``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ...core.clock import now_iso
from ...repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from ..audit import AuditService
from ..system_log import SystemLogService
from .parser import (
    BGMOPEN1FormatError,
    BGMOPEN1Reader,
    ParseHeader,
)

_AUDIT_TARGET_TYPE = "tax_cache"
_MAX_ZIP_BYTES = 500 * 1024 * 1024  # 500 MB — rejects obvious non-official files


class TaxRegistryImportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ImportResult:
    row_count: int
    cache_version: str
    source_sha256: str
    source_size: int
    data_freshness_raw: str | None
    data_freshness_iso: str | None
    imported_at: str


def sha256_of_file(path: Path) -> tuple[str, int]:
    """Stream-hash a file. Returns (hex_digest, size_bytes)."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


class TaxRegistryImporter:
    def __init__(
        self,
        registry_repo: TaxRegistryRepository,
        metadata_repo: TaxCacheMetadataRepository,
        audit: AuditService,
        system_log: SystemLogService,
    ) -> None:
        self._registry = registry_repo
        self._metadata = metadata_repo
        self._audit = audit
        self._system_log = system_log

    def import_zip(
        self,
        zip_path: Path | str,
        *,
        source_url: str | None = None,
        on_progress=None,
    ) -> ImportResult:
        """Validate + import a local ``BGMOPEN1.zip``.

        ``source_url`` is informational only (e.g. recorded if the file was
        previously downloaded from an allowlisted URL). This method never
        performs HTTP.
        """
        path = Path(zip_path)
        if path.suffix.lower() != ".zip":
            raise TaxRegistryImportError("registry.zip.wrong_extension")
        if not path.is_file():
            raise TaxRegistryImportError("registry.zip.not_found")
        try:
            file_size = path.stat().st_size
        except OSError as exc:
            self._system_log.error("tax_cache stat failed", exc=exc)
            raise TaxRegistryImportError("registry.zip.read_failed") from exc
        if file_size > _MAX_ZIP_BYTES:
            raise TaxRegistryImportError("registry.zip.too_large")

        try:
            sha, size = sha256_of_file(path)
        except OSError as exc:
            self._system_log.error("tax_cache hash failed", exc=exc)
            raise TaxRegistryImportError("registry.zip.read_failed") from exc

        try:
            with BGMOPEN1Reader(path) as reader:
                header: ParseHeader = reader.header
                cache_version = header.cache_version
                row_count = self._registry.replace_all_from_entries(
                    reader.entries(),
                    cache_version=cache_version,
                    on_progress=on_progress,
                )
        except BGMOPEN1FormatError:
            raise
        except TaxRegistryImportError:
            raise
        except Exception as exc:
            self._system_log.error("tax_cache import failed", exc=exc)
            raise TaxRegistryImportError("registry.import.failed") from exc

        imported_at = now_iso()
        meta_payload: dict[str, str] = {
            "cache_version": cache_version,
            "source": "zip",
            "source_sha256": sha,
            "source_size": str(size),
            "row_count": str(row_count),
            "imported_at": imported_at,
            "data_freshness_raw": header.data_freshness_raw or "",
            "data_freshness_iso": header.data_freshness_iso or "",
            "last_import_source": "zip",
        }
        if source_url:
            meta_payload["source_url"] = source_url

        self._metadata.upsert_many(meta_payload)

        self._audit.record(
            action="tax_cache.import.zip",
            target_type=_AUDIT_TARGET_TYPE,
            target_id=cache_version,
            detail={
                "row_count": row_count,
                "cache_version": cache_version,
                "source_sha256": sha,
                "source_size": size,
                "data_freshness_iso": header.data_freshness_iso,
            },
        )

        return ImportResult(
            row_count=row_count,
            cache_version=cache_version,
            source_sha256=sha,
            source_size=size,
            data_freshness_raw=header.data_freshness_raw,
            data_freshness_iso=header.data_freshness_iso,
            imported_at=imported_at,
        )
