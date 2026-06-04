"""Service for late-fee calculation and persistence."""

from __future__ import annotations

import datetime
import json
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


# 營業稅每 2 月為 1 期，於次期開始 15 日內申報繳納（財政部規則）。
PERIOD_CODES: tuple[str, ...] = ("1-2", "3-4", "5-6", "7-8", "9-10", "11-12")

# period_code -> (申報月, 年份位移). 11-12 期於次年 1/15 截止。
_PERIOD_DUE: dict[str, tuple[int, int]] = {
    "1-2": (3, 0),
    "3-4": (5, 0),
    "5-6": (7, 0),
    "7-8": (9, 0),
    "9-10": (11, 0),
    "11-12": (1, 1),
}

_MAX_PENALTY_PERCENT = 10


def last_payment_date_for_period(year: int, period_code: str) -> str:
    """Return the statutory last payment date (ISO) for a 營業稅 period.

    1-2 -> year/3/15, 3-4 -> year/5/15, ..., 11-12 -> (year+1)/1/15.
    """
    try:
        month, year_offset = _PERIOD_DUE[period_code]
    except KeyError as err:
        raise LateFeeValidationError("late_fee.period.invalid") from err
    return datetime.date(year + year_offset, month, 15).isoformat()


def build_penalty_schedule(last_payment_date: str) -> list[dict]:
    """Return penalty-rate bands as concrete date ranges after the last payment date.

    Band ``p`` (0..9) covers overdue days ``3p+1`` .. ``3p+3``; the final band (10%)
    covers day 31 onward (open-ended, ``end_day``/``end_date`` = ``None``). This mirrors
    :func:`calculate_penalty_percent` exactly: <=3 days 0%, then +1% per 3-day unit,
    capped at 10%.
    """
    try:
        last_day = datetime.date.fromisoformat(last_payment_date)
    except (ValueError, TypeError) as err:
        raise LateFeeValidationError("late_fee.date.invalid") from err
    bands: list[dict] = []
    for percent in range(0, _MAX_PENALTY_PERCENT):  # 0% .. 9%
        start_day = 3 * percent + 1
        end_day = 3 * percent + 3
        bands.append(
            {
                "percent": percent,
                "start_day": start_day,
                "end_day": end_day,
                "start_date": (last_day + datetime.timedelta(days=start_day)).isoformat(),
                "end_date": (last_day + datetime.timedelta(days=end_day)).isoformat(),
            }
        )
    bands.append(
        {
            "percent": _MAX_PENALTY_PERCENT,
            "start_day": 31,
            "end_day": None,
            "start_date": (last_day + datetime.timedelta(days=31)).isoformat(),
            "end_date": None,
        }
    )
    return bands


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
    period_year: int | None = None
    period_code: str | None = None


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
        self._conn = repo._conn

    def calculate_and_save(self, payload: CalculateLateFeeInput) -> LateFeeRow:
        has_period_year = payload.period_year is not None
        has_period_code = payload.period_code is not None
        if has_period_year != has_period_code:
            raise LateFeeValidationError("late_fee.period.invalid")
        if has_period_code and payload.period_code not in PERIOD_CODES:
            raise LateFeeValidationError("late_fee.period.invalid")

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

        breakdown_json: str | None = None
        if has_last and payload.last_payment_date is not None:
            breakdown_json = json.dumps(
                build_penalty_schedule(payload.last_payment_date),
                ensure_ascii=False,
            )

        with self._conn:
            row = self._repo.insert(
                request_id=payload.request_id,
                overdue_days=overdue_days,
                penalty_percent=penalty_percent,
                base_amount=payload.base_amount,
                penalty_amount=penalty_amount,
                tax_type=tax_type,
                needs_manual_review=needs_manual_review,
                period_year=payload.period_year,
                period_code=payload.period_code,
                last_payment_date=payload.last_payment_date,
                actual_payment_date=payload.actual_payment_date,
                penalty_breakdown_json=breakdown_json,
            )
            self._audit.record(
                action="late_fee.calculate",
                target_type="late_fee_record",
                target_id=str(row.id),
                detail={
                    "request_id": payload.request_id,
                    "overdue_days": overdue_days,
                    "period_year": payload.period_year,
                    "period_code": payload.period_code,
                    "last_payment_date": payload.last_payment_date,
                    "actual_payment_date": payload.actual_payment_date,
                    "penalty_percent": penalty_percent,
                    "penalty_amount": penalty_amount,
                },
            )
        return row

    def list_by_request(self, request_id: int) -> list[LateFeeRow]:
        return self._repo.list_by_request(request_id)
