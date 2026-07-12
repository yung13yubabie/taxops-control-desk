from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp, container, monkeypatch):
    from taxops.ui.pages.settings_page import SettingsPage

    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.critical",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    return SettingsPage(container)


def _run_synchronously(page, container, monkeypatch):
    def run(task_fn, _title, on_success):
        on_success(task_fn(container))

    monkeypatch.setattr(page, "_run_async", run)


@pytest.mark.parametrize("button_index", [0, 1, 2])
def test_cache_file_actions_cancel_at_picker(
    page, container, monkeypatch, button_index
):
    calls = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(page, "_run_async", lambda *_args: calls.append(True))

    page._slice2_buttons[button_index].click()

    assert calls == []


@pytest.mark.parametrize("button_index", [0, 1])
def test_cache_import_actions_cancel_at_confirmation(
    page, monkeypatch, tmp_path, button_index
):
    calls = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "cache.zip"), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(page, "_run_async", lambda *_args: calls.append(True))

    page._slice2_buttons[button_index].click()

    assert calls == []


def test_import_zip_button_runs_service_and_reports_exact_result(
    page, container, monkeypatch, tmp_path
):
    selected = tmp_path / "mof.zip"
    received = []
    result = SimpleNamespace(
        row_count=12, cache_version="v12", data_freshness_iso="2026-07-11"
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        container.tax_cache_importer,
        "import_zip",
        lambda path: received.append(path) or result,
    )
    _run_synchronously(page, container, monkeypatch)

    page._slice2_buttons[0].click()

    assert received == [selected]


def test_import_and_export_bundle_buttons_run_services(
    page, container, monkeypatch, tmp_path
):
    source = tmp_path / "source.taxops-cache.zip"
    destination = tmp_path / "dest.taxops-cache.zip"
    imported = []
    exported = []
    result = SimpleNamespace(
        row_count=3,
        cache_version="v3",
        data_freshness_iso=None,
        bundle_path=destination,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), ""),
    )
    monkeypatch.setattr(
        container.tax_cache_bundle,
        "import_bundle",
        lambda path: imported.append(path) or result,
    )
    monkeypatch.setattr(
        container.tax_cache_bundle,
        "export_bundle",
        lambda path: exported.append(path) or result,
    )
    _run_synchronously(page, container, monkeypatch)

    page._slice2_buttons[1].click()
    page._slice2_buttons[2].click()

    assert imported == [source]
    assert exported == [destination]


def test_regenerate_button_handles_mismatch_review_choice(
    page, container, monkeypatch
):
    summary = SimpleNamespace(
        client_count=2,
        histogram={"matched": 1, "mismatch": 1, "not_found": 0},
    )
    questions = iter(
        [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes]
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: next(questions),
    )
    monkeypatch.setattr(
        container.tax_cache_matcher, "regenerate_mof", lambda: summary
    )
    monkeypatch.setattr(
        container.tax_cache_matcher, "list_mismatches", lambda: []
    )
    _run_synchronously(page, container, monkeypatch)

    page._slice2_buttons[4].click()


def test_save_buttons_persist_user_values(page, container, monkeypatch):
    infos = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.information",
        lambda _parent, title, body: infos.append((title, body)),
    )
    page._display_name.setText("  Alice  ")
    page._save_display_name_btn.click()
    page._query_mode.setCurrentIndex(page._query_mode.findData("allow_online"))
    page._save_query_mode_btn.click()

    assert page._display_name.text() == "Alice"
    assert container.settings.get("display.local_user_name") == "Alice"
    assert container.settings.get("tax_cache.query_mode") == "allow_online"
    assert len(infos) == 2


def test_save_display_name_validation_error_is_visible(
    page, container, monkeypatch
):
    from taxops.services.settings import SettingsValidationError

    warnings = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        container.settings,
        "set_setting",
        lambda *_args: (_ for _ in ()).throw(
            SettingsValidationError("settings.save.failed")
        ),
    )
    page._display_name.setText("invalid")

    page._save_display_name_btn.click()

    assert len(warnings) == 1


