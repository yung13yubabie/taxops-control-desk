"""Tests for DocumentRequestsService + DocumentRequestsRepository (Slice 4)."""

from __future__ import annotations

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.document_requests import DocumentRequestsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.services.audit import AuditService
from taxops.services.document_requests import (
    CreateDocumentRequestInput,
    DocumentRequestValidationError,
    DocumentRequestsService,
    UpdateDocumentRequestInput,
    VAT_ITEMS,
)
from taxops.services.engagements import CreateEngagementInput, EngagementsService


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def audit(conn):
    return AuditService(AuditLogRepository(conn), actor="test_user")


@pytest.fixture()
def eng_svc(conn, audit):
    return EngagementsService(EngagementsRepository(conn), audit)


@pytest.fixture()
def svc(conn, audit):
    return DocumentRequestsService(DocumentRequestsRepository(conn), audit)


@pytest.fixture()
def engagement_id(conn, eng_svc):
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, datetime('now'), datetime('now'))",
        ("CL001", "測試客戶"),
    )
    conn.commit()
    cid = cur.lastrowid
    row = eng_svc.create_engagement(
        CreateEngagementInput(
            client_id=cid,
            engagement_name="2024 營業稅",
            tax_type="vat",
            period_name="2024Q1",
        )
    )
    return row.id


def _req_input(engagement_id: int, **kwargs) -> CreateDocumentRequestInput:
    defaults = dict(engagement_id=engagement_id, tax_type="vat", period_name="2024Q1")
    defaults.update(kwargs)
    return CreateDocumentRequestInput(**defaults)


# ── create ────────────────────────────────────────────────────────────────────


def test_create_request_returns_row(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id))
    assert req.id > 0
    assert req.engagement_id == engagement_id
    assert req.request_name == "2024Q1 vat request"
    assert req.status == "not_requested"
    assert items == []


def test_create_request_accepts_custom_request_name(svc, engagement_id):
    req, _ = svc.create_request(
        _req_input(engagement_id, request_name="A公司第一批補件")
    )
    assert req.request_name == "A公司第一批補件"


def test_create_request_blank_request_name_uses_default(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id, request_name="   "))
    assert req.request_name == "2024Q1 vat request"


def test_create_request_vat_template(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    assert len(items) == len(VAT_ITEMS)
    names = [i.item_name for i in items]
    assert names == list(VAT_ITEMS)


def test_create_request_all_items_default_missing(svc, engagement_id):
    _, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    for item in items:
        assert item.item_status == "missing"


def test_create_request_records_audit(svc, engagement_id, conn):
    svc.create_request(_req_input(engagement_id))
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.create'"
    ).fetchall()
    assert len(rows) == 1


