"""Slice 14 Dashboard tests.

Covers:
- DashboardRepository: all 8 count methods, empty DB, boundary dates
- DashboardService: get_counts with injectable today, no-hardcode guarantee
- DashboardPage UI: instantiates, shows "0" for empty DB, navigate buttons exist
- Action registry: PAGE_DASHBOARD contracts
"""

from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fresh_container():
    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "TestSlice14")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


def _seed_client(conn) -> int:
    conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES ('C001', '測試客戶', datetime('now'), datetime('now'))"
    )
    conn.commit()
    return conn.execute("SELECT id FROM clients WHERE client_code='C001'").fetchone()[0]


def _seed_engagement(conn, client_id: int, *, due_date: str | None = None, status: str = "active") -> int:
    conn.execute(
        "INSERT INTO engagements(client_id, engagement_name, tax_type, period_name, status,"
        " due_date, created_at, updated_at)"
        " VALUES (?, '年度所得稅', 'income_tax', '2026', ?, ?, datetime('now'), datetime('now'))",
        (client_id, status, due_date),
    )
    conn.commit()
    return conn.execute("SELECT id FROM engagements ORDER BY id DESC LIMIT 1").fetchone()[0]


def _seed_task(conn, engagement_id: int, *, due_date: str | None, status: str = "todo") -> None:
    conn.execute(
        "INSERT INTO workflow_tasks(engagement_id, title, priority, status, due_date,"
        " created_at, updated_at)"
        " VALUES (?, '測試待辦', 'normal', ?, ?, datetime('now'), datetime('now'))",
        (engagement_id, status, due_date),
    )
    conn.commit()


def _seed_doc_request(conn, engagement_id: int, *, status: str = "not_requested") -> int:
    conn.execute(
        "INSERT INTO document_requests(engagement_id, tax_type, period_name, status,"
        " follow_up_count, created_at, updated_at)"
        " VALUES (?, 'income_tax', '2026', ?, 0, datetime('now'), datetime('now'))",
        (engagement_id, status),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM document_requests ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]


def _seed_doc_item(conn, request_id: int, *, item_status: str = "missing") -> None:
    conn.execute(
        "INSERT INTO document_request_items(request_id, item_name, item_status,"
        " created_at, updated_at)"
        " VALUES (?, '測試文件', ?, datetime('now'), datetime('now'))",
        (request_id, item_status),
    )
    conn.commit()


