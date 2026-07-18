from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from taxops.services.compliance_rules import (
    ComplianceRuleError,
    WORK_TYPE_LABELS,
    WorkDraft,
    build_standard_drafts,
)


def _by_type(drafts: tuple[WorkDraft, ...], work_type: str) -> list[WorkDraft]:
    return [draft for draft in drafts if draft.work_type == work_type]


def test_bimonthly_vat_generates_six_exact_suggested_periods() -> None:
    drafts = build_standard_drafts(
        2026, fiscal_start_month=1, enabled={"vat": "bimonthly"}
    )

    assert [
        (draft.tax_year, draft.period_code, draft.suggested_due_date)
        for draft in drafts
    ] == [
        (2026, "01-02", "2026-03-15"),
        (2026, "03-04", "2026-05-15"),
        (2026, "05-06", "2026-07-15"),
        (2026, "07-08", "2026-09-15"),
        (2026, "09-10", "2026-11-15"),
        (2026, "11-12", "2027-01-15"),
    ]


def test_monthly_vat_and_withholding_use_explicit_next_month_dates() -> None:
    drafts = build_standard_drafts(
        2026,
        fiscal_start_month=1,
        enabled={
            "monthly_withholding_payment": "monthly",
            "vat": "monthly",
        },
    )

    vat = _by_type(drafts, "vat")
    withholding = _by_type(drafts, "monthly_withholding_payment")
    assert len(vat) == len(withholding) == 12
    assert (vat[0].period_code, vat[0].suggested_due_date) == (
        "01",
        "2026-02-15",
    )
    assert (vat[-1].period_code, vat[-1].suggested_due_date) == (
        "12",
        "2027-01-15",
    )
    assert (withholding[0].period_code, withholding[0].suggested_due_date) == (
        "01",
        "2026-02-10",
    )
    assert (withholding[-1].period_code, withholding[-1].suggested_due_date) == (
        "12",
        "2027-01-10",
    )


def test_calendar_annual_rules_keep_operation_and_tax_years_distinct() -> None:
    drafts = build_standard_drafts(
        2026,
        fiscal_start_month=1,
        enabled={
            "annual_withholding_statements": "annual",
            "corporate_income_tax": "annual",
            "undistributed_earnings": "annual",
            "provisional_tax": "annual",
        },
    )

    values = {
        draft.work_type: (
            draft.operation_year,
            draft.tax_year,
            draft.period_code,
            draft.suggested_due_date,
        )
        for draft in drafts
    }
    assert values == {
        "annual_withholding_statements": (2026, 2025, None, "2026-01-31"),
        "corporate_income_tax": (2026, 2025, None, "2026-05-31"),
        "undistributed_earnings": (2026, 2024, None, "2026-05-31"),
        "provisional_tax": (2026, 2026, None, "2026-09-30"),
    }


@pytest.mark.parametrize(
    ("start_month", "tax_year", "period_code", "due_date", "ue_tax_year", "ue_period"),
    [
        (2, 2025, "2025-02~2026-01", "2026-06-30", 2024, "2024-02~2025-01"),
        (3, 2025, "2025-03~2026-02", "2026-07-31", 2024, "2024-03~2025-02"),
        (4, 2025, "2025-04~2026-03", "2026-08-31", 2024, "2024-04~2025-03"),
        (5, 2025, "2025-05~2026-04", "2026-09-30", 2024, "2024-05~2025-04"),
        (6, 2025, "2025-06~2026-05", "2026-10-31", 2024, "2024-06~2025-05"),
        (7, 2025, "2025-07~2026-06", "2026-11-30", 2024, "2024-07~2025-06"),
        (8, 2025, "2025-08~2026-07", "2026-12-31", 2024, "2024-08~2025-07"),
        (9, 2024, "2024-09~2025-08", "2026-01-31", 2023, "2023-09~2024-08"),
        (10, 2024, "2024-10~2025-09", "2026-02-28", 2023, "2023-10~2024-09"),
        (11, 2024, "2024-11~2025-10", "2026-03-31", 2023, "2023-11~2024-10"),
        (12, 2024, "2024-12~2025-11", "2026-04-30", 2023, "2023-12~2024-11"),
    ],
)
def test_special_fiscal_corporate_and_ue_are_derived_from_operation_year(
    start_month: int,
    tax_year: int,
    period_code: str,
    due_date: str,
    ue_tax_year: int,
    ue_period: str,
) -> None:
    drafts = build_standard_drafts(
        2026,
        fiscal_start_month=start_month,
        enabled={
            "corporate_income_tax": "annual",
            "undistributed_earnings": "annual",
        },
    )

    corporate, undistributed = drafts
    assert (
        corporate.operation_year,
        corporate.tax_year,
        corporate.period_code,
        corporate.suggested_due_date,
    ) == (2026, tax_year, period_code, due_date)
    assert (
        undistributed.operation_year,
        undistributed.tax_year,
        undistributed.period_code,
        undistributed.suggested_due_date,
    ) == (2026, ue_tax_year, ue_period, due_date)
    assert due_date.startswith("2026-")


