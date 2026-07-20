from __future__ import annotations

import sqlite3

import pytest

from taxops.db.connection import open_connection
from taxops.repositories.annual_work import AnnualWorkRepository
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.annual_work import AnnualWorkError, AnnualWorkValidationError


def _work_item(
    container: object,
    *,
    code: str,
    name: str = "年度總覽測試客戶",
    operation_year: int = 2026,
) -> object:
    client_id = getattr(container, "clients").create_client(
        CreateClientInput(client_code=code, client_name=name)
    ).id
    getattr(container, "compliance_profiles").upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    annual_work = getattr(container, "annual_work")
    drafts = annual_work.preview(client_id, operation_year)
    return annual_work.confirm_preview(client_id, operation_year, drafts).items[0]


def _add_transactions(
    container: object,
    item_id: int,
    amounts: dict[str, int],
) -> None:
    add = getattr(container, "annual_transactions").add
    for category, amount in amounts.items():
        add(item_id, category, amount, "2026-05-10")


def test_overview_row_contains_exact_balance_in_one_pure_ledger_select(
    container: object,
) -> None:
    item = _work_item(container, code="OVERVIEW-EXACT")
    _add_transactions(
        container,
        item.id,
        {
            "tax_liability": 62_000,
            "client_tax_collection": 43_400,
            "tax_payment": 40_000,
            "fee_receivable": 5_000,
            "fee_receipt": 2_000,
        },
    )
    conn: sqlite3.Connection = getattr(container, "conn")
    before_audits = getattr(container, "audit")._repo.count()
    before_changes = conn.total_changes
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        rows = getattr(container, "annual_work").search_overview(
            {"query": "OVERVIEW-EXACT"}
        )
    finally:
        conn.set_trace_callback(None)

    assert len(rows) == 1
    assert (
        rows[0].balance.tax_liability,
        rows[0].balance.client_tax_collection,
        rows[0].balance.tax_payment,
        rows[0].balance.tax_credit_or_refund,
        rows[0].balance.fee_receivable,
        rows[0].balance.fee_receipt,
        rows[0].balance.collection_shortfall,
        rows[0].balance.unpaid_tax,
        rows[0].balance.outstanding_fee,
    ) == (62_000, 43_400, 40_000, 0, 5_000, 2_000, 18_600, 22_000, 3_000)
    ledger_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        and "ANNUAL_WORK_TRANSACTIONS" in statement.upper()
    ]
    assert len(ledger_selects) == 1
    assert "TOTAL(" not in ledger_selects[0].upper()
    plan = conn.execute("EXPLAIN QUERY PLAN " + ledger_selects[0]).fetchall()
    assert any(
        "idx_annual_transactions_work_item" in str(step[3]) for step in plan
    )
    assert conn.total_changes == before_changes
    assert getattr(container, "audit")._repo.count() == before_audits


def test_overview_risk_allowlist_matches_status_and_exact_money_risks(
    container: object,
) -> None:
    annual_work = getattr(container, "annual_work")

    exception = _work_item(container, code="RISK-EXCEPTION")
    annual_work.set_work_status(exception.id, "exception")
    missing = _work_item(container, code="RISK-DOC-MISSING")
    annual_work.set_document_status(missing.id, "missing")
    partial = _work_item(container, code="RISK-DOC-PARTIAL")
    annual_work.set_document_status(partial.id, "partially_received")

    shortfall = _work_item(container, code="RISK-SHORTFALL")
    _add_transactions(
        container,
        shortfall.id,
        {
            "tax_liability": 10,
            "client_tax_collection": 9,
            "tax_payment": 10,
        },
    )
    unpaid = _work_item(container, code="RISK-UNPAID")
    _add_transactions(
        container,
        unpaid.id,
        {
            "tax_liability": 10,
            "client_tax_collection": 10,
            "tax_payment": 9,
        },
    )
    fee = _work_item(container, code="RISK-FEE")
    _add_transactions(
        container, fee.id, {"fee_receivable": 10, "fee_receipt": 9}
    )
    overage = _work_item(container, code="RISK-OVERAGE")
    _add_transactions(container, overage.id, {"fee_receipt": 1})

    deleted_only = _work_item(container, code="RISK-DELETED")
    transaction = getattr(container, "annual_transactions").add(
        deleted_only.id, "tax_liability", 99, "2026-05-10"
    )
    getattr(container, "annual_transactions").delete(transaction.id, "測試刪除")

    expected = {
        "exception": {"RISK-EXCEPTION"},
        "document_missing": {"RISK-DOC-MISSING", "RISK-DOC-PARTIAL"},
        "collection_shortfall": {"RISK-SHORTFALL"},
        "unpaid_tax": {"RISK-UNPAID"},
        "outstanding_fee": {"RISK-FEE"},
        "overage": {"RISK-OVERAGE"},
    }
    for risk, client_codes in expected.items():
        assert {
            row.client_code
            for row in annual_work.search_overview({"risk": risk})
        } == client_codes

    deleted_row = annual_work.search_overview({"query": "RISK-DELETED"})[0]
    assert deleted_row.balance == type(deleted_row.balance)()
    with pytest.raises(AnnualWorkValidationError, match="^annual_work.filters.invalid$"):
        annual_work.search_overview({"risk": "tax_status; DROP TABLE clients"})


