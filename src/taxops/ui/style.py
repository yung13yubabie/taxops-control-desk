"""Global application stylesheet composed from `tokens.py`.

Button appearance is driven by a `role` dynamic property rather than by whichever
colour a page happened to set inline. The bare `QPushButton` rule is the secondary
role — a neutral surface with a border — so a button that declares no role reads as
an ordinary action instead of shouting like a primary one. Use
`widgets.buttons.set_button_role` to assign a role; it repolishes the widget so the
new role paints immediately.

Checkbox and radio indicators are left to the platform style. The stylesheet sets
only spacing and type on them, which keeps Qt drawing the native indicator — with a
real tick mark — instead of the solid blue square a QSS `::indicator` override
produced.

Legacy colour and spacing names are re-exported here because pages already import
them from this module.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from . import icons, tokens
from .icons import UnknownIconRole

# ── Legacy re-exports (pages import these names from `style`) ────────
PRIMARY_COLOR = tokens.PRIMARY
PRIMARY_HOVER = tokens.PRIMARY_HOVER
DANGER_COLOR = tokens.DANGER
DANGER_HOVER_COLOR = tokens.DANGER_HOVER
BORDER_COLOR = tokens.BORDER
TEXT_MUTED = tokens.TEXT_MUTED
TEXT_MAIN = tokens.TEXT

STATUS_PENDING_BG = tokens.STATUS_PENDING_BG
STATUS_PENDING_FG = tokens.STATUS_PENDING_FG
STATUS_CONFIRMED_BG = tokens.STATUS_CONFIRMED_BG
STATUS_CONFIRMED_FG = tokens.STATUS_CONFIRMED_FG
STATUS_SKIPPED_BG = tokens.STATUS_SKIPPED_BG
STATUS_SKIPPED_FG = tokens.STATUS_SKIPPED_FG
STATUS_OVERDUE_BG = tokens.STATUS_OVERDUE_BG
STATUS_OVERDUE_FG = tokens.STATUS_OVERDUE_FG
STATUS_ARCHIVED_FG = tokens.STATUS_ARCHIVED_FG

WARNING_BG = tokens.WARNING_BG
WARNING_FG = tokens.WARNING_FG
INFO_BG = tokens.INFO_BG
INFO_FG = tokens.INFO_FG

SPACING_XS = tokens.SPACING_XS
SPACING_SM = tokens.SPACING_SM
SPACING_MD = tokens.SPACING_MD
SPACING_LG = tokens.SPACING_LG
SPACING_XL = tokens.SPACING_XL

# ── Derived box metrics ─────────────────────────────────────────────
# Qt applies min-height to the content rect, so padding and border add on top.
# Subtracting them keeps the rendered control on its token height instead of
# overshooting by 14px the way the previous sheet did.
_V_PADDING = 6
_BORDER_W = 1
_BOX_OVERHEAD = _V_PADDING * 2 + _BORDER_W * 2

_BTN_CONTENT_H = tokens.BUTTON_HEIGHT - _BOX_OVERHEAD
_BTN_COMPACT_CONTENT_H = tokens.BUTTON_HEIGHT_COMPACT - _BOX_OVERHEAD
_INPUT_CONTENT_H = tokens.INPUT_HEIGHT - _BOX_OVERHEAD
_INPUT_COMPACT_CONTENT_H = tokens.INPUT_HEIGHT_COMPACT - _BOX_OVERHEAD
# Icon buttons carry no padding, so only the border is deducted. Measured: leaving
# the full token here rendered a 34px control against a 32px setFixedSize.
_ICON_BTN_CONTENT = tokens.ICON_BUTTON_SIZE - _BORDER_W * 2

# ── Compact in-row buttons ──────────────────────────────────────────
# Kept as string constants because per-row widgets in recurring billing apply them
# directly. They now honour the 13px type floor and the compact height token; the
# secondary variant is a neutral surface rather than the old grey fill.
BTN_PRIMARY_SM = (
    f"QPushButton {{ background-color: {tokens.PRIMARY}; color: {tokens.TEXT_ON_PRIMARY}; "
    f"border: 1px solid {tokens.PRIMARY}; border-radius: {tokens.RADIUS_SM}px; "
    f"padding: 4px 10px; font-size: {tokens.FONT_HINT}px; font-weight: 500; "
    f"min-height: {_BTN_COMPACT_CONTENT_H}px; }}"
    f"QPushButton:hover {{ background-color: {tokens.PRIMARY_HOVER}; "
    f"border-color: {tokens.PRIMARY_HOVER}; }}"
    f"QPushButton:pressed {{ background-color: {tokens.PRIMARY_PRESSED}; }}"
    f"QPushButton:focus {{ border: 2px solid {tokens.FOCUS_RING}; }}"
    f"QPushButton:disabled {{ background-color: {tokens.SURFACE_SECTION}; "
    f"color: {tokens.TEXT_DISABLED}; border-color: {tokens.BORDER}; }}"
)
BTN_SECONDARY_SM = (
    f"QPushButton {{ background-color: {tokens.SURFACE_CONTENT}; color: {tokens.TEXT}; "
    f"border: 1px solid {tokens.BORDER_STRONG}; border-radius: {tokens.RADIUS_SM}px; "
    f"padding: 4px 10px; font-size: {tokens.FONT_HINT}px; font-weight: 500; "
    f"min-height: {_BTN_COMPACT_CONTENT_H}px; }}"
    f"QPushButton:hover {{ background-color: {tokens.SURFACE_HOVER}; }}"
    f"QPushButton:pressed {{ background-color: {tokens.BORDER}; }}"
    f"QPushButton:focus {{ border: 2px solid {tokens.FOCUS_RING}; }}"
    f"QPushButton:disabled {{ background-color: {tokens.SURFACE_SECTION}; "
    f"color: {tokens.TEXT_DISABLED}; border-color: {tokens.BORDER}; }}"
)
BTN_DANGER_SM = (
    f"QPushButton {{ background-color: {tokens.SURFACE_CONTENT}; color: {tokens.DANGER}; "
    f"border: 1px solid {tokens.DANGER}; border-radius: {tokens.RADIUS_SM}px; "
    f"padding: 4px 10px; font-size: {tokens.FONT_HINT}px; font-weight: 500; "
    f"min-height: {_BTN_COMPACT_CONTENT_H}px; }}"
    f"QPushButton:hover {{ background-color: {tokens.DANGER_SOFT}; }}"
    f"QPushButton:pressed {{ background-color: #FDE4E4; }}"
    f"QPushButton:focus {{ border: 2px solid {tokens.DANGER}; }}"
    f"QPushButton:disabled {{ background-color: {tokens.SURFACE_SECTION}; "
    f"color: {tokens.TEXT_DISABLED}; border-color: {tokens.BORDER}; }}"
)

# ── Stylesheet sections ─────────────────────────────────────────────

_QSS_BASE = f"""
QWidget {{
    font-family: {tokens.FONT_FAMILY};
    font-size: {tokens.FONT_BODY}px;
    color: {tokens.TEXT};
    background-color: {tokens.SURFACE_PAGE};
}}

