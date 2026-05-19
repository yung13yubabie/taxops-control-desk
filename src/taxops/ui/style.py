"""Global application stylesheet — clean, professional, Traditional Chinese office tool."""

from __future__ import annotations

_PRIMARY = "#2563EB"
_PRIMARY_HOVER = "#1D4ED8"
_PRIMARY_PRESSED = "#1E40AF"
_SURFACE = "#F8FAFC"
_SIDEBAR_BG = "#1E293B"
_SIDEBAR_TEXT = "#CBD5E1"
_BORDER = "#E2E8F0"
_TEXT = "#0F172A"
_TEXT_MUTED = "#64748B"
_INPUT_BG = "#FFFFFF"
DANGER_COLOR = "#DC2626"
DANGER_HOVER_COLOR = "#B91C1C"

APP_STYLESHEET = f"""
QWidget {{
    font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
    font-size: 13px;
    color: {_TEXT};
    background-color: {_SURFACE};
}}

QMainWindow, QDialog {{
    background-color: {_SURFACE};
}}

QListWidget#MainNav {{
    background-color: {_SIDEBAR_BG};
    border: none;
    outline: none;
    padding: 8px 0;
}}
QListWidget#MainNav::item {{
    color: {_SIDEBAR_TEXT};
    padding: 12px 20px;
    font-size: 14px;
    font-weight: 500;
}}
QListWidget#MainNav::item:selected {{
    background-color: {_PRIMARY};
    color: #FFFFFF;
    border-left: 3px solid #93C5FD;
    padding-left: 17px;
}}
QListWidget#MainNav::item:hover:!selected {{
    background-color: #2D3E52;
    color: #FFFFFF;
}}

QPushButton {{
    background-color: {_PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    min-height: 32px;
}}
QPushButton:hover {{ background-color: {_PRIMARY_HOVER}; }}
QPushButton:pressed {{ background-color: {_PRIMARY_PRESSED}; }}
QPushButton:disabled {{ background-color: #CBD5E1; color: #94A3B8; }}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {_INPUT_BG};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #BFDBFE;
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {_PRIMARY}; }}
QLineEdit:disabled, QTextEdit:disabled {{ background-color: #F1F5F9; color: {_TEXT_MUTED}; }}

QComboBox {{
    background-color: {_INPUT_BG};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 32px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {_BORDER};
    selection-background-color: #DBEAFE;
    selection-color: {_TEXT};
    outline: none;
}}

QTableWidget {{
    background-color: {_INPUT_BG};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    gridline-color: {_BORDER};
    outline: none;
    alternate-background-color: #F8FAFC;
}}
QTableWidget::item {{ padding: 6px 8px; }}
QTableWidget::item:selected {{ background-color: #DBEAFE; color: {_TEXT}; }}
QHeaderView::section {{
    background-color: #F1F5F9;
    color: {_TEXT_MUTED};
    font-weight: 600;
    font-size: 12px;
    border: none;
    border-bottom: 1px solid {_BORDER};
    border-right: 1px solid {_BORDER};
    padding: 8px 10px;
}}

QGroupBox {{
    border: 1px solid {_BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    background-color: {_SURFACE};
    color: {_TEXT_MUTED};
    font-size: 12px;
    font-weight: 600;
}}

QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: #CBD5E1; border-radius: 4px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QProgressBar {{
    border: 1px solid {_BORDER};
    border-radius: 4px;
    background: #E2E8F0;
    text-align: center;
}}
QProgressBar::chunk {{ background: {_PRIMARY}; border-radius: 4px; }}

QRadioButton, QCheckBox {{ spacing: 6px; }}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 3px;
    border: 1px solid #94A3B8;
    background: {_INPUT_BG};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    background: {_PRIMARY}; border-color: {_PRIMARY};
}}

QDialogButtonBox QPushButton {{ min-width: 80px; }}
"""


from PySide6.QtWidgets import QStyle as _QStyle

_TOOLBAR_ICON_MAP: dict[str, _QStyle.StandardPixmap] = {
    "new": _QStyle.StandardPixmap.SP_FileDialogNewFolder,
    "edit": _QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "delete": _QStyle.StandardPixmap.SP_TrashIcon,
    "refresh": _QStyle.StandardPixmap.SP_BrowserReload,
    "back": _QStyle.StandardPixmap.SP_ArrowBack,
    "save": _QStyle.StandardPixmap.SP_DialogSaveButton,
    "trial": _QStyle.StandardPixmap.SP_MessageBoxInformation,
    "complete": _QStyle.StandardPixmap.SP_DialogApplyButton,
    "export": _QStyle.StandardPixmap.SP_ArrowRight,
    "bulk": _QStyle.StandardPixmap.SP_DirLinkIcon,
}


def toolbar_icon(role: str) -> "QIcon":
    from PySide6.QtWidgets import QApplication
    sp = _TOOLBAR_ICON_MAP.get(role, _QStyle.StandardPixmap.SP_MessageBoxInformation)
    return QApplication.style().standardIcon(sp)


def apply(app: object) -> None:
    """Apply the global stylesheet and app icon to a QApplication instance."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
    from PySide6.QtCore import Qt

    app.setStyleSheet(APP_STYLESHEET)  # type: ignore[attr-defined]

    # Generate a simple icon: blue square with white "T" letter
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563EB"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 64, 64, 12, 12)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Arial", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    app.setWindowIcon(QIcon(px))  # type: ignore[attr-defined]
