"""Client × tax registry cache matcher.

Implements the rules in ``docs/registry_cache_workflow.md`` "Match Rules"
for the MOF source.

Hard rules:
- Empty / non-8-digit / non-numeric tax_id → ``needs_manual_review``.
- Tax id not found in cache → ``not_found``. The UI text MUST NOT use
  「公司不存在」 — only 「本地快取查無此統一編號，可能是快取未更新或
  資料來源未涵蓋。」.
- Tax id found and ``business_name`` matches client name (after trim) →
  ``matched``.
- Tax id found and name differs → ``mismatch``; the difference summary is
  written to ``differences_json`` and is NEVER applied back to clients.
- Address differences are recorded inside ``differences_json``.

The matcher always writes an audit log row and returns a status
histogram so the UI can render an honest summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ...repositories.clients import ClientRow, ClientsRepository
from ...repositories.registry_matches import (
    MatchInsert,
    MatchResultRow,
    REGISTRY_SOURCE_MOF,
    RegistryMatchRepository,
)
from ...repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from ..audit import AuditService

_TAX_ID_RE = re.compile(r"^\d{8}$")
_AUDIT_TARGET_TYPE = "tax_cache"


@dataclass(frozen=True)
class MatchSummary:
    client_count: int
    cache_version: str | None
    histogram: dict[str, int]


class RegistryMatcher:
    def __init__(
        self,
        clients_repo: ClientsRepository,
        registry_repo: TaxRegistryRepository,
        match_repo: RegistryMatchRepository,
        metadata_repo: TaxCacheMetadataRepository,
        audit: AuditService,
    ) -> None:
        self._clients = clients_repo
        self._registry = registry_repo
        self._matches = match_repo
        self._metadata = metadata_repo
        self._audit = audit

    def regenerate_mof(self) -> MatchSummary:
        cache_version = self._metadata.get("cache_version")
        clients = self._clients.list_clients(limit=1_000_000)
        items = list(self._build_items(clients, cache_version))
        histogram = self._matches.replace_for_source(REGISTRY_SOURCE_MOF, items)
        self._audit.record(
            action="tax_cache.match.regenerate",
            target_type=_AUDIT_TARGET_TYPE,
            target_id=cache_version,
            detail={
                "registry_source": REGISTRY_SOURCE_MOF,
                "client_count": len(clients),
                "cache_version": cache_version,
                "histogram": histogram,
            },
        )
        return MatchSummary(
            client_count=len(clients),
            cache_version=cache_version,
            histogram=histogram,
        )

    def list_mismatches(self) -> list[tuple[MatchResultRow, ClientRow]]:
        """Return all current mismatch rows paired with their client record."""
        rows = self._matches.list_for_source(REGISTRY_SOURCE_MOF)
        result: list[tuple[MatchResultRow, ClientRow]] = []
        for m in rows:
            if m.match_status != "mismatch":
                continue
            client = self._clients.get(m.client_id)
            if client is not None:
                result.append((m, client))
        return result

    # ------------------------------------------------------------------
    def _build_items(
        self,
        clients: list[ClientRow],
        cache_version: str | None,
    ) -> Iterable[MatchInsert]:
        for client in clients:
            yield self._classify(client, cache_version)

    def _classify(
        self,
        client: ClientRow,
        cache_version: str | None,
    ) -> MatchInsert:
        tax_id = (client.tax_id or "").strip()
        if not _TAX_ID_RE.match(tax_id):
            return MatchInsert(
                client_id=client.id,
                tax_id=client.tax_id,
                cache_version=cache_version,
                match_status="needs_manual_review",
            )

        row = self._registry.find_by_tax_id(tax_id)
        if row is None:
            return MatchInsert(
                client_id=client.id,
                tax_id=tax_id,
                cache_version=cache_version,
                match_status="not_found",
            )

        registry_name = (row["business_name"] or "").strip()
        registry_address = (row["business_address"] or "").strip()
        client_name = (client.client_name or "").strip()
        client_address = (client.address or "").strip()

        differences: dict[str, dict[str, str]] = {}
        if registry_name != client_name:
            differences["name"] = {
                "client": client_name,
                "registry": registry_name,
            }
        if client_address and registry_address and client_address != registry_address:
            differences["address"] = {
                "client": client_address,
                "registry": registry_address,
            }

        if "name" in differences:
            status = "mismatch"
        else:
            status = "matched"

        return MatchInsert(
            client_id=client.id,
            tax_id=tax_id,
            cache_version=cache_version,
            match_status=status,
            matched_name=registry_name or None,
            matched_address=registry_address or None,
            differences=differences or None,
        )
