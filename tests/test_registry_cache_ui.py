"""Registry cache UI contract and message guard tests.

Verifies:
1. The five slice-2 offline buttons are enabled and have complete contracts.
2. The HTTP download button remains disabled (slice 3).
3. No error message contains the forbidden phrase 「公司不存在」.
4. The not-found message uses the mandated canonical text.
5. The ZIP importer guard rejects wrong extensions and oversized files.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from taxops.i18n.errors import ERROR_MESSAGES
from taxops.services.registry.importer import (
    TaxRegistryImportError,
    TaxRegistryImporter,
    _MAX_ZIP_BYTES,
)
from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_SETTINGS

# ---------------------------------------------------------------------------
# Action contract assertions
# ---------------------------------------------------------------------------

_SLICE2_ENABLED = {
    "從 ZIP 匯入稅籍資料",
    "匯入稅籍快取包",
    "匯出稅籍快取包",
    "驗證快取",
    "重新產生客戶對照結果",
}

_SETTINGS_BY_LABEL = {
    a.button_label: a for a in ACTION_REGISTRY if a.page == PAGE_SETTINGS
}


def test_slice2_buttons_are_enabled() -> None:
    for label in _SLICE2_ENABLED:
        assert label in _SETTINGS_BY_LABEL, f"action missing from registry: {label}"
        assert _SETTINGS_BY_LABEL[label].enabled, f"expected enabled=True: {label}"


def test_slice2_buttons_have_service_repository_audit() -> None:
    for label in _SLICE2_ENABLED:
        action = _SETTINGS_BY_LABEL[label]
        assert action.service, f"missing service: {label}"
        assert action.repository, f"missing repository: {label}"
        assert action.audit_action, f"missing audit_action: {label}"


def test_slice2_buttons_have_settings_page_handler() -> None:
    for label in _SLICE2_ENABLED:
        action = _SETTINGS_BY_LABEL[label]
        assert action.handler.startswith("SettingsPage."), (
            f"handler must be SettingsPage.<method>: {label} → {action.handler}"
        )


def test_download_button_is_enabled_slice3() -> None:
    action = _SETTINGS_BY_LABEL["下載財政部稅籍資料"]
    assert action.enabled, "HTTP download must be enabled (Slice 3)"
    assert action.handler == "SettingsPage.on_download_registry"
    assert action.audit_action == "tax_cache.download"


# ---------------------------------------------------------------------------
# Forbidden phrase guard
# ---------------------------------------------------------------------------

_FORBIDDEN = "公司不存在"


def test_no_company_does_not_exist_in_any_error_message() -> None:
    for code, msg in ERROR_MESSAGES.items():
        assert _FORBIDDEN not in msg, (
            f"error code '{code}' contains forbidden phrase '{_FORBIDDEN}': {msg!r}"
        )


def test_not_found_message_uses_canonical_text() -> None:
    msg = ERROR_MESSAGES["registry.cache.not_found_message"]
    assert "本地快取查無此統一編號" in msg
    assert _FORBIDDEN not in msg


# ---------------------------------------------------------------------------
# ZIP importer guard
# ---------------------------------------------------------------------------


class _StubLog:
    def error(self, *a, **kw) -> None:
        pass


class _StubAudit:
    def record(self, **kw) -> None:
        pass


def _make_importer(tmp_path: Path) -> TaxRegistryImporter:
    from taxops.repositories.tax_registry import (
        TaxCacheMetadataRepository,
        TaxRegistryRepository,
    )

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE tax_registry_cache("
        "id INTEGER PRIMARY KEY, tax_id TEXT, business_name TEXT, "
        "business_address TEXT, parent_tax_id TEXT, capital INTEGER, "
        "registered_date_roc TEXT, organization_type TEXT, "
        "uses_uniform_invoice TEXT, industry_code_primary TEXT, "
        "industry_name_primary TEXT, industry_code_1 TEXT, industry_name_1 TEXT, "
        "industry_code_2 TEXT, industry_name_2 TEXT, "
        "industry_code_3 TEXT, industry_name_3 TEXT, "
        "cache_version TEXT, imported_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE tax_cache_metadata(key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()
    return TaxRegistryImporter(
        registry_repo=TaxRegistryRepository(conn),
        metadata_repo=TaxCacheMetadataRepository(conn),
        audit=_StubAudit(),  # type: ignore[arg-type]
        system_log=_StubLog(),  # type: ignore[arg-type]
    )


def test_importer_rejects_wrong_extension(tmp_path: Path) -> None:
    fake = tmp_path / "data.txt"
    fake.write_bytes(b"not a zip")
    importer = _make_importer(tmp_path)
    with pytest.raises(TaxRegistryImportError) as exc_info:
        importer.import_zip(fake)
    assert exc_info.value.code == "registry.zip.wrong_extension"


def test_importer_rejects_oversized_zip(tmp_path: Path) -> None:
    big = tmp_path / "big.zip"
    big.write_bytes(b"\x00" * (_MAX_ZIP_BYTES + 1))
    importer = _make_importer(tmp_path)
    with pytest.raises(TaxRegistryImportError) as exc_info:
        importer.import_zip(big)
    assert exc_info.value.code == "registry.zip.too_large"


def test_importer_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.zip"
    importer = _make_importer(tmp_path)
    with pytest.raises(TaxRegistryImportError) as exc_info:
        importer.import_zip(missing)
    assert exc_info.value.code == "registry.zip.not_found"


def test_max_zip_bytes_is_500mb() -> None:
    assert _MAX_ZIP_BYTES == 500 * 1024 * 1024


# ---------------------------------------------------------------------------
# Thread integration smoke: worker opens its own connection (no cross-thread)
# ---------------------------------------------------------------------------

import io
import threading
import zipfile as _zipfile

from taxops.core.paths import AppPaths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.services.container import build_container


def _make_minimal_bgmopen1_zip(tmp_path: Path) -> Path:
    """Two data rows, valid MOF CSV format (16 fields), written to a temp .zip."""
    # Header: exactly 16 named columns matching EXPECTED_HEADERS
    header = (
        "營業地址,統一編號,總機構統一編號,營業人名稱,資本額,設立日期,"
        "組織別名稱,使用統一發票,行業代號,名稱,行業代號1,名稱1,"
        "行業代號2,名稱2,行業代號3,名稱3\n"
    )
    # Meta row: col-0 is Oracle date, cols 1-15 are empty (15 trailing commas)
    meta_row = "09-MAY-26,,,,,,,,,,,,,,,\n"
    # Data rows: exactly 16 fields (15 commas per row)
    data_row1 = "台北市中正區,12345678,,測試公司甲,1000000,1040413,有限公司,Y,4711,零售,,,,,,\n"
    data_row2 = "台北市大安區,87654321,,測試公司乙,2000000,1050601,股份有限公司,Y,5812,餐飲,,,,,,\n"
    csv_content = header + meta_row + data_row1 + data_row2

    zip_path = tmp_path / "TEST_BGMOPEN1.zip"
    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BGMOPEN1.csv", csv_content.encode("utf-8"))
    zip_path.write_bytes(buf.getvalue())
    return zip_path


def _make_paths(tmp_path: Path) -> AppPaths:
    db_path = tmp_path / "taxops_thread_test.sqlite"
    return AppPaths(
        data_root=tmp_path,
        db_path=db_path,
        attachments_dir=tmp_path / "attachments",
        backups_dir=tmp_path / "backups",
    )


def test_worker_thread_opens_own_connection_no_cross_thread_error(
    tmp_path: Path,
) -> None:
    """_RegistryWorker pattern: fresh connection per thread → no ProgrammingError."""
    zip_path = _make_minimal_bgmopen1_zip(tmp_path)
    paths = _make_paths(tmp_path)

    # Pre-create the DB with migrations so the worker can find existing tables
    # (mirrors what the UI shell does at startup)
    init_conn = open_connection(paths.db_path)
    apply_migrations(init_conn)
    init_conn.close()

    errors: list[Exception] = []
    row_count_result: list[int] = []

    def _worker() -> None:
        conn = open_connection(paths.db_path)
        apply_migrations(conn)
        container = build_container(paths, conn)
        try:
            result = container.tax_cache_importer.import_zip(zip_path)
            row_count_result.append(result.row_count)
        except Exception as exc:
            errors.append(exc)
        finally:
            container.close()

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=30)

    assert not t.is_alive(), "worker thread timed out"
    assert not errors, f"worker raised: {errors[0]}"
    assert row_count_result == [2], f"expected 2 rows, got {row_count_result}"


def test_worker_thread_writes_audit_log(tmp_path: Path) -> None:
    """After worker import, audit_logs contains tax_cache.import.zip entry."""
    zip_path = _make_minimal_bgmopen1_zip(tmp_path)
    paths = _make_paths(tmp_path)

    init_conn = open_connection(paths.db_path)
    apply_migrations(init_conn)
    init_conn.close()

    def _worker() -> None:
        conn = open_connection(paths.db_path)
        apply_migrations(conn)
        container = build_container(paths, conn)
        try:
            container.tax_cache_importer.import_zip(zip_path)
        finally:
            container.close()

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=30)
    assert not t.is_alive()

    verify_conn = open_connection(paths.db_path)
    rows = verify_conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'tax_cache.import.zip'"
    ).fetchall()
    verify_conn.close()

    assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
