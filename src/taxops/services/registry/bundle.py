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
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

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
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CACHE_CSV_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_BUNDLE_ROWS = 5_000_000
MAX_FIELD_CHARS = 20_000

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


class _HashingReader(io.RawIOBase):
    def __init__(self, raw, digest) -> None:
        super().__init__()
        self._raw = raw
        self._digest = digest

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        chunk = self._raw.read(len(buffer))
        if not chunk:
            return 0
        self._digest.update(chunk)
        buffer[: len(chunk)] = chunk
        return len(chunk)


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
        self._conn = registry_repo._conn

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_bundle(self, dest_path: Path | str) -> ExportResult:
        if self._registry.count() == 0:
            raise BundleError("registry.bundle.empty_cache")
        meta = self._metadata.get_all()
        cache_version = meta.get("cache_version") or today_iso().replace("-", "")

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        row_count = 0
        digest = hashlib.sha256()

        def _write_csv_row(member, values) -> None:
            row_buffer = io.StringIO(newline="")
            csv.writer(row_buffer).writerow(values)
            encoded = row_buffer.getvalue().encode("utf-8")
            digest.update(encoded)
            member.write(encoded)

        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                with zf.open(CACHE_CSV_NAME, "w") as cache_member:
                    _write_csv_row(cache_member, CSV_COLUMNS)
                    for row in self._registry.iter_all():
                        _write_csv_row(cache_member, _row_to_csv_values(row))
                        row_count += 1

                bundle_sha = digest.hexdigest()
                manifest: dict[str, object] = {
                    "format_version": BUNDLE_FORMAT_VERSION,
                    "cache_version": cache_version,
                    "row_count": row_count,
                    "bundle_sha256_of_data": bundle_sha,
                    "exported_at": now_iso(),
                }
                for key in (
                    "data_freshness_raw",
                    "data_freshness_iso",
                    "source_url",
                    "source_sha256",
                    "source_size",
                ):
                    value = meta.get(key)
                    if value:
                        manifest[key] = value
                manifest_bytes = json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
                zf.writestr(MANIFEST_NAME, manifest_bytes)
            tmp.replace(dest)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                _log.warning("export_bundle: failed to clean up temp file %s", tmp)
            raise

        with self._conn:
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
            zf = zipfile.ZipFile(path, "r")
        except zipfile.BadZipFile as exc:
            raise BundleError("registry.bundle.bad_zip") from exc
        try:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            if len(infos) != 2 or set(names) != ALLOWED_BUNDLE_MEMBERS:
                raise BundleError("registry.bundle.unexpected_members")
            info_by_name = {info.filename: info for info in infos}
            if info_by_name[MANIFEST_NAME].file_size > MAX_MANIFEST_BYTES:
                raise BundleError("registry.bundle.bad_manifest")
            if info_by_name[CACHE_CSV_NAME].file_size > MAX_CACHE_CSV_BYTES:
                raise BundleError("registry.bundle.csv_too_large")
            for info in infos:
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > MAX_COMPRESSION_RATIO:
                    raise BundleError("registry.bundle.compression_ratio_invalid")

            manifest_raw = zf.read(MANIFEST_NAME)
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
            declared_row_count = manifest.get("row_count")
            if (
                not isinstance(declared_row_count, int)
                or isinstance(declared_row_count, bool)
                or declared_row_count < 0
            ):
                raise BundleError("registry.bundle.bad_manifest")
            expected_sha = manifest.get("bundle_sha256_of_data")
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise BundleError("registry.bundle.bad_manifest")

            digest = hashlib.sha256()
            imported_at = now_iso()
            with zf.open(CACHE_CSV_NAME, "r") as cache_member:
                hashing_reader = _HashingReader(cache_member, digest)
                with io.TextIOWrapper(
                    io.BufferedReader(hashing_reader),
                    encoding="utf-8",
                    newline="",
                ) as text_stream:
                    reader = csv.DictReader(text_stream)
                    if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_COLUMNS:
                        raise BundleError("registry.bundle.csv_schema_mismatch")

                    def _entries():
                        imported_rows = 0
                        for row in reader:
                            if not (row.get("tax_id") or "").strip():
                                continue
                            if imported_rows >= MAX_BUNDLE_ROWS:
                                raise BundleError("registry.bundle.too_many_rows")
                            if any(
                                len(value or "") > MAX_FIELD_CHARS
                                for value in row.values()
                            ):
                                raise BundleError("registry.bundle.field_too_large")
                            imported_rows += 1
                            yield _row_dict_to_entry(row)
                        if digest.hexdigest() != expected_sha:
                            raise BundleError("registry.bundle.tampered")

                    meta_payload: dict[str, str] = {
                        "cache_version": cache_version,
                        "source": "bundle",
                        "imported_at": imported_at,
                        "last_import_source": "bundle",
                        "bundle_sha256_of_data": expected_sha,
                    }
                    for key in (
                        "data_freshness_raw",
                        "data_freshness_iso",
                        "source_url",
                        "source_sha256",
                        "source_size",
                    ):
                        value = manifest.get(key)
                        if isinstance(value, str) and value:
                            meta_payload[key] = value
                        elif isinstance(value, int):
                            meta_payload[key] = str(value)

                    def _finalize(imported_rows: int) -> None:
                        if imported_rows != declared_row_count:
                            raise BundleError("registry.bundle.row_count_mismatch")
                        meta_payload["row_count"] = str(imported_rows)
                        self._metadata.upsert_many(meta_payload, commit=False)
                        self._audit.record(
                            action="tax_cache.bundle.import",
                            target_type=_AUDIT_TARGET_TYPE,
                            target_id=cache_version,
                            detail={
                                "row_count": imported_rows,
                                "cache_version": cache_version,
                                "bundle_sha256_of_data": expected_sha,
                            },
                        )

                    try:
                        row_count = self._registry.replace_all_from_entries(
                            _entries(),
                            cache_version=cache_version,
                            on_progress=on_progress,
                            before_commit=_finalize,
                        )
                    except BundleError as exc:
                        self._system_log.error(
                            "tax_cache bundle import failed",
                            exc=exc,
                        )
                        raise
                    except Exception as exc:
                        self._system_log.error(
                            "tax_cache bundle import failed",
                            exc=exc,
                        )
                        raise BundleError("registry.bundle.import_failed") from exc

            actual_sha = digest.hexdigest()
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
        finally:
            zf.close()
