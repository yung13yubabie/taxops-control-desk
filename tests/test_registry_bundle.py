"""Tax cache bundle export / import tests.

Strict whitelist enforcement (slice 2 hard rule):
- Bundle ZIP contains exactly ``manifest.json`` and ``tax_registry_cache.csv``.
- Bundle never contains ``clients``, ``registry_match_results``,
  ``audit_logs``, ``system_logs``, or any local-path / user-data fields.
- Manifest keys are restricted to a fixed allowlist.
- Tampered CSV is rejected.
- Bundle import failure preserves the existing cache.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from taxops.repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from taxops.services.clients import CreateClientInput
from taxops.services.container import ServiceContainer
from taxops.services.registry.bundle import (
    ALLOWED_BUNDLE_MEMBERS,
    ALLOWED_MANIFEST_KEYS,
    BUNDLE_FORMAT_VERSION,
    BundleError,
    CACHE_CSV_NAME,
    MANIFEST_NAME,
    TaxCacheBundleService,
    suggested_bundle_filename,
)
from taxops.services.registry.importer import TaxRegistryImporter
from taxops.services.registry.parser import EXPECTED_HEADERS

_BODY_TWO_ROWS = (
    "09-MAY-26,,,,,,,,,,,,,,,\n"
    "地址1,38965019,,原味商行,100000,1040413,獨資,N,472927,豆類製品零售,,,,,,\n"
    "地址2,61194605,,和興商店,1000,0400711,獨資,N,472913,菸酒零售,471913,雜貨店,,,,\n"
)

_FORBIDDEN_KEYWORDS = (
    "clients",
    "registry_match_results",
    "audit_logs",
    "system_logs",
    "app_settings",
    "display.local_user_name",
    "data_root",
    "db_path",
    "attachments_dir",
)


def _csv(body: str) -> str:
    return ",".join(EXPECTED_HEADERS) + "\n" + body


def _make_zip(tmp_path: Path, csv_text: str, name: str = "input.zip") -> Path:
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BGMOPEN1.csv", csv_text.encode("utf-8"))
    return zip_path


def _seed_cache(container: ServiceContainer, tmp_path: Path) -> Path:
    importer = TaxRegistryImporter(
        registry_repo=TaxRegistryRepository(container.conn),
        metadata_repo=TaxCacheMetadataRepository(container.conn),
        audit=container.audit,
        system_log=container.system_log,
    )
    z = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS), name="seed.zip")
    importer.import_zip(z)
    return z


def _build_bundle_service(container: ServiceContainer) -> TaxCacheBundleService:
    return TaxCacheBundleService(
        registry_repo=TaxRegistryRepository(container.conn),
        metadata_repo=TaxCacheMetadataRepository(container.conn),
        audit=container.audit,
        system_log=container.system_log,
    )


def test_suggested_filename_format() -> None:
    assert suggested_bundle_filename("20260509") == (
        "tax_registry_public_cache_20260509.taxops-cache.zip"
    )
    fallback = suggested_bundle_filename(None)
    assert fallback.startswith("tax_registry_public_cache_")
    assert fallback.endswith(".taxops-cache.zip")


def test_export_bundle_contains_only_whitelisted_members(
    tmp_path: Path, container: ServiceContainer
) -> None:
    _seed_cache(container, tmp_path)
    container.clients.create_client(
        CreateClientInput(client_code="C001", client_name="某客戶")
    )

    svc = _build_bundle_service(container)
    out = tmp_path / "out.taxops-cache.zip"
    result = svc.export_bundle(out)

    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest_text = zf.read(MANIFEST_NAME).decode("utf-8")
        csv_text = zf.read(CACHE_CSV_NAME).decode("utf-8")

    assert names == ALLOWED_BUNDLE_MEMBERS

    manifest = json.loads(manifest_text)
    assert set(manifest.keys()).issubset(ALLOWED_MANIFEST_KEYS)
    assert manifest["format_version"] == BUNDLE_FORMAT_VERSION
    assert manifest["row_count"] == 2
    assert manifest["cache_version"] == "20260509"
    assert manifest["bundle_sha256_of_data"] == result.bundle_sha256_of_data

    for forbidden in _FORBIDDEN_KEYWORDS:
        assert forbidden not in manifest_text, forbidden
        assert forbidden not in csv_text, forbidden

    assert "某客戶" not in manifest_text
    assert "某客戶" not in csv_text
    assert "C001" not in manifest_text
    assert "C001" not in csv_text


def test_export_then_import_roundtrip_into_fresh_db(
    tmp_path: Path, container: ServiceContainer
) -> None:
    """Round-trip: export, then import into a SECOND container at a fresh path
    and verify the cache row count + cache_version + sha match.
    """
    _seed_cache(container, tmp_path)
    svc = _build_bundle_service(container)
    out = tmp_path / "round.taxops-cache.zip"
    exp = svc.export_bundle(out)

    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations
    from taxops.services.container import build_container

    other_paths = resolve_paths(override_root=tmp_path / "OtherOffice")
    other_paths.data_root.mkdir(parents=True, exist_ok=True)
    other_paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn2 = open_connection(other_paths.db_path)
    apply_migrations(conn2)
    other = build_container(other_paths, conn2)
    try:
        other_svc = TaxCacheBundleService(
            registry_repo=TaxRegistryRepository(other.conn),
            metadata_repo=TaxCacheMetadataRepository(other.conn),
            audit=other.audit,
            system_log=other.system_log,
        )
        result = other_svc.import_bundle(out)
        assert result.row_count == exp.row_count
        assert result.cache_version == exp.cache_version
        assert result.bundle_sha256_of_data == exp.bundle_sha256_of_data
        repo2 = TaxRegistryRepository(other.conn)
        assert repo2.count() == 2
        assert repo2.find_by_tax_id("38965019") is not None

        # The second office machine should have NO clients (bundle never
        # carries them).
        assert other.clients.count() == 0
    finally:
        other.close()


def test_import_rejects_unexpected_member(
    tmp_path: Path, container: ServiceContainer
) -> None:
    _seed_cache(container, tmp_path)
    svc = _build_bundle_service(container)
    good = tmp_path / "good.taxops-cache.zip"
    svc.export_bundle(good)

    bad = tmp_path / "bad.taxops-cache.zip"
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(bad, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info))
        zout.writestr("clients.csv", "id,name\n1,leak\n")

    with pytest.raises(BundleError) as exc:
        svc.import_bundle(bad)
    assert exc.value.code == "registry.bundle.unexpected_members"


def test_import_rejects_tampered_csv_keeps_old_cache(
    tmp_path: Path, container: ServiceContainer
) -> None:
    _seed_cache(container, tmp_path)
    repo = TaxRegistryRepository(container.conn)
    assert repo.count() == 2

    svc = _build_bundle_service(container)
    bundle = tmp_path / "tampered.taxops-cache.zip"
    svc.export_bundle(bundle)

    with zipfile.ZipFile(bundle) as zin:
        manifest_bytes = zin.read(MANIFEST_NAME)
    tampered = tmp_path / "rebuilt.taxops-cache.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(MANIFEST_NAME, manifest_bytes)
        zout.writestr(CACHE_CSV_NAME, b"tax_id,business_name\n11111111,EVIL\n")

    with pytest.raises(BundleError) as exc:
        svc.import_bundle(tampered)
    assert exc.value.code in {
        "registry.bundle.tampered",
        "registry.bundle.csv_schema_mismatch",
    }
    assert repo.count() == 2
    assert repo.find_by_tax_id("38965019") is not None


def test_import_rejects_disallowed_manifest_key(
    tmp_path: Path, container: ServiceContainer
) -> None:
    _seed_cache(container, tmp_path)
    svc = _build_bundle_service(container)
    good = tmp_path / "good.taxops-cache.zip"
    svc.export_bundle(good)

    with zipfile.ZipFile(good) as zin:
        manifest = json.loads(zin.read(MANIFEST_NAME))
        csv_bytes = zin.read(CACHE_CSV_NAME)
    manifest["clients"] = {"leak": "should not be here"}

    bad = tmp_path / "bad-key.taxops-cache.zip"
    with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        )
        zout.writestr(CACHE_CSV_NAME, csv_bytes)

    with pytest.raises(BundleError) as exc:
        svc.import_bundle(bad)
    assert exc.value.code == "registry.bundle.disallowed_manifest_key"


def test_export_empty_cache_rejected(
    tmp_path: Path, container: ServiceContainer
) -> None:
    svc = _build_bundle_service(container)
    with pytest.raises(BundleError) as exc:
        svc.export_bundle(tmp_path / "out.taxops-cache.zip")
    assert exc.value.code == "registry.bundle.empty_cache"


def test_import_missing_file_rejected(
    tmp_path: Path, container: ServiceContainer
) -> None:
    svc = _build_bundle_service(container)
    with pytest.raises(BundleError) as exc:
        svc.import_bundle(tmp_path / "nope.taxops-cache.zip")
    assert exc.value.code == "registry.bundle.not_found"
