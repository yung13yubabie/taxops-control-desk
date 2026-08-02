from __future__ import annotations

import json
import sqlite3

import pytest

from taxops.repositories.annual_transactions import AnnualTransactionsRepository
from taxops.services.annual_transactions import (
    AnnualTransactionError,
    AnnualTransactionValidationError,
)
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput


def _work_item(container: object, *, code: str = "C-TX") -> object:
    client_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code=code, client_name="交易測試客戶")
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    service = getattr(container, "annual_work")
    drafts = service.preview(client_id, 2026)
    return service.confirm_preview(client_id, 2026, drafts).items[0]


def test_tax_and_fee_balances_are_independent(container: object) -> None:
    item = _work_item(container)
    add = getattr(container, "annual_transactions").add
    add(item.id, "tax_liability", 62_000, "2026-05-10")
    add(item.id, "client_tax_collection", 43_400, "2026-05-12")
    add(item.id, "tax_payment", 40_000, "2026-05-15")
    add(item.id, "fee_receivable", 5_000, "2026-05-01")
    add(item.id, "fee_receipt", 2_000, "2026-05-13")

    balance = getattr(container, "annual_transactions").balance(item.id)

    assert balance.tax_liability == 62_000
    assert balance.client_tax_collection == 43_400
    assert balance.tax_payment == 40_000
    assert balance.tax_credit_or_refund == 0
    assert balance.fee_receivable == 5_000
    assert balance.fee_receipt == 2_000
    assert balance.collection_shortfall == 18_600
    assert balance.unpaid_tax == 22_000
    assert balance.outstanding_fee == 3_000


def test_empty_balance_remains_all_zero(container: object) -> None:
    item = _work_item(container)

    balance = getattr(container, "annual_transactions").balance(item.id)

    assert (
        balance.tax_liability,
        balance.client_tax_collection,
        balance.tax_payment,
        balance.tax_credit_or_refund,
        balance.fee_receivable,
        balance.fee_receipt,
        balance.collection_shortfall,
        balance.unpaid_tax,
        balance.outstanding_fee,
        balance.excess_client_collection,
        balance.tax_overpayment,
        balance.fee_overpayment,
    ) == (0,) * 12


def test_all_six_categories_zero_large_refund_and_overpayments(container: object) -> None:
    item = _work_item(container)
    add = getattr(container, "annual_transactions").add
    for category, amount in (
        ("tax_liability", 1),
        ("client_tax_collection", 4),
        ("tax_payment", 5),
        ("tax_credit_or_refund", 2),
        ("fee_receivable", 0),
        ("fee_receipt", 9_000_000_000_000),
    ):
        add(item.id, category, amount, "2026-01-01")

    balance = getattr(container, "annual_transactions").balance(item.id)

    assert balance.collection_shortfall == 0
    assert balance.unpaid_tax == 0
    assert balance.outstanding_fee == 0
    assert balance.excess_client_collection == 5
    assert balance.tax_overpayment == 6
    assert balance.fee_overpayment == 9_000_000_000_000


