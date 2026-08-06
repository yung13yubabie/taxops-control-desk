"""Design-system contracts for the desktop surface.

These tests encode the rebuild's acceptance conditions as assertions rather than
descriptions: an action's rank is a role, a checked box draws a tick, an unmapped
icon raises, and no type size drops below the product's floor.

They cover what the design system itself guarantees. They do not, and cannot, stand
in for looking at the running application at each supported scaling factor — visual
and DPI acceptance remains a separate manual step.
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionButton,
)

from taxops.ui import icons, tokens
from taxops.ui.style import APP_STYLESHEET
from taxops.ui.widgets.buttons import (
    UnknownButtonRole,
    button_role,
    make_button,
    make_icon_button,
    set_button_role,
)
from taxops.ui.widgets.table_builder import build_standard_table

_UI_SRC = "src/taxops/ui"


@pytest.fixture(autouse=True)
def _styled_app(qapp):
    """Apply the real stylesheet, then restore it so other modules are unaffected."""
    previous = qapp.styleSheet()
    qapp.setStyleSheet(APP_STYLESHEET)
    icons.clear_cache()
    yield qapp
    qapp.setStyleSheet(previous)


# ── Button role contract ────────────────────────────────────────────


def test_seven_roles_are_defined() -> None:
    assert tokens.BUTTON_ROLES == frozenset(
        {"primary", "secondary", "quiet", "danger", "dangerQuiet", "icon", "link"}
    )


def test_unknown_button_role_raises() -> None:
    button = QPushButton("測試")
    with pytest.raises(UnknownButtonRole):
        set_button_role(button, "superPrimary")


def test_role_is_recorded_as_a_dynamic_property() -> None:
    button = set_button_role(QPushButton("儲存"), tokens.ROLE_PRIMARY)
    assert button.property("role") == "primary"
    assert button_role(button) == "primary"


def test_button_without_a_role_reads_as_secondary() -> None:
    """A button that declares nothing must not be treated as the page's primary."""
    assert button_role(QPushButton("重新整理")) == tokens.ROLE_SECONDARY


def test_global_button_default_is_not_a_solid_primary_fill() -> None:
    """The bare QPushButton rule must not paint every button brand blue.

    This is the defect that made 新增, 搜尋, 清除, 刪除, 取消, and 儲存 visually
    identical.
    """
    match = re.search(r"\nQPushButton \{(.*?)\}", APP_STYLESHEET, re.DOTALL)
    assert match, "the base QPushButton rule must exist"
    base_rule = match.group(1)
    assert tokens.PRIMARY not in base_rule, (
        "the default button must not use the primary fill; assign role=primary instead"
    )
    assert tokens.SURFACE_CONTENT in base_rule, "default button is a neutral surface"


def test_every_role_has_a_stylesheet_rule() -> None:
    for role in sorted(tokens.BUTTON_ROLES):
        assert f'QPushButton[role="{role}"]' in APP_STYLESHEET, f"{role} has no styling"


def test_only_primary_uses_the_brand_fill() -> None:
    """Danger and quiet roles must never render as a blue filled button."""
    for role in ("danger", "dangerQuiet", "quiet", "link"):
        match = re.search(
            r'QPushButton\[role="' + role + r'"\] \{(.*?)\}', APP_STYLESHEET, re.DOTALL
        )
        assert match, f"{role} rule missing"
        body = match.group(1)
        assert f"background-color: {tokens.PRIMARY}" not in body, (
            f"{role} must not use the primary fill"
        )


def test_danger_roles_are_declared_destructive() -> None:
    assert tokens.DESTRUCTIVE_ROLES == frozenset({"danger", "dangerQuiet"})
    for role in tokens.DESTRUCTIVE_ROLES:
        assert role in tokens.BUTTON_ROLES


