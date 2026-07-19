"""Audited annual transaction mutations and ledger-derived balances."""

from __future__ import annotations

import sqlite3
from datetime import date

from ..repositories.annual_transactions import (
    AnnualBalance,
    AnnualTransactionRow,
    AnnualTransactionsRepository,
)
from .audit import AuditService


CATEGORIES = frozenset(
    {
        "tax_liability",
        "client_tax_collection",
        "tax_payment",
        "tax_credit_or_refund",
        "fee_receivable",
        "fee_receipt",
    }
)
MAX_AMOUNT = 9_000_000_000_000


class AnnualTransactionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AnnualTransactionValidationError(AnnualTransactionError):
    """Caller input or the referenced active domain object is invalid."""


def _positive_id(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise AnnualTransactionValidationError(code)
    return value


def _text(
    value: object, *, code: str, maximum: int, optional: bool
) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise AnnualTransactionValidationError(code)
    if len(value) > maximum:
        raise AnnualTransactionValidationError(code)
    for char in value:
        ordinal = ord(char)
        if ordinal == 0 or ordinal == 127 or 128 <= ordinal <= 159:
            raise AnnualTransactionValidationError(code)
        if ordinal < 32 and char not in "\t\n\r":
            raise AnnualTransactionValidationError(code)
    return value


def _payload(
    category: object,
    amount: object,
    transaction_date: object,
    reference: object,
    notes: object,
) -> tuple[str, int, str, str | None, str | None]:
    if type(category) is not str or category not in CATEGORIES:
        raise AnnualTransactionValidationError(
            "annual_transactions.category.invalid"
        )
    if type(amount) is not int or not 0 <= amount <= MAX_AMOUNT:
        raise AnnualTransactionValidationError("annual_transactions.amount.invalid")
    if type(transaction_date) is not str:
        raise AnnualTransactionValidationError("annual_transactions.date.invalid")
    try:
        if date.fromisoformat(transaction_date).isoformat() != transaction_date:
            raise ValueError
    except ValueError as exc:
        raise AnnualTransactionValidationError(
            "annual_transactions.date.invalid"
        ) from exc
    return (
        category,
        amount,
        transaction_date,
        _text(
            reference,
            code="annual_transactions.reference.invalid",
            maximum=500,
            optional=True,
        ),
        _text(
            notes,
            code="annual_transactions.notes.invalid",
            maximum=4000,
            optional=True,
        ),
    )


class AnnualTransactionsService:
    CATEGORIES = CATEGORIES

    def __init__(
        self,
        conn: sqlite3.Connection,
        repository: AnnualTransactionsRepository,
        audit: AuditService,
    ) -> None:
        if repository.connection is not conn or audit.connection is not conn:
            raise ValueError("annual_transactions.connection.mismatch")
        self._conn = conn
        self._repo = repository
        self._audit = audit

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def repository(self) -> AnnualTransactionsRepository:
        return self._repo

    def _start(self) -> None:
        if self._conn.in_transaction:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction.already_active"
            )
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise self._database_error(exc, "mutation") from exc

    @staticmethod
    def _database_error(exc: sqlite3.Error, operation: str) -> AnnualTransactionError:
        code = getattr(exc, "sqlite_errorcode", None)
        if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(
            exc
        ).lower():
            return AnnualTransactionError("annual_transactions.transaction.busy")
        return AnnualTransactionError(f"annual_transactions.{operation}.failed")

    def _active_item(self, work_item_id: object) -> int:
        prepared = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        if not self._repo.active_work_item_exists(prepared):
            raise AnnualTransactionValidationError(
                "annual_transactions.work_item_not_found"
            )
        return prepared

    def _transaction(
        self, transaction_id: object, *, include_deleted: bool
    ) -> AnnualTransactionRow:
        prepared = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        row = self._repo.get(prepared, include_deleted=include_deleted)
        if row is None:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction_not_found"
            )
        self._active_item(row.work_item_id)
        return row

    def add(
        self,
        work_item_id: object,
        category: object,
        amount: object,
        transaction_date: object,
        reference: object = None,
        notes: object = None,
    ) -> AnnualTransactionRow:
        """Record one new business event.

        Identical calls intentionally create distinct rows. A future UI must
        disable its submit control while one call is in flight instead of
        suppressing legitimate repeated transactions by payload fingerprint.
        """
        if self._conn.in_transaction:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction.already_active"
            )
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        prepared = _payload(category, amount, transaction_date, reference, notes)
        try:
            self._start()
            self._active_item(work_item_id)
            row = self._repo.insert(work_item_id, *prepared)
            self._audit.record(
                action="annual_transaction.add",
                target_type="annual_transaction",
                target_id=str(row.id),
                detail={
                    "work_item_id": work_item_id,
                    "category": row.category,
                    "amount": row.amount,
                    "transaction_date": row.transaction_date,
                },
            )
            self._conn.commit()
            return row
        except AnnualTransactionError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.Error as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise self._database_error(exc, "add") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualTransactionError("annual_transactions.add.failed") from exc

    def update(
        self,
        transaction_id: object,
        category: object,
        amount: object,
        transaction_date: object,
        reference: object = None,
        notes: object = None,
    ) -> AnnualTransactionRow:
        if self._conn.in_transaction:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction.already_active"
            )
        transaction_id = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        prepared = _payload(category, amount, transaction_date, reference, notes)
        try:
            self._start()
            current = self._transaction(transaction_id, include_deleted=False)
            if prepared == (
                current.category,
                current.amount,
                current.transaction_date,
                current.reference,
                current.notes,
            ):
                self._conn.rollback()
                return current
            row = self._repo.update(transaction_id, *prepared)
            self._audit.record(
                action="annual_transaction.update",
                target_type="annual_transaction",
                target_id=str(row.id),
                detail={
                    "work_item_id": row.work_item_id,
                    "category": row.category,
                    "amount": row.amount,
                    "transaction_date": row.transaction_date,
                },
            )
            self._conn.commit()
            return row
        except AnnualTransactionError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.Error as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise self._database_error(exc, "update") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualTransactionError("annual_transactions.update.failed") from exc

    def delete(self, transaction_id: object, reason: object) -> AnnualTransactionRow:
        if self._conn.in_transaction:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction.already_active"
            )
        transaction_id = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        reason = _text(
            reason,
            code="annual_transactions.delete_reason.invalid",
            maximum=4000,
            optional=False,
        )
        if not reason.strip():
            raise AnnualTransactionValidationError(
                "annual_transactions.delete_reason.invalid"
            )
        try:
            self._start()
            current = self._transaction(transaction_id, include_deleted=True)
            if current.deleted_at is not None:
                raise AnnualTransactionValidationError(
                    "annual_transactions.already_deleted"
                )
            row = self._repo.soft_delete(transaction_id)
            self._audit.record(
                action="annual_transaction.delete",
                target_type="annual_transaction",
                target_id=str(row.id),
                detail={"work_item_id": row.work_item_id, "reason": reason},
            )
            self._conn.commit()
            return row
        except AnnualTransactionError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.Error as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise self._database_error(exc, "delete") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualTransactionError("annual_transactions.delete.failed") from exc

    def restore(self, transaction_id: object) -> AnnualTransactionRow:
        if self._conn.in_transaction:
            raise AnnualTransactionValidationError(
                "annual_transactions.transaction.already_active"
            )
        transaction_id = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        try:
            self._start()
            current = self._transaction(transaction_id, include_deleted=True)
            if current.deleted_at is None:
                raise AnnualTransactionValidationError(
                    "annual_transactions.already_active"
                )
            row = self._repo.restore(transaction_id)
            self._audit.record(
                action="annual_transaction.restore",
                target_type="annual_transaction",
                target_id=str(row.id),
                detail={"work_item_id": row.work_item_id},
            )
            self._conn.commit()
            return row
        except AnnualTransactionError:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise
        except sqlite3.Error as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise self._database_error(exc, "restore") from exc
        except Exception as exc:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise AnnualTransactionError("annual_transactions.restore.failed") from exc

    def get(
        self, transaction_id: object, *, include_deleted: object = False
    ) -> AnnualTransactionRow | None:
        transaction_id = _positive_id(
            transaction_id, "annual_transactions.transaction_id.invalid"
        )
        if type(include_deleted) is not bool:
            raise AnnualTransactionValidationError(
                "annual_transactions.include_deleted.invalid"
            )
        return self._repo.get(transaction_id, include_deleted=include_deleted)

    def list(
        self,
        work_item_id: object,
        *,
        include_deleted: object = False,
        limit: object = 100,
        offset: object = 0,
        order_by: object = "transaction_date",
        order_dir: object = "ASC",
    ) -> list[AnnualTransactionRow]:
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        try:
            return self._repo.list(
                work_item_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
                order_by=order_by,
                order_dir=order_dir,
            )
        except ValueError as exc:
            raise AnnualTransactionValidationError(str(exc)) from exc

    def list_for_work_item(
        self, work_item_id: object, **kwargs: object
    ) -> list[AnnualTransactionRow]:
        return self.list(work_item_id, **kwargs)

    def soft_delete(
        self, transaction_id: object, reason: object
    ) -> AnnualTransactionRow:
        return self.delete(transaction_id, reason)

    def balance(self, work_item_id: object) -> AnnualBalance:
        work_item_id = _positive_id(
            work_item_id, "annual_transactions.work_item_id.invalid"
        )
        if not self._repo.active_work_item_exists(work_item_id):
            raise AnnualTransactionValidationError(
                "annual_transactions.work_item_not_found"
            )
        try:
            return self._repo.balance(work_item_id)
        except sqlite3.Error as exc:
            raise self._database_error(exc, "balance") from exc
