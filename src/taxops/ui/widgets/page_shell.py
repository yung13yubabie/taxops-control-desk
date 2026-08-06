"""Shared page structure: a header and an action bar.

Two small widgets, deliberately not a framework. `PageHeader` separates the page
title from its actions so the title is no longer squeezed into a row of buttons.
`ActionBar` splits work actions from view tools and enforces the five-visible-action
ceiling by moving the rest into an overflow menu.

`FlowLayout` wrapped a wall of peer buttons onto more lines; it never established an
order. These widgets replace it as a toolbar. FlowLayout remains appropriate for tags
and chips.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons, tokens
from .buttons import make_icon_button, set_button_role

# A page may show this many actions before the rest must go into 更多.
MAX_VISIBLE_ACTIONS = 5


class ActionBarOverflowError(RuntimeError):
    """Raised when more actions are made visible than the ceiling allows."""


class PageHeader(QWidget):
    """Page title on the left, at most one primary action on the right."""

    def __init__(
        self,
        title: str,
        *,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACING_MD)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        text_column.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))
        self.subtitle_label.setWordWrap(True)
        text_column.addWidget(self.subtitle_label)

        row.addLayout(text_column)
        row.addStretch(1)

        self._action_row = QHBoxLayout()
        self._action_row.setContentsMargins(0, 0, 0, 0)
        self._action_row.setSpacing(tokens.SPACING_SM)
        row.addLayout(self._action_row)

        self._actions: list[QPushButton] = []

    def add_action(self, button: QPushButton, *, role: str | None = None) -> QPushButton:
        """Place an action in the header. At most one may be primary."""
        if role is not None:
            set_button_role(button, role)
        if button.property("role") == tokens.ROLE_PRIMARY:
            existing = [
                b for b in self._actions if b.property("role") == tokens.ROLE_PRIMARY
            ]
            if existing:
                raise ActionBarOverflowError(
                    f"header already has a primary action ({existing[0].text()!r}); "
                    f"{button.text()!r} must be secondary or move to the action bar"
                )
        self._actions.append(button)
        self._action_row.addWidget(button)
        return button

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def actions_visible(self) -> int:
        return len(self._actions)


class ActionBar(QWidget):
    """Work actions on the left, view tools and overflow on the right.

    Filters, search, import, and column settings are tools. Creating, running, and
    confirming are work. Keeping them on opposite sides is what makes a page
    scannable without reading every label.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActionBar")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACING_SM)

        self._work_row = QHBoxLayout()
        self._work_row.setContentsMargins(0, 0, 0, 0)
        self._work_row.setSpacing(tokens.SPACING_SM)
        row.addLayout(self._work_row)

        row.addStretch(1)

        self._tool_row = QHBoxLayout()
        self._tool_row.setContentsMargins(0, 0, 0, 0)
        self._tool_row.setSpacing(tokens.SPACING_SM)
        row.addLayout(self._tool_row)

        self._visible: list[QPushButton] = []
        self._overflow_button: QPushButton | None = None
        self._overflow_menu: QMenu | None = None

    # ── Visible actions ─────────────────────────────────────────────

    def add_leading_widget(self, widget: QWidget, *, stretch: int = 0) -> QWidget:
        """Place a non-action widget at the start of the bar, such as a search box.

        Does not count against the action ceiling: a search field is an input, not one
        of the page's five actions.
        """
        self._work_row.addWidget(widget, stretch)
        return widget

    def add_work_action(
        self, button: QPushButton, *, role: str = tokens.ROLE_SECONDARY
    ) -> QPushButton:
        """Add an action that advances the user's task."""
        set_button_role(button, role)
        self._register_visible(button)
        self._work_row.addWidget(button)
        return button

    def add_tool_action(
        self, button: QPushButton, *, role: str = tokens.ROLE_QUIET
    ) -> QPushButton:
        """Add a view control: filter, import, column settings, refresh."""
        set_button_role(button, role)
        self._register_visible(button)
        self._tool_row.addWidget(button)
        return button

    def add_tool_icon(
        self, icon_role: str, *, tooltip: str, accessible_name: str
    ) -> QPushButton:
        """Add an icon-only view control, such as refresh."""
        button = make_icon_button(
            icon_role, tooltip=tooltip, accessible_name=accessible_name
        )
        self._register_visible(button)
        self._tool_row.addWidget(button)
        return button

    def _register_visible(self, button: QPushButton) -> None:
        if len(self._visible) >= MAX_VISIBLE_ACTIONS:
            raise ActionBarOverflowError(
                f"action bar already shows {MAX_VISIBLE_ACTIONS} actions; "
                f"{button.text() or button.accessibleName()!r} belongs in the "
                f"overflow menu"
            )
        self._visible.append(button)

    # ── Overflow ────────────────────────────────────────────────────

    def add_overflow_action(
        self, text: str, callback: Callable[[], None], *, icon_role: str | None = None
    ) -> None:
        """Add a low-frequency action to the 更多 menu."""
        menu = self._ensure_overflow()
        action = menu.addAction(text)
        if icon_role is not None:
            action.setIcon(icons.icon(icon_role))
        action.triggered.connect(lambda _checked=False: callback())

    def add_overflow_separator(self) -> None:
        self._ensure_overflow().addSeparator()

    def _ensure_overflow(self) -> QMenu:
        if self._overflow_menu is None:
            self._overflow_menu = QMenu(self)
            button = make_icon_button(
                "overflow", tooltip="更多操作", accessible_name="更多操作"
            )
            button.setMenu(self._overflow_menu)
            self._overflow_button = button
            # The overflow button is chrome, not one of the five actions.
            self._tool_row.addWidget(button)
        return self._overflow_menu

    @property
    def overflow_button(self) -> QPushButton | None:
        return self._overflow_button

    def overflow_action_texts(self) -> tuple[str, ...]:
        if self._overflow_menu is None:
            return ()
        return tuple(a.text() for a in self._overflow_menu.actions() if not a.isSeparator())

    def visible_action_count(self) -> int:
        """Visible actions, excluding the overflow button itself."""
        return len(self._visible)

    def visible_actions(self) -> tuple[QPushButton, ...]:
        return tuple(self._visible)


def build_page_layout(
    header: PageHeader,
    *,
    action_bar: ActionBar | None = None,
    body: QWidget | None = None,
    dense: bool = False,
) -> QVBoxLayout:
    """Assemble the standard vertical page layout with one consistent margin."""
    margin = tokens.PAGE_MARGIN_DENSE if dense else tokens.PAGE_MARGIN
    layout = QVBoxLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(tokens.SPACING_LG)
    layout.addWidget(header)
    if action_bar is not None:
        layout.addWidget(action_bar)
    if body is not None:
        layout.addWidget(body, stretch=1)
    return layout


def elided_label(text: str, *, width: int, parent: QWidget | None = None) -> QLabel:
    """A label that elides instead of forcing its container wider."""
    label = QLabel(text, parent)
    label.setMaximumWidth(width)
    label.setToolTip(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def icon_size() -> QSize:
    return QSize(tokens.ICON_SIZE_MD, tokens.ICON_SIZE_MD)


__all__ = [
    "MAX_VISIBLE_ACTIONS",
    "ActionBar",
    "ActionBarOverflowError",
    "PageHeader",
    "build_page_layout",
    "elided_label",
    "icon_size",
]
