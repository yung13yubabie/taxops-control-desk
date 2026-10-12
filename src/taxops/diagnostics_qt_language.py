"""Exercise real Qt translation widgets inside the same source/frozen runtime."""
from __future__ import annotations

from pathlib import Path
import re


def _plain(text: str) -> str:
    return re.sub(r"\(&[A-Za-z]\)", "", text).replace("&", "").strip(" ：:")


def verify_chinese_widgets(app, root: Path) -> dict:
    """Verify a complete catalogue and an explicitly partial missing-file fallback.

    Only synthetic files below the caller's self-test temporary root are used.
    Each widget and superseded translator is disposed while its Python owner is
    still held. The normal catalogue is restored after the intentional missing
    catalogue case, including when that case raises.
    """
    from PySide6.QtCore import QCoreApplication, QEvent, QLibraryInfo, QLocale
    from PySide6.QtWidgets import (
        QCalendarWidget, QDialog, QDialogButtonBox, QFileDialog, QTableView, QToolButton,
    )
    from .i18n.qt import _install_from_path

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def dispose(widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)

    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)

    def install(path):
        retired = tuple(getattr(app, "_taxops_translators", ()))
        loaded = _install_from_path(app, str(path))
        for translator in retired:
            QCoreApplication.sendPostedEvents(translator, QEvent.Type.DeferredDelete)
        return loaded

    def buttons():
        expected = {"Ok": "確定", "Cancel": "取消", "Save": "儲存", "Open": "開啟"}
        flags = QDialogButtonBox.StandardButton.NoButton
        for name in expected:
            flags |= getattr(QDialogButtonBox.StandardButton, name)
        widget = QDialogButtonBox(flags)
        try:
            widget.show()
            app.processEvents()
            observed = {
                name: _plain(widget.button(getattr(QDialogButtonBox.StandardButton, name)).text())
                for name in expected
            }
            require(observed == expected, f"Standard button text is not complete Chinese: {observed}")
            require(all(button.isEnabled() for button in widget.buttons()), "Standard buttons disabled")
            return observed
        finally:
            dispose(widget)

    def file_dialog(kind, *, complete):
        widget = QFileDialog()
        try:
            folder = root / "合成 English 資料夾"
            folder.mkdir(exist_ok=True)
            widget.setOption(QFileDialog.Option.DontUseNativeDialog)
            widget.setDirectory(str(root))
            if kind == "save":
                widget.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
                selected = root / "尚未建立的合成檔案.txt"
            elif kind == "directory":
                widget.setFileMode(QFileDialog.FileMode.Directory)
                selected = root
            else:
                widget.setFileMode(QFileDialog.FileMode.ExistingFile)
                selected = root / "合成 English 檔名.txt"
                selected.write_text("synthetic unchanged", encoding="utf-8")
            widget.selectFile(str(selected))
            widget.show()
            app.processEvents()
            observed = {name: _plain(widget.labelText(getattr(QFileDialog.DialogLabel, name)))
                        for name in ("LookIn", "FileName", "FileType", "Accept", "Reject")}
            require(all(observed.values()), f"File dialog contains blank prompts: {observed}")
            box = widget.findChild(QDialogButtonBox)
            require(box is not None, "Qt file dialog has no visible action box")
            action_texts = {_plain(button.text()) for button in box.buttons()}
            require(all(action_texts), "File dialog contains a blank action")
            if complete:
                expected = {"LookIn": "尋找於", "FileName": "目錄" if kind == "directory" else "檔名",
                            "FileType": "檔案型態", "Accept": {"open": "開啟", "save": "儲存", "directory": "選擇"}[kind],
                            "Reject": "取消"}
                require(observed == expected, f"File dialog text is not complete Chinese: {observed}")
                require(action_texts == {expected["Accept"], expected["Reject"]},
                        f"Actual file-dialog buttons differ: {action_texts}")
            require(widget.testOption(QFileDialog.Option.DontUseNativeDialog), "Native file dialog used")
            proxy = widget.proxyModel()
            require(proxy is not None, "Localized file metadata model is unavailable")
            source = proxy.sourceModel()
            folder_source = source.index(str(folder))
            require(folder_source.isValid(), "Synthetic folder is missing from the file model")
            folder_index = proxy.mapFromSource(folder_source)
            metadata = {name: str(proxy.data(folder_index.siblingAtColumn(column)) or "")
                        for name, column in (("name", 0), ("type", 2), ("modified", 3))}
            require(metadata["name"] == folder.name, "File model changed a real folder name")
            require(metadata["type"] == "資料夾", f"Folder type is not Chinese: {metadata}")
            require(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", metadata["modified"]) is not None,
                    f"Generated modification date is not numeric: {metadata}")
            require(Path(source.filePath(proxy.mapToSource(folder_index))).resolve() == folder.resolve(),
                    "Display localization changed the source folder path")
            widget.accept()
            require(widget.result() == QDialog.DialogCode.Accepted, "Synthetic file selection was not accepted")
            require([Path(path).resolve() for path in widget.selectedFiles()] == [selected.resolve()],
                    "Selected filename or directory was changed")
            if kind == "save":
                require(not selected.exists(), "File picker unexpectedly created an output file")
            elif kind == "open":
                require(selected.read_text(encoding="utf-8") == "synthetic unchanged", "Input file changed")
            return {"labels": observed, "actions": sorted(action_texts), "non_native": True,
                    "selection_preserved": True, "folder_metadata": metadata}
        finally:
            dispose(widget)

    QLocale.setDefault(QLocale("en_US"))
    result = {"initial_locale": QLocale().name()}
    require(install(directory), "Full Traditional Chinese Qt catalogue is missing or unreadable")
    result.update(catalogue_loaded=True, locale=QLocale().name())
    require(result["locale"] == "zh_TW", "Traditional Chinese locale was not applied")
    result["standard_buttons"] = buttons()
    calendar = QCalendarWidget()
    try:
        calendar.setCurrentPage(2026, 1)
        calendar.show()
        app.processEvents()
        month = calendar.findChild(QToolButton, "qt_calendar_monthbutton")
        table = calendar.findChild(QTableView, "qt_calendar_calendarview")
        require(month is not None and table is not None, "Calendar native controls unavailable")
        month_text = month.text()
        model = table.model()
        weekdays = [str(model.data(model.index(0, column)) or "") for column in range(model.columnCount())]
        weekdays = [text for text in weekdays if text]
        require(month_text == "1月", f"Calendar month is not Chinese: {month_text}")
        require(set(weekdays) == {"週日", "週一", "週二", "週三", "週四", "週五", "週六"},
                f"Calendar visible weekday labels are not Chinese: {weekdays}")
        result["calendar"] = {"month": month_text, "weekdays": weekdays}
    finally:
        dispose(calendar)
    result["file_dialogs"] = {kind: file_dialog(kind, complete=True) for kind in ("open", "save", "directory")}
    missing_directory = root / "missing_translation_catalogue"
    require(not missing_directory.exists(), "Fallback test requires a genuinely absent catalogue")
    try:
        require(not install(missing_directory), "Missing catalogue incorrectly reported complete")
        result["missing_catalogue"] = {
            "catalogue_loaded": False, "fully_localized": False, "status": "standard_buttons_only",
            "standard_buttons": buttons(), "file_dialog": file_dialog("open", complete=False),
        }
    finally:
        require(install(directory), "Could not restore the full Qt catalogue after fallback check")
    return result