QMainWindow, QDialog {{
    background-color: {tokens.SURFACE_PAGE};
}}

QLabel#PageTitle {{
    font-size: {tokens.FONT_PAGE_TITLE}px;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    font-size: {tokens.FONT_SECTION_TITLE}px;
    font-weight: 600;
}}
QLabel#HintText {{
    font-size: {tokens.FONT_HINT}px;
    color: {tokens.TEXT_MUTED};
}}
QLabel#ErrorText {{
    font-size: {tokens.FONT_ERROR}px;
    color: {tokens.DANGER};
}}

/* Empty state: the title carries the weight, the body explains. */
QLabel#EmptyStateTitle {{
    font-size: {tokens.FONT_SECTION_TITLE}px;
    font-weight: 600;
    color: {tokens.TEXT};
}}
QLabel#EmptyStateBody {{
    font-size: {tokens.FONT_BODY}px;
    color: {tokens.TEXT_MUTED};
}}
QWidget#EmptyState {{
    background-color: transparent;
}}

/* Page shell */
QWidget#PageHeader {{
    background-color: transparent;
}}
QLabel#PageSubtitle {{
    font-size: {tokens.FONT_HINT}px;
    color: {tokens.TEXT_MUTED};
}}
QWidget#ActionBar {{
    background-color: transparent;
}}
QFrame#Inspector {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_LG}px;
}}
QLabel#InspectorTitle {{
    font-size: {tokens.FONT_SECTION_TITLE}px;
    font-weight: 600;
    color: {tokens.TEXT};
}}
QLabel#InspectorSection {{
    font-size: {tokens.FONT_HINT}px;
    font-weight: 600;
    color: {tokens.TEXT_MUTED};
}}
QLabel#InspectorLabel {{
    font-size: {tokens.FONT_HINT}px;
    color: {tokens.TEXT_MUTED};
}}
QLabel#InspectorValue {{
    font-size: {tokens.FONT_BODY}px;
    color: {tokens.TEXT};
}}
QLabel#InspectorPlaceholder {{
    font-size: {tokens.FONT_BODY}px;
    color: {tokens.TEXT_MUTED};
}}
"""

# The bare QPushButton rule is the secondary role. Every other role overrides it
# explicitly, and each keeps a 1px border — transparent where no border should show
# — so switching roles never changes a control's height.
_QSS_BUTTONS = f"""
QPushButton {{
    background-color: {tokens.SURFACE_CONTENT};
    color: {tokens.TEXT};
    border: {_BORDER_W}px solid {tokens.BORDER_STRONG};
    border-radius: {tokens.RADIUS_MD}px;
    padding: {_V_PADDING}px 14px;
    font-size: {tokens.FONT_BODY}px;
    font-weight: 500;
    min-height: {_BTN_CONTENT_H}px;
}}
QPushButton:hover {{ background-color: {tokens.SURFACE_HOVER}; }}
QPushButton:pressed {{ background-color: {tokens.BORDER}; }}
QPushButton:focus {{ border: 2px solid {tokens.FOCUS_RING}; }}
QPushButton:disabled {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_DISABLED};
    border-color: {tokens.BORDER};
}}