def test_each_add_is_a_new_business_event_without_payload_deduplication(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    values = (item.id, "tax_liability", 100, "2026-01-01", "同一憑證", "同一備註")

    first = service.add(*values)
    second = service.add(*values)

    assert first.id != second.id
    assert service.balance(item.id).tax_liability == 200


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("work_item_id", True, "annual_transactions.work_item_id.invalid"),
        ("work_item_id", 0, "annual_transactions.work_item_id.invalid"),
        ("category", "unknown", "annual_transactions.category.invalid"),
        ("category", 1, "annual_transactions.category.invalid"),
        ("amount", True, "annual_transactions.amount.invalid"),
        ("amount", 1.0, "annual_transactions.amount.invalid"),
        ("amount", -1, "annual_transactions.amount.invalid"),
        ("amount", 9_000_000_000_001, "annual_transactions.amount.invalid"),
        ("transaction_date", "2026-1-1", "annual_transactions.date.invalid"),
        ("transaction_date", "2026-02-29", "annual_transactions.date.invalid"),
        ("transaction_date", True, "annual_transactions.date.invalid"),
    ],
)
def test_add_rejects_invalid_types_and_boundaries_without_writes(
    container: object, field: str, value: object, code: str
) -> None:
    item = _work_item(container)
    payload: dict[str, object] = {
        "work_item_id": item.id,
        "category": "tax_liability",
        "amount": 0,
        "transaction_date": "2026-01-01",
    }
    payload[field] = value

    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").add(**payload)

    assert caught.value.code == code
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM annual_work_transactions"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("reference", 1, "annual_transactions.reference.invalid"),
        ("reference", "r" * 501, "annual_transactions.reference.invalid"),
        ("reference", "bad\x00", "annual_transactions.reference.invalid"),
        ("reference", "bad\x1f", "annual_transactions.reference.invalid"),
        ("reference", "bad\x7f", "annual_transactions.reference.invalid"),
        ("reference", "bad\u202e", "annual_transactions.reference.invalid"),
        ("reference", "bad\u2066", "annual_transactions.reference.invalid"),
        ("reference", "bad\u200b", "annual_transactions.reference.invalid"),
        ("notes", 1, "annual_transactions.notes.invalid"),
        ("notes", "n" * 4001, "annual_transactions.notes.invalid"),
        ("notes", "bad\x85", "annual_transactions.notes.invalid"),
    ],
)
def test_text_fields_reject_mistyped_overlength_and_unsafe_control_values(
    container: object, field: str, value: object, code: str
) -> None:
    item = _work_item(container)
    payload: dict[str, object] = {
        "work_item_id": item.id,
        "category": "tax_liability",
        "amount": 1,
        "transaction_date": "2026-01-01",
        field: value,
    }
    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").add(**payload)
    assert caught.value.code == code


def test_reference_and_notes_preserve_exact_multiline_whitespace(container: object) -> None:
    item = _work_item(container)
    reference = "  發票🧾\r\n第二行\t " + "r" * 479
    notes = "  備註🧾\n第二行\r第三行\t " + "n" * 3974

    row = getattr(container, "annual_transactions").add(
        item.id, "tax_liability", 0, "2026-01-01", reference, notes
    )

    assert row.reference == reference
    assert row.notes == notes


