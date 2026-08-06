"""Button construction with an explicit action role.

A role is a Qt dynamic property read by the global stylesheet. Setting the property
on a widget that is already shown does not repaint it, so `set_button_role`
unpolishes and repolishes the widget — without that step a role assigned after
construction silently has no visual effect.

Icon-only buttons carry no label, so this module refuses to build one without a
tooltip and an accessible name.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton, QWidget

from .. import icons, tokens


class UnknownButtonRole(ValueError):
    """Raised when a role is not one of the seven defined roles."""


def set_button_role(button: QPushButton, role: str) -> QPushButton:
    """Assign an action role and repolish so the new styling takes effect."""
    if role not in tokens.BUTTON_ROLES:
        raise UnknownButtonRole(
            f"button role {role!r} is not defined; expected one of "
            f"{sorted(tokens.BUTTON_ROLES)}"
        )
    button.setProperty("role", role)
    style = button.style()
    if style is not None:
        style.unpolish(button)
        style.polish(button)
    button.update()
    return button


def button_role(button: QPushButton) -> str:
    """The button's role, defaulting to secondary when none was assigned."""
    value = button.property("role")
    return str(value) if value else tokens.ROLE_SECONDARY


def make_button(
    label: str,
    *,
    role: str = tokens.ROLE_SECONDARY,
    icon_role: str | None = None,
    tooltip: str = "",
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a labelled button with an explicit role."""
    button = QPushButton(label, parent)
    if icon_role is not None:
        colour = tokens.DANGER if role in tokens.DESTRUCTIVE_ROLES else tokens.TEXT
        if role == tokens.ROLE_PRIMARY:
            colour = tokens.TEXT_ON_PRIMARY
        button.setIcon(icons.icon(icon_role, colour))
        button.setIconSize(QSize(tokens.ICON_SIZE_MD, tokens.ICON_SIZE_MD))
    if tooltip:
        button.setToolTip(tooltip)
    return set_button_role(button, role)


def make_icon_button(
    icon_role: str,
    *,
    tooltip: str,
    accessible_name: str,
    role: str = tokens.ROLE_ICON,
    icon_color: str | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    """Create an icon-only button.

    `tooltip` and `accessible_name` are required: an icon-only control with neither
    is unusable by keyboard and screen-reader users alike. `icon_color` overrides the
    glyph colour for buttons that sit on a dark surface, such as the sidebar.
    """
    if not tooltip.strip():
        raise ValueError("icon-only buttons require a tooltip")
    if not accessible_name.strip():
        raise ValueError("icon-only buttons require an accessible name")

    button = QPushButton("", parent)
    if icon_color is not None:
        colour = icon_color
    else:
        colour = tokens.DANGER if role in tokens.DESTRUCTIVE_ROLES else tokens.TEXT
    button.setIcon(icons.icon(icon_role, colour))
    button.setIconSize(QSize(tokens.ICON_SIZE_LG, tokens.ICON_SIZE_LG))
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    button.setFixedSize(tokens.ICON_BUTTON_SIZE, tokens.ICON_BUTTON_SIZE)
    return set_button_role(button, role)