QPushButton[role="primary"] {{
    background-color: {tokens.PRIMARY};
    color: {tokens.TEXT_ON_PRIMARY};
    border: {_BORDER_W}px solid {tokens.PRIMARY};
}}
QPushButton[role="primary"]:hover {{
    background-color: {tokens.PRIMARY_HOVER};
    border-color: {tokens.PRIMARY_HOVER};
}}
QPushButton[role="primary"]:pressed {{
    background-color: {tokens.PRIMARY_PRESSED};
    border-color: {tokens.PRIMARY_PRESSED};
}}
QPushButton[role="primary"]:focus {{ border: 2px solid {tokens.PRIMARY_PRESSED}; }}
QPushButton[role="primary"]:disabled {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_DISABLED};
    border-color: {tokens.BORDER};
}}

QPushButton[role="secondary"] {{
    background-color: {tokens.SURFACE_CONTENT};
    color: {tokens.TEXT};
    border: {_BORDER_W}px solid {tokens.BORDER_STRONG};
}}

QPushButton[role="quiet"] {{
    background-color: transparent;
    color: {tokens.TEXT};
    border: {_BORDER_W}px solid transparent;
}}
QPushButton[role="quiet"]:hover {{
    background-color: {tokens.SURFACE_HOVER};
    border-color: {tokens.BORDER};
}}
QPushButton[role="quiet"]:pressed {{ background-color: {tokens.BORDER}; }}
QPushButton[role="quiet"]:disabled {{
    background-color: transparent;
    color: {tokens.TEXT_DISABLED};
    border-color: transparent;
}}

QPushButton[role="danger"] {{
    background-color: {tokens.SURFACE_CONTENT};
    color: {tokens.DANGER};
    border: {_BORDER_W}px solid {tokens.DANGER};
}}
QPushButton[role="danger"]:hover {{ background-color: {tokens.DANGER_SOFT}; }}
QPushButton[role="danger"]:pressed {{ background-color: #FDE4E4; }}
QPushButton[role="danger"]:focus {{ border: 2px solid {tokens.DANGER_PRESSED}; }}
QPushButton[role="danger"]:disabled {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_DISABLED};
    border-color: {tokens.BORDER};
}}

QPushButton[role="dangerQuiet"] {{
    background-color: transparent;
    color: {tokens.DANGER};
    border: {_BORDER_W}px solid transparent;
}}
QPushButton[role="dangerQuiet"]:hover {{
    background-color: {tokens.DANGER_SOFT};
    border-color: {tokens.DANGER};
}}
QPushButton[role="dangerQuiet"]:disabled {{
    background-color: transparent;
    color: {tokens.TEXT_DISABLED};
    border-color: transparent;
}}

