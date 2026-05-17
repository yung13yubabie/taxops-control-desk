"""Tax cache bundle export / import.

A "tax cache bundle" is a ZIP file that an internet-connected dev box
exports so an offline office machine can import the same registry data
without HTTP access.

**Whitelist (slice 2 hard rule).** A bundle MUST contain exactly two
files and no others:

- ``manifest.json``
- ``tax_registry_cache.csv``

A bundle MUST NOT contain ``clients``, ``registry_match_results``,
``audit_logs``, ``system_logs``, or any local-path / user-data fields
from ``app_settings``. The tests in
``tests/test_registry_bundle.py`` enforce this.

The CSV uses our normalised snake_case column names (independent of the
upstream ``BGMOPEN1.csv`` Chinese headers) so the export/import round
trip is stable across upstream column reordering.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ...core.clock import now_iso, today_iso
from ...repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from ..audit import AuditService
from ..system_log import SystemLogService
from .parser import TaxRegistryEntry

BUNDLE_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CACHE_CSV_NAME = "tax_registry_cache.csv"
ALLOWED_BUNDLE_MEMBERS = frozenset({MANIFEST_NAME, CACHE_CSV_NAME})

CSV_COLUMNS: tuple[str, ...] = (
    "tax_id",
    "business_name",
    "business_address",
    "parent_tax_id",
    "capital",
    "registered_date_roc",
    "organization_type",
    "uses_uniform_invoice",
    "industry_code_primary",
    "industry_name_primary",
    "industry_code_1",
    "industry_name_1",
    "industry_code_2",
    "industry_name_2",
    "industry_code_3",
    "industry_name_3",
)

# Manifest keys that may be written. Any other field is rejected on import
# to prevent accidental leakage of user data through a future writer.
ALLOWED_MANIFEST_KEYS: frozenset[str] = frozenset({
    "format_version",
    "cache_version",
    "row_count",
    "bundle_sha256_of_data",
    "exported_at",
    "data_freshness_raw",
    "data_freshness_iso",
    "source_url",
    "source_sha256",
    "source_size",
})

_AUDIT_TARGET_TYPE = "tax_cache"


class BundleError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExportResult:
    bundle_path: Path
    row_count: int
    cache_version: str
    bundle_sha256_of_data: str
    exported_at: str


@dataclass(frozen=True)
class BundleImportResult:
    bundle_path: Path
    row_count: int
    cache_version: str
    bundle_sha256_of_data: str
    imported_at: str
    data_freshness_iso: str | None


def suggested_bundle_filename(cache_version: str | None) -> str:
    cv = cache_version or today_iso().replace("-", "")
    return f"tax_registry_public_cache_{cv}.taxops-cache.zip"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_csv_values(row) -> list[str]:
    out: list[str] = []
    for col in CSV_COLUMNS:
        value = row[col]
        if value is None:
            out.append("")
        else:
            out.append(str(value))
    return out


def _csv_value_to_entry_field(value: str) -> str | None:
    return value if value else None


def _row_dict_to_entry(d: dict[str, str]) -> TaxRegistryEntry:
    capital_raw = (d.get("capital") or "").strip()
    capital = int(capital_raw) if capital_raw.isdigit() else None
    return TaxRegistryEntry(
        tax_id=(d.get("tax_id") or "").strip(),
        business_name=_csv_value_to_entry_field(d.get("business_name") or ""),
        business_address=_csv_value_to_entry_field(d.get("business_address") or ""),
        parent_tax_id=_csv_value_to_entry_field(d.get("parent_tax_id") or ""),
        capital=capital,
        registered_date_roc=_csv_value_to_entry_field(
            d.get("registered_date_roc") or ""
        ),
        organization_type=_csv_value_to_entry_field(
            d.get("organization_type") or ""
        ),
        uses_uniform_invoice=_csv_value_to_entry_field(
            d.get("uses_uniform_invoice") or ""
        ),
        industry_code_primary=_csv_value_to_entry_field(
            d.get("industry_code_primary") or ""
        ),
        industry_name_primary=_csv_value_to_entry_field(
            d.get("industry_name_primary") or ""
        ),
        industry_code_1=_csv_value_to_entry_field(d.get("industry_code_1") or ""),
        industry_name_1=_csv_value_to_entry_field(d.get("industry_name_1") or ""),
        industry_code_2=_csv_value_to_entry_field(d.get("industry_code_2") or ""),
        industry_name_2=_csv_value_to_entry_field(d.get("industry_name_2") or ""),
        industry_code_3=_csv_value_to_entry_field(d.get("industry_code_3") or ""),
        industry_name_3=_csv_value_to_entry_field(d.get("industry_name_3") or ""),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class TaxCacheBundleService:
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

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_bundle(self, dest_path: Path | str) -> ExportResult:
        if self._registry.count() == 0:
            raise BundleError("registry.bundle.empty_cache")
        meta = self._metadata.get_all()
        cache_version = meta.get("cache_version") or today_iso().replace("-", "")

        # Build the CSV in memory. For slice 2 this is acceptable; a fully
        # streaming variant (write CSV directly into the zip member with
        # incremental SHA-256) is a follow-up if memory becomes an issue.
        csv_buffer = io.StringIO(newline="")
        writer = csv.writer(csv_buffer)
        writer.writerow(CSV_COLUMNS)
        row_count = 0
        for row in self._registry.iter_all():
            writer.writerow(_row_to_csv_values(row))
            row_count += 1
        csv_text = csv_buffer.getvalue()
        csv_bytes = csv_text.encode("utf-8")
        bundle_sha = hashlib.sha256(csv_bytes).hexdigest()

        manifest: dict[str, object] = {
            "format_version": BUNDLE_FORMAT_VERSION,
            "cache_version": cache_version,
            "row_count": row_count,
            "bundle_sha256_of_data": bundle_sha,
            "exported_at": now_iso(),
        }
        for key in ("data_freshness_raw", "data_freshness_iso",
                    "source_url", "source_sha256", "source_size"):
            value = meta.get(key)
            if value:
                manifest[key] = value

        for key in list(manifest.keys()):
            if key not in ALLOWED_MANIFEST_KEYS:
                del manifest[key]

        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, manifest_bytes)
                zf.writestr(CACHE_CSV_NAME, csv_bytes)
            tmp.replace(dest)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        self._audit.record(
            action="tax_cache.bundle.export",
            target_type=_AUDIT_TARGET_TYPE,
            target_id=cache_version,
            detail={
                "row_count": row_count,
                "cache_version": cache_version,
                "bundle_sha256_of_data": bundle_sha,
                "bundle_path": str(dest),
            },
        )
        return ExportResult(
            bundle_path=dest,
            row_count=row_count,
            cache_version=cache_version,
            bundle_sha256_of_data=bundle_sha,
            exported_at=str(manifest["exported_at"]),
        )

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def import_bundle(
        self,
        bundle_path: Path | str,
        *,
        on_progress=None,
    ) -> BundleImportResult:
        path = Path(bundle_path)
        if not path.is_file():
            raise BundleError("registry.bundle.not_found")

        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = set(zf.namelist())
                if names != ALLOWED_BUNDLE_MEMBERS:
                    raise BundleError("registry.bundle.unexpected_members")
                manifest_raw = zf.read(MANIFEST_NAME)
                csv_bytes = zf.read(CACHE_CSV_NAME)
        except zipfile.BadZipFile as exc:
            raise BundleError("registry.bundle.bad_zip") from exc

        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BundleError("registry.bundle.bad_manifest") from exc

        if not isinstance(manifest, dict):
            raise BundleError("registry.bundle.bad_manifest")
        if manifest.get("format_version") != BUNDLE_FORMAT_VERSION:
            raise BundleError("registry.bundle.unsupported_version")
        for key in manifest:
            if key not in ALLOWED_MANIFEST_KEYS:
                raise BundleError("registry.bundle.disallowed_manifest_key")

        cache_version = manifest.get("cache_version")
        if not isinstance(cache_version, str) or not cache_version:
            raise BundleError("registry.bundle.bad_manifest")
        expected_sha = manifest.get("bundle_sha256_of_data")
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise BundleError("registry.bundle.bad_manifest")

        actual_sha = hashlib.sha256(csv_bytes).hexdigest()
        if actual_sha != expected_sha:
            raise BundleError("registry.bundle.tampered")

        text = csv_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_COLUMNS:
            raise BundleError("registry.bundle.csv_schema_mismatch")

        def _entries():
            for row in reader:
                if not (row.get("tax_id") or "").strip():
                    continue
                yield _row_dict_to_entry(row)

        try:
            row_count = self._registry.replace_all_from_entries(
                _entries(),
                cache_version=cache_version,
                on_progress=on_progress,
            )
        except Exception as exc:
            self._system_log.error("tax_cache bundle import failed", exc=exc)
            raise BundleError("registry.bundle.import_failed") from exc

        imported_at = now_iso()
        meta_payload: dict[str, str] = {
            "cache_version": cache_version,
            "source": "bundle",
            "row_count": str(row_count),
            "imported_at": imported_at,
            "last_import_source": "bundle",
            "bundle_sha256_of_data": actual_sha,
        }
        for key in ("data_freshness_raw", "data_freshness_iso",
                    "source_url", "source_sha256", "source_size"):
            value = manifest.get(key)
            if isinstance(value, str) and value:
                meta_payload[key] = value
            elif isinstance(value, int):
                meta_payload[key] = str(value)

        self._metadata.upsert_many(meta_payload)
        self._audit.record(
            action="tax_cache.bundle.import",
            target_type=_AUDIT_TARGET_TYPE,
            target_id=cache_version,
            detail={
                "row_count": row_count,
                "cache_version": cache_version,
                "bundle_sha256_of_data": actual_sha,
            },
        )
        return BundleImportResult(
            bundle_path=path,
            row_count=row_count,
            cache_version=cache_version,
            bundle_sha256_of_data=actual_sha,
            imported_at=imported_at,
            data_freshness_iso=(
                manifest.get("data_freshness_iso")
                if isinstance(manifest.get("data_freshness_iso"), str)
                else None
            ),
        )