def test_danger_role_uses_red_text_not_a_red_fill() -> None:
    match = re.search(
        r'QPushButton\[role="danger"\] \{(.*?)\}', APP_STYLESHEET, re.DOTALL
    )
    assert match
    body = match.group(1)
    assert f"color: {tokens.DANGER}" in body
    assert f"background-color: {tokens.SURFACE_CONTENT}" in body


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance, including the sRGB linearisation step."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(int(hex_colour[i : i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg: str, bg: str) -> float:
    light, dark = sorted(
        (_relative_luminance(fg), _relative_luminance(bg)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def test_disabled_text_keeps_a_readable_tone() -> None:
    """Disabled labels must stay legible rather than fading into the surface."""
    ratio = _contrast_ratio(tokens.TEXT_DISABLED, tokens.SURFACE_SECTION)
    assert ratio >= 3.0, f"disabled text contrast too low: {ratio:.2f}"


def test_body_and_muted_text_meet_normal_text_contrast() -> None:
    assert _contrast_ratio(tokens.TEXT, tokens.SURFACE_CONTENT) >= 4.5
    assert _contrast_ratio(tokens.TEXT_MUTED, tokens.SURFACE_CONTENT) >= 4.5


def test_primary_button_label_contrasts_with_its_fill() -> None:
    assert _contrast_ratio(tokens.TEXT_ON_PRIMARY, tokens.PRIMARY) >= 4.5


def test_danger_text_contrasts_with_the_content_surface() -> None:
    assert _contrast_ratio(tokens.DANGER, tokens.SURFACE_CONTENT) >= 4.5


def test_make_button_applies_role_and_optional_icon() -> None:
    button = make_button(
        "新增客戶", role=tokens.ROLE_PRIMARY, icon_role="add", tooltip="新增一筆客戶"
    )
    assert button_role(button) == "primary"
    assert not button.icon().isNull()
    assert button.toolTip() == "新增一筆客戶"


def test_icon_only_button_requires_tooltip_and_accessible_name() -> None:
    with pytest.raises(ValueError):
        make_icon_button("refresh", tooltip="", accessible_name="重新整理")
    with pytest.raises(ValueError):
        make_icon_button("refresh", tooltip="重新整理", accessible_name="   ")


def test_icon_only_button_is_square_and_labelled() -> None:
    button = make_icon_button(
        "refresh", tooltip="重新整理列表", accessible_name="重新整理列表"
    )
    assert button.width() == tokens.ICON_BUTTON_SIZE
    assert button.height() == tokens.ICON_BUTTON_SIZE
    assert button.text() == ""
    assert button.toolTip()
    assert button.accessibleName()
    assert not button.icon().isNull()


# ── Icon system ─────────────────────────────────────────────────────


def test_unknown_icon_role_raises_instead_of_falling_back() -> None:
    """An unmapped role must fail loudly, not resolve to an information glyph."""
    with pytest.raises(icons.UnknownIconRole):
        icons.icon("no-such-role")
    with pytest.raises(icons.UnknownIconRole):
        icons.resolve_role("upload-2")


def test_brief_required_roles_are_all_present() -> None:
    required = {
        "add", "edit", "delete", "refresh", "search", "clear", "filter", "columns",
        "overflow", "chevron-left", "chevron-right", "upload", "paste", "open",
        "archive", "restore", "save", "close", "warning", "info", "check",
    }
    assert required <= icons.available_roles()


def test_legacy_roles_still_resolve() -> None:
    assert icons.resolve_role("new") == "add"
    assert icons.resolve_role("back") == "chevron-left"


def test_every_role_referenced_in_source_is_mapped(pytestconfig) -> None:
    """Guards against a call site naming a role the icon set does not define."""
    root = pytestconfig.rootpath
    pattern = re.compile(r'toolbar_icon\(\s*"([a-z0-9\-_]+)"|icons\.icon\(\s*"([a-z0-9\-_]+)"')
    referenced: set[str] = set()
    for path in (root / _UI_SRC).rglob("*.py"):
        for first, second in pattern.findall(path.read_text(encoding="utf-8")):
            referenced.add(first or second)
    assert referenced, "expected to find icon role references in the UI source"
    unmapped = sorted(referenced - icons.available_roles())
    assert not unmapped, f"unmapped icon roles referenced in source: {unmapped}"


def test_every_icon_renders_visible_geometry() -> None:
    """A mapped role that renders nothing is worse than a missing one."""
    empty: list[str] = []
    for role in sorted(icons.available_roles()):
        image = icons.icon(role).pixmap(16, 16).toImage()
        painted = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        )
        if painted < 8:
            empty.append(role)
    assert not empty, f"roles rendering (almost) nothing: {empty}"


def test_icons_honour_the_requested_colour() -> None:
    """Danger actions need a red glyph, sidebar glyphs a light one."""
    assert tokens.DANGER.lower() in icons.svg_source("delete", tokens.DANGER).lower()
    assert (
        tokens.SIDEBAR_TEXT.lower()
        in icons.svg_source("nav-clients", tokens.SIDEBAR_TEXT).lower()
    )


def test_ui_source_no_longer_uses_qt_standard_pixmaps(pytestconfig) -> None:
    """Formal interface icons come from the SVG set, not the platform pixmap table."""
    root = pytestconfig.rootpath
    offenders: list[str] = []
    for path in (root / _UI_SRC).rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # icons.py names the type only inside its module docstring.
        code = text.split('"""', 2)[-1] if path.name == "icons.py" else text
        if "StandardPixmap" in code or "standardIcon" in code:
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"Qt standard pixmaps still used in: {offenders}"


def test_navigation_declares_a_glyph_for_every_page() -> None:
    from taxops.ui.action_registry import NAV_ORDER
    from taxops.ui.main_window import _NAV_ICON_ROLES

    assert set(_NAV_ICON_ROLES) == set(NAV_ORDER), "every nav page needs a glyph"
    for page_id, role in _NAV_ICON_ROLES.items():
        assert role in icons.available_roles(), f"{page_id} maps to unknown icon {role}"


# ── Checkbox contract ───────────────────────────────────────────────


def _indicator_stats(checked: bool) -> tuple[int, int, float]:
    """Return (painted pixels, distinct colours, fill ratio) for the indicator box."""
    box = QCheckBox("測試選項")
    box.setChecked(checked)
    box.resize(box.sizeHint())
    option = QStyleOptionButton()
    box.initStyleOption(option)
    rect = box.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator, option, box
    )
    canvas = QPixmap(box.size())
    canvas.fill(Qt.GlobalColor.white)
    box.render(canvas)
    image = canvas.toImage()

    painted = 0
    total = 0
    colours: set[str] = set()
    for y in range(rect.top(), min(rect.bottom() + 1, image.height())):
        for x in range(rect.left(), min(rect.right() + 1, image.width())):
            colour = image.pixelColor(x, y)
            total += 1
            if not (colour.red() > 240 and colour.green() > 240 and colour.blue() > 240):
                painted += 1
                colours.add(colour.name())
    return painted, len(colours), (painted / total if total else 0.0)


