"""Frozen annual-work mutation codes shared by service and repository."""

WORK_STATUSES = frozenset(
    {
        "not_started", "in_progress", "completed", "completed_with_exception",
        "exception", "not_applicable", "cancelled",
    }
)
FILING_STATUSES = frozenset(
    {"not_filed", "filed", "filing_failed", "correction_required"}
)
DOCUMENT_STATUSES = frozenset(
    {"not_requested", "missing", "partially_received", "complete", "not_applicable"}
)
TAX_STATUSES = frozenset(
    {
        "unconfirmed", "awaiting_collection", "partially_collected", "collected",
        "paid", "unpaid", "refund", "not_applicable",
    }
)
FEE_STATUSES = frozenset(
    {"not_billed", "awaiting_payment", "partially_paid", "paid", "not_applicable"}
)

STATUS_SETS = {
    "work_status": WORK_STATUSES,
    "filing_status": FILING_STATUSES,
    "document_status": DOCUMENT_STATUSES,
    "tax_status": TAX_STATUSES,
    "fee_status": FEE_STATUSES,
}
