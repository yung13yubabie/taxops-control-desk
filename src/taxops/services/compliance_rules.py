"""Pure, deterministic suggested-period rules for the annual workbench.

The dates produced here are *suggested* dates, not legal guarantees.  The
calendar-year statutory suggestions encode the ordinary rules verified for
Taiwan's Business Tax Act article 35 and Income Tax Act articles 67, 71 and
92.  They deliberately do not infer public-holiday extensions, client-specific
exceptions, or changes in law.  Verified special-fiscal-year windows are
derived from the fiscal start month; internal work types keep
``suggested_due_date`` unset.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ..core.compliance import (
    SUPPORTED_FREQUENCIES,
    WORK_TYPE_LABELS,
    WORK_TYPE_ORDER,
)


class ComplianceRuleError(Exception):
    """A rule input cannot produce a deterministic, supported draft set."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkDraft:
    item_key: str
    operation_year: int
    work_type: str
    title: str
    tax_year: int | None
    period_code: str | None
    suggested_due_date: str | None


def validate_work_frequency(work_type: object, frequency: object) -> tuple[str, str]:
    """Return normalized supported codes or raise a stable rule error."""
    if not isinstance(work_type, str) or not isinstance(frequency, str):
        raise ComplianceRuleError("compliance_rules.enabled.invalid")
    normalized_type = work_type.strip().lower()
    normalized_frequency = frequency.strip().lower()
    supported = SUPPORTED_FREQUENCIES.get(normalized_type)
    if supported is None:
        raise ComplianceRuleError("compliance_rules.work_type.unknown")
    if normalized_frequency not in supported:
        raise ComplianceRuleError("compliance_rules.frequency.invalid")
    return normalized_type, normalized_frequency


def work_type_sort_key(work_type: str) -> tuple[int, str]:
    try:
        return WORK_TYPE_ORDER.index(work_type), work_type
    except ValueError:
        return len(WORK_TYPE_ORDER), work_type


def _require_operation_year(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1912 <= value <= 9999
    ):
        raise ComplianceRuleError("compliance_rules.operation_year.invalid")
    return value


def _require_fiscal_start_month(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 12
    ):
        raise ComplianceRuleError("compliance_rules.fiscal_start_month.invalid")
    return value


def _suggested_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except (OverflowError, ValueError) as exc:
        raise ComplianceRuleError("compliance_rules.due_date.out_of_range") from exc


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    zero_based = month - 1 + offset
    return year + zero_based // 12, zero_based % 12 + 1


def _month_end(year: int, month: int) -> str:
    try:
        day = monthrange(year, month)[1]
    except (OverflowError, ValueError) as exc:
        raise ComplianceRuleError("compliance_rules.due_date.out_of_range") from exc
    return _suggested_date(year, month, day)


def _fiscal_period(start_year: int, start_month: int) -> str:
    end_month = start_month - 1
    return (
        f"{start_year:04d}-{start_month:02d}~"
        f"{start_year + 1:04d}-{end_month:02d}"
    )


def _special_corporate_filing(
    operation_year: int, fiscal_start_month: int
) -> tuple[int, str]:
    # The suggested filing month is the fifth month after fiscal year-end.
    # Reverse from the operation year so this work occurs in that workbench.
    fiscal_start_year = (
        operation_year - 1 if fiscal_start_month <= 8 else operation_year - 2
    )
    due_year, due_month = _shift_month(
        fiscal_start_year, fiscal_start_month, 16
    )
    if due_year != operation_year:
        raise RuntimeError("special corporate filing escaped operation year")
    return fiscal_start_year, _month_end(due_year, due_month)


def _special_provisional_filing(
    operation_year: int, fiscal_start_month: int
) -> tuple[int, str]:
    # The suggested provisional window is the ninth fiscal month (offset 8).
    fiscal_start_year = (
        operation_year if fiscal_start_month <= 4 else operation_year - 1
    )
    due_year, due_month = _shift_month(
        fiscal_start_year, fiscal_start_month, 8
    )
    if due_year != operation_year:
        raise RuntimeError("special provisional filing escaped operation year")
    return fiscal_start_year, _month_end(due_year, due_month)


def _title(work_type: str, period_code: str | None) -> str:
    label = WORK_TYPE_LABELS[work_type]
    return f"{period_code} {label}" if period_code else label


def _draft(
    operation_year: int,
    work_type: str,
    tax_year: int | None,
    period_code: str | None,
    due_date: str | None,
) -> WorkDraft:
    if tax_year is not None and not 1912 <= tax_year <= 9999:
        raise ComplianceRuleError("compliance_rules.tax_year.out_of_range")
    key = f"{work_type}:{tax_year if tax_year is not None else '-'}:{period_code or '-'}"
    return WorkDraft(
        item_key=key,
        operation_year=operation_year,
        work_type=work_type,
        title=_title(work_type, period_code),
        tax_year=tax_year,
        period_code=period_code,
        suggested_due_date=due_date,
    )


def _monthly_internal(operation_year: int, work_type: str) -> list[WorkDraft]:
    return [
        _draft(operation_year, work_type, operation_year, f"{month:02d}", None)
        for month in range(1, 13)
    ]


