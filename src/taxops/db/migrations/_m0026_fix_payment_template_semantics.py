"""Migration 0026: stop presenting fixed-billing schedules as receivables."""

from __future__ import annotations

SQL = """
UPDATE message_templates
SET name = '固定開立提醒',
    body = '您好，{{ client_name }}：

依固定開立排程，以下項目已到預計開立日，但系統尚未確認完成：
{{ payment_records }}

全部待開立總額：NT${{ outstanding_amount }}
逾期待開立總額：NT${{ overdue_amount }}
最早預計開立日：{{ payment_due_date }}

請確認是否已完成開立；如已完成，請回到固定開立頁核定紀錄。謝謝。',
    updated_at = datetime('now')
WHERE id = 3
  AND is_builtin = 1;
"""
