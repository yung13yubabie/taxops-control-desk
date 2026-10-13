"""Discoverable local notice viewer. No network, HTML, or agreement acceptance."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout,
)

from ...core.third_party_notices import NoticeCatalog, NoticeError, load_notices

_log = logging.getLogger(__name__)
_FEATURED = {
    "README.txt": "元件與授權總覽",
    "SOURCE_ACCESS.txt": "取得原始碼與重組程式的方法",
    "qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt": "較寬鬆通用公眾授權第三版原文",
    "qt-6.10.2/qtbase/LICENSES/GPL-3.0-only.txt": "通用公眾授權第三版原文",
    "manifest.json": "版本、來源與檔案清單",
}


class ThirdPartyNoticesDialog(QDialog):
    def __init__(self, parent=None, *, catalog: NoticeCatalog | None = None) -> None:
        loaded = catalog if catalog is not None else load_notices()
        super().__init__(parent)
        self.setWindowTitle("第三方授權")
        self.resize(760, 560)
        self.catalog = loaded
        layout = QVBoxLayout(self)
        intro = QLabel("可在離線時閱讀或匯出隨程式附上的授權文件。\n"
                       "下方保留原作者的完整原文；閱讀與關閉此視窗不需要接受新條款。")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(intro)
        label = QLabel("選擇文件：")
        self.document_combo = QComboBox()
        self.document_combo.setMinimumContentsLength(18)
        self.document_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.document_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        label.setBuddy(self.document_combo)
        layout.addWidget(label)
        layout.addWidget(self.document_combo)
        names = [name for name in _FEATURED if name in self.catalog.files]
        names += sorted(set(self.catalog.files) - set(names))
        for name in names:
            self.document_combo.addItem(_FEATURED.get(name, name), name)
            self.document_combo.setItemData(self.document_combo.count() - 1, name, Qt.ItemDataRole.ToolTipRole)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setAccessibleName("授權文件原文")
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.text_view, 1)
        self.document_combo.currentIndexChanged.connect(self._show_document)
        self._show_document()
        buttons = QHBoxLayout()
        self.export_button = QPushButton("匯出全部授權文件")
        self.export_button.clicked.connect(self.on_export)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _show_document(self) -> None:
        self.text_view.setPlainText(self.catalog.text(self.document_combo.currentData()))

    def export_to(self, destination: Path) -> None:
        """Export the exact snapshot currently visible in this dialog."""
        self.catalog.export(destination)

    def on_export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "匯出授權文件", "TaxOps-第三方授權文件.zip", "壓縮檔 (*.zip)",
        )
        if not filename:
            return
        try:
            self.export_to(Path(filename))
        except (NoticeError, OSError):
            _log.exception("Third-party notice export failed")
            QMessageBox.warning(self, "未完成匯出", "授權文件無法儲存。請確認資料夾可寫入且空間足夠，再試一次。")
            return
        QMessageBox.information(self, "匯出完成", "全部授權文件已儲存，可解壓縮後離線閱讀。")
