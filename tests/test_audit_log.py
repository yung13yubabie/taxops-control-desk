"""Audit log repository behaviour."""

from __future__ import annotations

import json
import sqlite3

from taxops.repositories.audit_logs import AuditLogRepository


def test_append_persists_row(db_conn: sqlite3.Connection) -> None:
    repo = AuditLogRepository(db_conn)
    row = repo.append(
        actor="local_user",
        action="client.create",
        target_type="client",
        target_id="1",
        detail={"name": "測試公司A", "tax_id": "12345678"},
    )
    assert row.id > 0
    assert row.actor == "local_user"
    assert row.action == "client.create"
    assert row.target_id == "1"
    assert json.loads(row.detail_json or "{}") == {
        "name": "測試公司A",
        "tax_id": "12345678",
    }
    assert row.created_at.endswith("Z")


def test_list_recent_returns_descending(db_conn: sqlite3.Connection) -> None:
    repo = AuditLogRepository(db_conn)
    for action in ("client.create", "settings.update", "client.create"):
        repo.append(
            actor="local_user",
            action=action,
            target_type="client" if action.startswith("client") else "setting",
        )
    items = repo.list_recent(limit=10)
    assert [r.action for r in items] == [
        "client.create",
        "settings.update",
        "client.create",
    ]
    assert repo.count() == 3
