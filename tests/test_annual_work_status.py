from __future__ import annotations

import json
import sqlite3

import pytest

from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.engagements import CreateEngagementInput
from taxops.services.tasks import CreateTaskInput
from taxops.i18n.status_labels import (
    ANNUAL_DOCUMENT_STATUS_LABELS,
    ANNUAL_FEE_STATUS_LABELS,
    ANNUAL_FILING_STATUS_LABELS,
    ANNUAL_TAX_STATUS_LABELS,
    ANNUAL_WORK_STATUS_LABELS,
    UNKNOWN_STATUS_TEXT,
)


def _work_item(container: object):
    client_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code="C-STATUS", client_name="年度狀態測試")
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )
    service = getattr(container, "annual_work")
    result = service.confirm_preview(client_id, 2026, service.preview(client_id, 2026))
    return result.items[0]


def test_filing_status_updates_independently_and_audits(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")

    updated = service.set_filing_status(item.id, "filed")

    assert updated.filing_status == "filed"
    assert updated.work_status == item.work_status
    assert updated.document_status == item.document_status
    assert updated.tax_status == item.tax_status
    assert updated.fee_status == item.fee_status
    assert updated.title == item.title
    row = getattr(container, "conn").execute(
        "SELECT action, detail_json FROM audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["action"] == "annual_work.filing_status.update"
    assert json.loads(row["detail_json"]) == {
        "from_status": "not_filed",
        "to_status": "filed",
    }


@pytest.mark.parametrize(
    ("method", "field", "allowed"),
    [
        ("set_work_status", "work_status", ("not_started", "in_progress", "exception", "not_applicable")),
        ("set_filing_status", "filing_status", ("not_filed", "filed", "filing_failed", "correction_required")),
        ("set_document_status", "document_status", ("not_requested", "missing", "partially_received", "complete", "not_applicable")),
        ("set_tax_status", "tax_status", ("unconfirmed", "awaiting_collection", "partially_collected", "collected", "paid", "unpaid", "refund", "not_applicable")),
        ("set_fee_status", "fee_status", ("not_billed", "awaiting_payment", "partially_paid", "paid", "not_applicable")),
    ],
)
def test_each_status_accepts_exact_frozen_values_and_preserves_other_fields(
    container: object, method: str, field: str, allowed: tuple[str, ...]
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    status_fields = {"work_status", "filing_status", "document_status", "tax_status", "fee_status"}
    for status in allowed:
        before = service.repository.get_item(item.id)
        updated = getattr(service, method)(item.id, status)
        assert getattr(updated, field) == status
        for other in status_fields - {field}:
            assert getattr(updated, other) == getattr(before, other)
        assert updated.title == before.title
        assert updated.notes == before.notes


@pytest.mark.parametrize(
    ("method", "field"),
    [
        ("set_work_status", "work_status"),
        ("set_filing_status", "filing_status"),
        ("set_document_status", "document_status"),
        ("set_tax_status", "tax_status"),
        ("set_fee_status", "fee_status"),
    ],
)
@pytest.mark.parametrize("invalid", [None, 1, "", " filed", "FILED", "future_status"])
def test_status_setters_reject_mistyped_or_nonexact_values(
    container: object, method: str, field: str, invalid: object
) -> None:
    item = _work_item(container)
    before = getattr(item, field)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(getattr(container, "annual_work"), method)(item.id, invalid)
    assert caught.value.code == f"annual_work.{field}.invalid"
    assert getattr(getattr(container, "annual_work").repository.get_item(item.id), field) == before


@pytest.mark.parametrize("blocked", ["completed", "completed_with_exception", "cancelled"])
def test_work_status_setter_cannot_bypass_completion_or_cancellation(
    container: object, blocked: str
) -> None:
    item = _work_item(container)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").set_work_status(item.id, blocked)
    assert caught.value.code == "annual_work.work_status.transition_required"


def test_same_status_is_truthful_noop_without_audit_or_timestamp_change(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    before_audits = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    unchanged = getattr(container, "annual_work").set_filing_status(item.id, item.filing_status)
    assert unchanged == item
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == before_audits


def test_status_mutation_fails_fast_without_owning_caller_transaction(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) VALUES ('INFO', 'caller', '2026-07-19')"
    )
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").set_tax_status(item.id, "paid")
    assert caught.value.code == "annual_work.transaction.already_active"
    assert conn.in_transaction is True
    conn.rollback()


def test_status_audit_failure_rolls_back_business_update(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_status_audit BEFORE INSERT ON audit_logs "
        "BEGIN SELECT RAISE(ABORT, 'private raw failure'); END"
    )
    conn.commit()
    with pytest.raises(AnnualWorkError) as caught:
        getattr(container, "annual_work").set_tax_status(item.id, "paid")
    assert caught.value.code == "annual_work.status.update_failed"
    assert "private raw failure" not in str(caught.value)
    assert getattr(container, "annual_work").repository.get_item(item.id).tax_status == "unconfirmed"


@pytest.mark.parametrize(
    ("setter", "risk_status"),
    [
        ("set_filing_status", "filing_failed"),
        ("set_filing_status", "correction_required"),
        ("set_document_status", "missing"),
        ("set_document_status", "partially_received"),
        ("set_tax_status", "unconfirmed"),
        ("set_tax_status", "awaiting_collection"),
        ("set_tax_status", "partially_collected"),
        ("set_tax_status", "unpaid"),
        ("set_fee_status", "awaiting_payment"),
        ("set_fee_status", "partially_paid"),
    ],
)
def test_completion_with_each_open_risk_requires_reason_and_preserves_multiline(
    container: object, setter: str, risk_status: str
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    getattr(service, setter)(item.id, risk_status)
    before = service.repository.get_item(item.id)
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.complete_item(item.id, exception_reason=" \n ")
    assert caught.value.code == "annual_work.exception_reason.required"
    reason = "客戶資料尚待補正\n主管已知悉"
    completed = service.complete_item(item.id, exception_reason=reason)
    assert completed.work_status == "completed_with_exception"
    assert completed.exception_reason == reason
    assert completed.completed_at is not None
    assert completed.filing_status == before.filing_status
    assert completed.document_status == before.document_status
    assert completed.tax_status == before.tax_status
    assert completed.fee_status == before.fee_status


def test_completion_without_open_risk_is_completed_even_when_reason_is_kept(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    reason = "補充說明\n不代表例外完成"
    completed = service.complete_item(item.id, exception_reason=reason)
    assert completed.work_status == "completed"
    assert completed.exception_reason == reason
    assert completed.completed_at is not None


@pytest.mark.parametrize("reason", [1, True, [], "x" * 4001])
def test_completion_rejects_mistyped_or_overlong_reason(
    container: object, reason: object
) -> None:
    item = _work_item(container)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").complete_item(item.id, exception_reason=reason)
    assert caught.value.code == "annual_work.exception_reason.invalid"


def test_repeated_completion_is_stable_error_without_fake_audit(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    service.complete_item(item.id)
    conn = getattr(container, "conn")
    before = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.complete'"
    ).fetchone()[0]
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.complete_item(item.id)
    assert caught.value.code == "annual_work.item.already_completed"
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.complete'"
    ).fetchone()[0] == before


def test_work_status_reopen_clears_completion_metadata(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    service.complete_item(item.id, exception_reason="完成補充")
    reopened = service.set_work_status(item.id, "in_progress")
    assert reopened.work_status == "in_progress"
    assert reopened.completed_at is None
    assert reopened.exception_reason is None


def test_cancel_preserves_independent_states_and_exact_multiline_reason(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_filing_status(item.id, "filed")
    service.set_document_status(item.id, "partially_received")
    service.set_tax_status(item.id, "partially_collected")
    service.set_fee_status(item.id, "partially_paid")
    reason = "客戶停止委任\n保留原始說明  "
    cancelled = service.cancel_item(item.id, reason)
    assert cancelled.work_status == "cancelled"
    assert cancelled.cancelled_at is not None
    assert cancelled.completed_at is None
    assert cancelled.exception_reason == reason
    assert (
        cancelled.filing_status,
        cancelled.document_status,
        cancelled.tax_status,
        cancelled.fee_status,
    ) == ("filed", "partially_received", "partially_collected", "partially_paid")


@pytest.mark.parametrize("reason", [None, 1, True, "", " \n ", "x" * 4001])
def test_cancel_rejects_missing_mistyped_blank_or_overlong_reason(
    container: object, reason: object
) -> None:
    item = _work_item(container)
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").cancel_item(item.id, reason)
    expected = "annual_work.cancel_reason.required" if isinstance(reason, str) and not reason.strip() else "annual_work.cancel_reason.invalid"
    assert caught.value.code == expected


def test_same_cancel_reason_is_noop_but_changed_reason_is_audited(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    first = service.cancel_item(item.id, "原理由")
    conn = getattr(container, "conn")
    audit_count = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.cancel'"
    ).fetchone()[0]
    same = service.cancel_item(item.id, "原理由")
    assert same == first
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.cancel'"
    ).fetchone()[0] == audit_count
    changed = service.cancel_item(item.id, "新理由\n第二行")
    assert changed.exception_reason == "新理由\n第二行"
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.cancel'"
    ).fetchone()[0] == audit_count + 1


def test_restore_only_cancelled_item_and_clears_cancellation_reason(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    service.cancel_item(item.id, "取消理由")
    restored = service.restore_item(item.id)
    assert restored.work_status == "not_started"
    assert restored.cancelled_at is None
    assert restored.exception_reason is None
    assert restored.tax_status == "paid"
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.restore_item(item.id)
    assert caught.value.code == "annual_work.item.not_cancelled"


def test_hard_delete_physically_removes_history_free_active_item_and_audits(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.delete_item(item.id)
    assert service.repository.get_item(item.id) is None
    row = getattr(container, "conn").execute(
        "SELECT action, target_id FROM audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (row["action"], row["target_id"]) == ("annual_work.delete", str(item.id))
    with pytest.raises(AnnualWorkValidationError) as caught:
        service.restore_item(item.id)
    assert caught.value.code == "annual_work.item_not_found"


@pytest.mark.parametrize("dependency", ["transaction", "engagement", "task"])
def test_hard_delete_blocks_all_retained_history_without_cancelling(
    container: object, dependency: str
) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    client_id = conn.execute(
        "SELECT aw.client_id FROM annual_workspaces aw JOIN annual_work_items awi "
        "ON aw.id = awi.workspace_id WHERE awi.id = ?", (item.id,)
    ).fetchone()[0]
    if dependency == "transaction":
        conn.execute(
            "INSERT INTO annual_work_transactions(work_item_id, category, amount, transaction_date, created_at, updated_at) "
            "VALUES (?, 'tax_liability', 0, '2026-07-19', '2026-07-19', '2026-07-19')",
            (item.id,),
        )
    elif dependency == "engagement":
        engagement = getattr(container, "engagements").create_engagement(
            CreateEngagementInput(client_id, "年度申報委任", "vat", "2026")
        )
        conn.execute("UPDATE annual_work_items SET engagement_id = ? WHERE id = ?", (engagement.id, item.id))
    else:
        task = getattr(container, "tasks").create_task(
            CreateTaskInput(None, "年度工作追蹤", client_id=client_id)
        )
        conn.execute("UPDATE workflow_tasks SET annual_work_item_id = ? WHERE id = ?", (item.id, task.id))
    conn.commit()
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").delete_item(item.id)
    assert caught.value.code == "annual_work.delete.has_history"
    assert getattr(container, "annual_work").repository.get_item(item.id).work_status == "not_started"


def test_engagement_blocker_covers_document_and_attachment_history_by_contract(
    container: object,
) -> None:
    """Requests/attachments are engagement-owned, so any engagement link blocks delete."""
    item = _work_item(container)
    conn = getattr(container, "conn")
    client_id = conn.execute(
        "SELECT client_id FROM annual_workspaces WHERE id = ?", (item.workspace_id,)
    ).fetchone()[0]
    engagement = getattr(container, "engagements").create_engagement(
        CreateEngagementInput(client_id, "含憑證歷史", "vat", "2026")
    )
    conn.execute("UPDATE annual_work_items SET engagement_id = ? WHERE id = ?", (engagement.id, item.id))
    conn.commit()
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").delete_item(item.id)
    assert caught.value.code == "annual_work.delete.has_history"


def test_delete_audit_failure_rolls_back_physical_delete(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_delete_audit BEFORE INSERT ON audit_logs "
        "BEGIN SELECT RAISE(ABORT, 'private delete failure'); END"
    )
    conn.commit()
    with pytest.raises(AnnualWorkError) as caught:
        getattr(container, "annual_work").delete_item(item.id)
    assert caught.value.code == "annual_work.delete.failed"
    assert getattr(container, "annual_work").repository.get_item(item.id) is not None


def test_cancelled_item_rejects_status_completion_and_hard_delete(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.cancel_item(item.id, "停止")
    for call in (
        lambda: service.set_tax_status(item.id, "paid"),
        lambda: service.complete_item(item.id, exception_reason="說明"),
        lambda: service.delete_item(item.id),
    ):
        with pytest.raises(AnnualWorkValidationError) as caught:
            call()
        assert caught.value.code == "annual_work.item.cancelled"


def test_all_frozen_annual_statuses_have_dimension_specific_chinese_labels() -> None:
    assert set(ANNUAL_WORK_STATUS_LABELS) == {
        "not_started", "in_progress", "completed", "completed_with_exception",
        "exception", "not_applicable", "cancelled",
    }
    assert set(ANNUAL_FILING_STATUS_LABELS) == {
        "not_filed", "filed", "filing_failed", "correction_required",
    }
    assert set(ANNUAL_DOCUMENT_STATUS_LABELS) == {
        "not_requested", "missing", "partially_received", "complete", "not_applicable",
    }
    assert set(ANNUAL_TAX_STATUS_LABELS) == {
        "unconfirmed", "awaiting_collection", "partially_collected", "collected",
        "paid", "unpaid", "refund", "not_applicable",
    }
    assert set(ANNUAL_FEE_STATUS_LABELS) == {
        "not_billed", "awaiting_payment", "partially_paid", "paid", "not_applicable",
    }
    assert ANNUAL_TAX_STATUS_LABELS["paid"] != ANNUAL_FEE_STATUS_LABELS["paid"]


def test_unknown_stored_status_is_preserved_and_presented_with_sanitized_log(
    container: object,
) -> None:
    item = _work_item(container)
    raw = "future\nsecret" + "x" * 200
    conn = getattr(container, "conn")
    conn.execute("UPDATE annual_work_items SET tax_status = ? WHERE id = ?", (raw, item.id))
    conn.commit()
    presentation = getattr(container, "annual_work").get_status_presentation(item.id)
    assert presentation.tax_status_label == UNKNOWN_STATUS_TEXT
    assert presentation.work_status_label == ANNUAL_WORK_STATUS_LABELS["not_started"]
    assert getattr(container, "annual_work").repository.get_item(item.id).tax_status == raw
    log = conn.execute(
        "SELECT message, detail_json FROM system_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    detail = json.loads(log["detail_json"])
    assert log["message"] == "annual_work.unknown_status"
    assert detail["dimension"] == "tax_status"
    assert detail["item_id"] == item.id
    assert "\n" not in detail["raw_code"]
    assert len(detail["raw_code"]) <= 120


def test_unknown_label_logging_does_not_commit_caller_transaction(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute("UPDATE annual_work_items SET fee_status = 'future_fee' WHERE id = ?", (item.id,))
    conn.commit()
    before_logs = conn.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0]
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO system_logs(level, message, created_at) VALUES ('INFO', 'caller-owned', '2026-07-19')"
    )
    presentation = getattr(container, "annual_work").get_status_presentation(item.id)
    assert presentation.fee_status_label == UNKNOWN_STATUS_TEXT
    assert conn.in_transaction is True
    assert conn.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0] == before_logs + 2
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0] == before_logs


def test_exception_risk_search_and_strict_status_filters(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    completed = service.complete_item(item.id, exception_reason="稅款仍未確認")
    rows = service.search_overview(risk="exception")
    assert [row.item.id for row in rows] == [completed.id]
    with pytest.raises(ValueError, match="^annual_work.filters.invalid$"):
        service.repository.search_overview({"risk": "unknown"})
    with pytest.raises(ValueError, match="^annual_work.filters.invalid$"):
        service.repository.search_overview({"tax_status": "future_tax"})


@pytest.mark.parametrize("item_id", [True, False, "1", 1.0, 0, -1, None])
@pytest.mark.parametrize(
    "call",
    [
        lambda service, value: service.set_work_status(value, "in_progress"),
        lambda service, value: service.set_filing_status(value, "filed"),
        lambda service, value: service.set_document_status(value, "complete"),
        lambda service, value: service.set_tax_status(value, "paid"),
        lambda service, value: service.set_fee_status(value, "paid"),
        lambda service, value: service.complete_item(value, exception_reason="理由"),
        lambda service, value: service.cancel_item(value, "理由"),
        lambda service, value: service.restore_item(value),
        lambda service, value: service.delete_item(value),
        lambda service, value: service.get_status_presentation(value),
    ],
)
def test_public_item_apis_require_positive_exact_int(
    container: object, item_id: object, call: object
) -> None:
    with pytest.raises(AnnualWorkValidationError) as caught:
        call(getattr(container, "annual_work"), item_id)
    assert caught.value.code == "annual_work.item_id.invalid"


@pytest.mark.parametrize("deleted", ["missing", "item", "workspace", "client"])
def test_mutations_report_missing_or_soft_deleted_item_with_stable_code(
    container: object, deleted: str
) -> None:
    item = _work_item(container)
    item_id = item.id if deleted != "missing" else item.id + 999_999
    conn = getattr(container, "conn")
    if deleted == "item":
        getattr(container, "conn").execute(
            "UPDATE annual_work_items SET deleted_at = '2026-07-19' WHERE id = ?", (item.id,)
        )
    elif deleted == "workspace":
        conn.execute(
            "UPDATE annual_workspaces SET deleted_at = '2026-07-19' WHERE id = ?",
            (item.workspace_id,),
        )
    elif deleted == "client":
        conn.execute(
            "UPDATE clients SET deleted_at = '2026-07-19' WHERE id = "
            "(SELECT client_id FROM annual_workspaces WHERE id = ?)",
            (item.workspace_id,),
        )
    conn.commit()
    with pytest.raises(AnnualWorkValidationError) as caught:
        getattr(container, "annual_work").set_fee_status(item_id, "paid")
    assert caught.value.code == "annual_work.item_not_found"


def test_repository_status_column_allowlist_prevents_sql_identifier_injection(
    container: object,
) -> None:
    item = _work_item(container)
    with pytest.raises(ValueError, match="^annual_work.status_dimension.invalid$"):
        getattr(container, "annual_work").repository.update_status(
            item.id, "tax_status = 'paid'; DROP TABLE clients; --", "paid"
        )
    assert getattr(container, "conn").execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("operation", "action", "failure_code"),
    [
        ("complete", "annual_work.complete", "annual_work.complete.failed"),
        ("cancel", "annual_work.cancel", "annual_work.cancel.failed"),
        ("restore", "annual_work.restore", "annual_work.restore.failed"),
    ],
)
def test_lifecycle_audit_failure_rolls_back_business_state(
    container: object, operation: str, action: str, failure_code: str
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_work")
    service.set_tax_status(item.id, "paid")
    if operation == "restore":
        service.cancel_item(item.id, "先取消")
    before = service.repository.get_item(item.id)
    conn = getattr(container, "conn")
    conn.execute(
        f"CREATE TRIGGER fail_lifecycle_audit BEFORE INSERT ON audit_logs "
        f"WHEN NEW.action = '{action}' BEGIN SELECT RAISE(ABORT, 'raw private'); END"
    )
    conn.commit()
    with pytest.raises(AnnualWorkError) as caught:
        if operation == "complete":
            service.complete_item(item.id)
        elif operation == "cancel":
            service.cancel_item(item.id, "取消")
        else:
            service.restore_item(item.id)
    assert caught.value.code == failure_code
    assert service.repository.get_item(item.id) == before


def test_status_writer_contention_is_stable_and_does_not_partially_write(
    container: object,
) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    locker = sqlite3.connect(db_path)
    locker.execute("PRAGMA busy_timeout = 1")
    conn.execute("PRAGMA busy_timeout = 1")
    locker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(AnnualWorkError) as caught:
            getattr(container, "annual_work").set_tax_status(item.id, "paid")
        assert caught.value.code == "annual_work.transaction.busy"
        assert conn.in_transaction is False
        assert getattr(container, "annual_work").repository.get_item(item.id).tax_status == "unconfirmed"
    finally:
        locker.rollback()
        locker.close()


def test_committed_status_and_audit_are_visible_to_fresh_connection(container: object) -> None:
    item = _work_item(container)
    getattr(container, "annual_work").set_document_status(item.id, "complete")
    conn = getattr(container, "conn")
    fresh = sqlite3.connect(conn.execute("PRAGMA database_list").fetchone()[2])
    try:
        assert fresh.execute(
            "SELECT document_status FROM annual_work_items WHERE id = ?", (item.id,)
        ).fetchone()[0] == "complete"
        assert fresh.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'annual_work.document_status.update' "
            "AND target_id = ?", (str(item.id),)
        ).fetchone()[0] == 1
    finally:
        fresh.close()