QPushButton[role="icon"] {{
    background-color: transparent;
    border: {_BORDER_W}px solid transparent;
    border-radius: {tokens.RADIUS_MD}px;
    padding: 0px;
    min-width: {_ICON_BTN_CONTENT}px;
    max-width: {_ICON_BTN_CONTENT}px;
    min-height: {_ICON_BTN_CONTENT}px;
    max-height: {_ICON_BTN_CONTENT}px;
}}
QPushButton[role="icon"]:hover {{
    background-color: {tokens.SURFACE_HOVER};
    border-color: {tokens.BORDER};
}}
QPushButton[role="icon"]:pressed {{ background-color: {tokens.BORDER}; }}
QPushButton[role="icon"]:focus {{ border: 2px solid {tokens.FOCUS_RING}; }}
QPushButton[role="icon"]:disabled {{
    background-color: transparent;
    border-color: transparent;
}}

QPushButton[role="link"] {{
    background-color: transparent;
    color: {tokens.PRIMARY};
    border: none;
    padding: 2px 0px;
    font-weight: 500;
    text-align: left;
    min-height: 0px;
}}
QPushButton[role="link"]:hover {{ color: {tokens.PRIMARY_HOVER}; }}
QPushButton[role="link"]:disabled {{ color: {tokens.TEXT_DISABLED}; }}

QDialogButtonBox QPushButton {{ min-width: 88px; }}
"""

_QSS_INPUTS = f"""
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER_STRONG};
    border-radius: {tokens.RADIUS_MD}px;
    padding: {_V_PADDING}px 10px;
    font-size: {tokens.FONT_BODY}px;
    selection-background-color: #BFDBFE;
    selection-color: {tokens.TEXT};
}}
QLineEdit, QAbstractSpinBox {{ min-height: {_INPUT_CONTENT_H}px; }}
QLineEdit[density="compact"], QAbstractSpinBox[density="compact"] {{
    min-height: {_INPUT_COMPACT_CONTENT_H}px;
    padding: 4px 8px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus {{
    border: 2px solid {tokens.PRIMARY};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QAbstractSpinBox:disabled {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_DISABLED};
}}
QLineEdit[invalid="true"], QTextEdit[invalid="true"],
QPlainTextEdit[invalid="true"], QAbstractSpinBox[invalid="true"] {{
    border: 2px solid {tokens.DANGER};
}}

QComboBox {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER_STRONG};
    border-radius: {tokens.RADIUS_MD}px;
    padding: {_V_PADDING}px 10px;
    font-size: {tokens.FONT_BODY}px;
    min-height: {_INPUT_CONTENT_H}px;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox:focus {{ border: 2px solid {tokens.PRIMARY}; }}
QComboBox:disabled {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_DISABLED};
}}
QComboBox QAbstractItemView {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER};
    selection-background-color: {tokens.SURFACE_SELECTED};
    selection-color: {tokens.TEXT};
    outline: none;
}}

QDateEdit, QDateTimeEdit {{
    min-height: {_INPUT_CONTENT_H}px;
    font-size: {tokens.FONT_BODY}px;
}}

/* Indicators are left to the platform style so checked state shows a real tick
   rather than a solid fill.
   Only spacing, type, and text colour may be set here. Declaring any box-model
   property — `background-color` included, even `transparent` — makes Qt paint the
   indicator through the stylesheet instead of the platform style, which silently
   drops the unchecked border and leaves an invisible control. Measured: the
   unchecked border goes from 64 painted pixels to 0. */
QCheckBox, QRadioButton {{
    spacing: {tokens.SPACING_SM}px;
    font-size: {tokens.FONT_BODY}px;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {tokens.TEXT_DISABLED}; }}
