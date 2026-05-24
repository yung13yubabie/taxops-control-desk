"""Service for recurring billing plans, lines, and occurrences."""

from __future__ import annotations

import calendar
import datetime
import json
import logging
from dataclasses import dataclass

from ..core.clock import now_iso, today_iso
from ..repositories.recurring_billing import (
    LineRow,
    OccurrenceRow,
    PlanRow,
    RecurringBillingRepository,
)
from .audit import AuditService

_log = logging.getLogger(__name__)

_VALID_FREQUENCIES = frozenset({"monthly", "quarterly", "semiannual", "annual", "custom_months"})
_MAX_GENERATE_YEARS = 3


class RecurringBillingError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ── input dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreatePlanInput:
    client_id: int
    plan_name: str
    start_date: str
    frequency: str = "monthly"
    issue_day: int = 1
    months_json: str = "[]"
    contract_ref: str | None = None
    end_date: str | None = None
    advance_notice_days: int = 7
    notes: str | None = None


@dataclass(frozen=True)
class UpdatePlanInput:
    plan_name: str
    start_date: str
    frequency: str
    issue_day: int
    months_json: str = "[]"
    contract_ref: str | None = None
    end_date: str | None = None
    advance_notice_days: int = 7
    notes: str | None = None


@dataclass(frozen=True)
class CreateLineInput:
    plan_id: int
    bill_to_name: str
    amount: int
    description: str | None = None
    tax_type: str | None = None
    sort_order: int = 0


@dataclass(frozen=True)
class UpdateLineInput:
    bill_to_name: str
    amount: int
    description: str | None = None
    tax_type: str | None = None
    sort_order: int = 0


@dataclass(frozen=True)
class ConfirmOccurrenceInput:
    confirmed_amount: int
    confirmed_invoice_no: str | None = None
    confirmed_issue_date: str | None = None
    notes: str | None = None


# ── pure helpers ──────────────────────────────────────────────────────────────

def _clamp_day(year: int, month: int, day: int) -> datetime.date:
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day, last_day))


def _billing_dates(plan: PlanRow, until: datetime.date) -> list[datetime.date]:
    """Return all billing dates from plan.start_date to min(plan.end_date, until)."""
    start = datetime.date.fromisoformat(plan.start_date)
    end = until
    if plan.end_date:
        end = min(end, datetime.date.fromisoformat(plan.end_date))

    if start > end:
        return []

    custom_months: set[int] = set()
    if plan.frequency == "custom_months":
        custom_months = set(json.loads(plan.months_json))

    results: list[datetime.date] = []
    cur_year, cur_month = start.year, start.month

    while (cur_year, cur_month) <= (end.year, end.month):
        months_elapsed = (cur_year - start.year) * 12 + (cur_month - start.month)
        is_billing_month = False

        if plan.frequency == "monthly":
            is_billing_month = True
        elif plan.frequency == "quarterly":
            is_billing_month = (months_elapsed % 3 == 0)
        elif plan.frequency == "semiannual":
            is_billing_month = (months_elapsed % 6 == 0)
        elif plan.frequency == "annual":
            is_billing_month = (months_elapsed % 12 == 0)
        elif plan.frequency == "custom_months":
            is_billing_month = (cur_month in custom_months)

        if is_billing_month:
            d = _clamp_day(cur_year, cur_month, plan.issue_day)
            if start <= d <= end:
                results.append(d)

        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    return results