@pytest.mark.parametrize(
    ("start_month", "tax_year", "period_code", "due_date"),
    [
        (2, 2026, "2026-02~2027-01", "2026-10-31"),
        (3, 2026, "2026-03~2027-02", "2026-11-30"),
        (4, 2026, "2026-04~2027-03", "2026-12-31"),
        (5, 2025, "2025-05~2026-04", "2026-01-31"),
        (6, 2025, "2025-06~2026-05", "2026-02-28"),
        (7, 2025, "2025-07~2026-06", "2026-03-31"),
        (8, 2025, "2025-08~2026-07", "2026-04-30"),
        (9, 2025, "2025-09~2026-08", "2026-05-31"),
        (10, 2025, "2025-10~2026-09", "2026-06-30"),
        (11, 2025, "2025-11~2026-10", "2026-07-31"),
        (12, 2025, "2025-12~2026-11", "2026-08-31"),
    ],
)
def test_special_fiscal_provisional_is_derived_from_ninth_fiscal_month(
    start_month: int, tax_year: int, period_code: str, due_date: str
) -> None:
    draft = build_standard_drafts(
        2026, start_month, {"provisional_tax": "annual"}
    )[0]

    assert (draft.tax_year, draft.period_code, draft.suggested_due_date) == (
        tax_year,
        period_code,
        due_date,
    )
    assert due_date.startswith("2026-")


def test_special_fiscal_boundary_months_change_the_source_fiscal_year() -> None:
    def annual(start_month: int, work_type: str) -> WorkDraft:
        return build_standard_drafts(2026, start_month, {work_type: "annual"})[0]

    assert annual(8, "corporate_income_tax").tax_year == 2025
    assert annual(9, "corporate_income_tax").tax_year == 2024
    assert annual(4, "provisional_tax").tax_year == 2026
    assert annual(5, "provisional_tax").tax_year == 2025


def test_special_fiscal_month_end_uses_leap_year_without_holiday_extension() -> None:
    corporate = build_standard_drafts(
        2024, 10, {"corporate_income_tax": "annual"}
    )[0]
    provisional = build_standard_drafts(
        2024, 6, {"provisional_tax": "annual"}
    )[0]

    assert corporate.suggested_due_date == "2024-02-29"
    assert provisional.suggested_due_date == "2024-02-29"


def test_special_fiscal_item_keys_use_the_correct_source_year_and_period() -> None:
    drafts = build_standard_drafts(
        2026,
        7,
        {
            "corporate_income_tax": "annual",
            "undistributed_earnings": "annual",
            "provisional_tax": "annual",
        },
    )

    assert [draft.item_key for draft in drafts] == [
        "corporate_income_tax:2025:2025-07~2026-06",
        "undistributed_earnings:2024:2024-07~2025-06",
        "provisional_tax:2025:2025-07~2026-06",
    ]
    assert len({draft.item_key for draft in drafts}) == len(drafts)


def test_internal_monthly_and_optional_rules_do_not_claim_legal_due_dates() -> None:
    drafts = build_standard_drafts(
        2026,
        fiscal_start_month=1,
        enabled={
            "monthly_bookkeeping": "monthly",
            "payroll_insurance": "monthly",
            "company_annual": "annual",
        },
    )

    assert len(_by_type(drafts, "monthly_bookkeeping")) == 12
    assert len(_by_type(drafts, "payroll_insurance")) == 12
    assert len(_by_type(drafts, "company_annual")) == 1
    assert all(draft.suggested_due_date is None for draft in drafts)


