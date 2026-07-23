from __future__ import annotations

import json
import sqlite3

import pytest
import taxops.services.annual_work as annual_work_module
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError
from taxops.services.annual_transactions import (
    AnnualTransactionError,
    AnnualTransactionValidationError,
)
from taxops.i18n.errors import GENERIC_FALLBACK, error_message


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


def test_public_detail_context_returns_active_item_client_and_operation_year(
    container: object,
) -> None:
    client, item = _work_item(container)

    context = getattr(container, "annual_work").get_item_context(item.id)

    assert context.item == item
    assert context.client_id == client.id
    assert context.operation_year == 2026


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