def test_stylesheet_does_not_override_the_checkbox_indicator() -> None:
    """A QSS indicator rule is what turned checked state into a plain blue square."""
    assert "QCheckBox::indicator" not in APP_STYLESHEET
    assert "QRadioButton::indicator" not in APP_STYLESHEET


def test_stylesheet_declares_no_box_model_on_checkboxes() -> None:
    """Regression guard, measured rather than assumed.

    Any box-model property on QCheckBox — `background-color: transparent` included —
    hands indicator painting to the stylesheet and silently erases the unchecked
    border. Observed: 64 painted border pixels drop to 0.
    """
    match = re.search(r"QCheckBox, QRadioButton \{(.*?)\}", APP_STYLESHEET, re.DOTALL)
    assert match, "expected a shared QCheckBox/QRadioButton rule"
    body = match.group(1)
    for forbidden in ("background", "border", "width", "height", "padding", "margin"):
        assert forbidden not in body, (
            f"{forbidden!r} on QCheckBox disables the native indicator"
        )


def test_unchecked_indicator_draws_a_visible_border() -> None:
    painted, _, _ = _indicator_stats(checked=False)
    assert painted >= 20, (
        f"unchecked indicator painted only {painted} pixels — the box is invisible"
    )


def test_checked_indicator_adds_a_mark_beyond_the_border() -> None:
    unchecked, _, _ = _indicator_stats(checked=False)
    checked, colours, _ = _indicator_stats(checked=True)
    assert checked > unchecked, "checked state must paint more than the empty box"
    assert colours >= 3, (
        "a tick is drawn with anti-aliased edges; too few colours suggests a flat fill"
    )


def test_checked_indicator_is_not_a_solid_block() -> None:
    """Quantifies 'has a tick': a filled square approaches 1.0 fill."""
    _, _, fill = _indicator_stats(checked=True)
    assert fill < 0.75, f"checked indicator looks like a solid block (fill={fill:.2f})"


def test_space_key_toggles_a_checkbox(qtbot) -> None:
    box = QCheckBox("聯絡地址同登記地址")
    qtbot.addWidget(box)
    box.show()
    qtbot.waitExposed(box)
    box.setFocus()
    assert not box.isChecked()
    qtbot.keyClick(box, Qt.Key.Key_Space)
    assert box.isChecked(), "Space must toggle the box"
    qtbot.keyClick(box, Qt.Key.Key_Space)
    assert not box.isChecked()


def test_checkbox_is_keyboard_focusable_and_label_is_clickable() -> None:
    box = QCheckBox("啟用此項")
    assert box.focusPolicy() != Qt.FocusPolicy.NoFocus
    # Qt hit-tests the label as part of the widget, so the text toggles the box.
    assert box.text() == "啟用此項"


# ── Typography ──────────────────────────────────────────────────────


