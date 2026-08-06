"""Inline SVG icon set for the desktop surface.

Every icon lives in this module as an SVG string, so the set ships inside the
application with no filesystem lookup, no `.qrc` build step, and no network
dependency. `PySide6.QtSvg` is already declared in `TaxOpsControlDesk.spec`, so the
frozen build renders the same icons as the source tree.

The previous implementation mapped roles onto `QStyle.StandardPixmap` and returned
an information icon for anything unmapped, which meant a typo produced a plausible
but wrong glyph. `icon()` raises `UnknownIconRole` instead: a missing role is a
programming error and must fail where it can be seen.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

from . import tokens

_STROKE_WIDTH = "1.5"

# Rendered at these sizes so 100%, 125%, and 150% Windows scaling each get a
# natively sized pixmap instead of a blurred upscale.
_RENDER_SIZES: tuple[int, ...] = (16, 20, 24, 32, 48)


class UnknownIconRole(KeyError):
    """Raised when an icon role has no mapping.

    Deliberately loud: a silent fallback shows the wrong glyph to the user and
    hides the mistake from tests.
    """


# Geometry is drawn on a 16x16 grid with a single stroke weight so the set reads as
# one family. `{c}` is substituted with the requested colour.
_PATHS: dict[str, str] = {
    "add": '<path d="M8 3v10M3 8h10"/>',
    "edit": '<path d="M3 13h2.2l7.3-7.3-2.2-2.2L3 10.8z"/><path d="M10.6 3.9l2.2 2.2"/>',
    "delete": (
        '<path d="M2.8 4.8h10.4"/>'
        '<path d="M6.4 4.8V3.2h3.2v1.6"/>'
        '<path d="M4.4 4.8l.6 8.2h6l.6-8.2"/>'
        '<path d="M6.8 7.2v3.4M9.2 7.2v3.4"/>'
    ),
    "refresh": (
        '<path d="M13 8A5 5 0 1 1 4.1 4.9"/>'
        '<path d="M3.6 2.2v3.4h3.4"/>'
    ),
    "search": (
        '<circle cx="7" cy="7" r="4.2"/>'
        '<path d="M10.2 10.2L13.6 13.6"/>'
    ),
    "clear": '<path d="M4.6 4.6l6.8 6.8M11.4 4.6l-6.8 6.8"/>',
    "close": '<path d="M4 4l8 8M12 4l-8 8"/>',
    "filter": '<path d="M2.6 3.6h10.8L9.2 8.5v4.4l-2.4-1.3V8.5z"/>',
    "columns": (
        '<path d="M2.6 3.4h10.8v9.2H2.6z"/>'
        '<path d="M6.2 3.4v9.2M9.8 3.4v9.2"/>'
    ),
    "overflow": (
        '<circle cx="4" cy="8" r="1.15" fill="{c}" stroke="none"/>'
        '<circle cx="8" cy="8" r="1.15" fill="{c}" stroke="none"/>'
        '<circle cx="12" cy="8" r="1.15" fill="{c}" stroke="none"/>'
    ),
    "chevron-left": '<path d="M10 3.4L5.4 8l4.6 4.6"/>',
    "chevron-right": '<path d="M6 3.4L10.6 8 6 12.6"/>',
    "chevron-down": '<path d="M3.4 6L8 10.6 12.6 6"/>',
    "upload": (
        '<path d="M2.8 12.8h10.4"/>'
        '<path d="M8 10.4V3.2"/>'
        '<path d="M5.2 6L8 3.2 10.8 6"/>'
    ),
    "export": (
        '<path d="M2.8 12.8h10.4"/>'
        '<path d="M8 3.2v7.2"/>'
        '<path d="M5.2 7.6L8 10.4l2.8-2.8"/>'
    ),
    "paste": (
        '<path d="M3.8 4.2h8.4v8.8H3.8z"/>'
        '<path d="M6 4.2V2.9h4v1.3"/>'
        '<path d="M6.2 7.6h3.6M6.2 10h3.6"/>'
    ),
    "open": (
        '<path d="M9.2 3.2h3.6v3.6"/>'
        '<path d="M12.8 3.2L7.4 8.6"/>'
        '<path d="M11.2 9.4v3.4H3.2V4.8h3.4"/>'
    ),
    "archive": (
        '<path d="M2.6 3.8h10.8v2.6H2.6z"/>'
        '<path d="M3.7 6.4v6.2h8.6V6.4"/>'
        '<path d="M6.4 8.8h3.2"/>'
    ),
    "restore": (
        '<path d="M3 8A5 5 0 1 0 11.9 4.9"/>'
        '<path d="M12.4 2.2v3.4H9"/>'
    ),
    "save": (
        '<path d="M3.2 3.2h7.2l2.4 2.4v7.2H3.2z"/>'
        '<path d="M5.6 3.2v3.2h4.4V3.2"/>'
        '<path d="M5.6 12.8V9.4h4.8v3.4"/>'
    ),
    "warning": (
        '<path d="M8 2.8l5.4 9.6H2.6z"/>'
        '<path d="M8 6.4v2.8"/>'
        '<circle cx="8" cy="11" r="0.7" fill="{c}" stroke="none"/>'
    ),
    "info": (
        '<circle cx="8" cy="8" r="5.4"/>'
        '<path d="M8 7.4v3.4"/>'
        '<circle cx="8" cy="5.3" r="0.7" fill="{c}" stroke="none"/>'
    ),
    "check": '<path d="M3.2 8.4l3.2 3.2 6.4-7"/>',
    "complete": (
        '<circle cx="8" cy="8" r="5.4"/>'
        '<path d="M5.4 8.2l2 2 3.4-4"/>'
    ),
    # 試算 — a calculator, not the information glyph the old map returned.
    "trial": (
        '<path d="M4 2.6h8v10.8H4z"/>'
        '<path d="M5.6 4.4h4.8v2.2H5.6z"/>'
        '<circle cx="6" cy="8.8" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="8" cy="8.8" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="10" cy="8.8" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="6" cy="11.2" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="8" cy="11.2" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="10" cy="11.2" r="0.65" fill="{c}" stroke="none"/>'
    ),
    # 批次 — stacked layers, conveying "many records at once".
    "bulk": (
        '<path d="M8 2.6l5.2 2.6L8 7.8 2.8 5.2z"/>'
        '<path d="M2.8 8.1L8 10.7l5.2-2.6"/>'
        '<path d="M2.8 10.9L8 13.5l5.2-2.6"/>'
    ),
    # ── Navigation glyphs ───────────────────────────────────────────
    # One per sidebar module, so collapsing the sidebar keeps module identity
    # instead of leaving an unlabelled strip.
    "nav-clients": (
        '<circle cx="6.2" cy="5.6" r="2.4"/>'
        '<path d="M2.4 13c0-2.3 1.7-3.6 3.8-3.6S10 10.7 10 13"/>'
        '<path d="M10.8 4.2a2.2 2.2 0 010 4.1"/>'
        '<path d="M11.6 9.8c1.3.5 2 1.6 2 3.2"/>'
    ),
    "nav-calendar": (
        '<path d="M2.8 4.4h10.4v8.8H2.8z"/>'
        '<path d="M2.8 7h10.4"/>'
        '<path d="M5.6 2.8v2.4M10.4 2.8v2.4"/>'
        '<circle cx="6" cy="9.6" r="0.65" fill="{c}" stroke="none"/>'
        '<circle cx="8.6" cy="9.6" r="0.65" fill="{c}" stroke="none"/>'
    ),
    "nav-engagements": (
        '<path d="M2.6 5.4h10.8v7.4H2.6z"/>'
        '<path d="M6.2 5.4V3.8h3.6v1.6"/>'
        '<path d="M2.6 8.6h10.8"/>'
    ),
    "nav-tasks": (
        '<path d="M3 4.4l1.4 1.4 2.2-2.2"/>'
        '<path d="M3 9.6L4.4 11l2.2-2.2"/>'
        '<path d="M8.6 4.6h4.6M8.6 10h4.6"/>'
    ),
    "nav-work-records": (
        '<circle cx="8" cy="8" r="5.4"/>'
        '<path d="M8 4.8V8l2.4 1.6"/>'
    ),
    "nav-templates": (
        '<path d="M3.4 2.8h6l3.2 3.2v7.2H3.4z"/>'
        '<path d="M9.2 2.8V6h3.2"/>'
        '<path d="M5.6 8.4h4.4M5.6 10.6h3"/>'
    ),
    "nav-registry": (
        '<path d="M3.2 13V4.2L8 2.4l4.8 1.8V13"/>'
        '<path d="M3.2 13h9.6"/>'
        '<path d="M6.2 6.6h1.2M8.6 6.6h1.2M6.2 9h1.2M8.6 9h1.2"/>'
    ),
    "nav-attachments": (
        '<path d="M11.4 7L7 11.4a2.6 2.6 0 01-3.7-3.7l5-5a1.8 1.8 0 012.5 2.5l-5 5a1 1 0 01-1.4-1.4l4.4-4.4"/>'
    ),
    "nav-folders": (
        '<path d="M2.6 12.6V4.2h4l1.4 1.8h5.4v6.6z"/>'
    ),
    "nav-billing": (
        '<path d="M4 2.8h8v10.4l-2-1.3-2 1.3-2-1.3-2 1.3z"/>'
        '<path d="M6 5.6h4M6 8h4"/>'
    ),
    "nav-settings": (
        '<circle cx="8" cy="8" r="2.1"/>'
        '<path d="M8 2.4v1.7M8 11.9v1.7M3.6 8H2M14 8h-1.6"/>'
        '<path d="M4.9 4.9L3.8 3.8M12.2 12.2l-1.1-1.1M11.1 4.9l1.1-1.1M3.8 12.2l1.1-1.1"/>'
    ),
    # A calendar with today's cell marked, for "jump to today" affordances.
    "today": (
        '<path d="M2.8 4.4h10.4v8.8H2.8z"/>'
        '<path d="M2.8 7h10.4"/>'
        '<path d="M5.6 2.8v2.4M10.4 2.8v2.4"/>'
        '<circle cx="8" cy="10" r="1.5" fill="{c}" stroke="none"/>'
    ),
}

# Aliases keep two naming styles working: the legacy names already in call sites, and
# the unprefixed domain names used by the design brief. `new` predates `add`, and
# `back` is the navigation reading of `chevron-left`.
_ALIASES: dict[str, str] = {
    # Legacy call sites
    "new": "add",
    "back": "chevron-left",
    # Domain names without the nav- prefix
    "calendar": "nav-calendar",
    "client": "nav-clients",
    "engagement": "nav-engagements",
    "task": "nav-tasks",
    "workflow": "nav-work-records",
    "template": "nav-templates",
    "calculator": "trial",
    "attachment": "nav-attachments",
    "folder": "nav-folders",
    "billing": "nav-billing",
    "settings": "nav-settings",
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
    'fill="none" stroke="{c}" stroke-width="{w}" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

_cache: dict[tuple[str, str], QIcon] = {}


def available_roles() -> frozenset[str]:
    """Every role that resolves to an icon, aliases included."""
    return frozenset(_PATHS) | frozenset(_ALIASES)


def resolve_role(role: str) -> str:
    """Return the canonical role name, raising `UnknownIconRole` if unmapped."""
    canonical = _ALIASES.get(role, role)
    if canonical not in _PATHS:
        raise UnknownIconRole(
            f"icon role {role!r} has no mapping; add it to icons._PATHS "
            f"instead of relying on a fallback glyph"
        )
    return canonical


def svg_source(role: str, color: str = tokens.TEXT) -> str:
    """The raw SVG document for a role, useful for tests and for QSS assets."""
    canonical = resolve_role(role)
    body = _PATHS[canonical].replace("{c}", color)
    return _SVG_TEMPLATE.format(c=color, w=_STROKE_WIDTH, body=body)


def icon(role: str, color: str = tokens.TEXT) -> QIcon:
    """Return the icon for `role`, rendered at every scaling-relevant size.

    Raises `UnknownIconRole` for an unmapped role. Requires a live QApplication
    only insofar as QPixmap does.
    """
    canonical = resolve_role(role)
    key = (canonical, color)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    from PySide6.QtSvg import QSvgRenderer

    source = QByteArray(svg_source(canonical, color).encode("utf-8"))
    renderer = QSvgRenderer(source)
    built = QIcon()
    for size in _RENDER_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        built.addPixmap(pixmap)
    _cache[key] = built
    return built


def clear_cache() -> None:
    """Drop rendered icons. Used by tests that switch colours or styles."""
    _cache.clear()
