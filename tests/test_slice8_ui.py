"""Slice 8 UI smoke tests: ReviewNotesPage, LateFeePage, action registry contracts."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.document_requests import DocumentRequestsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.late_fee import LateFeeRepository
from taxops.repositories.review_notes import ReviewNotesRepository
from taxops.repositories.system_logs import SystemLogRepository
from taxops.services.audit import AuditService
from taxops.services.document_requests import DocumentRequestsService
from taxops.services.engagements import EngagementsService
from taxops.services.late_fee import LateFeeService
from taxops.services.review_notes import CreateReviewNoteInput, ReviewNotesService
from taxops.services.system_log import SystemLogService
from taxops.ui.action_registry import (
    PAGE_LATE_FEE,
    PAGE_REVIEW_NOTES,
    actions_for_page,
)
from taxops.ui.pages.late_fee_page import LateFeePage
from taxops.ui.pages.review_notes_page import ReviewNotesPage


# ── QApplication singleton ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ── DB + fake container ───────────────────────────────────────────────────────

class _FakeContainer:
    def __init__(self, conn):
        audit_repo = AuditLogRepository(conn)
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.system_log = SystemLogService(SystemLogRepository(conn))
        self.engagements = EngagementsService(EngagementsRepository(conn), self._audit)
        self.doc_requests = DocumentRequestsService(DocumentRequestsRepository(conn), self._audit)
        self.review_notes = ReviewNotesService(
            repo=ReviewNotesRepository(conn),
            engagements_repo=EngagementsRepository(conn),
            audit=self._audit,
        )
        self.late_fee = LateFeeService(
            repo=LateFeeRepository(conn),
            doc_requests_repo=DocumentRequestsRepository(conn),
            audit=self._audit,
        )


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


def _seed(conn):
    conn.execute(
        "INSERT INTO clients (client_code, client_name, created_at, updated_at) VALUES ('C001', '測試客戶', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO engagements
           (client_id, engagement_name, tax_type, period_name, status, created_at, updated_at)
           VALUES (?, '2024 VAT', 'vat', '2024Q1', 'draft', '2026-01-01T00:00:00', '2026-01-01T00:00:00')""",
        (client_id,),
    )
    eng_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO document_requests
           (engagement_id, period_name, tax_type, status, created_at, updated_at)
           VALUES (?, '2024Q1', 'vat', 'not_requested', '2026-01-01T00:00:00', '2026-01-01T00:00:00')""",
        (eng_id,),
    )
    req_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return eng_id, req_id


# ── ReviewNotesPage smoke ─────────────────────────────────────────────────────

def test_review_notes_page_renders(qapp, conn, container):
    page = ReviewNotesPage(container)
    assert page is not None


def test_review_notes_page_table_columns(qapp, conn, container):
    page = ReviewNotesPage(container)
    assert page._table.columnCount() == 6


def test_review_notes_page_loads_empty(qapp, conn, container):
    page = ReviewNotesPage(container)
    assert page._table.rowCount() == 0


def test_review_notes_page_loads_with_data(qapp, conn, container):
    eng_id, _ = _seed(conn)
    container.review_notes.create(
        CreateReviewNoteInput(engagement_id=eng_id, severity="minor", comment="Test note")
    )
    page = ReviewNotesPage(container)
    for i in range(page._eng_combo.count()):
        if page._eng_combo.itemData(i) == eng_id:
            page._eng_combo.setCurrentIndex(i)
            break
    assert page._table.rowCount() == 1


# ── LateFeePage smoke ─────────────────────────────────────────────────────────

def test_late_fee_page_renders(qapp, conn, container):
    page = LateFeePage(container)
    assert page is not None


def test_late_fee_page_has_calculate_button(qapp, conn, container):
    page = LateFeePage(container)
    assert page._calc_btn.text() == "開始試算"


def test_late_fee_page_history_table_empty_initial(qapp, conn, container):
    page = LateFeePage(container)
    assert page._table.rowCount() == 0


def test_late_fee_calculate_persists_to_db(qapp, conn, container):
    _, req_id = _seed(conn)
    page = LateFeePage(container)

    for i in range(page._eng_combo.count()):
        if page._eng_combo.itemData(i) != -1:
            page._eng_combo.setCurrentIndex(i)
            break
    for i in range(page._req_combo.count()):
        if page._req_combo.itemData(i) == req_id:
            page._req_combo.setCurrentIndex(i)
            break

    page._days_spin.setValue(7)
    page._base_spin.setValue(10000.0)
    page._on_calculate()

    records = container.late_fee.list_by_request(req_id)
    assert len(records) == 1
    assert records[0].penalty_percent == 2.0
    assert records[0].penalty_amount == 200.0


# ── action registry contracts ─────────────────────────────────────────────────

def test_late_fee_page_has_enabled_calculate_action():
    actions = actions_for_page(PAGE_LATE_FEE)
    labels = {a.button_label for a in actions if a.enabled}
    assert "開始試算" in labels


def test_review_notes_page_has_enabled_create_action():
    actions = actions_for_page(PAGE_REVIEW_NOTES)
    labels = {a.button_label for a in actions if a.enabled}
    assert "新增覆核意見" in labels


def test_review_notes_enabled_actions_have_audit():
    for a in actions_for_page(PAGE_REVIEW_NOTES):
        if a.enabled:
            assert a.audit_action is not None, f"{a.button_label} missing audit_action"


def test_late_fee_enabled_actions_have_service():
    for a in actions_for_page(PAGE_LATE_FEE):
        if a.enabled:
            assert a.service is not None, f"{a.button_label} missing service"