"""

_QSS_TABLE = f"""
QTableWidget, QTableView {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_MD}px;
    gridline-color: {tokens.BORDER_SUBTLE};
    font-size: {tokens.FONT_TABLE}px;
    outline: none;
    alternate-background-color: {tokens.SURFACE_SECTION};
}}
QTableWidget:focus, QTableView:focus {{ border: {_BORDER_W}px solid {tokens.PRIMARY}; }}
QTableWidget::item, QTableView::item {{
    padding: {_V_PADDING}px {tokens.SPACING_SM}px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {tokens.SURFACE_SELECTED};
    color: {tokens.TEXT};
}}
QHeaderView {{ background-color: {tokens.SURFACE_SECTION}; }}
QHeaderView::section {{
    background-color: {tokens.SURFACE_SECTION};
    color: {tokens.TEXT_MUTED};
    font-weight: 600;
    font-size: {tokens.FONT_TABLE_HEADER}px;
    border: none;
    border-bottom: {_BORDER_W}px solid {tokens.BORDER};
    padding: {tokens.SPACING_SM}px 10px;
}}
QTableCornerButton::section {{
    background-color: {tokens.SURFACE_SECTION};
    border: none;
}}
"""

# Three surface levels only. A group box contributes a heading and a top rule
# instead of a fourth box, which is what produced borders inside borders.
_QSS_CONTAINERS = f"""
QGroupBox {{
    border: none;
    border-top: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: 0px;
    margin-top: {tokens.SPACING_LG}px;
    padding: {tokens.SPACING_MD}px 0px 0px 0px;
    font-size: {tokens.FONT_BODY}px;
    font-weight: 600;
    background-color: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0px;
    padding: 0px {tokens.SPACING_SM}px 0px 0px;
    background-color: transparent;
    color: {tokens.TEXT};
    font-size: {tokens.FONT_BODY}px;
    font-weight: 600;
}}

QFrame#ContentSurface {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_LG}px;
}}
QFrame#SectionDivider {{
    background-color: {tokens.BORDER};
    max-height: {_BORDER_W}px;
    border: none;
}}

QTabWidget::pane {{
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_MD}px;
    background-color: {tokens.SURFACE_CONTENT};
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {tokens.TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {tokens.SPACING_SM}px {tokens.SPACING_LG}px;
    font-size: {tokens.FONT_BODY}px;
    min-height: {_BTN_CONTENT_H}px;
}}
QTabBar::tab:selected {{
    color: {tokens.TEXT};
    border-bottom: 2px solid {tokens.PRIMARY};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {tokens.TEXT}; }}
QTabBar:focus {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {tokens.BORDER_STRONG}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {tokens.BORDER_STRONG}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QProgressBar {{
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_SM}px;
    background: {tokens.SURFACE_SECTION};
    text-align: center;
    font-size: {tokens.FONT_HINT}px;
    min-height: 18px;
}}
QProgressBar::chunk {{ background: {tokens.PRIMARY}; border-radius: 3px; }}

QToolTip {{
    background-color: {tokens.TEXT};
    color: {tokens.SURFACE_CONTENT};
    border: none;
    padding: {tokens.SPACING_XS}px {tokens.SPACING_SM}px;
    font-size: {tokens.FONT_HINT}px;
}}

QMenu {{
    background-color: {tokens.SURFACE_CONTENT};
    border: {_BORDER_W}px solid {tokens.BORDER};
    border-radius: {tokens.RADIUS_MD}px;
    padding: {tokens.SPACING_XS}px;
}}
QMenu::item {{
    padding: {tokens.SPACING_SM}px {tokens.SPACING_LG}px;
    border-radius: {tokens.RADIUS_SM}px;
    font-size: {tokens.FONT_BODY}px;
}}
QMenu::item:selected {{ background-color: {tokens.SURFACE_SELECTED}; }}
QMenu::item:disabled {{ color: {tokens.TEXT_DISABLED}; }}
QMenu::separator {{
    height: {_BORDER_W}px;
    background: {tokens.BORDER};
    margin: {tokens.SPACING_XS}px {tokens.SPACING_SM}px;
}}
"""

# Active navigation reads as a left indicator plus a muted fill. The previous
# saturated blue block on a dark sidebar left no room for any other emphasis.
_QSS_NAV = f"""
QWidget#Sidebar {{
    background-color: {tokens.SIDEBAR_BG};
    border: none;
}}
QListWidget#MainNav {{
    background-color: {tokens.SIDEBAR_BG};
    border: none;
    outline: none;
    padding: {tokens.SPACING_XS}px 0px;
}}
QListWidget#MainNav::item {{
    color: {tokens.SIDEBAR_TEXT};
    padding: 10px 14px;
    font-size: {tokens.FONT_BODY}px;
    font-weight: 500;
    border-left: 3px solid transparent;
}}
QListWidget#MainNav::item:selected {{
    background-color: {tokens.SIDEBAR_ACTIVE_BG};
    color: {tokens.SIDEBAR_TEXT_ACTIVE};
    border-left: 3px solid {tokens.SIDEBAR_ACTIVE_INDICATOR};
    font-weight: 600;
}}
QListWidget#MainNav::item:hover:!selected {{
    background-color: {tokens.SIDEBAR_HOVER};
    color: {tokens.SIDEBAR_TEXT_ACTIVE};
}}
QListWidget#MainNav:focus {{ border: none; }}
/* Collapsed: the label is cleared in code, so padding recentres the lone glyph
   inside the narrow rail. */
