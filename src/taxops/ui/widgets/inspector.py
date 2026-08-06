"""Reusable detail panel for the selected row.

Replaces two habits this UI had: repeating a selected row as plain text underneath
the table, and opening a dialog just to read a record. Contextual actions live here
too, so a page no longer needs a row of disabled buttons for actions that require a
selection.

Sections are rebuilt on each selection. `clear()` returns the panel to its
placeholder, which is what a page must call when the selection is dropped.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import tokens

_DEFAULT_PLACEHOLDER = "選取左側項目後，可在此查看詳細資料。"


class Inspector(QFrame):
    """A titled detail panel with sections, fields, and contextual actions."""

    def __init__(
        self,
        *,
        placeholder: str = _DEFAULT_PLACEHOLDER,
        min_width: int = 300,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(min_width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACING_LG, tokens.SPACING_LG, tokens.SPACING_LG, tokens.SPACING_LG
        )
        outer.setSpacing(tokens.SPACING_MD)

        self.title_label = QLabel("")
        self.title_label.setObjectName("InspectorTitle")
        self.title_label.setWordWrap(True)
        outer.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("InspectorLabel")
        self.subtitle_label.setWordWrap(True)
        outer.addWidget(self.subtitle_label)

        self._placeholder_label = QLabel(placeholder)
        self._placeholder_label.setObjectName("InspectorPlaceholder")
        self._placeholder_label.setWordWrap(True)
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._placeholder_label, stretch=1)

        # One scroll region. The panel scrolls; its fields do not scroll separately.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(tokens.SPACING_MD)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, stretch=1)

        self._action_row = QHBoxLayout()
        self._action_row.setContentsMargins(0, 0, 0, 0)
        self._action_row.setSpacing(tokens.SPACING_SM)
        outer.addLayout(self._action_row)

        self._actions: list[QPushButton] = []
        self._current_section: QVBoxLayout | None = None
        # Tracked explicitly: Qt's isVisible() is False for any widget whose ancestors
        # are not shown yet, so it cannot answer "is the panel in placeholder mode".
        self._showing_placeholder = True
        self.clear()

    # ── Content ─────────────────────────────────────────────────────

    def set_title(self, title: str, *, subtitle: str = "") -> None:
        """Show the panel and set its heading."""
        self.title_label.setText(title)
        self.title_label.setVisible(bool(title))
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        self._placeholder_label.setVisible(False)
        self._scroll.setVisible(True)
        self._showing_placeholder = False
        self._set_actions_visible(True)

    def add_section(self, name: str) -> None:
        """Start a labelled group. Sections separate by spacing, not by borders."""
        label = QLabel(name)
        label.setObjectName("InspectorSection")
        self._content_layout.addWidget(label)
        holder = QVBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.setSpacing(tokens.SPACING_XS)
        self._content_layout.addLayout(holder)
        self._current_section = holder

    def add_field(self, label: str, value: str, *, multiline: bool = False) -> None:
        """Add a label-and-value pair to the current section.

        `multiline` keeps newlines exactly as stored, which client notes require.
        """
        target = self._current_section
        if target is None:
            self.add_section("")
            target = self._current_section
        assert target is not None

        caption = QLabel(label)
        caption.setObjectName("InspectorLabel")
        target.addWidget(caption)

        text = value if value else "—"
        body = QLabel(text)
        body.setObjectName("InspectorValue")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if multiline:
            # Qt collapses runs of whitespace in rich text; plain text preserves them.
            body.setTextFormat(Qt.TextFormat.PlainText)
        target.addWidget(body)

    def add_note(self, text: str) -> None:
        """Add a standalone explanatory line, such as a derived-value caveat."""
        label = QLabel(text)
        label.setObjectName("InspectorLabel")
        label.setWordWrap(True)
        self._content_layout.addWidget(label)

    def add_widget(self, widget: QWidget) -> QWidget:
        """Place a caller-owned widget in the panel.

        For content a label cannot carry — a small read-only table, or a scrollable
        notes box that must keep its exact newlines. The widget is reparented, so a
        caller that keeps a reference must re-add it after `begin_update`.
        """
        self._content_layout.addWidget(widget)
        return widget

    # ── Actions ─────────────────────────────────────────────────────

    def add_action(self, button: QPushButton) -> QPushButton:
        """Add a contextual action. These exist only while a row is selected.

        The button inherits the panel's current state, so one registered during page
        construction stays hidden until a selection arrives instead of appearing as
        yet another action with nothing to act on.
        """
        self._actions.append(button)
        self._action_row.addWidget(button)
        button.setVisible(not self._showing_placeholder)
        return button

    def clear_actions(self) -> None:
        while self._action_row.count():
            item = self._action_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._actions.clear()

    def _set_actions_visible(self, visible: bool) -> None:
        for button in self._actions:
            button.setVisible(visible)

    # ── Reset ───────────────────────────────────────────────────────

    def clear(self) -> None:
        """Return to the placeholder. Call this when the selection is dropped."""
        self.title_label.setText("")
        self.title_label.setVisible(False)
        self.subtitle_label.setText("")
        self.subtitle_label.setVisible(False)
        self._clear_content()
        self._scroll.setVisible(False)
        self._placeholder_label.setVisible(True)
        self._showing_placeholder = True
        self._set_actions_visible(False)

    def _clear_content(self) -> None:
        self._current_section = None
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                continue
            child = item.layout()
            if child is not None:
                _drain_layout(child)

    def begin_update(self) -> None:
        """Discard existing sections before repopulating for a new selection."""
        self._clear_content()

    # ── Introspection for tests ─────────────────────────────────────

    def is_showing_placeholder(self) -> bool:
        return self._showing_placeholder

    def actions_are_exposed(self) -> bool:
        """Whether contextual actions would be visible if the panel were shown."""
        return any(button.isVisibleTo(self) for button in self._actions)

    def field_values(self) -> dict[str, str]:
        """Every label-and-value pair currently shown, in insertion order."""
        values: dict[str, str] = {}
        pending_label: str | None = None
        for label in self._content.findChildren(QLabel):
            name = label.objectName()
            if name == "InspectorLabel":
                pending_label = label.text()
            elif name == "InspectorValue" and pending_label is not None:
                values[pending_label] = label.text()
                pending_label = None
        return values

    def section_names(self) -> tuple[str, ...]:
        return tuple(
            label.text()
            for label in self._content.findChildren(QLabel)
            if label.objectName() == "InspectorSection" and label.text()
        )

    def action_texts(self) -> tuple[str, ...]:
        return tuple(button.text() for button in self._actions)


def _drain_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            continue
        child = item.layout()
        if child is not None:
            _drain_layout(child)


__all__ = ["Inspector"]
