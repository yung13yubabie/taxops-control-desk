"""UI action contract registry consistency checks."""

from __future__ import annotations

from taxops.i18n import DISABLED_TOOLTIP, NAV_LABELS
from taxops.ui.action_registry import (
    ACTION_REGISTRY,
    NAV_ORDER,
    PAGE_DOC_REQUESTS,
    PLACEHOLDER_HANDLER,
    actions_for_page,
)

# Pages whose contracts still exist even though the page is no longer a
# sidebar destination (Slice 21B: doc_requests merged into engagements as
# an embedded widget; the contracts still describe real handlers on that
# embedded instance).
_EMBEDDED_ONLY_PAGES = {PAGE_DOC_REQUESTS}


def test_every_action_targets_a_known_page() -> None:
    for action in ACTION_REGISTRY:
        assert action.page in NAV_ORDER or action.page in _EMBEDDED_ONLY_PAGES, action
        assert action.page in NAV_LABELS, action


def test_action_labels_are_chinese_and_non_empty() -> None:
    for action in ACTION_REGISTRY:
        assert action.button_label.strip()
        assert any("一" <= ch <= "鿿" for ch in action.button_label), action


def test_enabled_actions_have_real_handler() -> None:
    for action in ACTION_REGISTRY:
        if action.enabled:
            assert action.handler != PLACEHOLDER_HANDLER, action


def test_audit_action_implies_service_and_repository() -> None:
    for action in ACTION_REGISTRY:
        if action.audit_action is not None:
            assert action.service, action
            assert action.repository, action


def test_action_keys_are_unique() -> None:
    seen: set[tuple[str, str]] = set()
    for action in ACTION_REGISTRY:
        key = (action.page, action.button_label)
        assert key not in seen, f"duplicate action contract: {key}"
        seen.add(key)


def test_every_nav_page_has_at_least_one_action() -> None:
    for page in NAV_ORDER:
        assert actions_for_page(page), page


def test_disabled_actions_marked_via_placeholder() -> None:
    for action in ACTION_REGISTRY:
        if not action.enabled:
            assert action.handler == PLACEHOLDER_HANDLER, action
            assert action.service is None
            assert action.repository is None
            assert action.audit_action is None


def test_disabled_tooltip_is_canonical_chinese() -> None:
    assert DISABLED_TOOLTIP == "此功能尚未開放"