def _vat(operation_year: int, frequency: str) -> list[WorkDraft]:
    span = 1 if frequency == "monthly" else 2
    drafts: list[WorkDraft] = []
    for start_month in range(1, 13, span):
        end_month = start_month + span - 1
        due_year, due_month = _next_month(operation_year, end_month)
        period = (
            f"{start_month:02d}"
            if span == 1
            else f"{start_month:02d}-{end_month:02d}"
        )
        drafts.append(
            _draft(
                operation_year,
                "vat",
                operation_year,
                period,
                _suggested_date(due_year, due_month, 15),
            )
        )
    return drafts


def _monthly_withholding(operation_year: int) -> list[WorkDraft]:
    drafts: list[WorkDraft] = []
    for month in range(1, 13):
        due_year, due_month = _next_month(operation_year, month)
        drafts.append(
            _draft(
                operation_year,
                "monthly_withholding_payment",
                operation_year,
                f"{month:02d}",
                _suggested_date(due_year, due_month, 10),
            )
        )
    return drafts


def _annual_withholding(operation_year: int) -> list[WorkDraft]:
    return [
        _draft(
            operation_year,
            "annual_withholding_statements",
            operation_year - 1,
            None,
            _suggested_date(operation_year, 1, 31),
        )
    ]


def _corporate_income_tax(
    operation_year: int, fiscal_start_month: int
) -> list[WorkDraft]:
    if fiscal_start_month == 1:
        return [
            _draft(
                operation_year,
                "corporate_income_tax",
                operation_year - 1,
                None,
                _suggested_date(operation_year, 5, 31),
            )
        ]
    tax_year, due_date = _special_corporate_filing(
        operation_year, fiscal_start_month
    )
    return [
        _draft(
            operation_year,
            "corporate_income_tax",
            tax_year,
            _fiscal_period(tax_year, fiscal_start_month),
            due_date,
        )
    ]


def _undistributed_earnings(
    operation_year: int, fiscal_start_month: int
) -> list[WorkDraft]:
    if fiscal_start_month == 1:
        return [
            _draft(
                operation_year,
                "undistributed_earnings",
                operation_year - 2,
                None,
                _suggested_date(operation_year, 5, 31),
            )
        ]
    corporate_tax_year, due_date = _special_corporate_filing(
        operation_year, fiscal_start_month
    )
    tax_year = corporate_tax_year - 1
    return [
        _draft(
            operation_year,
            "undistributed_earnings",
            tax_year,
            _fiscal_period(tax_year, fiscal_start_month),
            due_date,
        )
    ]


def _provisional_tax(
    operation_year: int, fiscal_start_month: int
) -> list[WorkDraft]:
    if fiscal_start_month != 1:
        tax_year, due_date = _special_provisional_filing(
            operation_year, fiscal_start_month
        )
        return [
            _draft(
                operation_year,
                "provisional_tax",
                tax_year,
                _fiscal_period(tax_year, fiscal_start_month),
                due_date,
            )
        ]
    return [
        _draft(
            operation_year,
            "provisional_tax",
            operation_year,
            None,
            _suggested_date(operation_year, 9, 30),
        )
    ]


def _company_annual(operation_year: int) -> list[WorkDraft]:
    return [
        _draft(operation_year, "company_annual", operation_year, None, None)
    ]


def build_standard_drafts(
    operation_year: int,
    fiscal_start_month: int = 1,
    enabled: Mapping[str, str] | None = None,
) -> tuple[WorkDraft, ...]:
    """Build drafts from explicit enabled work-type/frequency pairs.

    The result order and item keys do not depend on mapping insertion order.
    No clock, network, holiday calendar, or external mutable state is read.
    """
    year = _require_operation_year(operation_year)
    start_month = _require_fiscal_start_month(fiscal_start_month)
    if enabled is None or not isinstance(enabled, Mapping):
        raise ComplianceRuleError("compliance_rules.enabled.invalid")

    normalized: dict[str, str] = {}
    for raw_type, raw_frequency in enabled.items():
        work_type, frequency = validate_work_frequency(raw_type, raw_frequency)
        if work_type in normalized:
            raise ComplianceRuleError("compliance_rules.work_type.duplicate")
        normalized[work_type] = frequency

    drafts: list[WorkDraft] = []
    for work_type in WORK_TYPE_ORDER:
        frequency = normalized.get(work_type)
        if frequency is None:
            continue
        if work_type in {"monthly_bookkeeping", "payroll_insurance"}:
            drafts.extend(_monthly_internal(year, work_type))
        elif work_type == "vat":
            drafts.extend(_vat(year, frequency))
        elif work_type == "monthly_withholding_payment":
            drafts.extend(_monthly_withholding(year))
        elif work_type == "annual_withholding_statements":
            drafts.extend(_annual_withholding(year))
        elif work_type == "corporate_income_tax":
            drafts.extend(_corporate_income_tax(year, start_month))
        elif work_type == "undistributed_earnings":
            drafts.extend(_undistributed_earnings(year, start_month))
        elif work_type == "provisional_tax":
            drafts.extend(_provisional_tax(year, start_month))
        elif work_type == "company_annual":
            drafts.extend(_company_annual(year))
        else:
            raise RuntimeError(f"unsupported compliance dispatch: {work_type}")

    keys = [draft.item_key for draft in drafts]
    if len(keys) != len(set(keys)):
        raise RuntimeError("compliance_rules generated duplicate item keys")
    return tuple(drafts)
