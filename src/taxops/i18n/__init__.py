"""Traditional Chinese label maps for UI surfaces."""

from .labels import (
    NAV_LABELS,
    BUTTON_LABELS,
    TABLE_HEADERS,
    DISABLED_TOOLTIP,
)
from .status_labels import (
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
    "UNKNOWN_STATUS_TEXT",
    "status_to_label",
    "ERROR_MESSAGES",
    "error_message",
]