def _require_iso_date(value: str, code: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise RecurringBillingError(code)


def _validate_plan_input(
    plan_name: str,
    frequency: str,
    issue_day: int,
    months_json: str,
    start_date: str,
    end_date: str | None,
    advance_notice_days: int,
) -> None:
    if not plan_name.strip():
        raise RecurringBillingError("recurring_billing.plan_name.empty")
    if frequency not in _VALID_FREQUENCIES:
        raise RecurringBillingError("recurring_billing.frequency.invalid")
    if not (1 <= issue_day <= 31):
        raise RecurringBillingError("recurring_billing.issue_day.invalid")
    if not (0 <= advance_notice_days <= 365):
        raise RecurringBillingError("recurring_billing.advance_notice_days.invalid")

    sd = _require_iso_date(start_date, "recurring_billing.start_date.invalid")

    if end_date:
        ed = _require_iso_date(end_date, "recurring_billing.end_date.invalid")
        if ed < sd:
            raise RecurringBillingError("recurring_billing.date_range.invalid")

    if frequency == "custom_months":
        try:
            months = json.loads(months_json)
            if not isinstance(months, list) or not all(
                isinstance(m, int) and 1 <= m <= 12 for m in months
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise RecurringBillingError("recurring_billing.months_json.invalid")
        if not months:
            raise RecurringBillingError("recurring_billing.months_json.empty")


# ── bulk paste parser ─────────────────────────────────────────────────────────


def parse_bulk_lines(
    text: str,
) -> tuple[list[CreateLineInput], list[tuple[int, str]]]:
    """Parse tab-separated bulk paste into ``CreateLineInput`` rows.

    Format per non-empty line:

        bill_to_name<TAB>amount<TAB>tax_type<TAB>description

    Only the first two fields are required. Empty lines are skipped.

    Returns a tuple ``(valid_rows, errors)`` where ``errors`` is a list of
    ``(line_number, message)`` pairs using 1-indexed visible line numbers
    (matching what a user sees when they look at the source text). Rows with
    errors are NOT included in ``valid_rows``; the caller decides whether to
    commit only the valid rows or abort the whole batch (Slice 20C policy is
    to abort — no partial success).
    """
    valid: list[CreateLineInput] = []
    errors: list[tuple[int, str]] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            errors.append((idx, "缺少必要欄位（開立對象 + 金額）"))
            continue
        bill_to = parts[0].strip()
        if not bill_to:
            errors.append((idx, "開立對象不可為空"))
            continue
        amount_str = parts[1].strip()
        try:
            amount = int(amount_str)
        except ValueError:
            errors.append((idx, f"金額必須為整數（收到「{amount_str}」）"))
            continue
        if amount <= 0:
            errors.append((idx, f"金額必須大於零（收到 {amount}）"))
            continue
        tax_type = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None
        description = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else None
        valid.append(
            CreateLineInput(
                plan_id=0,
                bill_to_name=bill_to,
                amount=amount,
                tax_type=tax_type,
                description=description,
            )
        )
    return valid, errors


# ── service ───────────────────────────────────────────────────────────────────

class RecurringBillingService:
    def __init__(
        self,
        repo: RecurringBillingRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._audit = audit

    # ── plans ──────────────────────────────────────────────────────────────

    def create_plan_with_lines(
        self,
        plan_inp: CreatePlanInput,
        lines_inp: list[CreateLineInput],
    ) -> tuple[PlanRow, list[LineRow]]:
        """Atomically create a plan together with its initial billing lines.

        Validates the plan and every line up front; if any check fails, raises
        ``RecurringBillingError`` and nothing is written. On success a single
        audit log entry records the plan id and the line_count — the caller
        does not need to record per-line creation events separately.
        """
        if not lines_inp:
            raise RecurringBillingError("recurring_billing.lines.empty")
        _validate_plan_input(
            plan_inp.plan_name, plan_inp.frequency, plan_inp.issue_day,
            plan_inp.months_json, plan_inp.start_date, plan_inp.end_date,
            plan_inp.advance_notice_days,
        )
        for ln in lines_inp:
            if not ln.bill_to_name.strip():
                raise RecurringBillingError("recurring_billing.bill_to_name.empty")
            if ln.amount <= 0:
                raise RecurringBillingError("recurring_billing.amount.non_positive")
        plan_data = {
            "client_id": plan_inp.client_id,
            "plan_name": plan_inp.plan_name,
            "contract_ref": plan_inp.contract_ref,
            "frequency": plan_inp.frequency,
            "issue_day": plan_inp.issue_day,
            "months_json": plan_inp.months_json,
            "start_date": plan_inp.start_date,
            "end_date": plan_inp.end_date,
            "advance_notice_days": plan_inp.advance_notice_days,
            "notes": plan_inp.notes,
        }
        lines_data = [
            {
                "bill_to_name": ln.bill_to_name,
                "description": ln.description,
                "amount": ln.amount,
                "tax_type": ln.tax_type,
                "sort_order": ln.sort_order,
            }
            for ln in lines_inp
        ]
        plan, lines = self._repo.insert_plan_with_lines(plan_data, lines_data)
        self._audit.record(
            action="recurring_billing.plan.create_with_lines",
            target_type="recurring_billing_plan",
            target_id=str(plan.id),
            detail={
                "plan_name": plan.plan_name,
                "client_id": plan.client_id,
                "line_count": len(lines),
            },
        )
        return plan, lines

    def create_plan(self, inp: CreatePlanInput) -> PlanRow:
        _validate_plan_input(
            inp.plan_name, inp.frequency, inp.issue_day, inp.months_json,
            inp.start_date, inp.end_date, inp.advance_notice_days,
        )
        plan = self._repo.insert_plan(
            client_id=inp.client_id,
            plan_name=inp.plan_name,
            contract_ref=inp.contract_ref,
            frequency=inp.frequency,
            issue_day=inp.issue_day,
            months_json=inp.months_json,
            start_date=inp.start_date,
            end_date=inp.end_date,
            advance_notice_days=inp.advance_notice_days,
            notes=inp.notes,
        )
        self._audit.record(
            action="recurring_billing.plan.create",
            target_type="recurring_billing_plan",
            target_id=str(plan.id),
            detail={"plan_name": inp.plan_name, "client_id": inp.client_id},
        )
        return plan

    def get_plan(self, plan_id: int) -> PlanRow | None:
        return self._repo.get_plan(plan_id)

    def update_plan(self, plan_id: int, inp: UpdatePlanInput) -> PlanRow:
        existing = self._repo.get_plan(plan_id)
        if existing is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        _validate_plan_input(
            inp.plan_name, inp.frequency, inp.issue_day, inp.months_json,
            inp.start_date, inp.end_date, inp.advance_notice_days,
        )
        plan = self._repo.update_plan(
            plan_id=plan_id,
            plan_name=inp.plan_name,
            contract_ref=inp.contract_ref,
            frequency=inp.frequency,
            issue_day=inp.issue_day,
            months_json=inp.months_json,
            start_date=inp.start_date,
            end_date=inp.end_date,
            advance_notice_days=inp.advance_notice_days,
            notes=inp.notes,
        )
        if plan is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        self._audit.record(
            action="recurring_billing.plan.update",
            target_type="recurring_billing_plan",
            target_id=str(plan_id),
            detail={"plan_name": inp.plan_name},
        )
        return plan

    def archive_plan(self, plan_id: int) -> PlanRow:
        existing = self._repo.get_plan(plan_id)
        if existing is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        plan = self._repo.set_plan_status(plan_id, "archived", deleted_at=now_iso())
        if plan is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        self._audit.record(
            action="recurring_billing.plan.archive",
            target_type="recurring_billing_plan",
            target_id=str(plan_id),
        )
        return plan

    def list_plans(
        self, client_id: int | None = None, include_archived: bool = False
    ) -> list[PlanRow]:
        return self._repo.list_plans(client_id=client_id, include_archived=include_archived)

    # ── lines ──────────────────────────────────────────────────────────────

    def create_line(self, inp: CreateLineInput) -> LineRow:
        plan = self._repo.get_plan(inp.plan_id)
        if plan is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        if not inp.bill_to_name.strip():
            raise RecurringBillingError("recurring_billing.bill_to_name.empty")
        if inp.amount <= 0:
            raise RecurringBillingError("recurring_billing.amount.non_positive")
        line = self._repo.insert_line(
            plan_id=inp.plan_id,
            bill_to_name=inp.bill_to_name,
            description=inp.description,
            amount=inp.amount,
            tax_type=inp.tax_type,
            sort_order=inp.sort_order,
        )
        self._audit.record(
            action="recurring_billing.line.create",
            target_type="recurring_billing_line",
            target_id=str(line.id),
            detail={"plan_id": inp.plan_id, "bill_to_name": inp.bill_to_name},
        )
        return line

    def list_lines(self, plan_id: int, active_only: bool = False) -> list[LineRow]:
        return self._repo.list_lines(plan_id, active_only=active_only)

    def update_line(self, line_id: int, inp: UpdateLineInput) -> LineRow:
        existing = self._repo.get_line(line_id)
        if existing is None:
            raise RecurringBillingError("recurring_billing.line.not_found")
        if not inp.bill_to_name.strip():
            raise RecurringBillingError("recurring_billing.bill_to_name.empty")
        if inp.amount <= 0:
            raise RecurringBillingError("recurring_billing.amount.non_positive")
        line = self._repo.update_line(
            line_id=line_id,
            bill_to_name=inp.bill_to_name,
            description=inp.description,
            amount=inp.amount,
            tax_type=inp.tax_type,
            sort_order=inp.sort_order,
        )
        if line is None:
            raise RecurringBillingError("recurring_billing.line.not_found")
        return line

    def deactivate_line(self, line_id: int) -> LineRow:
        existing = self._repo.get_line(line_id)
        if existing is None:
            raise RecurringBillingError("recurring_billing.line.not_found")
        line = self._repo.set_line_active(line_id, False)
        if line is None:
            raise RecurringBillingError("recurring_billing.line.not_found")
        return line

    # ── occurrences ────────────────────────────────────────────────────────

    def generate_occurrences(
        self,
        plan_id: int,
        until_date: datetime.date | None = None,
    ) -> list[OccurrenceRow]:
        plan = self._repo.get_plan(plan_id)
        if plan is None:
            raise RecurringBillingError("recurring_billing.plan.not_found")
        if plan.status == "archived":
            return []

        today = datetime.date.fromisoformat(today_iso())
        until = until_date or today + datetime.timedelta(days=_MAX_GENERATE_YEARS * 365)

        dates = _billing_dates(plan, until)
        lines = self._repo.list_lines(plan_id, active_only=True)

        for line in lines:
            for d in dates:
                self._repo.insert_occurrence_if_missing(plan_id, line.id, d.isoformat())
        if lines and dates:
            self._repo.commit()

        return self._repo.list_occurrences(plan_id=plan_id)

    def list_occurrences(
        self,
        plan_id: int | None = None,
        line_id: int | None = None,
        status: str | None = None,
        before_date: str | None = None,
    ) -> list[OccurrenceRow]:
        return self._repo.list_occurrences(
            plan_id=plan_id, line_id=line_id, status=status, before_date=before_date
        )

    def upcoming_notices(self, today: datetime.date | None = None) -> list[OccurrenceRow]:
        """Return pending occurrences within each plan's advance_notice_days window."""
        ref = today or datetime.date.fromisoformat(today_iso())
        plans = self._repo.list_plans(include_archived=False)
        result: list[OccurrenceRow] = []
        for plan in plans:
            notice_until = (ref + datetime.timedelta(days=plan.advance_notice_days)).isoformat()
            occs = self._repo.list_occurrences(
                plan_id=plan.id,
                status="pending",
                before_date=notice_until,
            )
            result.extend(occs)
        result.sort(key=lambda o: o.expected_issue_date)
        return result

    def confirm_occurrence(
        self, occurrence_id: int, inp: ConfirmOccurrenceInput
    ) -> OccurrenceRow:
        occ = self._repo.get_occurrence(occurrence_id)
        if occ is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        if occ.status != "pending":
            raise RecurringBillingError("recurring_billing.occurrence.not_pending")
        if inp.confirmed_amount <= 0:
            raise RecurringBillingError("recurring_billing.confirmed_amount.non_positive")
        if inp.confirmed_invoice_no and len(inp.confirmed_invoice_no) > 50:
            raise RecurringBillingError("recurring_billing.confirmed_invoice_no.too_long")

        row = self._repo.update_occurrence_status(
            occurrence_id=occurrence_id,
            status="confirmed",
            confirmed_invoice_no=inp.confirmed_invoice_no,
            confirmed_issue_date=inp.confirmed_issue_date or occ.expected_issue_date,
            confirmed_amount=inp.confirmed_amount,
            confirmed_at=now_iso(),
            notes=inp.notes,
        )
        if row is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        self._audit.record(
            action="recurring_billing.occurrence.confirm",
            target_type="recurring_billing_occurrence",
            target_id=str(occurrence_id),
            detail={"confirmed_amount": inp.confirmed_amount},
        )
        return row

    def skip_occurrence(self, occurrence_id: int, reason: str) -> OccurrenceRow:
        if not reason.strip():
            raise RecurringBillingError("recurring_billing.skip_reason.empty")
        occ = self._repo.get_occurrence(occurrence_id)
        if occ is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        if occ.status != "pending":
            raise RecurringBillingError("recurring_billing.occurrence.not_pending")
        row = self._repo.update_occurrence_status(
            occurrence_id=occurrence_id,
            status="skipped",
            skipped_reason=reason.strip(),
        )
        if row is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        self._audit.record(
            action="recurring_billing.occurrence.skip",
            target_type="recurring_billing_occurrence",
            target_id=str(occurrence_id),
            detail={"reason": reason.strip()},
        )
        return row

    def cancel_occurrence(self, occurrence_id: int) -> OccurrenceRow:
        occ = self._repo.get_occurrence(occurrence_id)
        if occ is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        row = self._repo.update_occurrence_status(
            occurrence_id=occurrence_id,
            status="cancelled",
        )
        if row is None:
            raise RecurringBillingError("recurring_billing.occurrence.not_found")
        return row

    def get_occurrence_summary(self, plan_id: int) -> dict[str, int]:
        return self._repo.count_occurrences_by_status(plan_id)
