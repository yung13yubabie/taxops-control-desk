"""Unit tests for parse_excel() and parse_csv() in clients_bulk."""

from __future__ import annotations

import pathlib

import pytest

from taxops.services.clients_bulk import BulkParseError, parse_csv, parse_excel


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_xlsx(tmp_path: pathlib.Path, rows: list[list]) -> pathlib.Path:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return path


def _make_csv_file(
    tmp_path: pathlib.Path,
    content: str,
    filename: str,
    encoding: str,
) -> pathlib.Path:
    path = tmp_path / filename
    path.write_bytes(content.encode(encoding))
    return path


# ── parse_excel ───────────────────────────────────────────────────────────────


def test_parse_excel_valid(tmp_path: pathlib.Path) -> None:
    path = _make_xlsx(
        tmp_path,
        [
            ["client_code", "client_name", "tax_id"],
            ["C001", "測試公司A", "12345678"],
            ["C002", "測試公司B", "87654321"],
        ],
    )
    headers, rows = parse_excel(path)
    assert headers == ["client_code", "client_name", "tax_id"]
    assert len(rows) == 2
    assert rows[0].data["client_code"] == "C001"
    assert rows[0].data["client_name"] == "測試公司A"
    assert rows[1].data["client_code"] == "C002"


def test_parse_excel_blank_rows_skipped(tmp_path: pathlib.Path) -> None:
    path = _make_xlsx(
        tmp_path,
        [
            ["client_code", "client_name"],
            ["C001", "公司甲"],
            [None, None],
            ["C002", "公司乙"],
        ],
    )
    _headers, rows = parse_excel(path)
    assert len(rows) == 2


def test_parse_excel_header_only_raises(tmp_path: pathlib.Path) -> None:
    path = _make_xlsx(tmp_path, [["client_code", "client_name"]])
    with pytest.raises(BulkParseError) as exc_info:
        parse_excel(path)
    assert exc_info.value.code == "client.bulk.no_valid_rows"


def test_parse_excel_file_not_found_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "nonexistent.xlsx"
    with pytest.raises(BulkParseError) as exc_info:
        parse_excel(path)
    assert exc_info.value.code == "client.bulk.parse_failed"


# ── parse_csv ─────────────────────────────────────────────────────────────────


def test_parse_csv_utf8sig(tmp_path: pathlib.Path) -> None:
    content = "client_code,client_name,tax_id\nC001,台灣公司,12345678\n"
    path = _make_csv_file(tmp_path, content, "utf8sig.csv", "utf-8-sig")
    headers, rows = parse_csv(path)
    assert headers == ["client_code", "client_name", "tax_id"]
    assert len(rows) == 1
    assert rows[0].data["client_name"] == "台灣公司"


def test_parse_csv_utf8(tmp_path: pathlib.Path) -> None:
    content = "client_code,client_name\nC001,公司A\nC002,公司B\n"
    path = _make_csv_file(tmp_path, content, "utf8.csv", "utf-8")
    _headers, rows = parse_csv(path)
    assert len(rows) == 2


def test_parse_csv_cp950(tmp_path: pathlib.Path) -> None:
    content = "client_code,client_name\nC001,中文公司\n"
    path = _make_csv_file(tmp_path, content, "cp950.csv", "cp950")
    _headers, rows = parse_csv(path)
    assert rows[0].data["client_name"] == "中文公司"


def test_parse_csv_tab_delimited(tmp_path: pathlib.Path) -> None:
    content = "client_code\tclient_name\nC001\t公司甲\n"
    path = _make_csv_file(tmp_path, content, "tab.csv", "utf-8")
    headers, rows = parse_csv(path)
    assert headers == ["client_code", "client_name"]
    assert rows[0].data["client_code"] == "C001"


def test_parse_csv_header_only_raises(tmp_path: pathlib.Path) -> None:
    content = "client_code,client_name\n"
    path = _make_csv_file(tmp_path, content, "empty.csv", "utf-8")
    with pytest.raises(BulkParseError) as exc_info:
        parse_csv(path)
    assert exc_info.value.code == "client.bulk.no_valid_rows"
