"""Bulk client import — parse Excel/CSV/clipboard, map fields, validate, write."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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
    "address",
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
    "address": "地址",
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
    "地址": "address",
    "備註": "note",
    # English aliases
    "client_code": "client_code",
    "client_name": "client_name",
    "tax_id": "tax_id",
    "short_name": "short_name",
    "contact_name": "contact_name",
    "contact_phone": "contact_phone",
    "contact_email": "contact_email",
    "address": "address",
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


def parse_excel(path: Path) -> tuple[list[str], list[RawRow]]:
    """Return (headers, rows) from the first sheet of an xlsx file."""
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
        if i == 0:
            headers = cells
            continue
        if not any(cells):
            continue
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
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise BulkParseError("client.bulk.parse_failed", "cannot detect encoding")

    return _parse_delimited_text(text)


def parse_clipboard_text(text: str) -> tuple[list[str], list[RawRow]]:
    """Return (headers, rows) from tab- or comma-delimited clipboard text."""
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
        if i == 0:
            headers = cells
            continue
        if not any(cells):
            continue
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
        for orig_header, value in raw.data.items():
            canonical = mapping.get(orig_header)
            if canonical:
                mapped[canonical] = value

        vrow = BulkValidationRow(
            row_number=raw.row_number,
            raw=raw.data,
            mapped=mapped,
        )

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
                        address=m.get("address") or None,
                        note=m.get("note") or None,
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
                address=m.get("address") or None,
                note=m.get("note") or None,
            )
            clients_service.create_client(payload_create)
            imported += 1
        except (ClientValidationError, Exception) as exc:
            code = exc.code if isinstance(exc, ClientValidationError) else "system.unexpected"
            errors.append((vrow.row_number, code))
            skipped += 1

    return BulkImportResult(
        total=len(rows),
        imported=imported,
        skipped=skipped,
        overwritten=overwritten,
        errors=errors,
    )
