"""Offscreen smoke tests for SettingsPage.

Covers everything verifiable without a real display or human interaction:
- SettingsPage construction with empty cache
- Cache status label text (empty / populated states)
- on_verify_cache() result text (QMessageBox mocked)
- Slice-2 button enabled/disabled states
- Cache status label updates after import

QFileDialog / QProgressDialog / QThread visual interaction requires a real
desktop and is explicitly left as [待驗收] in docs/windows_candidate_gate.md.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from taxops.services.container import ServiceContainer
    from taxops.services.registry.importer import ImportResult

# ---------------------------------------------------------------------------
# Qt application fixture (offscreen, module-scoped — create only once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    if existing:
        yield existing
        return
    app = QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_container(tmp_path: Path):
    from taxops.core.paths import AppPaths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations
    from taxops.services.container import build_container

    paths = AppPaths(
        data_root=tmp_path,
        db_path=tmp_path / "taxops.sqlite",
        attachments_dir=tmp_path / "attachments",
        backups_dir=tmp_path / "backups",
    )
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


REAL_ZIP = Path(__file__).parent.parent / "tmp" / "BGMOPEN1.zip"


@dataclass(frozen=True)
class _ImportedCacheSnapshot:
    db_path: Path
    result: ImportResult
    empty_text: str
    populated_text: str


def _close_page(page) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def _import_cache_snapshot(root: Path, zip_path: Path) -> _ImportedCacheSnapshot:
    """Exercise the real importer and live page once, without UI assertions."""
    from taxops.ui.pages.settings_page import SettingsPage

    root.mkdir()
    container = _make_container(root)
    page = None
    try:
        page = SettingsPage(container)
        empty_text = page._cache_status_label.text()
        result = container.tax_cache_importer.import_zip(zip_path)
        page._refresh_cache_status()
        return _ImportedCacheSnapshot(
            container.paths.db_path, result, empty_text,
            page._cache_status_label.text(),
        )
    finally:
        if page is not None:
            _close_page(page)
        container.close()


@pytest.fixture(scope="module")
def real_import_snapshot(qt_app, tmp_path_factory) -> _ImportedCacheSnapshot:
    # Parse every row of the tracked government ZIP. Only this expensive setup
    # is shared; neither UI test receives a mutable shared page or connection.
    root = tmp_path_factory.mktemp("settings-real-import") / "seed"
    return _import_cache_snapshot(root, REAL_ZIP)


def _restore_cache_snapshot(
    snapshot: _ImportedCacheSnapshot, container: ServiceContainer,
) -> None:
    # SQLite's backup API includes committed WAL contents. A plain file copy
    # could silently lose rows, metadata, or the import audit record.
    source = sqlite3.connect(snapshot.db_path.as_uri() + "?mode=ro", uri=True)
    try:
        source.backup(container.conn)
    finally:
        source.close()


def _assert_import_provenance(
    snapshot: _ImportedCacheSnapshot, container: ServiceContainer,
) -> None:
    result = snapshot.result
    assert container.tax_registry_repo.count() == result.row_count
    assert container.tax_cache_metadata_repo.get_all() == {
        "cache_version": result.cache_version,
        "source": "zip",
        "source_sha256": result.source_sha256,
        "source_size": str(result.source_size),
        "imported_at": result.imported_at,
        "data_freshness_raw": result.data_freshness_raw or "",
        "data_freshness_iso": result.data_freshness_iso or "",
        "last_import_source": "zip",
        "row_count": str(result.row_count),
    }
    imports = container.conn.execute(
        "SELECT target_type, target_id, detail_json FROM audit_logs "
        "WHERE action = 'tax_cache.import.zip'"
    ).fetchall()
    assert len(imports) == 1
    assert imports[0]["target_type"] == "tax_cache"
    assert imports[0]["target_id"] == result.cache_version
    assert json.loads(imports[0]["detail_json"]) == {
        "row_count": result.row_count,
        "cache_version": result.cache_version,
        "source_sha256": result.source_sha256,
        "source_size": result.source_size,
        "data_freshness_iso": result.data_freshness_iso,
    }

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_settings_page_constructs_without_error(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        page.show()
        assert page is not None
    finally:
        container.close()


def test_empty_cache_status_label(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        text = page._cache_status_label.text()
        assert text.strip() != ""
        assert "本機稅籍資料" in text
    finally:
        container.close()


def test_five_slice2_buttons_are_enabled_in_ui(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        assert len(page._slice2_buttons) == 5
        for btn in page._slice2_buttons:
            assert btn.isEnabled(), f"button '{btn.text()}' should be enabled"
    finally:
        container.close()


def test_download_button_is_enabled_in_ui(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        assert page._download_btn is not None
        assert page._download_btn.isEnabled(), (
            "下載財政部稅籍資料 button must be enabled (Slice 3)"
        )
    finally:
        container.close()


def test_verify_cache_on_empty_db_shows_message(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        with patch("taxops.ui.pages.settings_page.QMessageBox") as mock_mb:
            mock_mb.information = MagicMock()
            mock_mb.warning = MagicMock()
            page.on_verify_cache()
            called = mock_mb.information.called or mock_mb.warning.called
            assert called, "QMessageBox was not called by on_verify_cache"
    finally:
        container.close()


@pytest.mark.skipif(
    not REAL_ZIP.exists(),
    reason="tmp/BGMOPEN1.zip not present — real zip smoke skipped",
)
def test_cache_status_label_updates_after_real_import(
    qt_app, tmp_path, real_import_snapshot,
) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    page = None
    try:
        page = SettingsPage(container)
        empty_text = page._cache_status_label.text()

        _restore_cache_snapshot(real_import_snapshot, container)
        page._refresh_cache_status()
        populated_text = page._cache_status_label.text()

        assert populated_text != empty_text, "status label did not change after import"
        # Also keep the original real service -> same-page refresh assertion,
        # independently of restoring that imported database to this test's page.
        assert real_import_snapshot.populated_text != real_import_snapshot.empty_text
        assert populated_text == real_import_snapshot.populated_text
        # Real BGMOPEN1.zip has ~1,705,060 rows
        assert any(marker in populated_text for marker in ("1,705", "1705", "170")), (
            f"expected ~1.7M row count in label; got: {populated_text!r}"
        )
        assert real_import_snapshot.result.row_count == 1_705_060
        _assert_import_provenance(real_import_snapshot, container)
    finally:
        if page is not None:
            _close_page(page)
        container.close()


@pytest.mark.skipif(
    not REAL_ZIP.exists(),
    reason="tmp/BGMOPEN1.zip not present — real zip smoke skipped",
)
def test_verify_cache_after_real_import_shows_healthy(
    qt_app, tmp_path, real_import_snapshot,
) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    page = None
    try:
        page = SettingsPage(container)
        _restore_cache_snapshot(real_import_snapshot, container)

        captured: list[str] = []

        def _capture_info(parent, title, text, *a, **kw):
            captured.append(text)

        with patch("taxops.ui.pages.settings_page.QMessageBox") as mock_mb:
            mock_mb.information = MagicMock(side_effect=_capture_info)
            mock_mb.warning = MagicMock()
            page.on_verify_cache()

        assert captured, "QMessageBox.information was not called"
        report = captured[0]
        assert "本機稅籍資料完整" in report or "✓" in report, (
            f"expected healthy report; got:\n{report}"
        )
        assert any(marker in report for marker in ("1,705", "1705", "170")), (
            f"expected ~1.7M rows in report; got:\n{report}"
        )
        assert real_import_snapshot.result.row_count == 1_705_060
        _assert_import_provenance(real_import_snapshot, container)
    finally:
        if page is not None:
            _close_page(page)
        container.close()


def test_import_snapshot_clones_are_independent(qt_app, tmp_path) -> None:
    """Small extra fixture contract; never replaces either full-ZIP UI test."""
    from taxops.services.registry.parser import EXPECTED_CSV_NAME, EXPECTED_HEADERS

    zip_path = tmp_path / "fixture-contract.zip"
    csv_text = ",".join(EXPECTED_HEADERS) + "\n" + (
        "09-MAY-26,,,,,,,,,,,,,,,\n"
        "合成地址甲,11111111,,合成商行甲,100000,1040413,獨資,N,472927,豆類製品零售,,,,,,\n"
        "合成地址乙,22222222,,合成商行乙,1000,0400711,獨資,N,472913,菸酒零售,471913,雜貨店,,,,\n"
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(EXPECTED_CSV_NAME, csv_text.encode("utf-8"))
    snapshot = _import_cache_snapshot(tmp_path / "seed", zip_path)
    assert snapshot.result.row_count == 2

    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
    first, second = (_make_container(root) for root in roots)
    try:
        for container in (first, second):
            _restore_cache_snapshot(snapshot, container)
            _assert_import_provenance(snapshot, container)
        first.conn.execute("DELETE FROM tax_registry_cache")
        first.conn.execute("DELETE FROM tax_cache_metadata")
        first.conn.execute("DELETE FROM audit_logs")
        first.conn.commit()
        assert first.tax_registry_repo.count() == 0
        _assert_import_provenance(snapshot, second)

        # The closed seed remains unchanged and can repopulate either clone in
        # any order, even after the other test has committed destructive writes.
        _restore_cache_snapshot(snapshot, first)
        _assert_import_provenance(snapshot, first)
        _assert_import_provenance(snapshot, second)
    finally:
        first.close()
        second.close()
