"""Service for late-fee calculation and persistence."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)

from ..repositories.document_requests import DocumentRequestsRepository
from ..repositories.late_fee import LateFeeRow, LateFeeRepository
from .audit import AuditService

_MANUAL_REVIEW_TAX_TYPES = frozenset({"labor_health"})


def calculate_penalty_percent(overdue_days: int) -> float:
    """Return penalty percentage per spec §18.

    0 for overdue_days <= 3; each 3-day unit after day 1 adds 1%; capped at 10%.
    """
    if overdue_days <= 3:
        return 0.0
    units = (overdue_days - 1) // 3
    return float(min(units, 10))


def calculate_overdue_days(last_payment_date: str, actual_payment_date: str) -> int:
    """Return calendar days after the last payment date until actual payment.

    Raises LateFeeValidationError("late_fee.date.range_invalid") if
    actual_payment_date is before last_payment_date.
    """
    try:
        last_day = datetime.date.fromisoformat(last_payment_date)
        paid_day = datetime.date.fromisoformat(actual_payment_date)
    except ValueError as err:
        raise LateFeeValidationError("late_fee.date.invalid") from err
    if paid_day < last_day:
        raise LateFeeValidationError("late_fee.date.range_invalid")
    return (paid_day - last_day).days


class LateFeeValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CalculateLateFeeInput:
    request_id: int
    overdue_days: int
    base_amount: float
    last_payment_date: str | None = None
    actual_payment_date: str | None = None


class LateFeeService:
    def __init__(
        self,
        repo: LateFeeRepository,
        doc_requests_repo: DocumentRequestsRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._doc_requests_repo = doc_requests_repo
        self._audit = audit

    def calculate_and_save(self, payload: CalculateLateFeeInput) -> LateFeeRow:
        has_last = bool(payload.last_payment_date)
        has_actual = bool(payload.actual_payment_date)
        if has_last != has_actual:
            raise LateFeeValidationError("late_fee.date.required_pair")

        overdue_days = payload.overdue_days
        if has_last and has_actual:
            overdue_days = calculate_overdue_days(
                payload.last_payment_date, payload.actual_payment_date
            )
        elif overdue_days < 0:
            raise LateFeeValidationError("late_fee.negative_overdue_days")
        if payload.base_amount < 0:
            raise LateFeeValidationError("late_fee.negative_base_amount")

        request = self._doc_requests_repo.get_request(payload.request_id)
        if request is None:
            raise LateFeeValidationError("late_fee.request_not_found")

        tax_type = request.tax_type
        needs_manual_review = tax_type in _MANUAL_REVIEW_TAX_TYPES

        if needs_manual_review:
            penalty_percent = 0.0
            penalty_amount = 0.0
        else:
            penalty_percent = calculate_penalty_percent(overdue_days)
            penalty_amount = round(payload.base_amount * penalty_percent / 100, 2)

        row = self._repo.insert(
            request_id=payload.request_id,
            overdue_days=overdue_days,
            penalty_percent=penalty_percent,
            base_amount=payload.base_amount,
            penalty_amount=penalty_amount,
            tax_type=tax_type,
            needs_manual_review=needs_manual_review,
        )
        self._audit.record(
            action="late_fee.calculate",
            target_type="late_fee_record",
            target_id=str(row.id),
            detail={
                "request_id": payload.request_id,
                "overdue_days": overdue_days,
                "last_payment_date": payload.last_payment_date,
                "actual_payment_date": payload.actual_payment_date,
                "penalty_percent": penalty_percent,
                "penalty_amount": penalty_amount,
            },
        )
        return row

    def list_by_request(self, request_id: int) -> list[LateFeeRow]:
        return self._repo.list_by_request(request_id)