def test_update_request_changes_request_name_due_date_and_notes(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    updated = svc.update_request(
        req.id,
        UpdateDocumentRequestInput(
            request_name="第二批資料",
            due_date="2026-06-30",
            notes="先補扣繳資料",
        ),
    )
    assert updated.request_name == "第二批資料"
    assert updated.due_date == "2026-06-30"
    assert updated.notes == "先補扣繳資料"


def test_update_request_blank_name_rejected(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.update_request(req.id, UpdateDocumentRequestInput(request_name=" "))
    assert exc_info.value.code == "doc_request.name.required"


def test_update_request_invalid_due_date_rejected(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.update_request(
            req.id,
            UpdateDocumentRequestInput(request_name="第二批資料", due_date="bad"),
        )
    assert exc_info.value.code == "doc_request.due_date.invalid"


def test_update_request_records_audit(svc, engagement_id, conn):
    req, _ = svc.create_request(_req_input(engagement_id))
    svc.update_request(req.id, UpdateDocumentRequestInput(request_name="第二批資料"))
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request.update'"
    ).fetchall()
    assert len(rows) == 1


# ── mark_requested ────────────────────────────────────────────────────────────


def test_mark_requested(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    updated = svc.mark_requested(req.id)
    assert updated.status == "requested"
    assert updated.requested_at is not None


def test_mark_requested_not_found(svc):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.mark_requested(99999)
    assert exc_info.value.code == "doc_request.not_found"


# ── set_request_status ────────────────────────────────────────────────────────


def test_set_request_status(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    updated = svc.set_request_status(req.id, "partially_received")
    assert updated.status == "partially_received"


def test_set_request_status_invalid(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.set_request_status(req.id, "bad_status")
    assert exc_info.value.code == "doc_request.status.invalid"


# ── follow up ─────────────────────────────────────────────────────────────────


def test_add_follow_up_increments(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    assert req.follow_up_count == 0
    updated = svc.add_follow_up(req.id)
    assert updated.follow_up_count == 1
    updated2 = svc.add_follow_up(req.id)
    assert updated2.follow_up_count == 2


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_request(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    svc.delete_request(req.id)
    assert svc.get_request(req.id) is None


def test_delete_request_not_found(svc):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.delete_request(99999)
    assert exc_info.value.code == "doc_request.not_found"


# ── item status ───────────────────────────────────────────────────────────────


def test_set_item_status(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    item = items[0]
    updated = svc.set_item_status(item.id, item_status="received")
    assert updated.item_status == "received"


def test_set_item_status_invalid(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.set_item_status(items[0].id, item_status="bad_status")
    assert exc_info.value.code == "doc_request_item.status.invalid"


def test_set_item_status_with_notes(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    updated = svc.set_item_status(items[0].id, item_status="incomplete", notes="缺少月份")
    assert updated.notes == "缺少月份"


def test_set_item_status_records_audit(svc, engagement_id, conn):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    svc.set_item_status(items[0].id, item_status="received")
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request_item.status_change'"
    ).fetchall()
    assert len(rows) == 1


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_by_engagement(svc, engagement_id):
    svc.create_request(_req_input(engagement_id))
    svc.create_request(_req_input(engagement_id, period_name="2024Q2"))
    rows = svc.list_by_engagement(engagement_id)
    assert len(rows) == 2


def test_list_by_engagement_excludes_deleted(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    svc.delete_request(req.id)
    rows = svc.list_by_engagement(engagement_id)
    assert len(rows) == 0


def test_list_items(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    fetched = svc.list_items(req.id)
    assert len(fetched) == len(VAT_ITEMS)


# ── FK validation ─────────────────────────────────────────────────────────────


def test_create_request_engagement_not_found(svc):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.create_request(_req_input(engagement_id=99999))
    assert exc_info.value.code == "doc_request.engagement_not_found"


# ── atomicity ─────────────────────────────────────────────────────────────────


def test_create_request_vat_template_is_atomic(conn, engagement_id):
    """Real insert_request_with_items() rolls back both request and items on mid-batch failure.

    Uses a connection proxy that raises on the 2nd item INSERT so the real
    try/except/rollback branch in the repository is exercised, not a manual simulation.
    """

    class _FailOnSecondItemConn:
        """Thin proxy that raises on the 2nd document_request_items INSERT."""

        def __init__(self, real):
            self._real = real
            self._item_count = 0

        def execute(self, sql, params=()):
            if "INSERT INTO document_request_items" in sql:
                self._item_count += 1
                if self._item_count == 2:
                    raise RuntimeError("simulated 2nd item insert failure")
            return self._real.execute(sql, params)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

    repo = DocumentRequestsRepository(_FailOnSecondItemConn(conn))

    with pytest.raises(RuntimeError, match="simulated 2nd item insert failure"):
        repo.insert_request_with_items(
            engagement_id=engagement_id,
            request_name="atomic request",
            tax_type="vat",
            period_name="2024Q1",
            item_names=VAT_ITEMS,  # 9 items; proxy fails on item [1]
        )

    rows = conn.execute("SELECT id FROM document_requests").fetchall()
    assert len(rows) == 0, "request row must be rolled back"
    item_rows = conn.execute("SELECT id FROM document_request_items").fetchall()
    assert len(item_rows) == 0, "partial item rows must be rolled back too"


# ── request status recompute ──────────────────────────────────────────────────


def test_recompute_all_received_gives_partially_received(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    for item in items:
        svc.set_item_status(item.id, item_status="received")
    updated = svc.get_request(req.id)
    assert updated.status == "partially_received"


def test_recompute_all_accepted_gives_accepted(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    for item in items:
        svc.set_item_status(item.id, item_status="accepted")
    updated = svc.get_request(req.id)
    assert updated.status == "accepted"


def test_recompute_any_invalid_gives_under_validation(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    svc.set_item_status(items[0].id, item_status="received")
    svc.set_item_status(items[1].id, item_status="invalid")
    updated = svc.get_request(req.id)
    assert updated.status == "under_validation"


def test_recompute_pending_confirm_gives_pending_confirm(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    svc.set_item_status(items[0].id, item_status="accepted")
    svc.set_item_status(items[1].id, item_status="pending_confirm")
    updated = svc.get_request(req.id)
    assert updated.status == "pending_confirm"


def test_recompute_mixed_resolved_gives_accepted(svc, engagement_id):
    req, items = svc.create_request(_req_input(engagement_id, item_names=VAT_ITEMS))
    statuses = ["accepted", "not_applicable", "client_said_none"]
    for i, item in enumerate(items):
        svc.set_item_status(item.id, item_status=statuses[i % len(statuses)])
    updated = svc.get_request(req.id)
    assert updated.status == "accepted"


# ── due_date validation ────────────────────────────────────────────────────────

def test_create_request_invalid_due_date_rejected(svc, engagement_id):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.create_request(
            _req_input(engagement_id, due_date="2026-02-31")
        )
    assert exc_info.value.code == "doc_request.due_date.invalid"


def test_create_request_nonsense_due_date_rejected(svc, engagement_id):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.create_request(
            _req_input(engagement_id, due_date="abc")
        )
    assert exc_info.value.code == "doc_request.due_date.invalid"


def test_create_request_valid_due_date_accepted(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id, due_date="2026-06-30"))
    assert req.due_date == "2026-06-30"


# ── Slice 19B: bulk add / update item / delete item ───────────────────────────

def test_add_items_bulk_adds_each_line(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    items = svc.add_items_bulk(req.id, "進項憑證\n銷項發票\n銀行對帳單")
    assert len(items) == 3
    names = [i.item_name for i in items]
    assert "進項憑證" in names
    assert "銷項發票" in names
    assert "銀行對帳單" in names


def test_add_items_bulk_skips_blank_lines(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    items = svc.add_items_bulk(req.id, "A\n\n  \nB")
    assert len(items) == 2


def test_add_items_bulk_trims_whitespace(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    items = svc.add_items_bulk(req.id, "  進項憑證  \n  ")
    assert len(items) == 1
    assert items[0].item_name == "進項憑證"


def test_add_items_bulk_empty_text_raises(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.add_items_bulk(req.id, "   \n  ")
    assert exc_info.value.code == "doc_request_item.bulk.empty"


def test_add_items_bulk_records_audit_per_item(svc, engagement_id, conn):
    req, _ = svc.create_request(_req_input(engagement_id))
    svc.add_items_bulk(req.id, "A\nB")
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request_item.create'"
    ).fetchall()
    assert len(rows) == 2


def test_update_item_changes_name(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "舊名稱")
    updated = svc.update_item(item.id, "新名稱")
    assert updated.item_name == "新名稱"


def test_update_item_empty_name_raises(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "舊名稱")
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.update_item(item.id, "   ")
    assert exc_info.value.code == "doc_request_item.name.required"


def test_update_item_not_found_raises(svc, engagement_id):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.update_item(99999, "名稱")
    assert exc_info.value.code == "doc_request_item.not_found"


def test_update_item_records_audit(svc, engagement_id, conn):
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "舊名稱")
    svc.update_item(item.id, "新名稱")
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request_item.update'"
    ).fetchall()
    assert len(rows) == 1


def test_delete_item_removes_from_list(svc, engagement_id):
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "要刪的")
    svc.delete_item(item.id)
    items = svc.list_items(req.id)
    assert item.id not in {i.id for i in items}


def test_delete_item_not_found_raises(svc, engagement_id):
    with pytest.raises(DocumentRequestValidationError) as exc_info:
        svc.delete_item(99999)
    assert exc_info.value.code == "doc_request_item.not_found"


def test_delete_item_records_audit(svc, engagement_id, conn):
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "要刪的")
    svc.delete_item(item.id)
    rows = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'doc_request_item.delete'"
    ).fetchall()
    assert len(rows) == 1


def test_delete_item_recomputes_request_status(svc, engagement_id):
    """Deleting an accepted item must recompute request status."""
    req, _ = svc.create_request(_req_input(engagement_id))
    item = svc.add_item(req.id, "項目A")
    svc.set_item_status(item.id, item_status="accepted")
    req_after_accept = svc.get_request(req.id)
    assert req_after_accept.status == "accepted"
    svc.delete_item(item.id)
    req_after_delete = svc.get_request(req.id)
    assert req_after_delete.status == "requested", (
        "Deleting all items must revert request to 'requested', not keep 'accepted'"
    )


def test_delete_all_items_returns_request_to_requested_not_accepted(svc, engagement_id):
    """Empty item set must not be misidentified as accepted."""
    req, _ = svc.create_request(_req_input(engagement_id))
    item1 = svc.add_item(req.id, "甲")
    item2 = svc.add_item(req.id, "乙")
    svc.set_item_status(item1.id, item_status="accepted")
    svc.set_item_status(item2.id, item_status="accepted")
    svc.delete_item(item1.id)
    svc.delete_item(item2.id)
    assert svc.list_items(req.id) == []
    req_final = svc.get_request(req.id)
    assert req_final.status == "requested", (
        "frozenset() is subset of any set — guard must prevent empty set from returning 'accepted'"
    )
