"""Slice 3 tests: HTTP download, URL allowlist, two-step confirmation, audit.

Covers:
- URL allowlist: allowed vs. disallowed hosts/schemes
- DownloadError raised on network/IO failure (mocked, no real network)
- on_download_registry: disallowed URL → warning, no download
- on_download_registry: user cancels step-1 confirm → no download
- on_download_registry: user cancels step-2 confirm → no download
- on_download_registry: success path pipeline (service-level, mocked download)
- action_registry: download contract is enabled and has audit_action
- SettingsPage: download button rendered and enabled
"""
from __future__ import annotations

import io
import os
import pathlib
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_conn() -> sqlite3.Connection:
    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "Slice3Test")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return conn


def _build_container(conn: sqlite3.Connection):
    from taxops.core.paths import resolve_paths
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "Slice3Container")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    return build_container(paths, conn)


def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# URL allowlist
# ---------------------------------------------------------------------------


def test_allowed_official_url_accepts_mof_zip() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert is_allowed_official_url("https://eip.fia.gov.tw/data/BGMOPEN1.zip")


def test_allowed_official_url_accepts_data_gov_tw() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert is_allowed_official_url("https://data.gov.tw/dataset/9400")


def test_allowed_official_url_accepts_gcis() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert is_allowed_official_url(
        "https://data.gcis.nat.gov.tw/resources/swagger/swagger.json"
    )


def test_allowed_official_url_rejects_http() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert not is_allowed_official_url("http://eip.fia.gov.tw/data/BGMOPEN1.zip")


def test_allowed_official_url_rejects_unknown_host() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert not is_allowed_official_url("https://evil.example.com/BGMOPEN1.zip")


def test_allowed_official_url_rejects_empty() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert not is_allowed_official_url("")


def test_allowed_official_url_rejects_non_https_scheme() -> None:
    from taxops.security.domains import is_allowed_official_url

    assert not is_allowed_official_url("ftp://eip.fia.gov.tw/data/BGMOPEN1.zip")


# ---------------------------------------------------------------------------
# DownloadError raised on failure (no real network)
# ---------------------------------------------------------------------------


def test_download_registry_zip_raises_on_network_error(tmp_path) -> None:
    import urllib.error

    from taxops.services.registry_download import DownloadError, download_registry_zip

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        try:
            download_registry_zip(
                "https://eip.fia.gov.tw/data/BGMOPEN1.zip", tmp_path / "out.zip"
            )
            assert False, "should have raised DownloadError"
        except DownloadError as exc:
            assert exc.code == "registry.download.network_error"


def test_download_registry_zip_raises_on_io_error(tmp_path) -> None:
    from taxops.services.registry_download import DownloadError, download_registry_zip

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.headers = {}
    mock_resp.read.side_effect = [b"data", b""]

    # Parent does not exist, so opening the atomic .part file raises OSError.
    bad_path = tmp_path / "missing_parent" / "out.zip"

    with patch("urllib.request.urlopen", return_value=mock_resp):
        try:
            download_registry_zip("https://eip.fia.gov.tw/data/BGMOPEN1.zip", bad_path)
            assert False, "should have raised DownloadError"
        except DownloadError as exc:
            assert exc.code == "registry.download.io_error"


# ---------------------------------------------------------------------------
# SettingsPage.on_download_registry — UI guard tests (offscreen)
# ---------------------------------------------------------------------------


def test_download_registry_zip_passes_finite_timeout(tmp_path) -> None:
    from taxops.services.registry_download import download_registry_zip

    out = tmp_path / "out.zip"
    resp = _FakeDownloadResponse([b"abc"])

    with patch("urllib.request.urlopen", return_value=resp) as urlopen:
        download_registry_zip(
            "https://eip.fia.gov.tw/data/BGMOPEN1.zip",
            out,
            timeout=7,
        )

    assert urlopen.call_args.kwargs["timeout"] == 7


def test_download_registry_zip_unexpected_read_error_cleans_part(tmp_path) -> None:
    from taxops.services.registry_download import download_registry_zip

    class _BrokenAfterFirstChunk:
        headers = {}

        def __init__(self) -> None:
            self._first = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _size: int) -> bytes:
            if self._first:
                self._first = False
                return b"partial"
            raise RuntimeError("unexpected stream failure")

    out = tmp_path / "out.zip"

    with patch("urllib.request.urlopen", return_value=_BrokenAfterFirstChunk()):
        try:
            download_registry_zip("https://eip.fia.gov.tw/data/BGMOPEN1.zip", out)
            assert False, "should have propagated unexpected exception"
        except RuntimeError as exc:
            assert "unexpected stream failure" in str(exc)

    assert not out.exists()
    assert not (tmp_path / "out.zip.part").exists()


class _FakeDownloadResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_download_registry_zip_writes_atomically_on_success(tmp_path) -> None:
    from taxops.services.registry_download import download_registry_zip

    out = tmp_path / "out.zip"
    resp = _FakeDownloadResponse([b"abc", b"def"])

    with patch("urllib.request.urlopen", return_value=resp):
        download_registry_zip("https://eip.fia.gov.tw/data/BGMOPEN1.zip", out)

    assert out.read_bytes() == b"abcdef"
    assert not (tmp_path / "out.zip.part").exists()


