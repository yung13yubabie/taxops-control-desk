"""FTS5 full-text search: migration, index sync, query, and UI contracts."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from taxops.db.migrate import apply_migrations
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.search import SearchRepository
from taxops.services.audit import AuditService
from taxops.services.clients import ClientsService, CreateClientInput, UpdateClientInput
from taxops.services.engagements import EngagementsService, CreateEngagementInput
from taxops.services.search import SearchService
from taxops.ui.action_registry import PAGE_CLIENTS, actions_for_page


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def search_repo(conn):
    return SearchRepository(conn)


@pytest.fixture
def clients_repo(conn):
    return ClientsRepository(conn)


@pytest.fixture
def engagements_repo(conn):
    return EngagementsRepository(conn)


@pytest.fixture
def audit(conn):
    return AuditService(AuditLogRepository(conn), actor="test")


@pytest.fixture
def clients_svc(clients_repo, audit, search_repo):
    return ClientsService(clients_repo, audit, search_repo)


@pytest.fixture
def engagements_svc(engagements_repo, audit, search_repo):
    return EngagementsService(engagements_repo, audit, search_repo)


@pytest.fixture
def search_svc(search_repo, clients_repo, engagements_repo):
    return SearchService(search_repo, clients_repo, engagements_repo)


def _make_client(svc: ClientsService, *, code: str, name: str, note: str = "") -> int:
    row = svc.create_client(
        CreateClientInput(
            client_code=code,
            client_name=name,
            note=note or None,
        )
    )
    return row.id


# ── migration: FTS5 tables exist ────────────────────────────────────────────


def test_fts_clients_table_exists(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "fts_clients" in tables


def test_fts_engagements_table_exists(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "fts_engagements" in tables


# ── index sync: create ───────────────────────────────────────────────────────


def test_create_client_appears_in_fts(clients_svc, search_svc):
    _make_client(clients_svc, code="A001", name="台灣測試公司")
    results = search_svc.search_clients("台灣測試")
    assert any(r.client_code == "A001" for r in results)


def test_create_client_searchable_by_code(clients_svc, search_svc):
    _make_client(clients_svc, code="XYZ999", name="隨機公司名稱")
    results = search_svc.search_clients("XYZ999")
    assert any(r.client_code == "XYZ999" for r in results)


def test_create_client_searchable_by_note(clients_svc, search_svc):
    _make_client(clients_svc, code="NTE001", name="備註測試", note="特殊備忘事項ABC")
    results = search_svc.search_clients("特殊備忘事項")
    assert any(r.client_code == "NTE001" for r in results)


# ── index sync: edit ─────────────────────────────────────────────────────────


def test_edit_client_old_term_not_found(clients_svc, search_svc):
    client_id = _make_client(clients_svc, code="UPD001", name="舊名稱公司")
    clients_svc.update_client(
        client_id,
        UpdateClientInput(client_code="UPD001", client_name="全新名稱企業"),
    )
    results = search_svc.search_clients("舊名稱公司")
    assert not any(r.id == client_id for r in results)


def test_edit_client_new_term_found(clients_svc, search_svc):
    client_id = _make_client(clients_svc, code="UPD002", name="原始名稱")
    clients_svc.update_client(
        client_id,
        UpdateClientInput(client_code="UPD002", client_name="更新後名稱企業"),
    )
    results = search_svc.search_clients("更新後名稱")
    assert any(r.id == client_id for r in results)


# ── index sync: delete / soft-delete ────────────────────────────────────────


def test_deleted_client_not_in_fts_results(clients_svc, search_svc):
    client_id = _make_client(clients_svc, code="DEL001", name="將被刪除公司")
    clients_svc.delete_client(client_id)
    results = search_svc.search_clients("將被刪除公司")
    assert not any(r.id == client_id for r in results)


def test_deleted_client_fts_entry_removed(clients_svc, search_repo):
    client_id = _make_client(clients_svc, code="DEL002", name="刪除後FTS確認")
    clients_svc.delete_client(client_id)
    ids = search_repo.search_client_ids("刪除後FTS確認")
    assert client_id not in ids


# ── Chinese full-text search ─────────────────────────────────────────────────


def test_chinese_substring_search(clients_svc, search_svc):
    _make_client(clients_svc, code="CHN001", name="中文全文搜尋測試公司")
    results = search_svc.search_clients("全文搜尋")
    assert any(r.client_code == "CHN001" for r in results)


def test_chinese_partial_match(clients_svc, search_svc):
    _make_client(clients_svc, code="CHN002", name="財政部稅籍資料整合系統")
    results = search_svc.search_clients("稅籍資料")
    assert any(r.client_code == "CHN002" for r in results)


# ── SQL injection safety ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "injection",
    [
        "'; DROP TABLE clients; --",
        '" OR "1"="1',
        "* OR *",
        "台灣 OR 1=1",
        '"injected"',
        "abc*def",
    ],
)
def test_injection_queries_do_not_raise(search_svc, injection):
    results = search_svc.search_clients(injection)
    assert isinstance(results, list)


# ── LIMIT enforcement ─────────────────────────────────────────────────────────


def test_search_respects_limit(clients_svc, search_repo):
    for i in range(10):
        clients_svc.create_client(
            CreateClientInput(
                client_code=f"LIM{i:03d}",
                client_name=f"極限測試公司{i:03d}",
            )
        )
    ids = search_repo.search_client_ids("極限測試公司", limit=5)
    assert len(ids) <= 5


def test_search_default_limit_is_bounded(search_repo):
    ids = search_repo.search_client_ids("不存在名稱", limit=200)
    assert isinstance(ids, list)


def test_update_client_rollback_keeps_old_fts_entry_on_insert_failure(conn):
    repo = SearchRepository(conn)
    repo.add_client(
        1,
        client_code="RB001",
        client_name="RollbackOldName",
        tax_id=None,
        short_name=None,
        contact_name=None,
        note=None,
    )

    class _FailingConn:
        def __init__(self, real):
            self._real = real
            self._seen_delete = False

        def execute(self, sql, params=()):
            if sql.startswith("DELETE FROM fts_clients"):
                self._seen_delete = True
            elif self._seen_delete and sql.startswith("INSERT INTO fts_clients"):
                raise RuntimeError("simulated FTS insert failure")
            return self._real.execute(sql, params)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

    failing_repo = SearchRepository(_FailingConn(conn))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        failing_repo.update_client(
            1,
            client_code="RB001",
            client_name="RollbackNewName",
            tax_id=None,
            short_name=None,
            contact_name=None,
            note=None,
        )

    assert repo.search_client_ids("RollbackOldName") == [1]
    assert repo.search_client_ids("RollbackNewName") == []


def test_client_service_logs_fts_failure_without_hiding_it(
    clients_repo, audit, caplog
):
    class _FailingSearchRepo:
        def add_client(self, *args, **kwargs):
            raise RuntimeError("simulated FTS add failure")

    svc = ClientsService(clients_repo, audit, _FailingSearchRepo())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        row = svc.create_client(
            CreateClientInput(client_code="LOG001", client_name="FTS記錄測試")
        )

    assert row.client_code == "LOG001"
    assert "client FTS add failed" in caplog.text


# ── engagement FTS ────────────────────────────────────────────────────────────


def test_create_engagement_appears_in_fts(clients_svc, engagements_svc, search_svc):
    client_id = _make_client(clients_svc, code="ENG001", name="案件測試客戶")
    engagements_svc.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="二〇二六年度營利事業所得稅申報",
            tax_type="cit",
            period_name="2026",
        )
    )
    results = search_svc.search_engagements("營利事業所得稅")
    assert any(r.engagement_name == "二〇二六年度營利事業所得稅申報" for r in results)


def test_deleted_engagement_not_in_fts(clients_svc, engagements_svc, search_svc):
    client_id = _make_client(clients_svc, code="ENG002", name="案件刪除測試")
    row = engagements_svc.create_engagement(
        CreateEngagementInput(
            client_id=client_id,
            engagement_name="將被刪除的申報案件",
            tax_type="vat",
            period_name="2026Q1",
        )
    )
    engagements_svc.delete_engagement(row.id)
    results = search_svc.search_engagements("將被刪除的申報案件")
    assert not any(r.id == row.id for r in results)


# ── rebuild index ─────────────────────────────────────────────────────────────


def test_rebuild_index_repopulates(clients_svc, search_svc, search_repo, conn):
    _make_client(clients_svc, code="REB001", name="重建索引測試")
    conn.execute("DELETE FROM fts_clients")
    conn.commit()
    assert search_repo.search_client_ids("重建索引測試") == []
    search_svc.rebuild_index()
    ids = search_repo.search_client_ids("重建索引測試")
    assert len(ids) > 0


# ── is_fts_eligible ───────────────────────────────────────────────────────────


def test_fts_eligible_for_3_chars(search_svc):
    assert search_svc.is_fts_eligible("abc") is True


def test_fts_eligible_for_chinese_3_chars(search_svc):
    assert search_svc.is_fts_eligible("台灣公") is True


def test_not_eligible_for_2_chars(search_svc):
    assert search_svc.is_fts_eligible("AB") is False


def test_not_eligible_for_empty(search_svc):
    assert search_svc.is_fts_eligible("") is False


# ── action registry contract ──────────────────────────────────────────────────


def test_search_clients_contract_in_registry():
    contracts = actions_for_page(PAGE_CLIENTS)
    labels = {c.button_label for c in contracts}
    assert "搜尋客戶" in labels


def test_search_clients_contract_fields():
    for c in actions_for_page(PAGE_CLIENTS):
        if c.button_label == "搜尋客戶":
            assert c.service == "SearchService.search_clients"
            assert c.repository == "SearchRepository.search_client_ids"
            assert c.enabled is True
            return
    pytest.fail("搜尋客戶 contract not found")
