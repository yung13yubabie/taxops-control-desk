"""Migration 0024: built-in payment follow-up message template."""

from __future__ import annotations

SQL = """
INSERT OR IGNORE INTO message_templates(id, name, template_type, body, is_builtin, created_at, updated_at)
VALUES
(
    3,
    '欠款催繳通知',
    'payment_follow_up',
    '您好，{{ client_name }}：

目前系統顯示尚有下列款項未完成：
{{ payment_records }}

未收款總額：NT${{ outstanding_amount }}
最早應收日：{{ payment_due_date }}

若已安排付款，請回覆付款日期或匯款末五碼，方便我更新紀錄。謝謝。',
    1,
    datetime('now'),
    datetime('now')
);
"""
