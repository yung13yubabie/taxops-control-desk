"""Offscreen smoke tests for SettingsPage.

Covers everything verifiable without a real display or human interaction:
- SettingsPage construction with empty cache
- Cache status label text (empty / populated states)
- on_verify_cache() result text (QMessageBox mocked)
- Slice-2 button enabled/disabled states
- Cache status label updates after import

QFileDialog / QProgressDialog / QThread visual interaction requires a real
desktop and is explicitly left as [待驗收] in .ai/HANDOFF.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
        assert "快取" in text
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
def test_cache_status_label_updates_after_real_import(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        empty_text = page._cache_status_label.text()

        container.tax_cache_importer.import_zip(REAL_ZIP)
        page._refresh_cache_status()
        populated_text = page._cache_status_label.text()

        assert populated_text != empty_text, "status label did not change after import"
        # Real BGMOPEN1.zip has ~1,705,060 rows
        assert any(marker in populated_text for marker in ("1,705", "1705", "170")), (
            f"expected ~1.7M row count in label; got: {populated_text!r}"
        )
    finally:
        container.close()


@pytest.mark.skipif(
    not REAL_ZIP.exists(),
    reason="tmp/BGMOPEN1.zip not present — real zip smoke skipped",
)
def test_verify_cache_after_real_import_shows_healthy(qt_app, tmp_path) -> None:
    from taxops.ui.pages.settings_page import SettingsPage

    container = _make_container(tmp_path)
    try:
        page = SettingsPage(container)
        container.tax_cache_importer.import_zip(REAL_ZIP)

        captured: list[str] = []

        def _capture_info(parent, title, text, *a, **kw):
            captured.append(text)

        with patch("taxops.ui.pages.settings_page.QMessageBox") as mock_mb:
            mock_mb.information = MagicMock(side_effect=_capture_info)
            mock_mb.warning = MagicMock()
            page.on_verify_cache()

        assert captured, "QMessageBox.information was not called"
        report = captured[0]
        assert "快取完整" in report or "✓" in report, (
            f"expected healthy report; got:\n{report}"
        )
        assert any(marker in report for marker in ("1,705", "1705", "170")), (
            f"expected ~1.7M rows in report; got:\n{report}"
        )
    finally:
        container.close()
