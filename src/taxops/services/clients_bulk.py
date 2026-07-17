"""Bulk client import — parse Excel/CSV/clipboard, map fields, validate, write."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_log = logging.getLogger(__name__)

MAX_BULK_ROWS = 10_000
MAX_BULK_COLUMNS = 100
MAX_BULK_CELL_CHARS = 10_000
MAX_BULK_FILE_BYTES = 50 * 1024 * 1024
MAX_BULK_CLIPBOARD_CHARS = 5_000_000

from ..core.text import sanitize_user_text
from ..repositories.clients import ClientsRepository
from .clients import ClientValidationError, ClientsService, CreateClientInput

BULK_FIELDS = [
    "client_code",
    "client_name",
    "tax_id",
    "short_name",
    "contact_name",
    "contact_phone",
    "contact_email",
    "registered_address",
    "contact_address",
    "contact_address_same",
    "note",
]

BULK_FIELD_LABELS: dict[str, str] = {
    "client_code": "客戶代號",
    "client_name": "客戶名稱",
    "tax_id": "統一編號",
    "short_name": "簡稱",
    "contact_name": "聯絡人",
    "contact_phone": "聯絡電話",
    "contact_email": "聯絡信箱",
    "registered_address": "登記地址",
    "contact_address": "聯絡地址",
    "contact_address_same": "聯絡地址同登記",
    "note": "備註",
}

_COLUMN_ALIASES: dict[str, str] = {
    # Chinese labels
    "客戶代號": "client_code",
    "代號": "client_code",
    "客戶名稱": "client_name",
    "名稱": "client_name",
    "統一編號": "tax_id",
    "統編": "tax_id",
    "簡稱": "short_name",
    "聯絡人": "contact_name",
    "聯絡電話": "contact_phone",
    "電話": "contact_phone",
    "聯絡信箱": "contact_email",
    "信箱": "contact_email",
    "email": "contact_email",
    "Email": "contact_email",
    "登記地址": "registered_address",
    "設籍地址": "registered_address",
    "地址": "registered_address",
    "聯絡地址": "contact_address",
    "聯絡地址同登記": "contact_address_same",
    "聯絡地址同設籍": "contact_address_same",
    "備註": "note",
    # English aliases
    "client_code": "client_code",
    "client_name": "client_name",
    "tax_id": "tax_id",
    "short_name": "short_name",
    "contact_name": "contact_name",
    "contact_phone": "contact_phone",
    "contact_email": "contact_email",
    "registered_address": "registered_address",
    "contact_address": "contact_address",
    "contact_address_same": "contact_address_same",
    "address": "registered_address",
    "note": "note",
    "code": "client_code",
    "name": "client_name",
    "phone": "contact_phone",
}


class BulkParseError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class RawRow:
    row_number: int
    data: dict[str, str]


@dataclass
class BulkValidationRow:
    row_number: int
    raw: dict[str, str]
    mapped: dict[str, str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_duplicate_code: bool = False
    is_duplicate_tax_id: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class BulkImportResult:
    total: int
    imported: int
    skipped: int
    overwritten: int
    errors: list[tuple[int, str]]


def _validate_bulk_file_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BulkParseError("client.bulk.parse_failed", str(exc)) from exc
    if size > MAX_BULK_FILE_BYTES:
        raise BulkParseError("client.bulk.file_too_large")


def parse_excel(path: Path) -> tuple[list[str], list[RawRow]]:
    """Return (headers, rows) from the first sheet of an xlsx file."""
    _validate_bulk_file_size(path)
    try:
        import openpyxl
    except ImportError as exc:
        raise BulkParseError("client.bulk.parse_failed", "openpyxl not installed") from exc

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise BulkParseError("client.bulk.parse_failed", str(exc)) from exc

    ws = wb.active
    if ws is None:
        raise BulkParseError("client.bulk.no_valid_rows")

    rows_iter = ws.iter_rows(values_only=True)
    headers: list[str] = []
    raw_rows: list[RawRow] = []

    for i, row in enumerate(rows_iter):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if any(len(cell) > MAX_BULK_CELL_CHARS for cell in cells):
            raise BulkParseError("client.bulk.cell_too_large")
        if i == 0:
            if len(cells) > MAX_BULK_COLUMNS:
                raise BulkParseError("client.bulk.too_many_columns")
            headers = cells
            continue
        if not any(cells):
            continue
        if len(raw_rows) >= MAX_BULK_ROWS:
            raise BulkParseError("client.bulk.too_many_rows")
        data = {headers[j]: cells[j] for j in range(min(len(headers), len(cells)))}
        raw_rows.append(RawRow(row_number=i + 1, data=data))

    wb.close()

    if not headers:
        raise BulkParseError("client.bulk.parse_failed", "empty sheet")
    if not raw_rows:
        raise BulkParseError("client.bulk.no_valid_rows")

    return headers, raw_rows


def parse_csv(path: Path) -> tuple[list[str], list[RawRow]]:
    """Return (headers, rows) from a CSV file (auto-detect encoding)."""
    _validate_bulk_file_size(path)
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError as exc:
            raise BulkParseError("client.bulk.parse_failed", str(exc)) from exc
    else:
        raise BulkParseError("client.bulk.parse_failed", "cannot detect encoding")

    return _parse_delimited_text(text)


def parse_clipboard_text(text: str) -> tuple[list[str], list[RawRow]]:
    """Return (headers, rows) from tab- or comma-delimited clipboard text."""
    if len(text) > MAX_BULK_CLIPBOARD_CHARS:
        raise BulkParseError("client.bulk.clipboard_too_large")
    if not text.strip():
        raise BulkParseError("client.bulk.no_valid_rows")
    return _parse_delimited_text(text)


def _parse_delimited_text(text: str) -> tuple[list[str], list[RawRow]]:
    sample = text[:2048]
    tab_count = sample.count("\t")
    comma_count = sample.count(",")
    delimiter = "\t" if tab_count >= comma_count else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers: list[str] = []
    raw_rows: list[RawRow] = []

    for i, row in enumerate(reader):
        cells = [c.strip() for c in row]
        if any(len(cell) > MAX_BULK_CELL_CHARS for cell in cells):
            raise BulkParseError("client.bulk.cell_too_large")
        if i == 0:
            if len(cells) > MAX_BULK_COLUMNS:
                raise BulkParseError("client.bulk.too_many_columns")
            headers = cells
            continue
        if not any(cells):
            continue
        if len(raw_rows) >= MAX_BULK_ROWS:
            raise BulkParseError("client.bulk.too_many_rows")
        data = {headers[j]: cells[j] for j in range(min(len(headers), len(cells)))}
        raw_rows.append(RawRow(row_number=i + 1, data=data))

    if not headers:
        raise BulkParseError("client.bulk.parse_failed", "no header row")
    if not raw_rows:
        raise BulkParseError("client.bulk.no_valid_rows")

    return headers, raw_rows


def auto_detect_mapping(headers: list[str]) -> dict[str, str]:
    """Map original header strings to canonical field names.

    Returns only headers that matched a known alias.
    """
    mapping: dict[str, str] = {}
    for h in headers:
        canonical = _COLUMN_ALIASES.get(h.strip())
        if canonical:
            mapping[h] = canonical
    return mapping


_TRUE_VALUES = frozenset({"1", "是", "true"})
_FALSE_VALUES = frozenset({"0", "否", "false"})
_LEGACY_ADDRESS_HEADERS = frozenset({"地址", "address"})


def _parse_contact_address_same(value: str) -> bool | None:
    cleaned = value.strip().casefold()
    if not cleaned:
        return None
    if cleaned in _TRUE_VALUES:
        return True
    if cleaned in _FALSE_VALUES:
        return False
    raise ValueError("invalid contact_address_same")


def validate_rows(
    raw_rows: list[RawRow],
    mapping: dict[str, str],
    clients_repo: ClientsRepository,
) -> list[BulkValidationRow]:
    """Validate each row against business rules.

    ``mapping`` maps original header → canonical field name.
    """
    reverse: dict[str, str] = {v: k for k, v in mapping.items()}
    results: list[BulkValidationRow] = []

    for raw in raw_rows:
        mapped: dict[str, str] = {}
        address_conflict = False
        registered_source_is_legacy: bool | None = None
        for orig_header, value in raw.data.items():
            canonical = mapping.get(orig_header)
            if canonical:
                if canonical == "registered_address":
                    incoming_is_legacy = orig_header.strip() in _LEGACY_ADDRESS_HEADERS
                    if "registered_address" in mapped:
                        previous = sanitize_user_text(
                            mapped["registered_address"],
                            max_length=MAX_BULK_CELL_CHARS,
                        )
                        incoming = sanitize_user_text(
                            value,
                            max_length=MAX_BULK_CELL_CHARS,
                        )
                        if previous and incoming and previous != incoming:
                            address_conflict = True
                        # A canonical header has precedence over a legacy one,
                        # independent of source-column order.
                        if incoming_is_legacy and registered_source_is_legacy is False:
                            continue
                    registered_source_is_legacy = incoming_is_legacy
                mapped[canonical] = value

        vrow = BulkValidationRow(
            row_number=raw.row_number,
            raw=raw.data,
            mapped=mapped,
        )
        if address_conflict:
            vrow.errors.append("client.address.conflict")

        client_code = sanitize_user_text(mapped.get("client_code", ""), max_length=50)
        if not client_code:
            label = BULK_FIELD_LABELS["client_code"]
            vrow.errors.append(f"缺少必填欄位：{label}")
        else:
            existing = clients_repo.find_by_code(client_code)
            if existing is not None:
                vrow.is_duplicate_code = True
                vrow.warnings.append(f"客戶代號「{client_code}」已存在")

        client_name = sanitize_user_text(mapped.get("client_name", ""), max_length=200)
        if not client_name:
            label = BULK_FIELD_LABELS["client_name"]
            vrow.errors.append(f"缺少必填欄位：{label}")

        tax_id_raw = mapped.get("tax_id", "").strip()
        if tax_id_raw:
            if len(tax_id_raw) != 8 or not tax_id_raw.isdigit():
                vrow.errors.append("統一編號格式不正確（需為 8 位數字）")
            else:
                existing_by_tax = clients_repo.find_by_tax_id(tax_id_raw)
                if existing_by_tax:
                    vrow.is_duplicate_tax_id = True
                    vrow.warnings.append(f"統一編號「{tax_id_raw}」已有其他客戶使用")

        if "contact_address_same" in mapped:
            try:
                _parse_contact_address_same(mapped["contact_address_same"])
            except ValueError:
                vrow.errors.append("client.contact_address_same.invalid")

        results.append(vrow)

    return results


DuplicatePolicy = Literal["skip", "overwrite"]


def import_validated(
    rows: list[BulkValidationRow],
    clients_service: ClientsService,
    on_duplicate_code: DuplicatePolicy = "skip",
) -> BulkImportResult:
    """Write valid rows to the database.

    Invalid rows (rows with errors) are always skipped.
    Duplicate-code rows are handled per ``on_duplicate_code``:
    - "skip": skip the row entirely
    - "overwrite": update the existing client with new data
    """
    imported = 0
    skipped = 0
    overwritten = 0
    errors: list[tuple[int, str]] = []

    for vrow in rows:
        if not vrow.is_valid:
            skipped += 1
            continue

        if vrow.is_duplicate_code and on_duplicate_code == "skip":
            skipped += 1
            continue

        m = vrow.mapped
        address_kwargs: dict[str, object] = {}
        if "registered_address" in m:
            address_kwargs["registered_address"] = m["registered_address"] or None
        if "contact_address" in m:
            address_kwargs["contact_address"] = m["contact_address"] or None
        if "contact_address_same" in m:
            parsed_same = _parse_contact_address_same(m["contact_address_same"])
            if parsed_same is not None:
                address_kwargs["contact_address_same"] = parsed_same
        try:
            if vrow.is_duplicate_code and on_duplicate_code == "overwrite":
                existing = clients_service.find_by_code(
                    sanitize_user_text(m.get("client_code", ""), max_length=50)
                )
                if existing is not None:
                    from .clients import UpdateClientInput

                    payload = UpdateClientInput(
                        client_code=m.get("client_code", ""),
                        client_name=m.get("client_name", ""),
                        tax_id=m.get("tax_id") or None,
                        short_name=m.get("short_name") or None,
                        contact_name=m.get("contact_name") or None,
                        contact_phone=m.get("contact_phone") or None,
                        contact_email=m.get("contact_email") or None,
                        note=m.get("note") or None,
                        **address_kwargs,
                    )
                    clients_service.update_client(existing.id, payload)
                    overwritten += 1
                else:
                    # TOCTOU: client was removed between validate and import
                    errors.append((vrow.row_number, "client.not_found"))
                    skipped += 1
                continue

            payload_create = CreateClientInput(
                client_code=m.get("client_code", ""),
                client_name=m.get("client_name", ""),
                tax_id=m.get("tax_id") or None,
                short_name=m.get("short_name") or None,
                contact_name=m.get("contact_name") or None,
                contact_phone=m.get("contact_phone") or None,
                contact_email=m.get("contact_email") or None,
                note=m.get("note") or None,
                **address_kwargs,
            )
            clients_service.create_client(payload_create)
            imported += 1
        except ClientValidationError as exc:
            errors.append((vrow.row_number, exc.code))
            skipped += 1
        except Exception:
            _log.error("bulk_import: unexpected error row=%d", vrow.row_number, exc_info=True)
            errors.append((vrow.row_number, "system.unexpected"))
            skipped += 1

    return BulkImportResult(
        total=len(rows),
        imported=imported,
        skipped=skipped,
        overwritten=overwritten,
        errors=errors,
    )
