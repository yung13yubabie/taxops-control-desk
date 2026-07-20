"""Typed, bounded persistence for annual tax and fee transactions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


EXACT_SUM_AGGREGATE = "annual_exact_int_sum"
EXACT_DECIMAL_SUM_AGGREGATE = "annual_exact_decimal_sum"
EXACT_BALANCE_RISK_FUNCTION = "annual_exact_balance_risk"
EXACT_BALANCE_VALUE_FUNCTION = "annual_exact_balance_value"
ANNUAL_OVERVIEW_RISKS = frozenset(
    {
        "exception",
        "document_missing",
        "collection_shortfall",
        "unpaid_tax",
        "outstanding_fee",
        "overage",
    }
)


class ExactIntegerSum:
    """SQLite aggregate that never narrows Python integers to int64 or float."""

    def __init__(self) -> None:
        self._total = 0

    def step(self, value: object) -> None:
        if value is None:
            return
        if type(value) is not int:
            raise TypeError("annual exact sum requires an integer")
        self._total += value

    def finalize(self) -> str:
        # Returning decimal text avoids sqlite3 converting an out-of-int64
        # Python integer back into SQLite INTEGER before repository decoding.
        return str(self._total)


class ExactDecimalSum:
    """Sum canonical decimal text without SQLite numeric coercion."""

    def __init__(self) -> None:
        self._total = 0

    def step(self, value: object) -> None:
        if value is not None:
            self._total += _canonical_decimal_int(value)

    def finalize(self) -> str:
        return str(self._total)


@dataclass(frozen=True)
class AnnualTransactionRow:
    id: int
    work_item_id: int
    category: str
    amount: int
    transaction_date: str
    reference: str | None
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class AnnualBalance:
    tax_liability: int = 0
    client_tax_collection: int = 0
    tax_payment: int = 0
    tax_credit_or_refund: int = 0
    fee_receivable: int = 0
    fee_receipt: int = 0
    collection_shortfall: int = 0
    unpaid_tax: int = 0
    outstanding_fee: int = 0
    excess_client_collection: int = 0
    tax_overpayment: int = 0
    fee_overpayment: int = 0

    @classmethod
    def from_totals(
        cls,
        *,
        tax_liability: int,
        client_tax_collection: int,
        tax_payment: int,
        tax_credit_or_refund: int,
        fee_receivable: int,
        fee_receipt: int,
    ) -> AnnualBalance:
        return cls(
            tax_liability=tax_liability,
            client_tax_collection=client_tax_collection,
            tax_payment=tax_payment,
            tax_credit_or_refund=tax_credit_or_refund,
            fee_receivable=fee_receivable,
            fee_receipt=fee_receipt,
            collection_shortfall=max(
                0, tax_liability - tax_credit_or_refund - client_tax_collection
            ),
            unpaid_tax=max(0, tax_liability - tax_credit_or_refund - tax_payment),
            outstanding_fee=max(0, fee_receivable - fee_receipt),
            excess_client_collection=max(
                0, tax_credit_or_refund + client_tax_collection - tax_liability
            ),
            tax_overpayment=max(
                0, tax_credit_or_refund + tax_payment - tax_liability
            ),
            fee_overpayment=max(0, fee_receipt - fee_receivable),
        )

    @property
    def client_collection_shortfall(self) -> int:
        """Compatibility name used by the accepted implementation plan."""
        return self.collection_shortfall

    @property
    def liability(self) -> int:
        return self.tax_liability

    @property
    def collected(self) -> int:
        return self.client_tax_collection

    @property
    def paid(self) -> int:
        return self.tax_payment

    @property
    def credits(self) -> int:
        return self.tax_credit_or_refund

    @property
    def fees(self) -> int:
        return self.fee_receivable

    @property
    def fee_receipts(self) -> int:
        return self.fee_receipt


def _canonical_decimal_int(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("annual exact decimal text required")
    if value != "0" and (not value.isdigit() or value.startswith("0")):
        raise ValueError("annual exact decimal text is not canonical")
    return int(value)


def decode_annual_exact_decimal(value: object) -> int:
    """Decode trusted aggregate text or raise a stable database data error."""
    try:
        return _canonical_decimal_int(value)
    except ValueError as exc:
        raise sqlite3.DataError("annual exact aggregate result invalid") from exc


def _annual_exact_balance_risk(
    risk: object,
    work_status: object,
    document_status: object,
    tax_liability: object,
    client_tax_collection: object,
    tax_payment: object,
    tax_credit_or_refund: object,
    fee_receivable: object,
    fee_receipt: object,
) -> int:
    if not isinstance(risk, str) or risk not in ANNUAL_OVERVIEW_RISKS:
        raise ValueError("annual overview risk is not allowlisted")
    if not isinstance(work_status, str) or not isinstance(document_status, str):
        raise ValueError("annual overview status text required")
    balance = _balance_from_decimal_totals(
        tax_liability,
        client_tax_collection,
        tax_payment,
        tax_credit_or_refund,
        fee_receivable,
        fee_receipt,
    )
    return int(
        (risk == "exception" and work_status in {"exception", "completed_with_exception"})
        or (
            risk == "document_missing"
            and document_status in {"missing", "partially_received"}
        )
        or (risk == "collection_shortfall" and balance.collection_shortfall > 0)
        or (risk == "unpaid_tax" and balance.unpaid_tax > 0)
        or (risk == "outstanding_fee" and balance.outstanding_fee > 0)
        or (
            risk == "overage"
            and any(
                amount > 0
                for amount in (
                    balance.excess_client_collection,
                    balance.tax_overpayment,
                    balance.fee_overpayment,
                )
            )
        )
    )


def _balance_from_decimal_totals(
    tax_liability: object,
    client_tax_collection: object,
    tax_payment: object,
    tax_credit_or_refund: object,
    fee_receivable: object,
    fee_receipt: object,
) -> AnnualBalance:
    return AnnualBalance.from_totals(
        tax_liability=_canonical_decimal_int(tax_liability),
        client_tax_collection=_canonical_decimal_int(client_tax_collection),
        tax_payment=_canonical_decimal_int(tax_payment),
        tax_credit_or_refund=_canonical_decimal_int(tax_credit_or_refund),
        fee_receivable=_canonical_decimal_int(fee_receivable),
        fee_receipt=_canonical_decimal_int(fee_receipt),
    )


def _annual_exact_balance_value(
    metric: object,
    tax_liability: object,
    client_tax_collection: object,
    tax_payment: object,
    tax_credit_or_refund: object,
    fee_receivable: object,
    fee_receipt: object,
) -> str:
    if metric not in {"collection_shortfall", "unpaid_tax", "outstanding_fee"}:
        raise ValueError("annual balance metric is not allowlisted")
    balance = _balance_from_decimal_totals(
        tax_liability,
        client_tax_collection,
        tax_payment,
        tax_credit_or_refund,
        fee_receivable,
        fee_receipt,
    )
    return str(getattr(balance, metric))


def register_annual_exact_sqlite_functions(conn: sqlite3.Connection) -> None:
    """Register annual-money helpers on one SQLite connection.

    SQLite functions are connection-local. Re-registering the same helper is
    supported by ``sqlite3`` and keeps repository construction deterministic on
    fresh or independently opened connections.
    """
    conn.create_aggregate(EXACT_SUM_AGGREGATE, 1, ExactIntegerSum)
    conn.create_aggregate(EXACT_DECIMAL_SUM_AGGREGATE, 1, ExactDecimalSum)
    conn.create_function(
        EXACT_BALANCE_RISK_FUNCTION,
        9,
        _annual_exact_balance_risk,
        deterministic=True,
    )
    conn.create_function(
        EXACT_BALANCE_VALUE_FUNCTION,
        7,
        _annual_exact_balance_value,
        deterministic=True,
    )


def _positive_id(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(code)
    return value


def _row(value: sqlite3.Row) -> AnnualTransactionRow:
    return AnnualTransactionRow(
        id=int(value["id"]),
        work_item_id=int(value["work_item_id"]),
        category=str(value["category"]),
        amount=int(value["amount"]),
        transaction_date=str(value["transaction_date"]),
        reference=value["reference"],
        notes=value["notes"],
        created_at=str(value["created_at"]),
        updated_at=str(value["updated_at"]),
        deleted_at=value["deleted_at"],
    )


class AnnualTransactionsRepository:
    _SORT_COLUMNS = {
        "id": "id",
        "transaction_date": "transaction_date",
        "category": "category",
        "amount": "amount",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        register_annual_exact_sqlite_functions(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def get(
        self, transaction_id: int, *, include_deleted: bool = False
    ) -> AnnualTransactionRow | None:
        transaction_id = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        if type(include_deleted) is not bool:
            raise ValueError("annual_transactions.include_deleted.invalid")
        clause = "" if include_deleted else " AND deleted_at IS NULL"
        value = self._conn.execute(
            f"SELECT * FROM annual_work_transactions WHERE id = ?{clause}",
            (transaction_id,),
        ).fetchone()
        return _row(value) if value is not None else None

    def list(
        self,
        work_item_id: int,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "transaction_date",
        order_dir: str = "ASC",
    ) -> list[AnnualTransactionRow]:
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        if type(include_deleted) is not bool:
            raise ValueError("annual_transactions.include_deleted.invalid")
        if (
            type(limit) is not int
            or not 1 <= limit <= 500
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise ValueError("annual_transactions.pagination.invalid")
        if type(order_by) is not str or order_by not in self._SORT_COLUMNS:
            raise ValueError("annual_transactions.sort.invalid")
        if type(order_dir) is not str or order_dir.upper() not in {"ASC", "DESC"}:
            raise ValueError("annual_transactions.sort.invalid")
        deleted_clause = "" if include_deleted else " AND deleted_at IS NULL"
        column = self._SORT_COLUMNS[order_by]
        direction = order_dir.upper()
        values = self._conn.execute(
            "SELECT * FROM annual_work_transactions WHERE work_item_id = ?"
            f"{deleted_clause} ORDER BY {column} {direction}, id {direction} "
            "LIMIT ? OFFSET ?",
            (work_item_id, limit, offset),
        ).fetchall()
        return [_row(value) for value in values]

    def list_for_work_item(
        self, work_item_id: int, **kwargs: object
    ) -> list[AnnualTransactionRow]:
        return self.list(work_item_id, **kwargs)

    def active_work_item_exists(self, work_item_id: int) -> bool:
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        row = self._conn.execute(
            "SELECT 1 FROM annual_work_items awi "
            "JOIN annual_workspaces aw ON aw.id = awi.workspace_id "
            "JOIN clients c ON c.id = aw.client_id "
            "WHERE awi.id = ? AND awi.deleted_at IS NULL "
            "AND aw.deleted_at IS NULL AND c.deleted_at IS NULL",
            (work_item_id,),
        ).fetchone()
        return row is not None

    def insert(
        self,
        work_item_id: int,
        category: str,
        amount: int,
        transaction_date: str,
        reference: str | None,
        notes: str | None,
    ) -> AnnualTransactionRow:
        timestamp = now_iso()
        cursor = self._conn.execute(
            "INSERT INTO annual_work_transactions("
            "work_item_id, category, amount, transaction_date, reference, notes, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                work_item_id,
                category,
                amount,
                transaction_date,
                reference,
                notes,
                timestamp,
                timestamp,
            ),
        )
        value = self.get(int(cursor.lastrowid))
        if value is None:
            raise RuntimeError("annual_transactions.insert.missing")
        return value

    def update(
        self,
        transaction_id: int,
        category: str,
        amount: int,
        transaction_date: str,
        reference: str | None,
        notes: str | None,
    ) -> AnnualTransactionRow:
        timestamp = now_iso()
        cursor = self._conn.execute(
            "UPDATE annual_work_transactions SET category = ?, amount = ?, "
            "transaction_date = ?, reference = ?, notes = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (
                category,
                amount,
                transaction_date,
                reference,
                notes,
                timestamp,
                transaction_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_transactions.not_found")
        value = self.get(transaction_id)
        if value is None:
            raise RuntimeError("annual_transactions.not_found")
        return value

    def soft_delete(self, transaction_id: int) -> AnnualTransactionRow:
        timestamp = now_iso()
        cursor = self._conn.execute(
            "UPDATE annual_work_transactions SET deleted_at = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (timestamp, timestamp, transaction_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_transactions.already_deleted")
        value = self.get(transaction_id, include_deleted=True)
        if value is None:
            raise RuntimeError("annual_transactions.not_found")
        return value

    def restore(self, transaction_id: int) -> AnnualTransactionRow:
        cursor = self._conn.execute(
            "UPDATE annual_work_transactions SET deleted_at = NULL, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (now_iso(), transaction_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("annual_transactions.already_active")
        value = self.get(transaction_id)
        if value is None:
            raise RuntimeError("annual_transactions.not_found")
        return value

    def balance(self, work_item_id: int) -> AnnualBalance:
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        value = self._conn.execute(
            "SELECT "
            "COALESCE(annual_exact_int_sum(CASE WHEN category='tax_liability' "
            "THEN amount ELSE 0 END), '0') AS liability, "
            "COALESCE(annual_exact_int_sum(CASE "
            "WHEN category='client_tax_collection' "
            "THEN amount ELSE 0 END), '0') AS collected, "
            "COALESCE(annual_exact_int_sum(CASE WHEN category='tax_payment' "
            "THEN amount ELSE 0 END), '0') AS paid, "
            "COALESCE(annual_exact_int_sum(CASE "
            "WHEN category='tax_credit_or_refund' "
            "THEN amount ELSE 0 END), '0') AS credits, "
            "COALESCE(annual_exact_int_sum(CASE WHEN category='fee_receivable' "
            "THEN amount ELSE 0 END), '0') AS fees, "
            "COALESCE(annual_exact_int_sum(CASE WHEN category='fee_receipt' "
            "THEN amount ELSE 0 END), '0') AS fee_receipts "
            "FROM annual_work_transactions "
            "WHERE work_item_id = ? AND deleted_at IS NULL",
            (work_item_id,),
        ).fetchone()
        if value is None:
            raise RuntimeError("annual_transactions.balance.failed")
        liability = decode_annual_exact_decimal(value["liability"])
        collected = decode_annual_exact_decimal(value["collected"])
        paid = decode_annual_exact_decimal(value["paid"])
        credits = decode_annual_exact_decimal(value["credits"])
        fees = decode_annual_exact_decimal(value["fees"])
        receipts = decode_annual_exact_decimal(value["fee_receipts"])
        return AnnualBalance.from_totals(
            tax_liability=liability,
            client_tax_collection=collected,
            tax_payment=paid,
            tax_credit_or_refund=credits,
            fee_receivable=fees,
            fee_receipt=receipts,
        )