QListWidget#MainNav[collapsed="true"]::item {{ padding: 10px 14px; }}

QPushButton#SidebarToggle {{
    background-color: transparent;
    color: {tokens.SIDEBAR_TEXT};
    border: {_BORDER_W}px solid transparent;
    border-radius: {tokens.RADIUS_MD}px;
    padding: 0px;
    min-width: {_ICON_BTN_CONTENT}px;
    max-width: {_ICON_BTN_CONTENT}px;
    min-height: {_ICON_BTN_CONTENT}px;
    max-height: {_ICON_BTN_CONTENT}px;
}}
QPushButton#SidebarToggle:hover {{
    background-color: {tokens.SIDEBAR_HOVER};
    border-color: {tokens.SIDEBAR_ACTIVE_BG};
}}
QPushButton#SidebarToggle:focus {{ border: 2px solid {tokens.SIDEBAR_ACTIVE_INDICATOR}; }}
"""

APP_STYLESHEET = (
    _QSS_BASE + _QSS_BUTTONS + _QSS_INPUTS + _QSS_TABLE + _QSS_CONTAINERS + _QSS_NAV
)


def toolbar_icon(role: str) -> QIcon:
    """Return the icon for an action role.

    Raises `UnknownIconRole` for an unmapped role rather than substituting a
    plausible-looking glyph.
    """
    return icons.icon(role)


def apply(app: object) -> None:
    """Apply the global stylesheet and app icon to a QApplication instance."""
    import sys
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

    app.setStyleSheet(APP_STYLESHEET)  # type: ignore[attr-defined]

    if getattr(sys, "frozen", False):
        icon_path = Path(sys.executable).parent / "assets" / "app_icon.ico"
    else:
        icon_path = Path(__file__).resolve().parents[3] / "assets" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))  # type: ignore[attr-defined]
        return

    # Generate a simple icon: blue square with white "T" letter
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(tokens.PRIMARY))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 64, 64, 12, 12)
    painter.setPen(QColor(tokens.TEXT_ON_PRIMARY))
    font = QFont("Arial", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    app.setWindowIcon(QIcon(px))  # type: ignore[attr-defined]


__all__ = [
    "APP_STYLESHEET",
    "BORDER_COLOR",
    "BTN_DANGER_SM",
    "BTN_PRIMARY_SM",
    "BTN_SECONDARY_SM",
    "DANGER_COLOR",
    "DANGER_HOVER_COLOR",
    "INFO_BG",
    "INFO_FG",
    "PRIMARY_COLOR",
    "PRIMARY_HOVER",
    "SPACING_LG",
    "SPACING_MD",
    "SPACING_SM",
    "SPACING_XL",
    "SPACING_XS",
    "STATUS_ARCHIVED_FG",
    "STATUS_CONFIRMED_BG",
    "STATUS_CONFIRMED_FG",
    "STATUS_OVERDUE_BG",
    "STATUS_OVERDUE_FG",
    "STATUS_PENDING_BG",
    "STATUS_PENDING_FG",
    "STATUS_SKIPPED_BG",
    "STATUS_SKIPPED_FG",
    "TEXT_MAIN",
    "TEXT_MUTED",
    "UnknownIconRole",
    "WARNING_BG",
    "WARNING_FG",
    "apply",
    "toolbar_icon",
]
