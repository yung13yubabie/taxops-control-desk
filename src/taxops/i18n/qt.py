"""Install bundled Traditional Chinese Qt text, independent of OS language."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QIdentityProxyModel, QLibraryInfo, QLocale, QObject, Qt, QTranslator
from PySide6.QtWidgets import QFileDialog, QHeaderView, QTreeView

from .labels import file_type_label


class _StandardButtons(QTranslator):
    """Small fallback for platform buttons if Qt's catalogue is unavailable."""

    _labels = {
        "OK": "確定", "Save": "儲存", "Save All": "全部儲存", "Open": "開啟",
        "Yes": "是", "Yes to All": "全部皆是", "No": "否", "No to All": "全部皆否",
        "Abort": "中止", "Retry": "重試", "Ignore": "略過", "Close": "關閉",
        "Cancel": "取消", "Discard": "捨棄", "Help": "說明", "Apply": "套用",
        "Reset": "重設", "Restore Defaults": "恢復預設值",
        "Show Details...": "查看詳細資料…", "Hide Details...": "收起詳細資料…",
    }

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        if context in {"QPlatformTheme", "QDialogButtonBox", "QMessageBox"}:
            return self._labels.get(sourceText.replace("&", ""))
        return None


class _FileDisplayProxy(QIdentityProxyModel):
    """Translate generated file metadata, preserving file names, paths and roles."""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.isValid() and index.column() in (1, 2, 3):
            source = self.sourceModel()
            info = source.fileInfo(self.mapToSource(index))
            if index.column() == 1:
                return "" if info.isDir() else f"{info.size():,} 位元組"
            if index.column() == 2:
                if info.isDir():
                    return "資料夾"
                return file_type_label("." + info.suffix())
            return info.lastModified().toString("yyyy-MM-dd HH:mm")
        return super().data(index, role)


class _FileDialogLanguage(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QFileDialog):
            if watched.proxyModel() is None:
                proxy = _FileDisplayProxy(watched)
                watched.setProxyModel(proxy)
                watched._taxops_file_proxy = proxy
                view = watched.findChild(QTreeView)
                if view is not None:
                    header = view.header()
                    header.setResizeContentsPrecision(30)
                    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                    for column in (1, 2, 3):
                        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return False


def _install_file_dialog_language(app) -> None:
    if not getattr(app, "_taxops_file_dialog_language", None):
        observer = _FileDialogLanguage(app)
        app.installEventFilter(observer)
        app._taxops_file_dialog_language = observer


def _install_from_path(app, directory: str) -> bool:
    """Replace translators from a specific local directory for offline diagnostics."""
    QLocale.setDefault(QLocale("zh_TW"))
    _install_file_dialog_language(app)
    for translator in getattr(app, "_taxops_translators", ()):
        app.removeTranslator(translator)
        translator.deleteLater()
    catalogue = QTranslator(app)
    catalogue.load("qtbase_zh_TW", directory)
    app.installTranslator(catalogue)
    fallback = _StandardButtons(app)
    app.installTranslator(fallback)
    app._taxops_translators = (catalogue, fallback)
    return not catalogue.isEmpty()


def install_chinese(app) -> bool:
    """Install once; return whether the full bundled catalogue is available."""
    QLocale.setDefault(QLocale("zh_TW"))
    _install_file_dialog_language(app)
    if getattr(app, "_taxops_translators", None):
        return not app._taxops_translators[0].isEmpty()
    return _install_from_path(
        app, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    )
