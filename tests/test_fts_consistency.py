from __future__ import annotations

import logging
import sqlite3

import pytest

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.search import SearchRepository
from taxops.services.audit import AuditService
from taxops.services.clients import (
    ClientsService,
    CreateClientInput,
    UpdateClientInput,
)
from taxops.services.engagements import EngagementsService, CreateEngagementInput
from taxops.services.search import SearchService


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    yield connection
    connection.close()


def _services(conn):
    clients_repo = ClientsRepository(conn)
    engagements_repo = EngagementsRepository(conn)
    audit = AuditService(AuditLogRepository(conn), actor="test")
    search_repo = SearchRepository(conn)
    return (
        clients_repo,
        engagements_repo,
        ClientsService(clients_repo, audit, search_repo),
        EngagementsService(engagements_repo, audit, search_repo),
        SearchService(search_repo, clients_repo, engagements_repo),
    )


def test_client_create_fts_failure_rolls_back_core_and_audit(tmp_path):
    db_path = tmp_path / "client-fts-failure.db"
    conn = open_connection(db_path)
    apply_migrations(conn)

    class _FailingSearchRepo:
        def add_client(self, *args, **kwargs):
            raise sqlite3.OperationalError("simulated FTS write failure")

    service = ClientsService(
        ClientsRepository(conn),
        AuditService(AuditLogRepository(conn), actor="test"),
        _FailingSearchRepo(),  # type: ignore[arg-type]
    )

    with pytest.raises(sqlite3.OperationalError, match="FTS write failure"):
        service.create_client(
            CreateClientInput(client_code="TX001", client_name="交易回滾客戶")
        )

    verifier = open_connection(db_path)
    try:
        assert verifier.execute(
            "SELECT COUNT(*) FROM clients WHERE client_code = 'TX001'"
        ).fetchone()[0] == 0
        assert verifier.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'client.create'"
        ).fetchone()[0] == 0
    finally:
        verifier.close()
        conn.close()


def test_fts_integrity_failure_is_not_reported_as_duplicate_client_code(conn):
    class _FailingSearchRepo:
        def add_client(self, *args, **kwargs):
            raise sqlite3.IntegrityError(
                "UNIQUE constraint failed: fts_clients.rowid"
            )

    service = ClientsService(
        ClientsRepository(conn),
        AuditService(AuditLogRepository(conn), actor="test"),
        _FailingSearchRepo(),  # type: ignore[arg-type]
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="fts_clients.rowid",
    ):
        service.create_client(
            CreateClientInput(client_code="TX002", client_name="索引錯誤分類測試")
        )


def test_engagement_create_fts_failure_rolls_back_core_and_audit(tmp_path):
    db_path = tmp_path / "engagement-fts-failure.db"
    conn = open_connection(db_path)
    apply_migrations(conn)
    client_id = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES ('TXC01', '交易測試客戶', datetime('now'), datetime('now'))"
    ).lastrowid
    conn.commit()

    class _FailingSearchRepo:
        connection = conn

        def add_engagement(self, *args, **kwargs):
            raise sqlite3.OperationalError("simulated FTS write failure")

    service = EngagementsService(
        EngagementsRepository(conn),
        AuditService(AuditLogRepository(conn), actor="test"),
        _FailingSearchRepo(),  # type: ignore[arg-type]
    )

    with pytest.raises(sqlite3.OperationalError, match="FTS write failure"):
        service.create_engagement(
            CreateEngagementInput(
                client_id=int(client_id),
                engagement_name="交易回滾案件",
                tax_type="vat",
                period_name="2026",
            )
        )

    verifier = open_connection(db_path)
    try:
        assert verifier.execute(
            "SELECT COUNT(*) FROM engagements WHERE engagement_name = '交易回滾案件'"
        ).fetchone()[0] == 0
        assert verifier.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'engagement.create'"
        ).fetchone()[0] == 0
    finally:
        verifier.close()
        conn.close()


