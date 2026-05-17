"""RegistryMatcher rules and post-conditions."""

from __future__ import annotations

import json

from taxops.repositories.clients import ClientsRepository
from taxops.repositories.registry_matches import (
    REGISTRY_SOURCE_MOF,
    RegistryMatchRepository,
)
from taxops.repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from taxops.services.clients import CreateClientInput
from taxops.services.container import ServiceContainer
from taxops.services.registry.matcher import RegistryMatcher


def _seed_cache_directly(container: ServiceContainer) -> None:
    """Insert two cache rows + cache_version metadata for matching tests."""
    conn = container.conn
    conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, business_address,"
        " cache_version, imported_at) VALUES (?, ?, ?, ?, ?)",
        ("11111111", "已登記公司A", "台北市信義區一號", "20260509", "2026-05-09T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO tax_registry_cache(tax_id, business_name, business_address,"
        " cache_version, imported_at) VALUES (?, ?, ?, ?, ?)",
        ("22222222", "已登記公司B", "新北市板橋區二號", "20260509", "2026-05-09T00:00:00Z"),
    )
    TaxCacheMetadataRepository(conn).upsert("cache_version", "20260509")
    conn.commit()


def _build_matcher(container: ServiceContainer) -> RegistryMatcher:
    return RegistryMatcher(
        clients_repo=ClientsRepository(container.conn),
        registry_repo=TaxRegistryRepository(container.conn),
        match_repo=RegistryMatchRepository(container.conn),
        metadata_repo=TaxCacheMetadataRepository(container.conn),
        audit=container.audit,
    )


def test_matcher_classifies_all_four_statuses(container: ServiceContainer) -> None:
    _seed_cache_directly(container)

    container.clients.create_client(
        CreateClientInput(client_code="C001", client_name="已登記公司A", tax_id="11111111")
    )
    container.clients.create_client(
        CreateClientInput(client_code="C002", client_name="差異名稱", tax_id="22222222")
    )
    container.clients.create_client(
        CreateClientInput(client_code="C003", client_name="找不到的公司", tax_id="99999999")
    )
    container.clients.create_client(
        CreateClientInput(client_code="C004", client_name="未填統編")
    )

    matcher = _build_matcher(container)
    summary = matcher.regenerate_mof()

    assert summary.client_count == 4
    assert summary.cache_version == "20260509"
    assert summary.histogram == {
        "matched": 1,
        "mismatch": 1,
        "not_found": 1,
        "needs_manual_review": 1,
    }


def test_matcher_writes_difference_summary_only(container: ServiceContainer) -> None:
    _seed_cache_directly(container)
    client = container.clients.create_client(
        CreateClientInput(
            client_code="C100",
            client_name="原始名稱",
            tax_id="11111111",
            address="客戶填的舊地址",
        )
    )
    matcher = _build_matcher(container)
    matcher.regenerate_mof()

    rows = RegistryMatchRepository(container.conn).list_for_client(client.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.match_status == "mismatch"
    assert row.matched_name == "已登記公司A"
    assert row.matched_address == "台北市信義區一號"
    assert row.differences_json is not None
    diff = json.loads(row.differences_json)
    assert diff["name"]["client"] == "原始名稱"
    assert diff["name"]["registry"] == "已登記公司A"
    assert diff["address"]["client"] == "客戶填的舊地址"
    assert diff["address"]["registry"] == "台北市信義區一號"

    # The clients table was NOT mutated — differences live only in the
    # match results table.
    refetched = container.clients.get_client(client.id)
    assert refetched is not None
    assert refetched.client_name == "原始名稱"
    assert refetched.address == "客戶填的舊地址"


def test_matcher_regenerate_replaces_previous_results(
    container: ServiceContainer,
) -> None:
    _seed_cache_directly(container)
    container.clients.create_client(
        CreateClientInput(client_code="C001", client_name="已登記公司A", tax_id="11111111")
    )
    matcher = _build_matcher(container)

    matcher.regenerate_mof()
    matches_repo = RegistryMatchRepository(container.conn)
    assert matches_repo.count_for_source(REGISTRY_SOURCE_MOF) == 1

    matcher.regenerate_mof()
    assert matches_repo.count_for_source(REGISTRY_SOURCE_MOF) == 1


def test_matcher_writes_audit_log(container: ServiceContainer) -> None:
    _seed_cache_directly(container)
    container.clients.create_client(
        CreateClientInput(client_code="C001", client_name="N", tax_id="11111111")
    )
    matcher = _build_matcher(container)
    matcher.regenerate_mof()

    audits = container.audit._repo.list_recent(limit=20)  # type: ignore[attr-defined]
    actions = [a.action for a in audits]
    assert "tax_cache.match.regenerate" in actions


def test_matcher_handles_blank_tax_id_as_needs_manual_review(
    container: ServiceContainer,
) -> None:
    _seed_cache_directly(container)
    for code in ("C1", "C2", "C3"):
        container.clients.create_client(
            CreateClientInput(client_code=code, client_name=f"客戶{code}", tax_id=None)
        )

    matcher = _build_matcher(container)
    summary = matcher.regenerate_mof()
    assert summary.histogram["needs_manual_review"] == 3
    assert summary.histogram["matched"] == 0
