"""Parser for the official MOF ``BGMOPEN1.zip`` tax registry export.

Format reference (verified 2026-05-09 against the real file at
``https://eip.fia.gov.tw/data/BGMOPEN1.zip``):

- Single ZIP member: ``BGMOPEN1.csv``
- Encoding: UTF-8 without BOM
- Delimiter: ``,``
- 16 columns (header order):
    0  營業地址
    1  統一編號 (8-digit unified business number, primary identifier)
    2  總機構統一編號 (parent business number; blank for non-branches)
    3  營業人名稱
    4  資本額 (integer NTD, may be blank)
    5  設立日期 (民國 YYYMMDD; e.g. ``1040413`` = 民國 104-04-13)
    6  組織別名稱
    7  使用統一發票 (Y/N)
    8  行業代號 (primary)
    9  名稱 (primary industry name)
    10 行業代號1 / 11 名稱1
    12 行業代號2 / 13 名稱2
    14 行業代號3 / 15 名稱3
- Row 1 (after header) is a metadata row whose only filled field is col 0
  with an Oracle-style ``DD-MON-YY`` date (e.g. ``09-MAY-26``); data rows
  start at row 2.

The parser streams the file — it does NOT load the 320MB CSV into memory.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ...core.clock import today_iso

EXPECTED_CSV_NAME: str = "BGMOPEN1.csv"

EXPECTED_HEADERS: tuple[str, ...] = (
    "營業地址",
    "統一編號",
    "總機構統一編號",
    "營業人名稱",
    "資本額",
    "設立日期",
    "組織別名稱",
    "使用統一發票",
    "行業代號",
    "名稱",
    "行業代號1",
    "名稱1",
    "行業代號2",
    "名稱2",
    "行業代號3",
    "名稱3",
)

_ORACLE_DATE_RE = re.compile(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{2})\s*$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


class BGMOPEN1FormatError(Exception):
    """Raised when the input ZIP/CSV does not match the expected MOF format."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TaxRegistryEntry:
    tax_id: str
    business_name: str | None
    business_address: str | None
    parent_tax_id: str | None
    capital: int | None
    registered_date_roc: str | None
    organization_type: str | None
    uses_uniform_invoice: str | None
    industry_code_primary: str | None
    industry_name_primary: str | None
    industry_code_1: str | None
    industry_name_1: str | None
    industry_code_2: str | None
    industry_name_2: str | None
    industry_code_3: str | None
    industry_name_3: str | None


@dataclass(frozen=True)
class ParseHeader:
    """Metadata captured from the BGMOPEN1 file header rows."""

    data_freshness_raw: str | None
    data_freshness_iso: str | None
    cache_version: str


def parse_oracle_date(value: str | None) -> str | None:
    """Convert ``DD-MON-YY`` to ISO ``YYYY-MM-DD`` (rolling century)."""
    if value is None:
        return None
    m = _ORACLE_DATE_RE.match(value)
    if not m:
        return None
    day_s, mon_s, yy_s = m.groups()
    month = _MONTHS.get(mon_s.upper())
    if month is None:
        return None
    yy = int(yy_s)
    year = 2000 + yy if yy < 70 else 1900 + yy
    try:
        return f"{year:04d}-{month:02d}-{int(day_s):02d}"
    except ValueError:
        return None


def cache_version_from_freshness(freshness_iso: str | None) -> str:
    """Derive ``YYYYMMDD`` cache_version; fall back to today (UTC)."""
    if freshness_iso:
        return freshness_iso.replace("-", "")
    return today_iso().replace("-", "")


def _trim_or_none(v: str) -> str | None:
    s = v.strip()
    return s if s else None


def _row_to_entry(row: list[str]) -> TaxRegistryEntry:
    capital_raw = (row[4] or "").strip().replace(",", "")
    capital = int(capital_raw) if capital_raw.isdigit() else None
    return TaxRegistryEntry(
        tax_id=row[1].strip(),
        business_name=_trim_or_none(row[3]),
        business_address=_trim_or_none(row[0]),
        parent_tax_id=_trim_or_none(row[2]),
        capital=capital,
        registered_date_roc=_trim_or_none(row[5]),
        organization_type=_trim_or_none(row[6]),
        uses_uniform_invoice=_trim_or_none(row[7]),
        industry_code_primary=_trim_or_none(row[8]),
        industry_name_primary=_trim_or_none(row[9]),
        industry_code_1=_trim_or_none(row[10]),
        industry_name_1=_trim_or_none(row[11]),
        industry_code_2=_trim_or_none(row[12]),
        industry_name_2=_trim_or_none(row[13]),
        industry_code_3=_trim_or_none(row[14]),
        industry_name_3=_trim_or_none(row[15]),
    )


class BGMOPEN1Reader:
    """Streaming reader for the official MOF tax registry zip.

    Use as a context manager; ``header`` is available immediately after
    ``__enter__`` and ``entries()`` yields data rows lazily.
    """

    def __init__(self, zip_path: Path | str) -> None:
        self._zip_path = Path(zip_path)
        self._zf: zipfile.ZipFile | None = None
        self._text: io.TextIOWrapper | None = None
        self._reader = None  # type: ignore[var-annotated]
        self._header: ParseHeader | None = None
        self._first_row: list[str] | None = None
        self._first_consumed: bool = False
        self._opened: bool = False

    def __enter__(self) -> "BGMOPEN1Reader":
        self._open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def header(self) -> ParseHeader:
        if not self._opened:
            self._open()
        assert self._header is not None
        return self._header

    def entries(self) -> Iterator[TaxRegistryEntry]:
        if not self._opened:
            self._open()
        assert self._reader is not None
        if self._first_row is not None and not self._first_consumed:
            row = self._first_row
            self._first_row = None
            if len(row) == 16 and row[1].strip():
                yield _row_to_entry(row)
        for row in self._reader:
            if not row or len(row) != 16 or not row[1].strip():
                continue
            yield _row_to_entry(row)

    def close(self) -> None:
        if self._text is not None:
            self._text.close()
            self._text = None
        if self._zf is not None:
            self._zf.close()
            self._zf = None
        self._reader = None
        self._opened = False

    # ------------------------------------------------------------------
    def _open(self) -> None:
        if self._opened:
            return
        zf = zipfile.ZipFile(str(self._zip_path))
        try:
            if EXPECTED_CSV_NAME not in zf.namelist():
                raise BGMOPEN1FormatError("registry.zip.member_missing")
            raw = zf.open(EXPECTED_CSV_NAME, "r")
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(text)

            header_row = next(reader, None)
            if header_row is None:
                raise BGMOPEN1FormatError("registry.csv.empty")
            if tuple(header_row) != EXPECTED_HEADERS:
                raise BGMOPEN1FormatError("registry.csv.header_mismatch")

            first = next(reader, None)
            freshness_raw: str | None = None
            freshness_iso: str | None = None
            consumed = False
            if first and first[0] and not any(v.strip() for v in first[1:]):
                iso = parse_oracle_date(first[0])
                if iso is not None:
                    freshness_raw = first[0].strip()
                    freshness_iso = iso
                    consumed = True

            self._zf = zf
            self._text = text
            self._reader = reader
            self._first_row = first
            self._first_consumed = consumed
            self._header = ParseHeader(
                data_freshness_raw=freshness_raw,
                data_freshness_iso=freshness_iso,
                cache_version=cache_version_from_freshness(freshness_iso),
            )
            self._opened = True
        except BaseException:
            zf.close()
            raise