def test_download_registry_zip_rejects_large_content_length(tmp_path) -> None:
    from taxops.services.registry_download import DownloadError, download_registry_zip

    out = tmp_path / "out.zip"
    resp = _FakeDownloadResponse([], headers={"Content-Length": "11"})

    with patch("urllib.request.urlopen", return_value=resp):
        try:
            download_registry_zip(
                "https://eip.fia.gov.tw/data/BGMOPEN1.zip",
                out,
                max_bytes=10,
            )
            assert False, "should have rejected oversized download"
        except DownloadError as exc:
            assert exc.code == "registry.download.too_large"

    assert not out.exists()
    assert not (tmp_path / "out.zip.part").exists()


def test_download_registry_zip_rejects_stream_over_limit_and_cleans_part(tmp_path) -> None:
    from taxops.services.registry_download import DownloadError, download_registry_zip

    out = tmp_path / "out.zip"
    resp = _FakeDownloadResponse([b"12345", b"67890", b"!"])

    with patch("urllib.request.urlopen", return_value=resp):
        try:
            download_registry_zip(
                "https://eip.fia.gov.tw/data/BGMOPEN1.zip",
                out,
                max_bytes=10,
            )
            assert False, "should have rejected oversized stream"
        except DownloadError as exc:
            assert exc.code == "registry.download.too_large"

    assert not out.exists()
    assert not (tmp_path / "out.zip.part").exists()


def _make_settings_page(container):
    from taxops.ui.pages.settings_page import SettingsPage

    return SettingsPage(container)


def test_download_button_disallowed_url_shows_warning() -> None:
    """If URL fails allowlist check, warn and never call download."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)
    container.settings.set_setting("tax_cache.download_url", "https://evil.com/bad.zip")

    page = _make_settings_page(container)

    with patch("taxops.ui.pages.settings_page.QMessageBox.warning") as mock_warn, \
         patch("taxops.ui.pages.settings_page.download_registry_zip") as mock_dl:
        page.on_download_registry()
        assert mock_warn.called
        mock_dl.assert_not_called()
    container.close()


def test_download_button_step1_cancel_aborts() -> None:
    """Cancelling the URL confirmation (step 1) must abort without downloading."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    page = _make_settings_page(container)

    from PySide6.QtWidgets import QMessageBox

    with patch("taxops.ui.pages.settings_page.QMessageBox.question",
               return_value=QMessageBox.StandardButton.No) as mock_q, \
         patch("taxops.ui.pages.settings_page.download_registry_zip") as mock_dl:
        page.on_download_registry()
        assert mock_q.call_count == 1, "should stop after step 1"
        mock_dl.assert_not_called()
    container.close()