def test_update_is_full_replacement_and_exact_noop_does_not_write_or_audit(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    row = service.add(
        item.id, "tax_liability", 10, "2026-01-01", "ref", "notes"
    )
    audit_count = getattr(container, "audit")._repo.count()

    unchanged = service.update(
        row.id, "tax_liability", 10, "2026-01-01", "ref", "notes"
    )

    assert unchanged.updated_at == row.updated_at
    assert getattr(container, "audit")._repo.count() == audit_count

    changed = service.update(
        row.id, "fee_receivable", 20, "2026-02-02", None, None
    )
    assert (changed.category, changed.amount, changed.transaction_date) == (
        "fee_receivable",
        20,
        "2026-02-02",
    )
    assert changed.reference is None
    assert changed.notes is None


def test_delete_restore_recalculate_and_repeated_operations_are_stable(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    row = service.add(item.id, "tax_liability", 100, "2026-01-01")
    reason = "  重複輸入\r\n保留原文\t "

    deleted = service.delete(row.id, reason)
    assert deleted.deleted_at is not None
    assert service.balance(item.id).tax_liability == 0
    with pytest.raises(AnnualTransactionValidationError) as repeated_delete:
        service.delete(row.id, reason)
    assert repeated_delete.value.code == "annual_transactions.already_deleted"

    restored = service.restore(row.id)
    assert restored.deleted_at is None
    assert service.balance(item.id).tax_liability == 100
    with pytest.raises(AnnualTransactionValidationError) as repeated_restore:
        service.restore(row.id)
    assert repeated_restore.value.code == "annual_transactions.already_active"

    detail = json.loads(
        getattr(container, "conn").execute(
            "SELECT detail_json FROM audit_logs WHERE action = 'annual_transaction.delete'"
        ).fetchone()[0]
    )
    assert detail["reason"] == reason


@pytest.mark.parametrize("reason", [None, "", " \r\n\t", True, "x" * 4001, "bad\x00"])
def test_delete_reason_is_required_exact_string_and_bounded(
    container: object, reason: object
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    row = service.add(item.id, "tax_liability", 1, "2026-01-01")
    with pytest.raises(AnnualTransactionValidationError) as caught:
        service.delete(row.id, reason)
    assert caught.value.code == "annual_transactions.delete_reason.invalid"
    assert service.get(row.id) is not None


def test_audit_never_contains_reference_or_notes(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    secret_reference = "PRIVATE-REF"
    secret_notes = "PRIVATE\nNOTES"
    row = service.add(
        item.id,
        "tax_liability",
        1,
        "2026-01-01",
        secret_reference,
        secret_notes,
    )
    service.update(
        row.id,
        "tax_payment",
        2,
        "2026-01-02",
        secret_reference,
        secret_notes,
    )
    service.delete(row.id, "刪除原因")
    service.restore(row.id)
    details = [
        value[0] or ""
        for value in getattr(container, "conn").execute(
            "SELECT detail_json FROM audit_logs "
            "WHERE action IN ('annual_transaction.add', 'annual_transaction.update', "
            "'annual_transaction.delete', 'annual_transaction.restore')"
        ).fetchall()
    ]
    assert all(secret_reference not in detail for detail in details)
    assert all(secret_notes not in detail for detail in details)
    assert all("reference" not in detail and "notes" not in detail for detail in details)


def test_audit_failure_rolls_back_mutation_with_sanitized_error(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_annual_audit BEFORE INSERT ON audit_logs "
        "WHEN NEW.action = 'annual_transaction.add' "
        "BEGIN SELECT RAISE(ABORT, 'SECRET audit detail'); END"
    )
    conn.commit()

    with pytest.raises(AnnualTransactionError) as caught:
        getattr(container, "annual_transactions").add(
            item.id, "tax_liability", 1, "2026-01-01"
        )

    assert caught.value.code == "annual_transactions.add.failed"
    assert "SECRET" not in str(caught.value)
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM annual_work_transactions").fetchone()[0] == 0


def test_update_audit_failure_restores_exact_previous_row(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    original = service.add(
        item.id, "tax_liability", 10, "2026-01-01", "private ref", "private notes"
    )
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_update_audit BEFORE INSERT ON audit_logs "
        "WHEN NEW.action = 'annual_transaction.update' "
        "BEGIN SELECT RAISE(ABORT, 'SECRET update detail'); END"
    )
    conn.commit()

    with pytest.raises(AnnualTransactionError) as caught:
        service.update(
            original.id, "tax_payment", 20, "2026-02-02", "new ref", "new notes"
        )

    assert caught.value.code == "annual_transactions.update.failed"
    assert "SECRET" not in str(caught.value)
    assert service.get(original.id) == original
    assert service.balance(item.id).tax_liability == 10
    assert service.balance(item.id).tax_payment == 0
    assert conn.in_transaction is False


def test_delete_audit_failure_keeps_transaction_active(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    original = service.add(
        item.id, "tax_liability", 10, "2026-01-01", "private ref", "private notes"
    )
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_delete_audit BEFORE INSERT ON audit_logs "
        "WHEN NEW.action = 'annual_transaction.delete' "
        "BEGIN SELECT RAISE(ABORT, 'SECRET delete detail'); END"
    )
    conn.commit()

    with pytest.raises(AnnualTransactionError) as caught:
        service.delete(original.id, "  精確\r\n多行原因\t ")

    assert caught.value.code == "annual_transactions.delete.failed"
    assert "SECRET" not in str(caught.value)
    assert service.get(original.id) == original
    assert service.balance(item.id).tax_liability == 10
    assert conn.in_transaction is False


def test_restore_audit_failure_keeps_transaction_deleted(container: object) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    original = service.add(
        item.id, "tax_liability", 10, "2026-01-01", "private ref", "private notes"
    )
    deleted = service.delete(original.id, "先刪除")
    conn = getattr(container, "conn")
    conn.execute(
        "CREATE TRIGGER fail_restore_audit BEFORE INSERT ON audit_logs "
        "WHEN NEW.action = 'annual_transaction.restore' "
        "BEGIN SELECT RAISE(ABORT, 'SECRET restore detail'); END"
    )
    conn.commit()

    with pytest.raises(AnnualTransactionError) as caught:
        service.restore(original.id)

    assert caught.value.code == "annual_transactions.restore.failed"
    assert "SECRET" not in str(caught.value)
    assert service.get(original.id) is None
    assert service.get(original.id, include_deleted=True) == deleted
    assert service.balance(item.id).tax_liability == 0
    assert conn.in_transaction is False


def test_caller_transaction_fails_fast_without_touching_it(container: object) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")

    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").add(
            item.id, "tax_liability", 1, "2026-01-01"
        )

    assert caught.value.code == "annual_transactions.transaction.already_active"
    assert conn.in_transaction is True
    conn.rollback()


def test_cancelled_and_completed_items_accept_historical_corrections(
    container: object,
) -> None:
    for index, status in enumerate(("cancelled", "completed"), start=1):
        item = _work_item(container, code=f"C-TX-{index}")
        conn = getattr(container, "conn")
        conn.execute(
            "UPDATE annual_work_items SET work_status = ? WHERE id = ?",
            (status, item.id),
        )
        conn.commit()
        row = getattr(container, "annual_transactions").add(
            item.id, "tax_liability", index, "2026-01-01"
        )
        assert row.amount == index


@pytest.mark.parametrize("ancestor", ["item", "workspace", "client"])
def test_deleted_item_or_ancestor_blocks_mutation(
    container: object, ancestor: str
) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    if ancestor == "item":
        conn.execute("UPDATE annual_work_items SET deleted_at = 'x' WHERE id = ?", (item.id,))
    elif ancestor == "workspace":
        conn.execute("UPDATE annual_workspaces SET deleted_at = 'x' WHERE id = ?", (item.workspace_id,))
    else:
        conn.execute(
            "UPDATE clients SET deleted_at = 'x' WHERE id = ("
            "SELECT client_id FROM annual_workspaces WHERE id = ?)",
            (item.workspace_id,),
        )
    conn.commit()
    with pytest.raises(AnnualTransactionValidationError) as caught:
        getattr(container, "annual_transactions").add(
            item.id, "tax_liability", 1, "2026-01-01"
        )
    assert caught.value.code == "annual_transactions.work_item_not_found"


def test_repository_get_list_are_typed_bounded_sorted_and_parameterized(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    later = service.add(item.id, "tax_payment", 2, "2026-02-01")
    earlier = service.add(item.id, "tax_liability", 1, "2026-01-01")
    repo = AnnualTransactionsRepository(getattr(container, "conn"))
    assert repo.get(earlier.id) == earlier
    assert [row.id for row in repo.list(item.id, limit=1)] == [earlier.id]
    assert [row.id for row in repo.list(item.id, order_dir="DESC")] == [later.id, earlier.id]
    service.delete(earlier.id, "刪除")
    assert repo.get(earlier.id) is None
    assert repo.get(earlier.id, include_deleted=True) is not None

    for kwargs in (
        {"limit": True},
        {"limit": 0},
        {"offset": True},
        {"offset": -1},
        {"order_by": "id; DROP TABLE clients"},
        {"order_dir": "ASC; DROP TABLE clients"},
        {"include_deleted": 1},
    ):
        with pytest.raises(ValueError):
            repo.list(item.id, **kwargs)
    assert getattr(container, "conn").execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 1


def test_committed_transaction_is_visible_from_another_connection(container: object) -> None:
    item = _work_item(container)
    row = getattr(container, "annual_transactions").add(
        item.id, "tax_liability", 7, "2026-01-01"
    )
    db_path = getattr(container, "conn").execute("PRAGMA database_list").fetchone()[2]
    other = sqlite3.connect(db_path)
    other.row_factory = sqlite3.Row
    try:
        other_repo = AnnualTransactionsRepository(other)
        assert other_repo.get(row.id) == row
        assert other_repo.balance(item.id).tax_liability == 7
    finally:
        other.close()


def test_writer_lock_returns_stable_busy_error_without_partial_write(
    container: object,
) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    locker = sqlite3.connect(db_path, timeout=0.01)
    conn.execute("PRAGMA busy_timeout = 1")
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(AnnualTransactionError) as caught:
            getattr(container, "annual_transactions").add(
                item.id, "tax_liability", 1, "2026-01-01"
            )
        assert caught.value.code == "annual_transactions.transaction.busy"
        assert conn.in_transaction is False
    finally:
        locker.rollback()
        locker.close()
    assert conn.execute("SELECT COUNT(*) FROM annual_work_transactions").fetchone()[0] == 0


def test_balance_is_pure_read_and_uses_one_aggregate_transaction_select(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    service.add(item.id, "tax_liability", 10, "2026-01-01")
    conn = getattr(container, "conn")
    before_status = conn.execute(
        "SELECT work_status, filing_status, document_status, tax_status, fee_status, updated_at "
        "FROM annual_work_items WHERE id = ?",
        (item.id,),
    ).fetchone()
    before_audits = getattr(container, "audit")._repo.count()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        service.balance(item.id)
    finally:
        conn.set_trace_callback(None)
    transaction_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "FROM annual_work_transactions" in statement
    ]
    assert len(transaction_selects) == 1
    assert "ANNUAL_EXACT_INT_SUM(CASE" in transaction_selects[0].upper()
    assert "TOTAL(" not in transaction_selects[0].upper()
    assert conn.execute(
        "SELECT work_status, filing_status, document_status, tax_status, fee_status, updated_at "
        "FROM annual_work_items WHERE id = ?",
        (item.id,),
    ).fetchone() == before_status
    assert getattr(container, "audit")._repo.count() == before_audits


def test_balance_exactly_aggregates_more_than_signed_int64_in_one_select(
    container: object,
) -> None:
    item = _work_item(container)
    conn = getattr(container, "conn")
    conn.execute(
        "WITH RECURSIVE counter(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM counter WHERE n < ?"
        ") INSERT INTO annual_work_transactions("
        "work_item_id, category, amount, transaction_date, created_at, updated_at"
        ") SELECT ?, 'tax_liability', 9000000000000, '2026-01-01', "
        "'2026-01-01T00:00:00', '2026-01-01T00:00:00' FROM counter",
        (1_024_820, item.id),
    )
    conn.commit()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        balance = getattr(container, "annual_transactions").balance(item.id)
    finally:
        conn.set_trace_callback(None)

    assert balance.tax_liability == 9_223_380_000_000_000_000
    transaction_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "FROM annual_work_transactions" in statement
    ]
    assert len(transaction_selects) == 1
    assert "ANNUAL_EXACT_INT_SUM" in transaction_selects[0].upper()
    assert "TOTAL(" not in transaction_selects[0].upper()


def test_exact_aggregate_failure_has_stable_sanitized_service_error(
    container: object,
) -> None:
    item = _work_item(container)
    service = getattr(container, "annual_transactions")
    service.add(item.id, "tax_liability", 1, "2026-01-01")

    class BrokenAggregate:
        def step(self, value: object) -> None:
            raise RuntimeError("SECRET aggregate failure")

        def finalize(self) -> str:
            return "0"

    getattr(container, "conn").create_aggregate(
        "annual_exact_int_sum", 1, BrokenAggregate
    )
    with pytest.raises(AnnualTransactionError) as caught:
        service.balance(item.id)
    assert caught.value.code == "annual_transactions.balance.failed"
    assert "SECRET" not in str(caught.value)
