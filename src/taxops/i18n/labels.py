"""Navigation, button, and table-header labels (Traditional Chinese)."""

from __future__ import annotations

from types import MappingProxyType

DISABLED_TOOLTIP = "此功能尚未開放"

NAV_LABELS: dict[str, str] = dict(
    MappingProxyType(
        {
            "dashboard": "首頁儀表板",
            "clients": "客戶管理",
            "engagements": "案件管理",
            "doc_requests": "索件管理",
            "tasks": "待辦事項",
            "templates": "訊息模板",
            "registry": "工商 / 稅籍查詢",
            "late_fee": "滯納金試算",
            "attachments": "附件管理",
            "review_notes": "覆核意見",  # retained label key for action-contract whitelist
            "folder_bookmarks": "資料夾管理",
            "recurring_billing": "固定開立",
            "settings": "設定",
        }
    )
)

# Primary buttons exposed in slice 1. Disabled / placeholder buttons declare
# their labels directly in the action registry.
BUTTON_LABELS: dict[str, str] = dict(
    MappingProxyType(
        {
            "clients.new": "新增客戶",
            "clients.refresh": "重新整理",
            "client_dialog.save": "儲存",
            "client_dialog.cancel": "取消",
            "settings.open_data_folder": "開啟資料庫資料夾",
            "settings.open_attachments_folder": "開啟附件資料夾",
            "settings.copy_db_path": "複製資料庫路徑",
            "settings.copy_attachments_path": "複製附件路徑",
            "settings.save_display_name": "儲存使用者顯示名稱",
            "settings.save_query_mode": "儲存查詢模式",
            "tax_cache.import_zip": "從 ZIP 匯入稅籍資料",
            "tax_cache.import_bundle": "匯入稅籍快取包",
            "tax_cache.export_bundle": "匯出稅籍快取包",
            "tax_cache.verify": "驗證快取",
            "tax_cache.regenerate_matches": "重新產生客戶對照結果",
        }
    )
)

# Column headers shown in the client list view.
TABLE_HEADERS: dict[str, dict[str, str]] = {
    "clients": {
        "id": "編號",
        "client_code": "客戶代號",
        "tax_id": "統一編號",
        "client_name": "客戶名稱",
        "short_name": "簡稱",
        "contact_name": "聯絡人",
        "contact_phone": "聯絡電話",
        "contact_email": "聯絡信箱",
        "address": "地址",
        "note": "備註",
        "lease_start": "租約起日",
        "lease_end": "租約迄日",
        "updated_at": "更新時間",
    }
}
