from __future__ import annotations

import json
import sqlite3
import threading

import pytest
import taxops.services.annual_work as annual_work_module
import taxops.repositories.annual_work as annual_work_repository_module
from taxops.repositories.annual_work import AnnualWorkItemVersionConflict
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError
from taxops.services.annual_transactions import (
    AnnualTransactionError,
    AnnualTransactionValidationError,
)
from taxops.i18n.errors import GENERIC_FALLBACK, error_message
from taxops.services.engagements import CreateEngagementInput


def _work_item(container: object):
    client = getattr(container, "clients").create_client(
        CreateClientInput(
            client_code="C-DETAIL",
            client_name="年度工作明細測試",
        )
    )
    getattr(container, "compliance_profiles").upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )
    service = getattr(container, "annual_work")
    result = service.confirm_preview(
        client.id,
        2026,
        service.preview(client.id, 2026),
    )
    return client, result.items[0]


def _payload(item: object, **changes: object):
    values: dict[str, object] = {
        "title": getattr(item, "title"),
        "tax_year": getattr(item, "tax_year"),
        "period_code": getattr(item, "period_code"),
        "due_date": getattr(item, "due_date"),
        "notes": getattr(item, "notes"),
        "work_status": getattr(item, "work_status"),
        "filing_status": getattr(item, "filing_status"),
        "document_status": getattr(item, "document_status"),
        "tax_status": getattr(item, "tax_status"),
        "fee_status": getattr(item, "fee_status"),
        "expected_updated_at": getattr(item, "updated_at"),
    }
    values.update(changes)
    return annual_work_module.UpdateAnnualWorkItemInput(**values)


def _freeze_annual_item_clock(
    monkeypatch: pytest.MonkeyPatch,
    timestamp: str,
) -> None:
    def fixed() -> str:
        return timestamp

    monkeypatch.setattr(annual_work_module, "now_iso", fixed, raising=False)
    monkeypatch.setattr(
        annual_work_repository_module,
        "now_iso",
        fixed,
        raising=False,
    )
    try:
        import taxops.core.version_tokens as version_tokens
    except ModuleNotFoundError:
        return
    monkeypatch.setattr(version_tokens, "now_iso", fixed)


def test_public_detail_context_returns_active_item_client_and_operation_year(
    container: object,
) -> None:
    client, item = _work_item(container)

    context = getattr(container, "annual_work").get_item_context(item.id)

    assert context.item == item
    assert context.client_id == client.id
    assert context.operation_year == 2026