def test_open_and_copy_helpers_cover_success_and_failure(
    page, container, monkeypatch
):
    warnings = []
    infos = []
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path))
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.information",
        lambda _parent, title, body: infos.append((title, body)),
    )

    page.on_open_data_folder()
    page.on_open_attachments_folder()
    page.on_copy_db_path()
    page.on_copy_attachments_path()
    assert len(opened) == 2
    assert QApplication.clipboard().text() == str(container.paths.attachments_dir)
    assert len(infos) == 2

    monkeypatch.setattr(
        os,
        "startfile",
        lambda _path: (_ for _ in ()).throw(OSError("shell unavailable")),
    )
    page.on_open_data_folder()
    assert len(warnings) == 1


def test_backup_button_success_and_domain_failure(page, container, monkeypatch):
    from taxops.services.backup import BackupError

    infos = []
    criticals = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.information",
        lambda _parent, title, body: infos.append((title, body)),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.critical",
        lambda _parent, _title, body: criticals.append(body),
    )
    monkeypatch.setattr(
        container.backup,
        "create_backup",
        lambda _paths: SimpleNamespace(backup_path=Path("backup.sqlite"), file_size=7),
    )
    page._backup_btn.click()
    assert len(infos) == 1

    monkeypatch.setattr(
        container.backup,
        "create_backup",
        lambda _paths: (_ for _ in ()).throw(BackupError("backup.invalid_file")),
    )
    page._backup_btn.click()
    assert len(criticals) == 1


def test_restore_button_cancel_confirm_and_success(
    page, container, monkeypatch, tmp_path
):
    selected = tmp_path / "backup.sqlite"
    restored = []
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_calls.append(True))
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )
    monkeypatch.setattr(
        container.backup,
        "restore_backup",
        lambda path, paths: restored.append((path, paths)),
    )

    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    page._restore_btn.click()
    assert restored == []

    answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: next(answers),
    )
    page._restore_btn.click()
    assert restored == [(selected, container.paths)]
    assert quit_calls == [True]


def test_verify_cache_unexpected_error_is_logged_and_visible(
    page, monkeypatch
):
    warnings = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.verify_cache",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("broken metadata")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._slice2_buttons[3].click()

    assert len(warnings) == 1