def test_overview_metrics_sum_per_item_risks_with_filters_in_one_select(
    container: object,
) -> None:
    annual_work = getattr(container, "annual_work")
    deficit = _work_item(container, code="METRIC-DEFICIT")
    annual_work.set_work_status(deficit.id, "exception")
    annual_work.set_document_status(deficit.id, "missing")
    _add_transactions(
        container,
        deficit.id,
        {"tax_liability": 100, "fee_receivable": 50},
    )
    surplus = _work_item(container, code="METRIC-SURPLUS")
    _add_transactions(
        container,
        surplus.id,
        {
            "client_tax_collection": 100,
            "tax_payment": 100,
            "fee_receipt": 50,
        },
    )

    conn: sqlite3.Connection = getattr(container, "conn")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        metrics = annual_work.overview_metrics(
            {
                "operation_year": 2026,
                "query": "METRIC-",
                "order_by": "client_name",
                "order_dir": "DESC",
            }
        )
    finally:
        conn.set_trace_callback(None)

    assert (
        metrics.item_count,
        metrics.client_count,
        metrics.exception_count,
        metrics.document_risk_count,
        metrics.collection_shortfall_total,
        metrics.unpaid_tax_total,
        metrics.outstanding_fee_total,
        metrics.overage_count,
    ) == (2, 2, 1, 1, 100, 100, 50, 1)
    ledger_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        and "ANNUAL_WORK_TRANSACTIONS" in statement.upper()
    ]
    assert len(ledger_selects) == 1
    assert "TOTAL(" not in ledger_selects[0].upper()

    overage = annual_work.overview_metrics({"risk": "overage"})
    assert overage.item_count == 1
    assert overage.overage_count == 1
    assert overage.collection_shortfall_total == 0
    empty = annual_work.overview_metrics({"query": "NO-SUCH-CLIENT"})
    assert empty == type(empty)()
    with pytest.raises(AnnualWorkValidationError, match="^annual_work.filters.invalid$"):
        annual_work.overview_metrics({"limit": 1})


def test_overview_money_risk_udf_is_exact_above_int64_when_difference_is_one(
    container: object,
) -> None:
    conn: sqlite3.Connection = getattr(container, "conn")
    statement = (
        "SELECT annual_exact_balance_risk("
        "'collection_shortfall', 'not_started', 'complete', ?, ?, '0', '0', '0', '0')"
    )
    liability = "9223380000000000000"
    assert conn.execute(
        statement, (liability, "9223379999999999999")
    ).fetchone()[0] == 1
    assert conn.execute(statement, (liability, liability)).fetchone()[0] == 0


def test_overview_fresh_connection_registers_exact_helpers(
    container: object,
) -> None:
    item = _work_item(container, code="OVERVIEW-FRESH-CONN")
    _add_transactions(container, item.id, {"tax_liability": 2, "tax_payment": 1})
    conn: sqlite3.Connection = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    fresh = open_connection(db_path)
    try:
        repository = AnnualWorkRepository(fresh)
        rows = repository.search_overview(
            {"risk": "unpaid_tax", "query": "OVERVIEW-FRESH-CONN"}
        )
    finally:
        fresh.close()
    assert len(rows) == 1
    assert rows[0].balance.unpaid_tax == 1


def test_overview_service_pagination_metrics_and_active_unknown_rows_are_consistent(
    container: object,
) -> None:
    annual_work = getattr(container, "annual_work")
    first = _work_item(container, code="PAGE-ONE")
    second = _work_item(container, code="PAGE-TWO")
    hidden = _work_item(container, code="PAGE-HIDDEN")
    conn: sqlite3.Connection = getattr(container, "conn")
    conn.execute(
        "UPDATE annual_work_items SET work_status = 'future_review' WHERE id = ?",
        (second.id,),
    )
    conn.execute(
        "UPDATE annual_work_items SET deleted_at = '2026-07-20' WHERE id = ?",
        (hidden.id,),
    )
    conn.commit()

    filters = {"query": "PAGE-", "order_by": "id", "order_dir": "ASC"}
    metrics = annual_work.overview_metrics(filters)
    first_page = annual_work.search_overview(filters, limit=1, offset=0)
    second_page = annual_work.search_overview(filters, limit=1, offset=1)
    assert metrics.item_count == 2
    assert [first_page[0].item.id, second_page[0].item.id] == [first.id, second.id]
    assert second_page[0].item.work_status == "future_review"
    with pytest.raises(
        AnnualWorkValidationError, match="^annual_work.pagination.invalid$"
    ):
        annual_work.search_overview(filters, limit=101)


def test_overview_metrics_udf_failure_has_stable_sanitized_service_error(
    container: object,
) -> None:
    _work_item(container, code="METRIC-UDF-FAIL")

    class BrokenAggregate:
        def step(self, value: object) -> None:
            pass

        def finalize(self) -> str:
            return "SECRET overview aggregate result"

    getattr(container, "conn").create_aggregate(
        "annual_exact_decimal_sum", 1, BrokenAggregate
    )
    with pytest.raises(AnnualWorkError) as caught:
        getattr(container, "annual_work").overview_metrics(
            {"query": "METRIC-UDF-FAIL"}
        )
    assert caught.value.code == "annual_work.overview.failed"
    assert "SECRET" not in str(caught.value)
