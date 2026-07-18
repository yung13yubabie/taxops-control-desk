"""Stable annual-compliance codes shared below the repository/service layers."""

from __future__ import annotations

from types import MappingProxyType


WORK_TYPE_ORDER = (
    "monthly_bookkeeping",
    "vat",
    "monthly_withholding_payment",
    "annual_withholding_statements",
    "corporate_income_tax",
    "undistributed_earnings",
    "provisional_tax",
    "payroll_insurance",
    "company_annual",
)

WORK_TYPE_LABELS = MappingProxyType({
    "monthly_bookkeeping": "每月帳務處理",
    "vat": "營業稅",
    "monthly_withholding_payment": "每月扣繳稅款",
    "annual_withholding_statements": "年度扣繳憑單",
    "corporate_income_tax": "營利事業所得稅結算申報",
    "undistributed_earnings": "未分配盈餘申報",
    "provisional_tax": "營利事業所得稅暫繳",
    "payroll_insurance": "薪資與勞健保作業",
    "company_annual": "公司年度例行作業",
})

SUPPORTED_FREQUENCIES = MappingProxyType({
    "monthly_bookkeeping": frozenset({"monthly"}),
    "vat": frozenset({"monthly", "bimonthly"}),
    "monthly_withholding_payment": frozenset({"monthly"}),
    "annual_withholding_statements": frozenset({"annual"}),
    "corporate_income_tax": frozenset({"annual"}),
    "undistributed_earnings": frozenset({"annual"}),
    "provisional_tax": frozenset({"annual"}),
    "payroll_insurance": frozenset({"monthly"}),
    "company_annual": frozenset({"annual"}),
})
