"""BGMOPEN1 parser tests.

Synthetic-format coverage uses small zips built in ``tmp_path``. A real-
format coverage test runs only when ``tmp/BGMOPEN1.zip`` exists at the
project root (the dev box downloads it once via the format-probe step).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from taxops.services.registry.parser import (
    BGMOPEN1FormatError,
    BGMOPEN1Reader,
    EXPECTED_CSV_NAME,
    EXPECTED_HEADERS,
    cache_version_from_freshness,
    parse_oracle_date,
)


def _make_zip(
    tmp_path: Path,
    csv_text: str,
    member_name: str = EXPECTED_CSV_NAME,
) -> Path:
    zip_path = tmp_path / "input.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, csv_text.encode("utf-8"))
    return zip_path


def _csv_with_header(body: str) -> str:
    return ",".join(EXPECTED_HEADERS) + "\n" + body


def test_parse_oracle_date_basic() -> None:
    assert parse_oracle_date("09-MAY-26") == "2026-05-09"
    assert parse_oracle_date("31-DEC-99") == "1999-12-31"
    assert parse_oracle_date("01-JAN-00") == "2000-01-01"
    assert parse_oracle_date("  15-FEB-25  ") == "2025-02-15"


def test_parse_oracle_date_invalid() -> None:
    assert parse_oracle_date(None) is None
    assert parse_oracle_date("") is None
    assert parse_oracle_date("garbage") is None
    assert parse_oracle_date("2026-05-09") is None
    assert parse_oracle_date("99-XYZ-26") is None


def test_cache_version_uses_freshness_when_available() -> None:
    assert cache_version_from_freshness("2026-05-09") == "20260509"


def test_cache_version_falls_back_to_today_when_missing() -> None:
    cv = cache_version_from_freshness(None)
    assert len(cv) == 8 and cv.isdigit()


def test_parser_reads_synthetic_zip(tmp_path: Path) -> None:
    body = (
        "09-MAY-26,,,,,,,,,,,,,,,\n"
        "南投縣中寮鄉中寮村永平路371號,38965019,,原味商行,100000,1040413,獨資,N,472927,豆類製品零售,,,,,,\n"
        "南投縣中寮鄉中寮村鄉林巷43號,61194605,,和興商店,1000,0400711,獨資,N,472913,菸酒零售,471913,雜貨店,,,,\n"
    )
    zip_path = _make_zip(tmp_path, _csv_with_header(body))

    with BGMOPEN1Reader(zip_path) as reader:
        h = reader.header
        assert h.data_freshness_raw == "09-MAY-26"
        assert h.data_freshness_iso == "2026-05-09"
        assert h.cache_version == "20260509"
        entries = list(reader.entries())

    assert len(entries) == 2
    e0 = entries[0]
    assert e0.tax_id == "38965019"
    assert e0.business_name == "原味商行"
    assert e0.business_address == "南投縣中寮鄉中寮村永平路371號"
    assert e0.capital == 100000
    assert e0.registered_date_roc == "1040413"
    assert e0.organization_type == "獨資"
    assert e0.uses_uniform_invoice == "N"
    assert e0.industry_code_primary == "472927"
    assert e0.industry_name_primary == "豆類製品零售"
    assert e0.industry_code_1 is None

    e1 = entries[1]
    assert e1.tax_id == "61194605"
    assert e1.industry_code_1 == "471913"
    assert e1.industry_name_1 == "雜貨店"


def test_parser_rejects_unexpected_zip_member(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path, _csv_with_header(""), member_name="OTHER.csv")
    with pytest.raises(BGMOPEN1FormatError) as exc:
        BGMOPEN1Reader(zip_path).__enter__()
    assert exc.value.code == "registry.zip.member_missing"


def test_parser_rejects_header_mismatch(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path, "wrong,header\n")
    with pytest.raises(BGMOPEN1FormatError) as exc:
        BGMOPEN1Reader(zip_path).__enter__()
    assert exc.value.code == "registry.csv.header_mismatch"


def test_parser_rejects_empty_csv(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path, "")
    with pytest.raises(BGMOPEN1FormatError) as exc:
        BGMOPEN1Reader(zip_path).__enter__()
    assert exc.value.code == "registry.csv.empty"


def test_parser_treats_metadata_row_as_data_when_other_cols_filled(tmp_path: Path) -> None:
    """A row with date in col 0 but real values in other cols is data, not metadata."""
    body = "09-MAY-26,12345678,,測試A公司,500000,1100101,獨資,Y,000000,測試業,,,,,,\n"
    zip_path = _make_zip(tmp_path, _csv_with_header(body))

    with BGMOPEN1Reader(zip_path) as reader:
        assert reader.header.data_freshness_iso is None
        entries = list(reader.entries())

    assert len(entries) == 1
    assert entries[0].tax_id == "12345678"
    assert entries[0].business_name == "測試A公司"


def test_parser_skips_rows_with_blank_tax_id(tmp_path: Path) -> None:
    body = (
        "09-MAY-26,,,,,,,,,,,,,,,\n"
        ",,,,,,,,,,,,,,,\n"
        "地址X,11111111,,公司X,1000,1100101,獨資,N,000000,業,,,,,,\n"
    )
    zip_path = _make_zip(tmp_path, _csv_with_header(body))
    with BGMOPEN1Reader(zip_path) as reader:
        entries = list(reader.entries())
    assert len(entries) == 1
    assert entries[0].tax_id == "11111111"


def test_parser_capital_handles_blank_and_non_digit(tmp_path: Path) -> None:
    body = (
        "09-MAY-26,,,,,,,,,,,,,,,\n"
        "地址1,11111111,,公司1, ,1100101,獨資,N,000000,業,,,,,,\n"
        "地址2,22222222,,公司2,N/A,1100101,獨資,N,000000,業,,,,,,\n"
        "地址3,33333333,,公司3,5000000,1100101,獨資,N,000000,業,,,,,,\n"
    )
    zip_path = _make_zip(tmp_path, _csv_with_header(body))
    with BGMOPEN1Reader(zip_path) as reader:
        entries = list(reader.entries())
    assert [e.capital for e in entries] == [None, None, 5000000]


# ---------------------------------------------------------------------------
# Real BGMOPEN1.zip coverage — runs only on dev boxes that have the file.
# ---------------------------------------------------------------------------

REAL_BGMOPEN1 = Path("tmp/BGMOPEN1.zip")


@pytest.mark.skipif(
    not REAL_BGMOPEN1.exists(),
    reason="real BGMOPEN1.zip not present at tmp/BGMOPEN1.zip — skip; "
    "see docs/registry_cache_workflow.md for how to fetch it.",
)
def test_parser_handles_real_bgmopen1_first_n_rows() -> None:
    with BGMOPEN1Reader(REAL_BGMOPEN1) as reader:
        h = reader.header
        assert h.data_freshness_iso, "real MOF file should have a freshness row"
        assert h.cache_version and len(h.cache_version) == 8
        first_n: list = []
        for entry in reader.entries():
            first_n.append(entry)
            if len(first_n) >= 100:
                break

    assert len(first_n) == 100
    for entry in first_n:
        assert entry.tax_id and len(entry.tax_id) == 8 and entry.tax_id.isdigit(), entry
        assert entry.business_name, entry
        assert entry.business_address, entry
        assert entry.industry_code_primary, entry
