"""Typed, bounded persistence for annual tax and fee transactions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


EXACT_SUM_AGGREGATE = "annual_exact_int_sum"


class _ExactIntegerSum:
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
    tax_liability: int
    client_tax_collection: int
    tax_payment: int
    tax_credit_or_refund: int
    fee_receivable: int
    fee_receipt: int
    collection_shortfall: int
    unpaid_tax: int
    outstanding_fee: int
    excess_client_collection: int
    tax_overpayment: int
    fee_overpayment: int

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
        self._conn.create_aggregate(EXACT_SUM_AGGREGATE, 1, _ExactIntegerSum)

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
        liability = int(value["liability"])
        collected = int(value["collected"])
        paid = int(value["paid"])
        credits = int(value["credits"])
        fees = int(value["fees"])
        receipts = int(value["fee_receipts"])
        return AnnualBalance(
            tax_liability=liability,
            client_tax_collection=collected,
            tax_payment=paid,
            tax_credit_or_refund=credits,
            fee_receivable=fees,
            fee_receipt=receipts,
            collection_shortfall=max(0, liability - credits - collected),
            unpaid_tax=max(0, liability - credits - paid),
            outstanding_fee=max(0, fees - receipts),
            excess_client_collection=max(0, credits + collected - liability),
            tax_overpayment=max(0, credits + paid - liability),
            fee_overpayment=max(0, receipts - fees),
        )