def test_client_update_fts_failure_preserves_committed_row(tmp_path):
    db_path = tmp_path / "client-fts-update-failure.db"
    conn = open_connection(db_path)
    apply_migrations(conn)
    clients_repo = ClientsRepository(conn)
    audit = AuditService(AuditLogRepository(conn), actor="test")
    created = ClientsService(
        clients_repo, audit, SearchRepository(conn)
    ).create_client(
        CreateClientInput(client_code="TXU01", client_name="修改前名稱")
    )

    class _FailingSearchRepo:
        def update_client(self, *args, **kwargs):
            raise sqlite3.OperationalError("simulated FTS update failure")

    service = ClientsService(
        clients_repo,
        audit,
        _FailingSearchRepo(),  # type: ignore[arg-type]
    )
    with pytest.raises(sqlite3.OperationalError, match="FTS update failure"):
        service.update_client(
            created.id,
            UpdateClientInput(client_code="TXU01", client_name="修改後名稱"),
        )

    verifier = open_connection(db_path)
    try:
        row = verifier.execute(
            "SELECT client_name FROM clients WHERE id = ?", (created.id,)
        ).fetchone()
        assert row["client_name"] == "修改前名稱"
        assert verifier.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'client.update'"
        ).fetchone()[0] == 0
    finally:
        verifier.close()
        conn.close()


def test_client_delete_fts_failure_preserves_active_row(tmp_path):
    db_path = tmp_path / "client-fts-delete-failure.db"
    conn = open_connection(db_path)
    apply_migrations(conn)
    clients_repo = ClientsRepository(conn)
    audit = AuditService(AuditLogRepository(conn), actor="test")
    created = ClientsService(
        clients_repo, audit, SearchRepository(conn)
    ).create_client(
        CreateClientInput(client_code="TXD01", client_name="刪除交易測試")
    )

    class _FailingSearchRepo:
        def delete_client(self, *args, **kwargs):
            raise sqlite3.OperationalError("simulated FTS delete failure")

    service = ClientsService(
        clients_repo,
        audit,
        _FailingSearchRepo(),  # type: ignore[arg-type]
    )
    with pytest.raises(sqlite3.OperationalError, match="FTS delete failure"):
        service.delete_client(created.id)

    verifier = open_connection(db_path)
    try:
        row = verifier.execute(
            "SELECT deleted_at FROM clients WHERE id = ?", (created.id,)
        ).fetchone()
        assert row["deleted_at"] is None
        assert verifier.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'client.delete'"
        ).fetchone()[0] == 0
    finally:
        verifier.close()
        conn.close()


def test_search_clients_falls_back_when_fts_table_is_missing(conn, caplog):
    clients_repo, engagements_repo, clients, _, _ = _services(conn)
    clients.create_client(
        CreateClientInput(client_code="FB001", client_name="缺表仍可搜尋客戶")
    )
    conn.execute("DROP TABLE fts_clients")
    conn.commit()
    search = SearchService(SearchRepository(conn), clients_repo, engagements_repo)

    with caplog.at_level(logging.WARNING):
        rows = search.search_clients("缺表仍可搜尋")

    assert [row.client_code for row in rows] == ["FB001"]
    assert "client FTS search failed; using SQL fallback" in caplog.text


def test_search_engagements_falls_back_when_fts_table_is_missing(conn, caplog):
    clients_repo, engagements_repo, clients, engagements, _ = _services(conn)
    client = clients.create_client(
        CreateClientInput(client_code="FBE01", client_name="案件搜尋客戶")
    )
    engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="缺表仍可搜尋案件",
            tax_type="cit",
            period_name="2026",
        )
    )
    conn.execute("DROP TABLE fts_engagements")
    conn.commit()
    search = SearchService(SearchRepository(conn), clients_repo, engagements_repo)

    with caplog.at_level(logging.WARNING):
        rows = search.search_engagements("缺表仍可搜尋")

    assert [row.engagement_name for row in rows] == ["缺表仍可搜尋案件"]
    assert "engagement FTS search failed; using SQL fallback" in caplog.text


def test_search_clients_supplements_stale_fts_index(conn, caplog):
    _, _, clients, _, search = _services(conn)
    client = clients.create_client(
        CreateClientInput(
            client_code="STALE1",
            client_name="索引遺漏仍可找到客戶",
        )
    )
    conn.execute("DELETE FROM fts_clients WHERE rowid = ?", (client.id,))
    conn.commit()

    with caplog.at_level(logging.WARNING):
        rows = search.search_clients("索引遺漏仍可找到")

    assert [row.id for row in rows] == [client.id]
    assert "client FTS index incomplete" in caplog.text