def test_regenerate_cancel_does_not_start_worker(page, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(page, "_run_async", lambda *_args: calls.append(True))

    page._slice2_buttons[4].click()

    assert calls == []


@pytest.mark.parametrize("control_name", ["display", "query"])
def test_setting_save_unexpected_error_is_visible(
    page, container, monkeypatch, control_name
):
    warnings = []
    monkeypatch.setattr(
        container.settings,
        "set_setting",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("database locked")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    if control_name == "display":
        page._save_display_name_btn.click()
    else:
        page._save_query_mode_btn.click()

    assert len(warnings) == 1


@pytest.mark.parametrize("platform, command", [("darwin", "open"), ("linux", "xdg-open")])
def test_open_folder_cross_platform_commands(
    page, monkeypatch, tmp_path, platform, command
):
    calls = []
    monkeypatch.setattr("taxops.ui.pages.settings_page.sys.platform", platform)
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.subprocess.run",
        lambda args, check: calls.append((args, check)),
    )

    page._open_folder(tmp_path / platform)

    assert calls == [([command, str(tmp_path / platform)], False)]


def test_copy_helper_failure_is_visible(page, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QGuiApplication.clipboard",
        lambda: (_ for _ in ()).throw(RuntimeError("clipboard unavailable")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._copy("value")

    assert len(warnings) == 1


def test_close_event_is_blocked_only_while_operation_is_active(page):
    from PySide6.QtGui import QCloseEvent

    class RunningWorker:
        def isRunning(self):
            return True

    page._active_worker = RunningWorker()
    blocked = QCloseEvent()
    page.closeEvent(blocked)
    assert not blocked.isAccepted()

    page._active_worker = None
    allowed = QCloseEvent()
    page.closeEvent(allowed)
    assert allowed.isAccepted()


def test_backup_unexpected_failure_is_visible(page, container, monkeypatch):
    criticals = []
    monkeypatch.setattr(
        container.backup,
        "create_backup",
        lambda _paths: (_ for _ in ()).throw(RuntimeError("disk failed")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.critical",
        lambda _parent, _title, body: criticals.append(body),
    )

    page._backup_btn.click()

    assert len(criticals) == 1


def test_restore_cancel_at_picker_and_second_confirmation(
    page, container, monkeypatch, tmp_path
):
    restored = []
    monkeypatch.setattr(
        container.backup,
        "restore_backup",
        lambda *_args: restored.append(True),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    page._restore_btn.click()

    selected = tmp_path / "backup.sqlite"
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )
    answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: next(answers),
    )
    page._restore_btn.click()

    assert restored == []


@pytest.mark.parametrize("unexpected", [False, True])
def test_restore_failures_are_visible(
    page, container, monkeypatch, tmp_path, unexpected
):
    from taxops.services.backup import BackupError

    criticals = []
    selected = tmp_path / "backup.sqlite"
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    error = RuntimeError("unexpected") if unexpected else BackupError("backup.invalid_file")
    monkeypatch.setattr(
        container.backup,
        "restore_backup",
        lambda *_args: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.critical",
        lambda _parent, _title, body: criticals.append(body),
    )

    page._restore_btn.click()

    assert len(criticals) == 1


def test_cache_status_renders_populated_and_failure_states(
    page, container, monkeypatch
):
    status = SimpleNamespace(
        has_cache=True,
        cache_version="v20260712",
        row_count=1234,
        data_freshness_iso="2026-07-11",
        last_import_source="官方 ZIP",
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.get_cache_status", lambda *_args: status
    )
    page._refresh_cache_status()
    assert page._cache_status_label.text() == (
        "快取版本：v20260712  │  筆數：1,234  │  資料日期：2026-07-11  │  來源：官方 ZIP"
    )

    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.get_cache_status",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("metadata corrupt")),
    )
    page._refresh_cache_status()
    assert page._cache_status_label.text() == "無法取得快取狀態。"


def test_download_button_rejects_unofficial_url(page, container, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(container.settings, "get", lambda _key: "https://evil.example/file.zip")
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    calls: list[bool] = []
    monkeypatch.setattr(page, "_run_async", lambda *_args, **_kwargs: calls.append(True))

    page._download_btn.click()

    assert len(warnings) == 1
    assert warnings[0].strip()
    assert calls == []


@pytest.mark.parametrize("answers", [(QMessageBox.StandardButton.No,), (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)])
def test_download_button_cancel_confirmations_do_not_start_worker(
    page, container, monkeypatch, answers
):
    monkeypatch.setattr(
        container.settings,
        "get",
        lambda _key: "https://eip.fia.gov.tw/data/BGMOPEN1.zip",
    )
    choices = iter(answers)
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: next(choices),
    )
    calls: list[bool] = []
    monkeypatch.setattr(page, "_run_async", lambda *_args, **_kwargs: calls.append(True))

    page._download_btn.click()

    assert calls == []


def test_download_button_runs_download_import_cleanup_audit_and_exact_success(
    page, container, monkeypatch
):
    url = "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    monkeypatch.setattr(container.settings, "get", lambda _key: url)
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    tmp_path = container.paths.data_root / "_registry_download_tmp.zip"
    downloads: list[tuple[str, Path]] = []

    def download(source_url, destination):
        downloads.append((source_url, destination))
        destination.write_bytes(b"downloaded")

    result = SimpleNamespace(
        row_count=4321,
        cache_version="v4321",
        data_freshness_iso="2026-07-11",
    )
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.download_registry_zip", download
    )
    monkeypatch.setattr(
        container.tax_cache_importer,
        "import_zip",
        lambda path: result if path == tmp_path else None,
    )
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QMessageBox.information",
        lambda _parent, title, body: infos.append((title, body)),
    )
    _run_synchronously(page, container, monkeypatch)

    page._download_btn.click()

    assert downloads == [(url, tmp_path)]
    assert not tmp_path.exists()
    assert infos == [
        (
            "下載完成",
            "已成功下載並匯入 4,321 筆稅籍資料。\n版本：v4321\n資料日期：2026-07-11",
        )
    ]
    audit = container.conn.execute(
        "SELECT action, detail_json FROM audit_logs WHERE action = 'tax_cache.download' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit is not None
    assert audit[0] == "tax_cache.download"
