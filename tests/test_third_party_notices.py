"""Offline notice readability, honest failures, and exact-byte export contracts."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from types import MappingProxyType

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QPushButton

from taxops.core import third_party_notices as notices
from taxops.ui.dialogs import third_party_notices_dialog as ui
from taxops.ui.pages import settings_page

ROOT = Path(__file__).resolve().parents[1] / "assets" / "third_party_licenses"


@pytest.fixture
def corpus(tmp_path):
    destination = tmp_path / "notices"
    shutil.copytree(ROOT, destination)
    return destination


def _write_manifest(root, mutate):
    path = root / "manifest.json"
    manifest = json.loads(path.read_bytes())
    mutate(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_source_and_frozen_notice_paths_ignore_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert notices.notice_directory() == ROOT
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "解壓 路徑"), raising=False)
    assert notices.notice_directory() == tmp_path / "解壓 路徑" / "third_party_licenses"


def test_real_corpus_readable_snapshot_and_export_exact_bytes(corpus, tmp_path):
    catalog = notices.load_notices(corpus)
    assert len(catalog.files) == len(json.loads((corpus / "manifest.json").read_bytes())["files"]) + 1
    assert "LESSER GENERAL PUBLIC LICENSE" in catalog.text("qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt")
    for name, content in catalog.files.items():
        assert catalog.text(name) == content.decode(notices._TEXT_ENCODINGS.get(name, "utf-8"))
    freetype = "qt-pdf-chromium/chromium/third_party/pdfium/third_party/freetype/FTL.TXT"
    assert "©" in catalog.text(freetype) and "\ufffd" not in catalog.text(freetype)
    (corpus / "README.txt").write_text("changed after validation", encoding="utf-8")
    assert catalog.files["README.txt"] != b"changed after validation"
    with pytest.raises(TypeError):
        catalog.files["new"] = b"not allowed"
    target = tmp_path / "中文 空白.zip"
    catalog.export(target)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(catalog.files)
        for name, content in catalog.files.items():
            assert archive.read(name) == content
    assert not list(tmp_path.glob(".taxops-notices-*"))


@pytest.mark.parametrize("mode", ["missing_manifest", "bad_json", "schema", "no_list", "changed", "missing", "missing_required", "duplicate", "missing_hash", "bad_type", "not_utf8"])
def test_incomplete_corpus_is_error_not_empty(corpus, mode):
    if mode == "missing_manifest":
        (corpus / "manifest.json").unlink()
    elif mode == "bad_json":
        (corpus / "manifest.json").write_text("{")
    elif mode == "schema":
        _write_manifest(corpus, lambda m: m.update(schema=2))
    elif mode == "no_list":
        _write_manifest(corpus, lambda m: m.update(files=None))
    elif mode == "changed":
        (corpus / "README.txt").write_text("changed")
    elif mode == "missing":
        (corpus / "README.txt").unlink()
    elif mode == "missing_required":
        _write_manifest(corpus, lambda m: m.update(files=[r for r in m["files"] if r["path"] != "README.txt"]))
    elif mode == "duplicate":
        _write_manifest(corpus, lambda m: m["files"].append(m["files"][0]))
    elif mode == "missing_hash":
        _write_manifest(corpus, lambda m: m["files"][0].pop("sha256"))
    elif mode == "bad_type":
        _write_manifest(corpus, lambda m: m["files"].append(None))
    else:
        (corpus / "README.txt").write_bytes(b"\xff")
        _write_manifest(corpus, lambda m: next(r for r in m["files"] if r["path"] == "README.txt").update(sha256=hashlib.sha256(b"\xff").hexdigest()))
    with pytest.raises(notices.NoticeError, match="notice.read_failed"):
        notices.load_notices(corpus)


@pytest.mark.parametrize("name", ["", "../outside.txt", "/outside.txt", "C:/outside.txt", "folder\\file.txt", "./README.txt", "manifest.json"])
def test_manifest_paths_must_be_canonical_relative(corpus, name):
    _write_manifest(corpus, lambda m: m["files"][0].update(path=name))
    with pytest.raises(notices.NoticeError):
        notices.load_notices(corpus)


def test_notice_file_symlink_rejected(corpus, tmp_path):
    original = corpus / "README.txt"
    other = tmp_path / "original.txt"
    original.rename(other)
    try:
        original.symlink_to(other)
    except OSError as exc:
        # Do not omit this contract on Windows without symlink privileges.
        # The same Path API result is the branch under test.
        assert getattr(exc, "winerror", None) == 1314
        from unittest.mock import patch
        with patch.object(Path, "is_symlink", lambda p: p == original):
            with pytest.raises(notices.NoticeError):
                notices.load_notices(corpus)
    else:
        with pytest.raises(notices.NoticeError):
            notices.load_notices(corpus)


@pytest.mark.parametrize("name,content", [("missing", b"text"), ("bad", b"\xff")])
def test_text_failure_is_explicit(name, content):
    catalog = notices.NoticeCatalog(MappingProxyType({"bad": content}))
    with pytest.raises(notices.NoticeError):
        catalog.text(name)


def test_failed_export_preserves_existing_file_and_cleans_stage(tmp_path, monkeypatch):
    catalog = notices.load_notices()
    target = tmp_path / "old.zip"
    target.write_bytes(b"keep existing target")
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(notices.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("synthetic write failure")))
    with pytest.raises(notices.NoticeError):
        catalog.export(target)
    assert target.read_bytes() == b"keep existing target"
    assert set(tmp_path.iterdir()) == before


def test_missing_destination_parent_fails_without_creating_it(tmp_path):
    target = tmp_path / "missing" / "notices.zip"
    with pytest.raises(notices.NoticeError):
        notices.load_notices().export(target)
    assert not target.parent.exists()


def test_notice_viewer_plain_readonly_and_compact(qtbot):
    dialog = ui.ThirdPartyNoticesDialog()
    qtbot.addWidget(dialog)
    dialog.resize(480, 360)
    dialog.show()
    assert dialog.width() == 480
    assert dialog.text_view.isReadOnly()
    assert dialog.document_combo.count() == len(dialog.catalog.files)
    for name in ("README.txt", "SOURCE_ACCESS.txt", "qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt"):
        dialog.document_combo.setCurrentIndex(dialog.document_combo.findData(name))
        assert dialog.text_view.toPlainText() == dialog.catalog.text(name)
    assert dialog.text_view.viewport().width() > 100
    close = next(b for b in dialog.findChildren(QPushButton) if b.text() == "關閉")
    qtbot.mouseClick(close, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()


@pytest.mark.parametrize("mode", ["success", "cancel", "failure"])
def test_notice_export_button(qtbot, tmp_path, monkeypatch, mode):
    dialog = ui.ThirdPartyNoticesDialog()
    qtbot.addWidget(dialog)
    target = tmp_path / "文件.zip"
    messages = []
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *a: ("" if mode == "cancel" else str(target), ""))
    monkeypatch.setattr(ui.QMessageBox, "information", lambda *a: messages.append("success"))
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a: messages.append("failure"))
    if mode == "failure":
        monkeypatch.setattr(dialog, "export_to", lambda *a: (_ for _ in ()).throw(notices.NoticeError("test")))
    dialog.export_button.click()
    assert messages == ([] if mode == "cancel" else [mode])
    assert target.exists() == (mode == "success")
    if target.exists():
        with zipfile.ZipFile(target) as archive:
            assert archive.read("SOURCE_ACCESS.txt") == dialog.catalog.files["SOURCE_ACCESS.txt"]


def test_settings_opens_notices_offline(qtbot, container):
    page = settings_page.SettingsPage(container)
    qtbot.addWidget(page)
    observed = []
    def close_dialog():
        dialog = page.findChild(ui.ThirdPartyNoticesDialog)
        observed.append(dialog is not None and dialog.isVisible())
        if dialog:
            dialog.reject()
    for _ in range(3):
        QTimer.singleShot(0, close_dialog)
        page._licenses_btn.click()
        for dialog in page.findChildren(ui.ThirdPartyNoticesDialog):
            QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert page.findChildren(ui.ThirdPartyNoticesDialog) == []
    assert observed == [True] * 3


def test_settings_missing_notices_explains_retry(qtbot, container, monkeypatch):
    page = settings_page.SettingsPage(container)
    qtbot.addWidget(page)
    messages = []
    monkeypatch.setattr(settings_page, "ThirdPartyNoticesDialog", lambda *a: (_ for _ in ()).throw(notices.NoticeError("test")))
    monkeypatch.setattr(settings_page.QMessageBox, "warning", lambda *a: messages.append(a[2]))
    page._licenses_btn.click()
    assert len(messages) == 1 and "重新下載" in messages[0]


def test_repeated_real_loader_failures_leave_no_partial_dialog(qtbot, container, monkeypatch):
    page = settings_page.SettingsPage(container)
    qtbot.addWidget(page)
    messages = []
    monkeypatch.setattr(ui, "load_notices", lambda: (_ for _ in ()).throw(notices.NoticeError("synthetic missing assets")))
    monkeypatch.setattr(settings_page.QMessageBox, "warning", lambda *a: messages.append(a[2]))
    before = len(page.children())
    for _ in range(3):
        page._licenses_btn.click()
        assert page.findChildren(ui.ThirdPartyNoticesDialog) == []
        assert len(page.children()) == before
    assert len(messages) == 3


def test_frozen_notice_check_fails_cleanly_when_second_read_fails(qtbot, container, tmp_path, monkeypatch, qapp):
    from taxops.diagnostics_notices import verify_notice_widgets
    from taxops.ui.main_window import MainWindow
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(settings_page, "ThirdPartyNoticesDialog", lambda *a: (_ for _ in ()).throw(notices.NoticeError("synthetic second read failure")))
    with pytest.raises(RuntimeError, match="did not open"):
        verify_notice_widgets(window, qapp, tmp_path)
    assert qapp.activeModalWidget() is None


def test_real_export_failure_closes_modal_and_restores_navigation(qtbot, container, tmp_path, qapp):
    from taxops.diagnostics_notices import verify_notice_widgets
    from taxops.ui.main_window import MainWindow
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()
    previous = window._nav.currentRow()
    with pytest.raises(notices.NoticeError):
        verify_notice_widgets(window, qapp, tmp_path / "parent-does-not-exist")
    assert window._nav.currentRow() == previous
    assert window.findChildren(ui.ThirdPartyNoticesDialog) == []
    assert qapp.activeModalWidget() is None


def test_notice_keyboard_and_actual_style_fit_compact_window(qtbot, qapp):
    from taxops.ui.style import apply
    apply(qapp)
    dialog = ui.ThirdPartyNoticesDialog()
    qtbot.addWidget(dialog)
    dialog.resize(480, 360)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(dialog.isActiveWindow)
    dialog.document_combo.setFocus()
    controls = {dialog.document_combo, dialog.text_view, dialog.export_button,
                next(b for b in dialog.findChildren(QPushButton) if b.text() == "關閉")}
    visited = set()
    for _ in range(12):
        focused = qapp.focusWidget()
        if focused in controls:
            visited.add(focused)
        qtbot.keyClick(focused or dialog, Qt.Key.Key_Tab)
    assert controls <= visited
    assert dialog.width() == 480 and dialog.height() == 360
    for control in controls:
        assert control.isVisible()
        assert dialog.rect().contains(control.geometry())