def _seed_review_note(conn, engagement_id: int, *, severity: str = "major", status: str = "open") -> int:
    conn.execute(
        "INSERT INTO review_notes(engagement_id, severity, comment, status,"
        " created_at, updated_at)"
        " VALUES (?, ?, '測試覆核', ?, datetime('now'), datetime('now'))",
        (engagement_id, severity, status),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM review_notes ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# DashboardRepository tests
# ---------------------------------------------------------------------------

class TestDashboardRepository:
    def test_empty_db_all_zeros(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        repo = DashboardRepository(container.conn)
        today = "2026-05-17"
        assert repo.count_tasks_due_today(today) == 0
        assert repo.count_tasks_overdue(today) == 0
        assert repo.count_waiting_client() == 0
        assert repo.count_open_review_notes() == 0
        assert repo.count_missing_item_requests() == 0
        assert repo.count_upcoming_engagements(today, "2026-05-24") == 0
        assert repo.count_overdue_engagements(today) == 0
        assert repo.count_high_risk_engagements() == 0

    def test_tasks_due_today_counts(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-17")  # today
        _seed_task(conn, eng_id, due_date="2026-05-16")  # yesterday
        repo = DashboardRepository(conn)
        assert repo.count_tasks_due_today("2026-05-17") == 1

    def test_tasks_due_today_excludes_done(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-17", status="done")
        repo = DashboardRepository(conn)
        assert repo.count_tasks_due_today("2026-05-17") == 0

    def test_tasks_overdue_boundary(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-16")  # yesterday = overdue
        _seed_task(conn, eng_id, due_date="2026-05-17")  # today = NOT overdue
        repo = DashboardRepository(conn)
        assert repo.count_tasks_overdue("2026-05-17") == 1

    def test_tasks_overdue_excludes_cancelled(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-16", status="cancelled")
        repo = DashboardRepository(conn)
        assert repo.count_tasks_overdue("2026-05-17") == 0

    def test_waiting_client(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-20", status="waiting_client")
        _seed_task(conn, eng_id, due_date="2026-05-20", status="todo")
        repo = DashboardRepository(conn)
        assert repo.count_waiting_client() == 1

    def test_open_review_notes_counts_open_responded_reopened(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_review_note(conn, eng_id, status="open")
        _seed_review_note(conn, eng_id, status="responded")
        _seed_review_note(conn, eng_id, status="reopened")
        _seed_review_note(conn, eng_id, status="resolved")  # should NOT count
        repo = DashboardRepository(conn)
        assert repo.count_open_review_notes() == 3

    def test_missing_item_requests_distinct_by_request(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        req_id = _seed_doc_request(conn, eng_id)
        _seed_doc_item(conn, req_id, item_status="missing")
        _seed_doc_item(conn, req_id, item_status="incomplete")  # same request → still 1
        repo = DashboardRepository(conn)
        assert repo.count_missing_item_requests() == 1

    def test_missing_item_requests_excludes_provided(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        req_id = _seed_doc_request(conn, eng_id)
        _seed_doc_item(conn, req_id, item_status="provided")
        repo = DashboardRepository(conn)
        assert repo.count_missing_item_requests() == 0

    def test_upcoming_engagements_in_window(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        _seed_engagement(conn, client_id, due_date="2026-05-17")  # today = in window
        _seed_engagement(conn, client_id, due_date="2026-05-24")  # until = in window
        _seed_engagement(conn, client_id, due_date="2026-05-25")  # beyond → not counted
        _seed_engagement(conn, client_id, due_date="2026-05-16")  # yesterday → not counted
        repo = DashboardRepository(conn)
        assert repo.count_upcoming_engagements("2026-05-17", "2026-05-24") == 2

    def test_upcoming_engagements_excludes_done(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        _seed_engagement(conn, client_id, due_date="2026-05-20", status="closed")
        repo = DashboardRepository(conn)
        assert repo.count_upcoming_engagements("2026-05-17", "2026-05-24") == 0

    def test_overdue_engagements_excludes_closed(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        _seed_engagement(conn, client_id, due_date="2026-05-16", status="closed")
        repo = DashboardRepository(conn)
        assert repo.count_overdue_engagements("2026-05-17") == 0

    def test_overdue_engagements_boundary(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        _seed_engagement(conn, client_id, due_date="2026-05-16")  # yesterday = overdue
        _seed_engagement(conn, client_id, due_date="2026-05-17")  # today = NOT overdue
        repo = DashboardRepository(conn)
        assert repo.count_overdue_engagements("2026-05-17") == 1

    def test_high_risk_engagements_distinct_by_engagement(self):
        from taxops.repositories.dashboard import DashboardRepository

        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng1 = _seed_engagement(conn, client_id)
        eng2 = _seed_engagement(conn, client_id)
        _seed_review_note(conn, eng1, severity="critical", status="open")
        _seed_review_note(conn, eng1, severity="critical", status="open")  # same eng → still 1
        _seed_review_note(conn, eng2, severity="major", status="open")     # not critical
        _seed_review_note(conn, eng2, severity="critical", status="resolved")  # resolved
        repo = DashboardRepository(conn)
        assert repo.count_high_risk_engagements() == 1


# ---------------------------------------------------------------------------
# DashboardService tests
# ---------------------------------------------------------------------------

class TestDashboardService:
    def test_get_counts_empty_db_all_zero(self):
        from taxops.services.dashboard import DashboardCounts

        container = _fresh_container()
        counts = container.dashboard.get_counts(today="2026-05-17")
        assert isinstance(counts, DashboardCounts)
        assert counts.tasks_due_today == 0
        assert counts.tasks_overdue == 0
        assert counts.waiting_client == 0
        assert counts.open_review_notes == 0
        assert counts.missing_item_requests == 0
        assert counts.upcoming_engagements == 0
        assert counts.overdue_engagements == 0
        assert counts.high_risk_engagements == 0

    def test_get_counts_no_hardcode_guarantee(self):
        """Empty DB must return 0 for every field — not any positive hardcoded number."""
        container = _fresh_container()
        counts = container.dashboard.get_counts(today="2000-01-01")
        for val in [
            counts.tasks_due_today,
            counts.tasks_overdue,
            counts.waiting_client,
            counts.open_review_notes,
            counts.missing_item_requests,
            counts.upcoming_engagements,
            counts.overdue_engagements,
            counts.high_risk_engagements,
        ]:
            assert val == 0, f"Expected 0 from empty DB, got {val}"

    def test_get_counts_with_data(self):
        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date="2026-05-17")
        counts = container.dashboard.get_counts(today="2026-05-17")
        assert counts.tasks_due_today == 1

    def test_get_counts_upcoming_window_uses_7_days(self):
        """today='2026-05-17' → window ends '2026-05-24' (inclusive)."""
        container = _fresh_container()
        conn = container.conn
        client_id = _seed_client(conn)
        _seed_engagement(conn, client_id, due_date="2026-05-24")
        counts = container.dashboard.get_counts(today="2026-05-17")
        assert counts.upcoming_engagements == 1


# ---------------------------------------------------------------------------
# DashboardPage UI tests
# ---------------------------------------------------------------------------

class TestDashboardPageUI:
    def test_page_instantiates(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage(container)
        assert page is not None

    def test_all_8_cards_present(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage, _CARD_DEFS
        page = DashboardPage(container)
        assert len(page._cards) == 8
        assert len(page._cards) == len(_CARD_DEFS)

    def test_empty_db_cards_show_zero(self):
        """After init, empty DB → all cards show '0', not any hardcoded positive number."""
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage(container)
        for field, card in page._cards.items():
            assert card._count_lbl.text() == "0", (
                f"Card {field!r} showed {card._count_lbl.text()!r}, expected '0'"
            )

    def test_refresh_button_exists_and_enabled(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage(container)
        assert page._refresh_btn.text() == "重新整理"
        assert page._refresh_btn.isEnabled()

    def test_all_nav_buttons_enabled(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage(container)
        for field, card in page._cards.items():
            assert card.nav_btn.isEnabled(), f"nav_btn for card {field!r} should be enabled"

    def test_navigate_signal_emitted_for_tasks(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        from taxops.ui.action_registry import PAGE_TASKS
        page = DashboardPage(container)
        emitted: list[tuple[str, str]] = []
        page.navigate_to_page.connect(lambda p, f: emitted.append((p, f)))
        page._cards["tasks_due_today"].nav_btn.click()
        assert emitted == [(PAGE_TASKS, "due_today")]

    def test_navigate_signal_emitted_for_engagements(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        from taxops.ui.action_registry import PAGE_ENGAGEMENTS
        page = DashboardPage(container)
        emitted: list[tuple[str, str]] = []
        page.navigate_to_page.connect(lambda p, f: emitted.append((p, f)))
        page._cards["waiting_client"].nav_btn.click()
        assert emitted == [(PAGE_ENGAGEMENTS, "")]

    def test_refresh_updates_count_after_seed(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        import datetime
        today = datetime.date.today().isoformat()
        conn = container.conn
        client_id = _seed_client(conn)
        eng_id = _seed_engagement(conn, client_id)
        _seed_task(conn, eng_id, due_date=today)

        page = DashboardPage(container)
        page._on_refresh()
        assert page._cards["tasks_due_today"]._count_lbl.text() == "1"

    def test_status_label_empty_on_success(self):
        _make_app()
        container = _fresh_container()
        from taxops.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage(container)
        assert page._status_lbl.text() == ""


# ---------------------------------------------------------------------------
# Action registry contracts
# ---------------------------------------------------------------------------

class TestDashboardActionContracts:
    def test_page_dashboard_has_at_least_4_contracts(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_DASHBOARD
        contracts = [c for c in ACTION_REGISTRY if c.page == PAGE_DASHBOARD]
        assert len(contracts) >= 4

    def test_refresh_contract_enabled_with_service(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_DASHBOARD
        contracts = [
            c for c in ACTION_REGISTRY
            if c.page == PAGE_DASHBOARD and c.button_label == "重新整理"
        ]
        assert len(contracts) == 1
        c = contracts[0]
        assert c.enabled is True
        assert c.service == "DashboardService.get_counts"
        assert c.repository == "DashboardRepository"

    def test_all_nav_contracts_present_and_enabled(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_DASHBOARD
        nav_labels = {"前往待辦事項", "前往覆核意見", "前往案件管理"}
        for label in nav_labels:
            contracts = [
                c for c in ACTION_REGISTRY
                if c.page == PAGE_DASHBOARD and c.button_label == label
            ]
            assert len(contracts) == 1, f"Missing contract for {label!r}"
            assert contracts[0].enabled is True

    def test_no_disabled_dashboard_contracts(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_DASHBOARD
        disabled = [c for c in ACTION_REGISTRY if c.page == PAGE_DASHBOARD and not c.enabled]
        assert disabled == [], f"Dashboard should have no disabled contracts, got: {disabled}"