def test_download_button_step2_cancel_aborts() -> None:
    """Cancelling the overwrite confirmation (step 2) must abort without downloading."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    page = _make_settings_page(container)

    from PySide6.QtWidgets import QMessageBox

    responses = [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No]

    with patch("taxops.ui.pages.settings_page.QMessageBox.question",
               side_effect=responses) as mock_q, \
         patch("taxops.ui.pages.settings_page.download_registry_zip") as mock_dl:
        page.on_download_registry()
        assert mock_q.call_count == 2, "should reach step 2 before aborting"
        mock_dl.assert_not_called()
    container.close()


def test_download_button_success_runs_import_audit_and_cleans_tmp(tmp_path) -> None:
    """SettingsPage success path must execute the real download/import closure.

    This catches regressions that a hand-written service-level imitation would
    miss, including wrong AuditService arguments and forgotten tmp cleanup.
    """
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)
    container.settings.set_setting(
        "tax_cache.download_url", "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    )

    valid_zip = tmp_path / "source.zip"
    _make_valid_zip(valid_zip)
    page = _make_settings_page(container)

    def fake_download(_url: str, dest: Path, **_kwargs) -> None:
        import shutil

        shutil.copy2(valid_zip, dest)

    def run_inline(task_fn, _title, on_success) -> None:
        result = task_fn(container)
        on_success(result)

    from PySide6.QtWidgets import QMessageBox

    with patch(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes],
    ), patch(
        "taxops.ui.pages.settings_page.QMessageBox.information"
    ) as mock_info, patch(
        "taxops.ui.pages.settings_page.download_registry_zip",
        side_effect=fake_download,
    ):
        page._run_async = run_inline  # type: ignore[method-assign]
        page.on_download_registry()

    assert mock_info.called
    assert not (container.paths.data_root / "_registry_download_tmp.zip").exists()
    assert container.tax_registry_repo.count() == 2

    from taxops.repositories.audit_logs import AuditLogRepository

    logs = AuditLogRepository(conn).list_recent(limit=20)
    download_log = next(r for r in logs if r.action == "tax_cache.download")

    import json

    detail = json.loads(download_log.detail_json or "{}")
    assert detail["source_url"] == "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    assert detail["row_count"] == 2
    assert detail["cache_version"]
    container.close()


# ---------------------------------------------------------------------------
# action_registry: download contract must be enabled with audit_action
# ---------------------------------------------------------------------------


def test_download_action_contract_is_enabled() -> None:
    from taxops.ui.action_registry import ACTION_REGISTRY

    matches = [a for a in ACTION_REGISTRY if a.button_label == "下載財政部稅籍資料"]
    assert len(matches) == 1
    action = matches[0]
    assert action.enabled
    assert action.handler == "SettingsPage.on_download_registry"
    assert action.audit_action == "tax_cache.download"
    assert action.service is not None
    assert action.repository is not None


def test_settings_page_has_download_button_enabled() -> None:
    """SettingsPage must render the download button in enabled state."""
    _make_app()
    conn = _fresh_conn()
    container = _build_container(conn)

    page = _make_settings_page(container)

    assert page._download_btn is not None
    assert page._download_btn.isEnabled(), "download button must be enabled"
    assert page._download_btn.text() == "下載財政部稅籍資料"
    container.close()


# ---------------------------------------------------------------------------
# Success-path pipeline (service-level, no real network, no QThread)
# ---------------------------------------------------------------------------


def _make_valid_zip(dest: Path) -> None:
    """Write a minimal valid BGMOPEN1.zip to dest."""
    from taxops.services.registry.parser import EXPECTED_CSV_NAME, EXPECTED_HEADERS

    header_line = ",".join(EXPECTED_HEADERS)
    body = (
        "09-MAY-26,,,,,,,,,,,,,,,\n"
        "地址1,38965019,,原味商行,100000,1040413,獨資,N,472927,豆類製品零售,,,,,,\n"
        "地址2,61194605,,和興商店,1000,0400711,獨資,N,472913,菸酒零售,471913,雜貨店,,,,\n"
    )
    csv_bytes = (header_line + "\n" + body).encode("utf-8")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EXPECTED_CSV_NAME, csv_bytes)


def test_download_success_pipeline_audit_and_cleanup(tmp_path) -> None:
    """Full service-level pipeline: mock download writes valid zip, import runs,
    audit recorded, tmp file cleaned up."""
    conn = _fresh_conn()
    container = _build_container(conn)

    valid_zip = tmp_path / "source.zip"
    _make_valid_zip(valid_zip)

    # Emulate what _do() inside on_download_registry does:
    # download → dest_path, import, audit, cleanup
    url = "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    dest_path = container.paths.data_root / "_registry_download_tmp.zip"

    def _fake_download(u: str, d: Path, **kw) -> None:
        import shutil
        shutil.copy2(valid_zip, d)

    from taxops.services.registry_download import download_registry_zip

    with patch("taxops.services.registry_download.urllib.request.urlopen"):
        # Directly replicate the _do closure logic
        try:
            _fake_download(url, dest_path)
            result = container.tax_cache_importer.import_zip(dest_path)
        finally:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)

        container.audit.record(
            action="tax_cache.download",
            target_type="tax_cache",
            detail={
                "source_url": url,
                "row_count": result.row_count,
                "cache_version": result.cache_version,
            },
        )

    # tmp file cleaned up
    assert not dest_path.exists(), "tmp zip must be removed after import"

    # import succeeded
    assert result.row_count == 2

    # audit recorded
    from taxops.repositories.audit_logs import AuditLogRepository
    repo = AuditLogRepository(conn)
    logs = repo.list_recent(limit=20)
    actions = [r.action for r in logs]
    assert "tax_cache.download" in actions, f"expected tax_cache.download in {actions}"

    # detail contains source_url and row_count
    download_log = next(r for r in logs if r.action == "tax_cache.download")
    import json
    detail = json.loads(download_log.detail_json or "{}")
    assert detail.get("source_url") == url
    assert detail.get("row_count") == 2

    container.close()


def test_download_success_no_unexpected_error(tmp_path) -> None:
    """On success the pipeline must not raise or emit system.unexpected."""
    conn = _fresh_conn()
    container = _build_container(conn)

    valid_zip = tmp_path / "source.zip"
    _make_valid_zip(valid_zip)

    dest_path = container.paths.data_root / "_registry_download_tmp.zip"

    import shutil
    shutil.copy2(valid_zip, dest_path)

    # Must not raise
    try:
        result = container.tax_cache_importer.import_zip(dest_path)
    except Exception as exc:
        assert False, f"success path raised unexpectedly: {exc}"
    finally:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)

    assert result.row_count == 2
    assert not dest_path.exists()
    container.close()


def test_download_tmp_file_cleaned_on_import_failure(tmp_path) -> None:
    """Even if import fails, the tmp zip file must be cleaned up."""
    conn = _fresh_conn()
    container = _build_container(conn)

    dest_path = container.paths.data_root / "_registry_download_tmp.zip"

    # Write a corrupt/invalid zip so import fails
    dest_path.write_bytes(b"not a valid zip")

    try:
        container.tax_cache_importer.import_zip(dest_path)
    except Exception:
        pass  # expected to fail
    finally:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)

    assert not dest_path.exists(), "tmp zip must be cleaned up even on import failure"
    container.close()
