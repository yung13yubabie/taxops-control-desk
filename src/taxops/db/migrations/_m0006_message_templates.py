"""Migration 0006: message_templates.

Built-in and custom templates for generating plain-text messages
(follow-up requests, initial requests, client notifications).
Variables rendered via Jinja2 against a whitelist.
Soft-deleted via deleted_at.
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS message_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    template_type   TEXT    NOT NULL DEFAULT 'custom',
    body            TEXT    NOT NULL,
    is_builtin      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    deleted_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_message_templates_type ON message_templates(template_type);

INSERT OR IGNORE INTO message_templates(id, name, template_type, body, is_builtin, created_at, updated_at)
VALUES
(
    1,
    '首次索件通知',
    'initial_request',
    '您好，{{ client_name }}：

這邊通知您，{{ period_name }} 的 {{ tax_type_name }} 申報作業即將開始。

請您提供以下資料：
{{ missing_items }}

麻煩您於 {{ due_date }} 前完成提供，如有疑問請隨時聯絡我們。

謝謝。',
    1,
    datetime('now'),
    datetime('now')
),
(
    2,
    '催件通知',
    'follow_up',
    '您好，{{ client_name }}：

這邊提醒您，{{ period_name }} 的 {{ tax_type_name }} 資料尚有以下項目未收到：
{{ missing_items }}

麻煩您於 {{ due_date }} 前提供，謝謝。',
    1,
    datetime('now'),
    datetime('now')
);
"""