def test_public_detail_context_sanitizes_database_failure(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")

    def fail_read(_item_id: int):
        raise sqlite3.DatabaseError("PRIVATE detail read")

    monkeypatch.setattr(service.repository, "get_item_context", fail_read)
    with pytest.raises(AnnualWorkError) as caught:
        service.get_item_context(item.id)
    assert caught.value.code == "annual_work.item_details.read_failed"
    assert "PRIVATE" not in str(caught.value)


def test_update_item_details_atomically_replaces_metadata_and_five_statuses(
    container: object,
) -> None:
    _client, item = _work_item(container)
    notes = "第一行：客戶要求保留原始說明\n第二行：月底前電話確認\t承辦人"
    update_type = annual_work_module.UpdateAnnualWorkItemInput
    payload = update_type(
        title="營業稅 01–02 月（人工調整）",
        tax_year=2027,
        period_code="01–02",
        due_date="2026-03-16",
        notes=notes,
        work_status="in_progress",
        filing_status="filed",
        document_status="complete",
        tax_status="paid",
        fee_status="awaiting_payment",
        expected_updated_at=item.updated_at,
    )

    updated = getattr(container, "annual_work").update_item_details(
        item.id,
        payload,
    )

    assert (
        updated.title,
        updated.tax_year,
        updated.period_code,
        updated.due_date,
        updated.notes,
    ) == (
        "營業稅 01–02 月（人工調整）",
        2027,
        "01–02",
        "2026-03-16",
        notes,
    )
    assert (
        updated.work_status,
        updated.filing_status,
        updated.document_status,
        updated.tax_status,
        updated.fee_status,
    ) == (
        "in_progress",
        "filed",
        "complete",
        "paid",
        "awaiting_payment",
    )
    assert updated.workspace_id == item.workspace_id
    assert updated.item_key == item.item_key
    assert updated.work_type == item.work_type
    assert updated.suggested_due_date == item.suggested_due_date

    stored = getattr(container, "annual_work").get_item_context(item.id).item
    assert stored == updated
    assert stored.notes == notes
    audit = getattr(container, "conn").execute(
        "SELECT action, detail_json FROM audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit["action"] == "annual_work.item_details.update"
    detail = json.loads(audit["detail_json"])
    assert detail == {
        "changed_fields": [
            "title",
            "tax_year",
            "period_code",
            "due_date",
            "notes",
            "work_status",
            "filing_status",
            "document_status",
            "tax_status",
            "fee_status",
        ]
    }
    assert notes not in audit["detail_json"]


def test_exact_noop_preserves_timestamp_and_does_not_audit(
    container: object,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    before = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]

    unchanged = getattr(container, "annual_work").update_item_details(
        item.id,
        _payload(item),
    )

    assert unchanged == item
    assert unchanged.updated_at == item.updated_at
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == before
    assert conn.in_transaction is False


@pytest.mark.parametrize("item_id", [None, True, 0, -1, "1"])
def test_detail_query_and_update_reject_invalid_item_id(
    container: object,
    item_id: object,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")
    for call in (
        lambda: service.get_item_context(item_id),
        lambda: service.update_item_details(item_id, _payload(item)),
    ):
        with pytest.raises(AnnualWorkValidationError) as caught:
            call()
        assert caught.value.code == "annual_work.item_id.invalid"


def test_update_rejects_untyped_payload_without_opening_transaction(
    container: object,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").update_item_details(item.id, {})
    assert caught.value.code == "annual_work.item_details.invalid"
    assert conn.in_transaction is False


def test_update_fails_fast_without_owning_caller_transaction(
    container: object,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) "
        "VALUES ('INFO', 'caller-owned', '2026-07-23T00:00:00Z')"
    )
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").update_item_details(
            item.id,
            _payload(item, title="不可更新"),
        )
    assert caught.value.code == "annual_work.transaction.already_active"
    assert conn.in_transaction is True
    conn.rollback()


def test_stale_expected_updated_at_rejects_lost_update_without_audit(
    container: object,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")
    first = service.update_item_details(
        item.id,
        _payload(item, title="第一個視窗先儲存"),
    )
    before_audits = getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM audit_logs"
    ).fetchone()[0]

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.update_item_details(
            item.id,
            _payload(item, title="第二個過期視窗不可覆蓋"),
        )

    assert caught.value.code == "annual_work.item_details.stale"
    assert service.get_item_context(item.id).item == first
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM audit_logs"
    ).fetchone()[0] == before_audits


@pytest.mark.parametrize(
    "terminal",
    ["completed", "completed_with_exception", "cancelled"],
)
def test_active_item_cannot_enter_terminal_status_through_composite_update(
    container: object,
    terminal: str,
) -> None:
    _client, item = _work_item(container)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").update_item_details(
            item.id,
            _payload(item, work_status=terminal),
        )
    assert caught.value.code == "annual_work.work_status.transition_required"
    assert getattr(container, "annual_work").get_item_context(item.id).item == item


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"title": ""}, "annual_work.title.invalid"),
        ({"title": "　"}, "annual_work.title.invalid"),
        ({"title": "x" * 501}, "annual_work.title.invalid"),
        ({"title": "不可\n換行"}, "annual_work.title.invalid"),
        ({"title": "不可\u200b隱藏"}, "annual_work.title.invalid"),
        ({"title": "\u0301\ufe0f"}, "annual_work.title.invalid"),
        ({"tax_year": True}, "annual_work.tax_year.invalid"),
        ({"tax_year": 1911}, "annual_work.tax_year.invalid"),
        ({"tax_year": 10000}, "annual_work.tax_year.invalid"),
        ({"period_code": "x" * 51}, "annual_work.period_code.invalid"),
        ({"period_code": "不可\n換行"}, "annual_work.period_code.invalid"),
        ({"period_code": "不可\u202e控制"}, "annual_work.period_code.invalid"),
        ({"due_date": "2026-1-01"}, "annual_work.due_date.invalid"),
        ({"due_date": "2026-02-29"}, "annual_work.due_date.invalid"),
        ({"notes": "x" * 100_001}, "annual_work.notes.invalid"),
        ({"notes": "不可\x00控制"}, "annual_work.notes.invalid"),
        ({"notes": "不可\u2066控制"}, "annual_work.notes.invalid"),
        ({"work_status": "completed"}, "annual_work.work_status.transition_required"),
        ({"work_status": "future"}, "annual_work.work_status.invalid"),
        ({"filing_status": "future"}, "annual_work.filing_status.invalid"),
        ({"document_status": "future"}, "annual_work.document_status.invalid"),
        ({"tax_status": "future"}, "annual_work.tax_status.invalid"),
        ({"fee_status": "future"}, "annual_work.fee_status.invalid"),
        (
            {"expected_updated_at": "bad\nvalue"},
            "annual_work.expected_updated_at.invalid",
        ),
    ],
)
def test_update_validation_rejects_invalid_boundaries_without_writes(
    container: object,
    changes: dict[str, object],
    code: str,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.update_item_details(item.id, _payload(item, **changes))
    assert caught.value.code == code
    assert service.get_item_context(item.id).item == item


def test_optional_boundaries_and_maximum_multiline_notes_roundtrip(
    container: object,
) -> None:
    _client, item = _work_item(container)
    prefix = "繁中第一行\r\n第二行\t說明\n"
    notes = prefix + "註" * (100_000 - len(prefix))
    assert len(notes) == 100_000

    updated = getattr(container, "annual_work").update_item_details(
        item.id,
        _payload(
            item,
            title="標" * 500,
            tax_year=None,
            period_code="期" * 50,
            due_date=None,
            notes=notes,
        ),
    )

    assert updated.title == "標" * 500
    assert updated.tax_year is None
    assert updated.period_code == "期" * 50
    assert updated.due_date is None
    assert updated.notes == notes


@pytest.mark.parametrize("terminal", ["completed", "completed_with_exception", "cancelled"])
def test_terminal_history_allows_metadata_and_other_axis_correction_but_not_transition(
    container: object,
    terminal: str,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")
    if terminal == "completed":
        item = service.set_tax_status(item.id, "paid")
        current = service.complete_item(item.id, exception_reason="歷史原因")
    elif terminal == "completed_with_exception":
        current = service.complete_item(item.id, exception_reason="歷史原因")
    else:
        current = service.cancel_item(item.id, "歷史原因")
    assert current.work_status == terminal

    corrected = service.update_item_details(
        item.id,
        _payload(
            current,
            title="歷史資料更正",
            filing_status="filed",
            notes="保留\n歷史說明",
        ),
    )

    assert corrected.work_status == terminal
    assert corrected.title == "歷史資料更正"
    assert corrected.filing_status == "filed"
    assert corrected.exception_reason == "歷史原因"
    assert corrected.completed_at == current.completed_at
    assert corrected.cancelled_at == current.cancelled_at

    with pytest.raises(AnnualWorkValidationError) as caught:
        service.update_item_details(
            corrected.id,
            _payload(corrected, work_status="in_progress"),
        )
    assert caught.value.code == "annual_work.work_status.transition_required"


@pytest.mark.parametrize("ancestor", ["item", "workspace", "client"])
def test_deleted_item_or_ancestor_is_not_exposed_as_active_detail(
    container: object,
    ancestor: str,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    if ancestor == "item":
        conn.execute(
            "UPDATE annual_work_items SET deleted_at = 'x' WHERE id = ?",
            (item.id,),
        )
    elif ancestor == "workspace":
        conn.execute(
            "UPDATE annual_workspaces SET deleted_at = 'x' WHERE id = ?",
            (item.workspace_id,),
        )
    else:
        conn.execute(
            "UPDATE clients SET deleted_at = 'x' WHERE id = ("
            "SELECT client_id FROM annual_workspaces WHERE id = ?)",
            (item.workspace_id,),
        )
    conn.commit()
    service = getattr(container, "annual_work")
    with pytest.raises(AnnualWorkValidationError) as read_error:
        service.get_item_context(item.id)
    assert read_error.value.code == "annual_work.item_not_found"
    with pytest.raises(AnnualWorkValidationError) as update_error:
        service.update_item_details(item.id, _payload(item, title="不可更新"))
    assert update_error.value.code == "annual_work.item_not_found"


def test_audit_failure_rolls_back_exact_item_update(container: object) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_detail_audit BEFORE INSERT ON audit_logs "
        "WHEN NEW.action = 'annual_work.item_details.update' "
        "BEGIN SELECT RAISE(ABORT, 'PRIVATE NOTES'); END"
    )
    conn.commit()

    with pytest.raises(AnnualWorkError) as caught:
        getattr(container, "annual_work").update_item_details(
            item.id,
            _payload(item, title="不可留下", notes="敏感內容"),
        )

    assert caught.value.code == "annual_work.item_details.update_failed"
    assert "PRIVATE" not in str(caught.value)
    assert getattr(container, "annual_work").get_item_context(item.id).item == item
    assert conn.in_transaction is False


def test_database_failure_rolls_back_exact_item_update(container: object) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_detail_update BEFORE UPDATE ON annual_work_items "
        "WHEN OLD.id = %d BEGIN SELECT RAISE(ABORT, 'PRIVATE DB'); END" % item.id
    )
    conn.commit()

    with pytest.raises(AnnualWorkError) as caught:
        getattr(container, "annual_work").update_item_details(
            item.id,
            _payload(item, title="不可留下"),
        )

    assert caught.value.code == "annual_work.item_details.update_failed"
    assert "PRIVATE" not in str(caught.value)
    assert getattr(container, "annual_work").get_item_context(item.id).item == item
    assert conn.in_transaction is False


def test_writer_lock_returns_stable_busy_without_partial_item_update(
    container: object,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    locker = sqlite3.connect(db_path, timeout=0.01)
    conn.execute("PRAGMA busy_timeout = 1")
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(AnnualWorkError) as caught:
            getattr(container, "annual_work").update_item_details(
                item.id,
                _payload(item, title="不可留下"),
            )
        assert caught.value.code == "annual_work.transaction.busy"
        assert conn.in_transaction is False
    finally:
        locker.rollback()
        locker.close()
    assert getattr(container, "annual_work").get_item_context(item.id).item == item


@pytest.mark.parametrize(
    "operation",
    [
        "work_status",
        "filing_status",
        "document_status",
        "tax_status",
        "fee_status",
        "complete",
        "cancel",
        "restore",
        "reopen",
        "link",
        "unlink",
        "linked_request",
        "linked_task",
    ],
)
def test_every_item_mutation_advances_one_shared_token_and_keeps_old_dto_stale(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    client, item = _work_item(container)
    service = getattr(container, "annual_work")
    engagement = None
    if operation in {"link", "unlink"}:
        engagement = getattr(container, "engagements").create_engagement(
            CreateEngagementInput(
                client_id=client.id,
                engagement_name="版本控制案件",
                tax_type="vat",
                period_name="2026",
            )
        )
    if operation == "unlink":
        item = service.link_existing_engagement(item.id, engagement.id)
    elif operation == "restore":
        item = service.cancel_item(item.id, "先取消再測試復原")
    elif operation == "reopen":
        item = service.complete_item(item.id, exception_reason="先完成再重新開啟")

    _freeze_annual_item_clock(monkeypatch, item.updated_at)
    stale_payload = _payload(item, title="舊視窗不可覆蓋")
    detailed = service.update_item_details(
        item.id,
        _payload(item, title="第一個視窗已儲存"),
    )
    assert detailed.updated_at > item.updated_at

    if operation == "work_status":
        mutated = service.set_work_status(item.id, "in_progress")
    elif operation == "filing_status":
        mutated = service.set_filing_status(item.id, "filed")
    elif operation == "document_status":
        mutated = service.set_document_status(item.id, "complete")
    elif operation == "tax_status":
        mutated = service.set_tax_status(item.id, "paid")
    elif operation == "fee_status":
        mutated = service.set_fee_status(item.id, "paid")
    elif operation == "complete":
        mutated = service.complete_item(
            item.id,
            exception_reason="風險狀態保留完成說明",
        )
    elif operation == "cancel":
        mutated = service.cancel_item(item.id, "使用者確認取消")
    elif operation == "restore":
        mutated = service.restore_item(item.id)
    elif operation == "reopen":
        mutated = service.set_work_status(item.id, "in_progress")
    elif operation == "link":
        mutated = service.link_existing_engagement(item.id, engagement.id)
    elif operation == "unlink":
        mutated = service.unlink_engagement(item.id)
    elif operation == "linked_request":
        mutated = service.create_linked_request(
            item.id,
            request_name="版本控制補件",
            item_names=("發票",),
        ).item
    else:
        service.create_linked_task(item.id, title="版本控制任務")
        mutated = service.get_item_context(item.id).item

    assert mutated.updated_at > detailed.updated_at
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.update_item_details(item.id, stale_payload)
    assert caught.value.code == "annual_work.item_details.stale"
    assert service.get_item_context(item.id).item == mutated


@pytest.mark.parametrize(
    ("operation", "repository_method"),
    [
        ("details", "update_item_details"),
        ("status", "update_status"),
        ("complete", "complete_item"),
        ("cancel", "cancel_item"),
        ("restore", "restore_item"),
        ("reopen", "reopen_item"),
        ("link", "set_engagement_link"),
        ("unlink", "set_engagement_link"),
    ],
)
def test_repository_version_guard_conflict_is_stable_stale_not_generic(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    repository_method: str,
) -> None:
    client, item = _work_item(container)
    service = getattr(container, "annual_work")
    engagement = None
    if operation in {"link", "unlink"}:
        engagement = getattr(container, "engagements").create_engagement(
            CreateEngagementInput(
                client.id,
                "版本衝突案件",
                "vat",
                "2026",
            )
        )
    if operation == "unlink":
        item = service.link_existing_engagement(item.id, engagement.id)
    elif operation == "restore":
        item = service.cancel_item(item.id, "先取消")
    elif operation == "reopen":
        item = service.complete_item(item.id, exception_reason="先完成")

    def conflict(*_args: object, **_kwargs: object):
        raise AnnualWorkItemVersionConflict

    monkeypatch.setattr(service.repository, repository_method, conflict)
    calls = {
        "details": lambda: service.update_item_details(
            item.id,
            _payload(item, title="不可寫入"),
        ),
        "status": lambda: service.set_filing_status(item.id, "filed"),
        "complete": lambda: service.complete_item(
            item.id,
            exception_reason="仍有風險",
        ),
        "cancel": lambda: service.cancel_item(item.id, "取消"),
        "restore": lambda: service.restore_item(item.id),
        "reopen": lambda: service.set_work_status(item.id, "in_progress"),
        "link": lambda: service.link_existing_engagement(
            item.id,
            engagement.id,
        ),
        "unlink": lambda: service.unlink_engagement(item.id),
    }
    with pytest.raises(AnnualWorkValidationError) as caught:
        calls[operation]()
    assert caught.value.code == "annual_work.item_details.stale"
    assert getattr(container, "conn").in_transaction is False


@pytest.mark.parametrize(
    ("operation", "timestamp_field"),
    [("complete", "completed_at"), ("cancel", "cancelled_at")],
)
def test_business_event_time_is_not_replaced_by_future_version_token(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    timestamp_field: str,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_work")
    _freeze_annual_item_clock(monkeypatch, item.updated_at)
    detailed = service.update_item_details(
        item.id,
        _payload(item, title="先推進版本"),
    )
    assert detailed.updated_at > item.updated_at

    if operation == "complete":
        mutated = service.complete_item(
            item.id,
            exception_reason="完成時間應是事件時間",
        )
    else:
        mutated = service.cancel_item(item.id, "取消時間應是事件時間")

    assert mutated.updated_at > detailed.updated_at
    assert getattr(mutated, timestamp_field) == item.updated_at


def test_transaction_page_returns_total_and_one_bounded_snapshot(
    container: object,
) -> None:
    _client, item = _work_item(container)
    _insert_transaction_history(container, item.id, 501)

    page = getattr(container, "annual_transactions").page(
        item.id,
        limit=500,
        offset=0,
        order_by="id",
    )

    assert page.total == 501
    assert page.limit == 500
    assert page.offset == 0
    assert len(page.rows) == 500
    assert page.rows[0].id == 1
    assert page.rows[-1].id == 500
    assert getattr(container, "conn").in_transaction is False


def test_transaction_page_rejects_caller_owned_transaction(
    container: object,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").page(item.id)
    assert caught.value.code == "annual_transactions.transaction.already_active"
    assert conn.in_transaction is True
    conn.rollback()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"limit": 0}, "annual_transactions.pagination.invalid"),
        ({"limit": 501}, "annual_transactions.pagination.invalid"),
        ({"limit": True}, "annual_transactions.pagination.invalid"),
        ({"offset": -1}, "annual_transactions.pagination.invalid"),
        ({"offset": 1_000_001}, "annual_transactions.pagination.invalid"),
        ({"offset": True}, "annual_transactions.pagination.invalid"),
        ({"include_deleted": 1}, "annual_transactions.include_deleted.invalid"),
        (
            {"order_by": "id; DROP TABLE clients"},
            "annual_transactions.sort.invalid",
        ),
        ({"order_dir": "SIDEWAYS"}, "annual_transactions.sort.invalid"),
    ],
)
def test_transaction_page_rejects_invalid_public_query_contract(
    container: object,
    kwargs: dict[str, object],
    code: str,
) -> None:
    _client, item = _work_item(container)
    conn = getattr(container, "conn")
    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").page(item.id, **kwargs)
    assert caught.value.code == code
    assert conn.in_transaction is False


@pytest.mark.parametrize("ancestor", ["item", "workspace", "client"])
def test_transaction_page_keeps_one_snapshot_when_parent_is_deleted_after_check(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
    ancestor: str,
) -> None:
    _client, item = _work_item(container)
    _insert_transaction_history(container, item.id, 3)
    service = getattr(container, "annual_transactions")
    conn = getattr(container, "conn")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    active_checked = threading.Event()
    writer_finished = threading.Event()
    writer_errors: list[BaseException] = []
    original_active_check = service.repository.active_work_item_exists

    def checked_then_wait(work_item_id: int) -> bool:
        active = original_active_check(work_item_id)
        active_checked.set()
        assert writer_finished.wait(timeout=5)
        return active

    def delete_parent() -> None:
        writer = sqlite3.connect(db_path, timeout=3)
        try:
            assert active_checked.wait(timeout=5)
            writer.execute("PRAGMA busy_timeout = 3000")
            if ancestor == "item":
                writer.execute(
                    "UPDATE annual_work_items SET deleted_at = 'race' "
                    "WHERE id = ?",
                    (item.id,),
                )
            elif ancestor == "workspace":
                writer.execute(
                    "UPDATE annual_workspaces SET deleted_at = 'race' "
                    "WHERE id = ?",
                    (item.workspace_id,),
                )
            else:
                writer.execute(
                    "UPDATE clients SET deleted_at = 'race' WHERE id = ("
                    "SELECT client_id FROM annual_workspaces WHERE id = ?)",
                    (item.workspace_id,),
                )
            writer.commit()
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer.close()
            writer_finished.set()

    monkeypatch.setattr(
        service.repository,
        "active_work_item_exists",
        checked_then_wait,
    )
    thread = threading.Thread(target=delete_parent, daemon=True)
    thread.start()
    page = service.page(item.id, limit=2, order_by="id")
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert writer_errors == []
    assert page.total == 3
    assert [row.reference for row in page.rows] == ["REF-0001", "REF-0002"]
    assert conn.in_transaction is False
    assert original_active_check(item.id) is False


def _insert_transaction_history(
    container: object,
    item_id: int,
    count: int,
) -> None:
    getattr(container, "conn").execute(
        "WITH RECURSIVE counter(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM counter WHERE n < ?"
        ") INSERT INTO annual_work_transactions("
        "work_item_id, category, amount, transaction_date, reference, "
        "created_at, updated_at"
        ") SELECT ?, 'tax_liability', n, '2026-01-01', printf('REF-%04d', n), "
        "'2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z' FROM counter",
        (count, item_id),
    )
    getattr(container, "conn").commit()


def test_transaction_count_and_pages_expose_all_history_beyond_500(
    container: object,
) -> None:
    _client, item = _work_item(container)
    _insert_transaction_history(container, item.id, 501)
    service = getattr(container, "annual_transactions")

    assert service.count(item.id) == 501
    first = service.list(item.id, limit=500, offset=0, order_by="id")
    second = service.list(item.id, limit=500, offset=500, order_by="id")

    assert len(first) == 500
    assert len(second) == 1
    assert [row.id for row in first[-1:] + second] == [500, 501]


def test_transaction_count_has_explicit_active_and_deleted_semantics(
    container: object,
) -> None:
    _client, item = _work_item(container)
    _insert_transaction_history(container, item.id, 3)
    conn = getattr(container, "conn")
    conn.execute(
        "UPDATE annual_work_transactions SET deleted_at = '2026-07-23T00:00:00Z' "
        "WHERE work_item_id = ? AND reference = 'REF-0002'",
        (item.id,),
    )
    conn.commit()
    service = getattr(container, "annual_transactions")

    assert service.count(item.id) == 2
    assert service.count(item.id, include_deleted=True) == 3
    assert [row.reference for row in service.list(item.id, order_by="id")] == [
        "REF-0001",
        "REF-0003",
    ]
    assert [
        row.reference
        for row in service.list(item.id, include_deleted=True, order_by="id")
    ] == ["REF-0001", "REF-0002", "REF-0003"]


@pytest.mark.parametrize("include_deleted", [None, 0, 1, "yes"])
def test_transaction_count_rejects_invalid_deleted_flag(
    container: object,
    include_deleted: object,
) -> None:
    _client, item = _work_item(container)
    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").count(
            item.id,
            include_deleted=include_deleted,
        )
    assert caught.value.code == "annual_transactions.include_deleted.invalid"