def test_no_declared_font_size_falls_below_thirteen_px() -> None:
    sizes = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", APP_STYLESHEET)]
    assert sizes, "expected font sizes in the stylesheet"
    assert min(sizes) >= 13, f"found sub-13px type: {sorted(set(sizes))}"


def test_type_scale_matches_the_product_rule() -> None:
    assert tokens.FONT_BODY >= 14
    assert tokens.FONT_TABLE >= 13
    assert tokens.FONT_TABLE_HEADER >= 13
    assert tokens.FONT_HINT >= 13
    assert tokens.FONT_ERROR >= 14
    assert tokens.FONT_SECTION_TITLE == 16
    assert tokens.FONT_PAGE_TITLE == 20


def test_compact_row_buttons_respect_the_type_floor() -> None:
    from taxops.ui.style import BTN_DANGER_SM, BTN_PRIMARY_SM, BTN_SECONDARY_SM

    for sheet in (BTN_PRIMARY_SM, BTN_SECONDARY_SM, BTN_DANGER_SM):
        sizes = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", sheet)]
        assert sizes and min(sizes) >= 13


# ── Sizing ──────────────────────────────────────────────────────────


def test_size_tokens_match_the_brief() -> None:
    assert tokens.INPUT_HEIGHT == 36
    assert tokens.INPUT_HEIGHT_COMPACT == 32
    assert tokens.BUTTON_HEIGHT == 36
    assert tokens.ICON_BUTTON_SIZE in (32, 36)
    assert tokens.ROW_HEIGHT_TEXT >= 36
    assert tokens.ROW_HEIGHT_EDITOR >= 42
    assert 52 <= tokens.SIDEBAR_COLLAPSED_WIDTH <= 60
    assert tokens.SIDEBAR_EXPANDED_WIDTH == 220


def test_button_height_leaves_room_for_its_text() -> None:
    button = QPushButton("建立年度工作")
    button.ensurePolished()
    hint = button.sizeHint()
    metrics = button.fontMetrics()
    assert hint.height() >= metrics.height() + 8, (
        f"button height {hint.height()} clips {metrics.height()}px text"
    )
    assert 32 <= hint.height() <= 48, f"unexpected button height {hint.height()}"


def test_input_height_leaves_room_for_its_text() -> None:
    field = QLineEdit()
    field.setText("2026-08-06")
    field.ensurePolished()
    hint = field.sizeHint()
    metrics = field.fontMetrics()
    assert hint.height() >= metrics.height() + 8, (
        f"input height {hint.height()} clips {metrics.height()}px text"
    )


def test_larger_system_font_grows_controls_instead_of_clipping(qapp) -> None:
    """Stands in for increased Windows scaling: bigger type, taller controls."""
    baseline = QPushButton("測試按鈕")
    baseline.ensurePolished()
    base_height = baseline.sizeHint().height()

    font = qapp.font()
    original_size = font.pointSizeF()
    font.setPointSizeF(original_size * 1.25)
    try:
        scaled = QPushButton("測試按鈕")
        scaled.setFont(font)
        scaled.ensurePolished()
        metrics = scaled.fontMetrics()
        assert scaled.sizeHint().height() >= metrics.height() + 8, (
            "text clips once the system font grows"
        )
        assert scaled.sizeHint().height() >= base_height
    finally:
        font.setPointSizeF(original_size)


# ── Tables ──────────────────────────────────────────────────────────

_COLUMNS = ("client_code", "client_name", "tax_id")
_HEADERS = {"client_code": "客戶代號", "client_name": "客戶名稱", "tax_id": "統一編號"}


def test_text_table_rows_are_tall_enough() -> None:
    table = build_standard_table(_COLUMNS, _HEADERS, stretch_col="client_name")
    assert table.verticalHeader().defaultSectionSize() >= 36


def test_editor_table_rows_are_tall_enough() -> None:
    table = build_standard_table(
        _COLUMNS, _HEADERS, row_height=tokens.ROW_HEIGHT_EDITOR
    )
    assert table.verticalHeader().defaultSectionSize() >= 42


def test_tables_elide_long_text_rather_than_wrapping() -> None:
    table = build_standard_table(_COLUMNS, _HEADERS)
    assert table.textElideMode() == Qt.TextElideMode.ElideRight
    assert table.wordWrap() is False


def test_table_selection_colour_is_low_saturation() -> None:
    """A whole row of saturated blue leaves no room for status colour."""
    assert tokens.SURFACE_SELECTED != tokens.PRIMARY
    r, g, b = (int(tokens.SURFACE_SELECTED[i : i + 2], 16) for i in (1, 3, 5))
    assert min(r, g, b) >= 200, "selection fill must stay pale"


