"""Design tokens for the desktop surface.

Single source of truth for colour, type scale, and sizing. `style.py` composes the
global stylesheet from these values and re-exports the legacy names that pages
already import, so nothing outside this module hard-codes a hex value or a pixel
height.

Sizing follows `.ai/DESIGN.md`: 14px minimum for general text, 13px minimum inside
tables, and enough height that Traditional Chinese glyphs never clip at 125% or
150% Windows scaling.
"""

from __future__ import annotations

# ── Brand and accent ────────────────────────────────────────────────
PRIMARY = "#2563EB"
PRIMARY_HOVER = "#1D4ED8"
PRIMARY_PRESSED = "#1E40AF"
PRIMARY_SOFT = "#EFF4FE"
FOCUS_RING = "#93C5FD"

DANGER = "#DC2626"
DANGER_HOVER = "#B91C1C"
DANGER_PRESSED = "#991B1B"
DANGER_SOFT = "#FEF2F2"

SUCCESS = "#16A34A"
WARNING = "#B45309"

# ── Surfaces ────────────────────────────────────────────────────────
# Three levels only: page behind content behind section. Anything deeper is the
# nested-border problem the rebuild removes.
SURFACE_PAGE = "#F5F7FA"
SURFACE_CONTENT = "#FFFFFF"
SURFACE_SECTION = "#F8FAFC"
SURFACE_HOVER = "#F1F5F9"
SURFACE_SELECTED = "#EAF1FD"  # low-saturation selection, not a saturated blue row

# ── Borders ─────────────────────────────────────────────────────────
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
BORDER_SUBTLE = "#EDF1F6"

# ── Text ────────────────────────────────────────────────────────────
TEXT = "#0F172A"
TEXT_MUTED = "#64748B"
# Disabled text stays legible: 3.3:1 against SURFACE_SECTION by WCAG relative
# luminance. The previous #94A3B8 on a #CBD5E1 fill was effectively unreadable.
TEXT_DISABLED = "#808A9B"
TEXT_ON_PRIMARY = "#FFFFFF"

# ── Sidebar ─────────────────────────────────────────────────────────
SIDEBAR_BG = "#1E293B"
SIDEBAR_TEXT = "#CBD5E1"
SIDEBAR_TEXT_ACTIVE = "#FFFFFF"
SIDEBAR_HOVER = "#2D3E52"
SIDEBAR_ACTIVE_BG = "#27354A"
SIDEBAR_ACTIVE_INDICATOR = "#60A5FA"

# ── Status ──────────────────────────────────────────────────────────
# Every status pairs with words in the UI; colour is a secondary cue only.
STATUS_PENDING_BG = "#FEF3C7"
STATUS_PENDING_FG = "#B45309"
STATUS_CONFIRMED_BG = "#DCFCE7"
STATUS_CONFIRMED_FG = "#15803D"
STATUS_SKIPPED_BG = "#F1F5F9"
STATUS_SKIPPED_FG = "#5B6472"
STATUS_OVERDUE_BG = "#FEE2E2"
STATUS_OVERDUE_FG = "#DC2626"
STATUS_ARCHIVED_FG = "#7A8494"

WARNING_BG = "#FEF9C3"
WARNING_FG = "#B45309"
INFO_BG = "#DBEAFE"
INFO_FG = "#1E3A8A"

# ── Type scale (px) ─────────────────────────────────────────────────
FONT_BODY = 14
FONT_TABLE = 14
FONT_TABLE_HEADER = 13
FONT_HINT = 13
FONT_SECTION_TITLE = 16
FONT_PAGE_TITLE = 20
FONT_ERROR = 14

# ── Component heights (px) ──────────────────────────────────────────
INPUT_HEIGHT = 36
INPUT_HEIGHT_COMPACT = 32
BUTTON_HEIGHT = 36
BUTTON_HEIGHT_COMPACT = 30
ICON_BUTTON_SIZE = 32
ROW_HEIGHT_TEXT = 36
ROW_HEIGHT_EDITOR = 42

# ── Spacing (px) ────────────────────────────────────────────────────
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 20
SPACING_2XL = 24
SPACING_3XL = 32

# Outer margin for a page. Dense pages may use SPACING_XL, but a page must pick one
# of these two rather than inventing its own.
PAGE_MARGIN = 24
PAGE_MARGIN_DENSE = 20

# ── Type family ─────────────────────────────────────────────────────
# Traditional Chinese first. JhengHei UI carries the tighter UI metrics; plain
# JhengHei is the fallback on systems without it.
FONT_FAMILY = (
    '"Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans TC", '
    '"PingFang TC", sans-serif'
)

# ── Radius (px) ─────────────────────────────────────────────────────
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8

# ── Sidebar geometry (px) ───────────────────────────────────────────
SIDEBAR_EXPANDED_WIDTH = 220
SIDEBAR_EXPANDED_MAX_WIDTH = 240
# Wide enough to keep a 20px icon centred inside a 32px hit target, so collapsing
# preserves module identity instead of leaving a bare strip.
SIDEBAR_COLLAPSED_WIDTH = 56

# ── Icon sizes (px) ─────────────────────────────────────────────────
ICON_SIZE_SM = 14
ICON_SIZE_MD = 16
ICON_SIZE_LG = 20

# ── Button roles ────────────────────────────────────────────────────
ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "secondary"
ROLE_QUIET = "quiet"
ROLE_DANGER = "danger"
ROLE_DANGER_QUIET = "dangerQuiet"
ROLE_ICON = "icon"
ROLE_LINK = "link"

BUTTON_ROLES: frozenset[str] = frozenset(
    {
        ROLE_PRIMARY,
        ROLE_SECONDARY,
        ROLE_QUIET,
        ROLE_DANGER,
        ROLE_DANGER_QUIET,
        ROLE_ICON,
        ROLE_LINK,
    }
)

# Roles that must never carry a destructive action, and roles that must never be
# used for routine navigation or view controls. Tests assert both directions.
DESTRUCTIVE_ROLES: frozenset[str] = frozenset({ROLE_DANGER, ROLE_DANGER_QUIET})