def test_transaction_count_and_list_reject_deleted_parent_instead_of_fake_empty(
    container: object,
) -> None:
    _client, item = _work_item(container)
    _insert_transaction_history(container, item.id, 1)
    conn = getattr(container, "conn")
    conn.execute(
        "UPDATE annual_work_items SET deleted_at = '2026-07-23T00:00:00Z' "
        "WHERE id = ?",
        (item.id,),
    )
    conn.commit()
    service = getattr(container, "annual_transactions")
    for call in (
        lambda: service.count(item.id),
        lambda: service.list(item.id),
    ):
        with pytest.raises(AnnualTransactionValidationError) as caught:
            call()
        assert caught.value.code == "annual_transactions.work_item_not_found"


@pytest.mark.parametrize("operation", ["list", "count"])
def test_transaction_page_reads_sanitize_database_failures(
    container: object,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _client, item = _work_item(container)
    service = getattr(container, "annual_transactions")

    def fail_active_check(_item_id: int) -> bool:
        raise sqlite3.DatabaseError("PRIVATE ledger failure")

    monkeypatch.setattr(
        service.repository,
        "active_work_item_exists",
        fail_active_check,
    )
    with pytest.raises(AnnualTransactionError) as caught:
        getattr(service, operation)(item.id)
    assert getattr(caught.value, "code", None) == (
        f"annual_transactions.{operation}.failed"
    )
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize(
    "code",
    [
        "annual_work.item_details.invalid",
        "annual_work.title.invalid",
        "annual_work.tax_year.invalid",
        "annual_work.period_code.invalid",
        "annual_work.due_date.invalid",
        "annual_work.notes.invalid",
        "annual_work.expected_updated_at.invalid",
        "annual_work.item_details.stale",
        "annual_work.item_details.read_failed",
        "annual_work.item_details.update_failed",
        "annual_work.item.updated_at.invalid",
        "annual_work.item_not_found",
        "annual_transactions.include_deleted.invalid",
        "annual_transactions.pagination.invalid",
        "annual_transactions.work_item_not_found",
        "annual_transactions.list.failed",
        "annual_transactions.count.failed",
    ],
)
def test_new_detail_and_pagination_errors_have_visible_chinese_messages(
    code: str,
) -> None:
    message = error_message(code)
    assert message != GENERIC_FALLBACK
    assert any("\u4e00" <= char <= "\u9fff" for char in message)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("annual_work.item_id.invalid", "年度工作識別碼不正確"),
        (
            "annual_work.transaction.already_active",
            "目前已有資料操作進行中，請完成後再試",
        ),
        (
            "annual_work.work_status.transition_required",
            "完成、取消或重新開啟必須使用對應的專用操作",
        ),
        ("annual_work.transaction.busy", "資料庫忙碌中，請稍後再試"),
        ("annual_work.work_status.invalid", "工作狀態不正確"),
        ("annual_work.filing_status.invalid", "申報狀態不正確"),
        ("annual_work.document_status.invalid", "文件狀態不正確"),
        ("annual_work.tax_status.invalid", "稅款狀態不正確"),
        ("annual_work.fee_status.invalid", "服務費狀態不正確"),
        ("annual_transactions.work_item_id.invalid", "年度工作識別碼不正確"),
        ("annual_transactions.transaction_id.invalid", "交易紀錄識別碼不正確"),
        ("annual_transactions.category.invalid", "交易類別不正確"),
        ("annual_transactions.amount.invalid", "交易金額不正確"),
        (
            "annual_transactions.date.invalid",
            "交易日期格式不正確，請使用 YYYY-MM-DD",
        ),
        (
            "annual_transactions.reference.invalid",
            "交易參考資訊過長或包含不安全字元",
        ),
        (
            "annual_transactions.notes.invalid",
            "交易備註過長或包含不安全字元",
        ),
        (
            "annual_transactions.delete_reason.invalid",
            "刪除交易時必須填寫有效原因",
        ),
        (
            "annual_transactions.transaction.already_active",
            "目前已有交易資料操作進行中，請完成後再試",
        ),
        ("annual_transactions.sort.invalid", "交易歷史排序條件不正確"),
        ("annual_transactions.transaction.busy", "交易資料庫忙碌中，請稍後再試"),
        (
            "annual_transactions.transaction_not_found",
            "找不到指定的交易紀錄",
        ),
        ("annual_transactions.already_deleted", "此交易紀錄已刪除"),
        ("annual_transactions.already_active", "此交易紀錄已是有效狀態"),
        ("annual_transactions.add.failed", "新增交易紀錄失敗，資料未變更"),
        ("annual_transactions.update.failed", "更新交易紀錄失敗，資料未變更"),
        ("annual_transactions.delete.failed", "刪除交易紀錄失敗，資料未變更"),
        ("annual_transactions.restore.failed", "復原交易紀錄失敗，資料未變更"),
        ("annual_transactions.balance.failed", "計算交易餘額失敗，請稍後再試"),
        ("annual_transactions.page.failed", "讀取交易歷史頁面失敗，請稍後再試"),
    ],
)
def test_public_detail_and_transaction_errors_have_exact_chinese_messages(
    code: str,
    message: str,
) -> None:
    assert error_message(code) == message
