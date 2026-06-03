"""Dashboard removal regression tests."""

from __future__ import annotations


def test_dashboard_page_contracts_are_removed() -> None:
    from taxops.ui.action_registry import ACTION_REGISTRY

    assert all(action.page != "dashboard" for action in ACTION_REGISTRY)


def test_dashboard_label_is_removed() -> None:
    from taxops.i18n import NAV_LABELS

    assert "dashboard" not in NAV_LABELS


def test_service_container_has_no_dashboard(container) -> None:
    assert not hasattr(container, "dashboard")
