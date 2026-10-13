"""Exercise the real Settings entry and export bytes in the packaged runtime."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from .core.third_party_notices import load_notices
from .ui.action_registry import NAV_ORDER, PAGE_SETTINGS
from .ui.dialogs.third_party_notices_dialog import ThirdPartyNoticesDialog
from .ui.pages.settings_page import SettingsPage


def verify_notice_widgets(window, app, root: Path) -> dict:
    # Fail before entering the modal handler if its package assets are missing.
    expected = load_notices()
    page = window.findChild(SettingsPage)
    if page is None:
        raise RuntimeError("Settings notice entry missing")
    previous_page = window._nav.currentRow()
    window._nav.setCurrentRow(NAV_ORDER.index(PAGE_SETTINGS))
    app.processEvents()
    if not page._licenses_btn.isVisible():
        raise RuntimeError("Settings notice entry is not visible")
    export = root / "第三方 授權文件.zip"
    result: dict = {}
    errors: list[Exception] = []

    def inspect_open_dialog():
        dialog = page.findChild(ThirdPartyNoticesDialog)
        try:
            if dialog is None or not dialog.isVisible():
                raise RuntimeError("Notice viewer did not open")
            for name in ("README.txt", "SOURCE_ACCESS.txt",
                         "qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt",
                         "qt-6.10.2/qtbase/LICENSES/GPL-3.0-only.txt"):
                index = dialog.document_combo.findData(name)
                if index < 0:
                    raise RuntimeError("Required notice not selectable")
                dialog.document_combo.setCurrentIndex(index)
                if dialog.text_view.toPlainText() != expected.text(name):
                    raise RuntimeError("Displayed notice text changed")
            dialog.export_to(export)
            with zipfile.ZipFile(export) as archive:
                if set(archive.namelist()) != set(expected.files):
                    raise RuntimeError("Exported notice set differs")
                for name, content in expected.files.items():
                    if archive.read(name) != content:
                        raise RuntimeError("Exported notice bytes differ")
            result.update(file_count=len(expected.files),
                          manifest_sha256=hashlib.sha256(expected.files["manifest.json"]).hexdigest(),
                          export_sha256=hashlib.sha256(export.read_bytes()).hexdigest(),
                          entry="settings", displayed_text_verified=True,
                          export_bytes_verified=True)
        except Exception as exc:
            errors.append(exc)
        finally:
            if dialog is not None:
                dialog.reject()
            else:
                # Close only an error dialog owned by this settings page. A
                # missing asset must produce a failed check, not hang CI in a
                # message box that normally waits for a person.
                active = app.activeModalWidget()
                if active is not None and active.parentWidget() is page:
                    active.reject()

    timer = QTimer(page)
    timer.setSingleShot(True)
    timer.timeout.connect(inspect_open_dialog)
    try:
        timer.start(0)
        page._licenses_btn.click()
    finally:
        timer.stop()
        timer.deleteLater()
        QCoreApplication.sendPostedEvents(timer, QEvent.Type.DeferredDelete)
        for dialog in page.findChildren(ThirdPartyNoticesDialog):
            QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        window._nav.setCurrentRow(previous_page)
    if errors:
        raise errors[0]
    if not result:
        raise RuntimeError("Notice viewer check did not run")
    return result