def test_all_builtin_rules_have_stable_unique_keys_and_canonical_order() -> None:
    enabled_reverse = {
        "company_annual": "annual",
        "payroll_insurance": "monthly",
        "provisional_tax": "annual",
        "undistributed_earnings": "annual",
        "corporate_income_tax": "annual",
        "annual_withholding_statements": "annual",
        "monthly_withholding_payment": "monthly",
        "vat": "bimonthly",
        "monthly_bookkeeping": "monthly",
    }

    first = build_standard_drafts(2026, 1, enabled_reverse)
    second = build_standard_drafts(2026, 1, dict(reversed(enabled_reverse.items())))

    assert first == second
    assert len(first) == 47
    keys = [draft.item_key for draft in first]
    assert len(keys) == len(set(keys))
    assert keys[0] == "monthly_bookkeeping:2026:01"
    assert keys[-1] == "company_annual:2026:-"
    assert first[0].title != first[0].work_type
    with pytest.raises(FrozenInstanceError):
        first[0].title = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        WORK_TYPE_LABELS["vat"] = "被竄改"  # type: ignore[index]


@pytest.mark.parametrize("year", [True, 1911, 10000, 2026.0, "2026"])
def test_operation_year_requires_exact_bounded_integer(year: object) -> None:
    with pytest.raises(ComplianceRuleError) as exc:
        build_standard_drafts(
            year,  # type: ignore[arg-type]
            fiscal_start_month=1,
            enabled={"vat": "bimonthly"},
        )
    assert exc.value.code == "compliance_rules.operation_year.invalid"


@pytest.mark.parametrize("month", [True, 0, 13, 1.0, "1"])
def test_fiscal_start_requires_exact_bounded_integer(month: object) -> None:
    with pytest.raises(ComplianceRuleError) as exc:
        build_standard_drafts(
            2026,
            fiscal_start_month=month,  # type: ignore[arg-type]
            enabled={"vat": "bimonthly"},
        )
    assert exc.value.code == "compliance_rules.fiscal_start_month.invalid"


@pytest.mark.parametrize("enabled", ["vat", b"vat", [("vat", "bimonthly")]])
def test_enabled_requires_a_real_mapping(enabled: object) -> None:
    with pytest.raises(ComplianceRuleError) as exc:
        build_standard_drafts(2026, 1, enabled)  # type: ignore[arg-type]
    assert exc.value.code == "compliance_rules.enabled.invalid"


@pytest.mark.parametrize(
    ("enabled", "code"),
    [
        ({1: "annual"}, "compliance_rules.enabled.invalid"),
        ({"vat": True}, "compliance_rules.enabled.invalid"),
        ({"unknown": "annual"}, "compliance_rules.work_type.unknown"),
        ({"vat": "weekly"}, "compliance_rules.frequency.invalid"),
        ({"corporate_income_tax": "monthly"}, "compliance_rules.frequency.invalid"),
    ],
)
def test_unknown_or_mistyped_rule_inputs_have_stable_errors(
    enabled: object, code: str
) -> None:
    with pytest.raises(ComplianceRuleError) as exc:
        build_standard_drafts(2026, 1, enabled)  # type: ignore[arg-type]
    assert exc.value.code == code


def test_empty_enabled_mapping_generates_nothing() -> None:
    assert build_standard_drafts(2026, 1, {}) == ()


def test_date_rules_do_not_read_clock_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExplodingDate(date):
        @classmethod
        def today(cls) -> date:
            raise AssertionError("rules must not read the clock")

    monkeypatch.setattr("taxops.services.compliance_rules.date", ExplodingDate)
    assert build_standard_drafts(
        2026, 1, {"provisional_tax": "annual"}
    )[0].suggested_due_date == "2026-09-30"


def test_date_overflow_is_a_stable_validation_error() -> None:
    with pytest.raises(ComplianceRuleError) as exc:
        build_standard_drafts(9999, 1, {"vat": "monthly"})
    assert exc.value.code == "compliance_rules.due_date.out_of_range"
