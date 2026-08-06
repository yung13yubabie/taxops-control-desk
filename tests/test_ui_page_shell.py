"""Contracts for the shared page shell and inspector.

The ceilings here are enforced at construction time rather than checked by review:
a header refuses a second primary, and an action bar refuses a sixth visible action.
A page that needs more must put the remainder in the overflow menu.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPushButton

from taxops.ui import tokens
from taxops.ui.style import APP_STYLESHEET
from taxops.ui.widgets.buttons import button_role
from taxops.ui.widgets.empty_state import EmptyState
from taxops.ui.widgets.inspector import Inspector
from taxops.ui.widgets.page_shell import (
    MAX_VISIBLE_ACTIONS,
    ActionBar,
    ActionBarOverflowError,
    PageHeader,
    build_page_layout,
)


@pytest.fixture(autouse=True)
def _styled_app(qapp):
    previous = qapp.styleSheet()
    qapp.setStyleSheet(APP_STYLESHEET)
    yield qapp
    qapp.setStyleSheet(previous)


# ── PageHeader ──────────────────────────────────────────────────────


def test_header_shows_title_and_optional_subtitle() -> None:
    header = PageHeader("客戶管理")
    assert header.title_label.text() == "客戶管理"
    assert not header.subtitle_label.isVisible()

    header.set_subtitle("共 128 筆")
    assert header.subtitle_label.text() == "共 128 筆"


def test_header_accepts_one_primary_action() -> None:
    header = PageHeader("客戶管理")
    button = header.add_action(QPushButton("新增客戶"), role=tokens.ROLE_PRIMARY)
    assert button_role(button) == "primary"
    assert header.actions_visible() == 1


def test_header_refuses_a_second_primary_action() -> None:
    header = PageHeader("客戶管理")
    header.add_action(QPushButton("新增客戶"), role=tokens.ROLE_PRIMARY)
    with pytest.raises(ActionBarOverflowError):
        header.add_action(QPushButton("批量匯入"), role=tokens.ROLE_PRIMARY)


def test_header_allows_several_non_primary_actions() -> None:
    header = PageHeader("年度工作台")
    header.add_action(QPushButton("年度規則"), role=tokens.ROLE_SECONDARY)
    header.add_action(QPushButton("建立年度工作"), role=tokens.ROLE_PRIMARY)
    assert header.actions_visible() == 2


# ── ActionBar ───────────────────────────────────────────────────────


def test_action_bar_separates_work_from_tools() -> None:
    bar = ActionBar()
    work = bar.add_work_action(QPushButton("產生待開立紀錄"))
    tool = bar.add_tool_action(QPushButton("欄位"))
    assert button_role(work) == tokens.ROLE_SECONDARY
    assert button_role(tool) == tokens.ROLE_QUIET
    assert bar.visible_action_count() == 2


def test_action_bar_enforces_the_five_action_ceiling() -> None:
    bar = ActionBar()
    for index in range(MAX_VISIBLE_ACTIONS):
        bar.add_tool_action(QPushButton(f"動作 {index}"))
    assert bar.visible_action_count() == MAX_VISIBLE_ACTIONS
    with pytest.raises(ActionBarOverflowError):
        bar.add_tool_action(QPushButton("第六個"))


def test_overflow_button_does_not_count_against_the_ceiling() -> None:
    """Otherwise adding 更多 would cost one of the five slots."""
    bar = ActionBar()
    for index in range(MAX_VISIBLE_ACTIONS):
        bar.add_tool_action(QPushButton(f"動作 {index}"))
    calls: list[str] = []
    bar.add_overflow_action("永久刪除", lambda: calls.append("purge"))
    assert bar.visible_action_count() == MAX_VISIBLE_ACTIONS
    assert bar.overflow_button is not None
    assert bar.overflow_action_texts() == ("永久刪除",)


def test_overflow_actions_are_invocable() -> None:
    bar = ActionBar()
    calls: list[str] = []
    bar.add_overflow_action("復原客戶", lambda: calls.append("restore"))
    menu = bar.overflow_button.menu()
    actions = [a for a in menu.actions() if not a.isSeparator()]
    actions[0].trigger()
    assert calls == ["restore"]


def test_overflow_button_is_labelled_for_assistive_use() -> None:
    bar = ActionBar()
    bar.add_overflow_action("刪除", lambda: None)
    button = bar.overflow_button
    assert button is not None
    assert button.toolTip()
    assert button.accessibleName()
    assert button.text() == ""


def test_tool_icon_requires_labels() -> None:
    bar = ActionBar()
    icon_button = bar.add_tool_icon(
        "refresh", tooltip="重新整理", accessible_name="重新整理"
    )
    assert icon_button.toolTip() == "重新整理"
    assert icon_button.accessibleName() == "重新整理"
    assert button_role(icon_button) == tokens.ROLE_ICON


def test_page_layout_uses_one_consistent_margin() -> None:
    header = PageHeader("待辦事項")
    layout = build_page_layout(header, action_bar=ActionBar())
    margins = layout.contentsMargins()
    assert margins.left() == tokens.PAGE_MARGIN
    assert margins.top() == tokens.PAGE_MARGIN

    dense = build_page_layout(PageHeader("固定開立"), dense=True)
    assert dense.contentsMargins().left() == tokens.PAGE_MARGIN_DENSE


# ── Inspector ───────────────────────────────────────────────────────


def test_inspector_starts_on_its_placeholder() -> None:
    inspector = Inspector()
    assert inspector.is_showing_placeholder()
    assert inspector.field_values() == {}


def test_inspector_shows_fields_for_a_selection() -> None:
    inspector = Inspector()
    inspector.set_title("曜川保全股份有限公司", subtitle="2301 · 13087090")
    inspector.add_section("聯絡資訊")
    inspector.add_field("聯絡人", "王小明")
    inspector.add_field("聯絡電話", "02-1234-5678")

    assert not inspector.is_showing_placeholder()
    assert inspector.title_label.text() == "曜川保全股份有限公司"
    assert inspector.section_names() == ("聯絡資訊",)
    assert inspector.field_values() == {
        "聯絡人": "王小明",
        "聯絡電話": "02-1234-5678",
    }


def test_inspector_preserves_newlines_in_multiline_fields() -> None:
    """Client notes are stored with exact newlines and must display that way."""
    notes = "第一行\n第二行\n\n第四行"
    inspector = Inspector()
    inspector.set_title("測試客戶")
    inspector.add_section("備註")
    inspector.add_field("備註", notes, multiline=True)
    assert inspector.field_values()["備註"] == notes


def test_inspector_renders_empty_values_as_a_dash() -> None:
    inspector = Inspector()
    inspector.set_title("測試客戶")
    inspector.add_section("聯絡資訊")
    inspector.add_field("聯絡信箱", "")
    assert inspector.field_values()["聯絡信箱"] == "—"


def test_inspector_clear_returns_to_placeholder() -> None:
    """A page that drops its selection must be able to blank the panel."""
    inspector = Inspector()
    inspector.set_title("測試客戶")
    inspector.add_section("基本資料")
    inspector.add_field("客戶代號", "2301")
    assert inspector.field_values()

    inspector.clear()
    assert inspector.is_showing_placeholder()
    assert inspector.field_values() == {}
    assert inspector.section_names() == ()


def test_inspector_repopulates_without_stacking_old_fields() -> None:
    inspector = Inspector()
    inspector.set_title("客戶 A")
    inspector.add_section("基本資料")
    inspector.add_field("客戶代號", "2301")

    inspector.begin_update()
    inspector.set_title("客戶 B")
    inspector.add_section("基本資料")
    inspector.add_field("客戶代號", "2330")

    values = inspector.field_values()
    assert values == {"客戶代號": "2330"}


def test_inspector_hides_contextual_actions_until_a_selection_exists() -> None:
    """This is what replaces a row of disabled buttons on the page.

    Checked with isVisibleTo rather than isVisible: an unshown widget tree reports
    everything as invisible, which would make the assertion pass for the wrong reason.
    """
    inspector = Inspector()
    inspector.add_action(QPushButton("編輯客戶"))
    assert inspector.action_texts() == ("編輯客戶",)
    assert not inspector.actions_are_exposed()

    inspector.set_title("測試客戶")
    assert inspector.actions_are_exposed()

    inspector.clear()
    assert not inspector.actions_are_exposed()


# ── EmptyState ──────────────────────────────────────────────────────


def test_empty_state_has_at_most_one_action() -> None:
    state = EmptyState(
        "尚無客戶資料",
        detail="建立第一筆客戶後，即可開始建立案件與年度工作。",
        action_text="新增第一筆客戶",
    )
    assert state.action_button is not None
    assert state.title_label.text() == "尚無客戶資料"
    assert state.detail_label.isVisibleTo(state)


def test_empty_state_action_is_not_primary() -> None:
    """The page header usually owns the same action as its primary."""
    state = EmptyState("尚無資料", action_text="新增第一筆客戶")
    assert button_role(state.action_button) != tokens.ROLE_PRIMARY


def test_empty_state_without_detail_hides_the_body() -> None:
    state = EmptyState("尚無資料")
    assert not state.detail_label.isVisibleTo(state)
    assert state.action_button is None


def test_empty_state_uses_stylesheet_ids_not_inline_styles() -> None:
    """Colour and type belong in the stylesheet so the scale stays in one place."""
    state = EmptyState("尚無資料", detail="說明")
    assert state.title_label.styleSheet() == ""
    assert state.detail_label.styleSheet() == ""
    assert "QLabel#EmptyStateTitle" in APP_STYLESHEET
    assert "QLabel#EmptyStateBody" in APP_STYLESHEET