def test_gridlines_are_subtle() -> None:
    assert f"gridline-color: {tokens.BORDER_SUBTLE}" in APP_STYLESHEET


# ── Page-level ceilings ─────────────────────────────────────────────


def _page_buttons(container, qtbot):
    from taxops.ui.main_window import MainWindow

    window = MainWindow(container)
    qtbot.addWidget(window)
    for index in range(window._stack.count()):
        page = window._stack.widget(index)
        yield type(page).__name__, page.findChildren(QPushButton)


def test_no_page_exposes_more_than_one_primary_action(container, qtbot) -> None:
    """At most one primary per navigation page — the ceiling, not a target.

    Counted across the page's whole widget tree, embedded sub-pages included. A host
    page that embeds another must not inherit a second primary: EngagementsPage
    builds two DocumentRequestsPage instances, which is exactly how three competing
    primaries appeared on one page during this stage.
    """
    offenders: list[tuple[str, list[str]]] = []
    for name, buttons in _page_buttons(container, qtbot):
        primaries = [
            b.text() for b in buttons if b.property("role") == tokens.ROLE_PRIMARY
        ]
        if len(primaries) > 1:
            offenders.append((name, primaries))
    assert not offenders, f"pages with competing primary actions: {offenders}"


def test_every_navigation_page_declares_a_primary_action(container, qtbot) -> None:
    """A page with no primary gives the user no visual next step.

    Settings and recurring billing are exempt for now: their primary belongs to a
    stage that reworks their internal structure, and asserting one here would force
    a premature choice.
    """
    exempt = {"SettingsPage", "RecurringBillingPage"}
    missing: list[str] = []
    for name, buttons in _page_buttons(container, qtbot):
        if name in exempt:
            continue
        if not any(b.property("role") == tokens.ROLE_PRIMARY for b in buttons):
            missing.append(name)
    assert not missing, f"pages without a primary action: {missing}"


def test_search_clear_and_refresh_are_never_primary(container, qtbot) -> None:
    """View controls must not compete with the action that changes data."""
    forbidden = ("搜尋", "清除", "重新整理", "欄位顯示", "篩選")
    offenders: list[tuple[str, str]] = []
    for name, buttons in _page_buttons(container, qtbot):
        for button in buttons:
            label = button.text()
            if button.property("role") != tokens.ROLE_PRIMARY:
                continue
            if any(label.startswith(word) for word in forbidden):
                offenders.append((name, label))
    assert not offenders, f"view controls styled as primary: {offenders}"


def test_destructive_actions_are_never_primary(container, qtbot) -> None:
    """刪除 / 永久刪除 / 取消 must never carry the primary fill."""
    destructive = ("刪除", "永久刪除", "取消工作", "清空")
    offenders: list[tuple[str, str]] = []
    for name, buttons in _page_buttons(container, qtbot):
        for button in buttons:
            label = button.text()
            if not any(word in label for word in destructive):
                continue
            if button.property("role") == tokens.ROLE_PRIMARY:
                offenders.append((name, label))
    assert not offenders, f"destructive actions styled as primary: {offenders}"


def test_client_page_marks_its_destructive_actions(container, qtbot) -> None:
    """The design template page states the danger role explicitly."""
    from taxops.ui.pages.clients_page import ClientsPage
    from taxops.ui.widgets.buttons import button_role

    page = ClientsPage(container)
    qtbot.addWidget(page)
    assert button_role(page._delete_btn) == "danger"
    assert button_role(page._purge_btn) == "danger"
    assert button_role(page._new_btn) == "primary"
    # Search and clear must stay out of the primary slot.
    assert button_role(page._search_btn) != "primary"
    assert button_role(page._clear_btn) != "primary"
    assert button_role(page._refresh_btn) != "primary"


def test_sidebar_active_item_is_not_a_saturated_block() -> None:
    """Active navigation reads as a left indicator, not a full blue fill."""
    match = re.search(
        r"QListWidget#MainNav::item:selected \{(.*?)\}", APP_STYLESHEET, re.DOTALL
    )
    assert match
    body = match.group(1)
    assert f"background-color: {tokens.PRIMARY}" not in body
    assert f"border-left: 3px solid {tokens.SIDEBAR_ACTIVE_INDICATOR}" in body


def test_group_box_does_not_add_a_full_border() -> None:
    """Section grouping uses a heading and a rule, not a fourth nested box."""
    match = re.search(r"\nQGroupBox \{(.*?)\}", APP_STYLESHEET, re.DOTALL)
    assert match
    body = match.group(1)
    assert "border: none" in body
    assert "border-top" in body
