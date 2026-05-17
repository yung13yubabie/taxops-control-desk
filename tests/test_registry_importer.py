"""TaxRegistryImporter end-to-end tests.

Covers:
- Successful import populates tax_registry_cache + tax_cache_metadata
  + audit log row.
- Re-import replaces all rows atomically (count never grows beyond the
  latest source).
- Bad header / missing member / non-existent file are rejected without
  touching the formal cache.
- Staging rollback: an error mid-stream leaves the formal cache intact.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from taxops.repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from taxops.services.container import ServiceContainer
from taxops.services.registry.importer import (
    TaxRegistryImporter,
    TaxRegistryImportError,
    sha256_of_file,
)
from taxops.services.registry.parser import (
    BGMOPEN1FormatError,
    EXPECTED_CSV_NAME,
    EXPECTED_HEADERS,
)


def _csv(body: str) -> str:
    return ",".join(EXPECTED_HEADERS) + "\n" + body


def _make_zip(
    tmp_path: Path,
    csv_text: str,
    member_name: str = EXPECTED_CSV_NAME,
    name: str = "input.zip",
) -> Path:
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, csv_text.encode("utf-8"))
    return zip_path


def _build_importer(container: ServiceContainer) -> TaxRegistryImporter:
    return TaxRegistryImporter(
        registry_repo=TaxRegistryRepository(container.conn),
        metadata_repo=TaxCacheMetadataRepository(container.conn),
        audit=container.audit,
        system_log=container.system_log,
    )


_BODY_TWO_ROWS = (
    "09-MAY-26,,,,,,,,,,,,,,,\n"
    "地址1,38965019,,原味商行,100000,1040413,獨資,N,472927,豆類製品零售,,,,,,\n"
    "地址2,61194605,,和興商店,1000,0400711,獨資,N,472913,菸酒零售,471913,雜貨店,,,,\n"
)


def test_import_zip_populates_cache_and_metadata_and_audit(
    tmp_path: Path, container: ServiceContainer
) -> None:
    zip_path = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS))
    importer = _build_importer(container)

    result = importer.import_zip(zip_path)

    assert result.row_count == 2
    assert result.cache_version == "20260509"
    assert result.data_freshness_iso == "2026-05-09"
    assert len(result.source_sha256) == 64

    repo = TaxRegistryRepository(container.conn)
    assert repo.count() == 2
    row = repo.find_by_tax_id("38965019")
    assert row is not None
    assert row["business_name"] == "原味商行"
    assert row["cache_version"] == "20260509"

    meta = TaxCacheMetadataRepository(container.conn).get_all()
    assert meta["cache_version"] == "20260509"
    assert meta["row_count"] == "2"
    assert meta["last_import_source"] == "zip"
    assert meta["source_sha256"] == result.source_sha256
    assert meta["data_freshness_iso"] == "2026-05-09"

    audits = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    actions = [r.action for r in audits]
    assert "tax_cache.import.zip" in actions


def test_import_replaces_existing_cache(
    tmp_path: Path, container: ServiceContainer
) -> None:
    """Re-importing a smaller file shrinks the cache (atomic replace)."""
    big = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS), name="big.zip")
    small_body = (
        "10-MAY-26,,,,,,,,,,,,,,,\n"
        "地址A,11111111,,新公司,5000,1100101,獨資,Y,000000,業,,,,,,\n"
    )
    small = _make_zip(tmp_path, _csv(small_body), name="small.zip")

    importer = _build_importer(container)
    importer.import_zip(big)
    repo = TaxRegistryRepository(container.conn)
    assert repo.count() == 2

    importer.import_zip(small)
    assert repo.count() == 1
    assert repo.find_by_tax_id("38965019") is None
    assert repo.find_by_tax_id("11111111") is not None
    meta = TaxCacheMetadataRepository(container.conn).get_all()
    assert meta["cache_version"] == "20260510"
    assert meta["row_count"] == "1"


def test_import_rejects_missing_file(container: ServiceContainer, tmp_path: Path) -> None:
    importer = _build_importer(container)
    with pytest.raises(TaxRegistryImportError) as exc:
        importer.import_zip(tmp_path / "nope.zip")
    assert exc.value.code == "registry.zip.not_found"


def test_import_rejects_bad_zip_member(
    tmp_path: Path, container: ServiceContainer
) -> None:
    bad = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS), member_name="OTHER.csv")
    importer = _build_importer(container)
    with pytest.raises(BGMOPEN1FormatError) as exc:
        importer.import_zip(bad)
    assert exc.value.code == "registry.zip.member_missing"


def test_import_rejects_header_mismatch_keeps_old_cache(
    tmp_path: Path, container: ServiceContainer
) -> None:
    importer = _build_importer(container)
    good = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS), name="good.zip")
    importer.import_zip(good)
    repo = TaxRegistryRepository(container.conn)
    assert repo.count() == 2

    bad = _make_zip(tmp_path, "wrong,header\n", name="bad.zip")
    with pytest.raises(BGMOPEN1FormatError):
        importer.import_zip(bad)
    assert repo.count() == 2


def test_import_zero_rows_rejected_keeps_old_cache(
    tmp_path: Path, container: ServiceContainer
) -> None:
    importer = _build_importer(container)
    good = _make_zip(tmp_path, _csv(_BODY_TWO_ROWS), name="good.zip")
    importer.import_zip(good)
    repo = TaxRegistryRepository(container.conn)
    assert repo.count() == 2

    empty = _make_zip(
        tmp_path,
        _csv("09-MAY-26,,,,,,,,,,,,,,,\n"),
        name="empty.zip",
    )
    with pytest.raises(TaxRegistryImportError) as exc:
        importer.import_zip(empty)
    assert exc.value.code == "registry.import.failed"
    assert repo.count() == 2


def test_sha256_of_file_matches_hashlib(tmp_path: Path) -> None:
    payload = b"hello taxops"
    p = tmp_path / "x.bin"
    p.write_bytes(payload)
    digest, size = sha256_of_file(p)
    import hashlib

    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)
