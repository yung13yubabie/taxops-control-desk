"""Traditional Chinese label maps for UI surfaces."""

from .labels import (
    NAV_LABELS,
    BUTTON_LABELS,
    TABLE_HEADERS,
    DISABLED_TOOLTIP,
)
from .status_labels import (
    ANNUAL_DOCUMENT_STATUS_LABELS,
    ANNUAL_FEE_STATUS_LABELS,
    ANNUAL_FILING_STATUS_LABELS,
    ANNUAL_TAX_STATUS_LABELS,
    ANNUAL_WORK_STATUS_LABELS,
    STATUS_LABELS,
    UNKNOWN_STATUS_TEXT,
    status_to_label,
)
from .errors import ERROR_MESSAGES, error_message

__all__ = [
    "NAV_LABELS",
    "BUTTON_LABELS",
    "TABLE_HEADERS",
    "DISABLED_TOOLTIP",
    "STATUS_LABELS",
    "ANNUAL_DOCUMENT_STATUS_LABELS",
    "ANNUAL_FEE_STATUS_LABELS",
    "ANNUAL_FILING_STATUS_LABELS",
    "ANNUAL_TAX_STATUS_LABELS",
    "ANNUAL_WORK_STATUS_LABELS",
    "UNKNOWN_STATUS_TEXT",
    "status_to_label",
    "ERROR_MESSAGES",
    "error_message",
]
