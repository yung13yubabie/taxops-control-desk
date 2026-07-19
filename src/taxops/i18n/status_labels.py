"""Workflow status labels (Traditional Chinese).

Raw enum values are never shown in UI. Unknown status falls back to a
generic Chinese message and the unknown value is recorded to system log
by the caller.
"""

from __future__ import annotations

from types import MappingProxyType

STATUS_LABELS: dict[str, str] = dict(
    MappingProxyType(
        {
            "todo": "待處理",
            "doing": "處理中",
            "waiting_client": "等客戶回覆",
            "waiting_internal_review": "等內部覆核",
            "done": "已完成",
            "cancelled": "已取消",
            "needs_manual_review": "需人工確認",
            # engagement statuses
            "draft": "草稿",
            "pending_acceptance": "待客戶確認",
            "accepted": "已確認",
            "in_progress": "進行中",
            "waiting_review": "等覆核",
            "ready_to_file": "待申報",
            "filed": "已申報",
            "delivered": "已交付",
            "closed": "已結案",
            # document request statuses
            "not_requested": "未索件",
            "requested": "已發出索件",
            "partially_received": "部分收件",
            "under_validation": "驗核中",
            "pending_confirm": "待確認",
            # document request item statuses
            "missing": "未收到",
            "received": "已收到",
            "incomplete": "不完整",
            "invalid": "不符規格",
            "not_applicable": "不適用",
            "client_said_none": "客戶表示無",
            # tax types
            "vat": "營業稅",
            "cit": "營利事業所得稅",
            "iit": "綜合所得稅",
            "stamp": "印花稅",
            "inheritance": "遺產稅",
            "labor_health": "勞健保",
            "other": "其他",
            # review note severities
            "critical": "嚴重",
            "major": "重要",
            "minor": "一般",
            # review note statuses
            "open": "待處理",
            "responded": "已回覆",
            "waived": "已豁免",
            "resolved": "已解決",
            "reopened": "重新開啟",
        }
    )
)

TEMPLATE_TYPE_LABELS: dict[str, str] = {
    "initial_request": "首次索件",
    "follow_up": "催件通知",
    "payment_follow_up": "固定開立提醒",
    "custom": "自訂",
}

PRIORITY_LABELS: dict[str, str] = {
    "low": "低",
    "normal": "一般",
    "high": "高",
    "urgent": "緊急",
}

SEVERITY_LABELS: dict[str, str] = {
    "critical": "嚴重",
    "major": "重要",
    "minor": "一般",
}

REVIEW_NOTE_STATUS_LABELS: dict[str, str] = {
    "open": "待處理",
    "responded": "已回覆",
    "waived": "已豁免",
    "resolved": "已解決",
    "reopened": "重新開啟",
}

UNKNOWN_STATUS_TEXT = "未知狀態，請聯絡系統管理員"

ANNUAL_WORK_STATUS_LABELS: dict[str, str] = {
    "not_started": "未開始",
    "in_progress": "進行中",
    "completed": "已完成",
    "completed_with_exception": "例外完成",
    "exception": "異常",
    "not_applicable": "不適用",
    "cancelled": "已取消",
}

ANNUAL_FILING_STATUS_LABELS: dict[str, str] = {
    "not_filed": "未申報",
    "filed": "已申報",
    "filing_failed": "申報失敗",
    "correction_required": "需要更正",
}

ANNUAL_DOCUMENT_STATUS_LABELS: dict[str, str] = {
    "not_requested": "未要求",
    "missing": "缺件",
    "partially_received": "部分收件",
    "complete": "文件齊全",
    "not_applicable": "不適用",
}

ANNUAL_TAX_STATUS_LABELS: dict[str, str] = {
    "unconfirmed": "稅款未確認",
    "awaiting_collection": "稅款待收",
    "partially_collected": "稅款部分收取",
    "collected": "稅款已收取",
    "paid": "稅款已繳納",
    "unpaid": "稅款未繳納",
    "refund": "退稅",
    "not_applicable": "不適用",
}

ANNUAL_FEE_STATUS_LABELS: dict[str, str] = {
    "not_billed": "服務費未開帳",
    "awaiting_payment": "服務費待付款",
    "partially_paid": "服務費部分付款",
    "paid": "服務費已付款",
    "not_applicable": "不適用",
}


def status_to_label(value: str | None) -> str:
    """Map a raw enum value to its Chinese label.

    Returns ``UNKNOWN_STATUS_TEXT`` if the value is missing or unrecognised.
    Callers should also write ``value`` to system log when this happens.
    """

    if not value:
        return UNKNOWN_STATUS_TEXT
    return STATUS_LABELS.get(value, UNKNOWN_STATUS_TEXT)
