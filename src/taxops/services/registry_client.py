"""Atomic application of official registry fields to an existing client."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ..core.clock import now_iso
from ..repositories.client_industries import ClientIndustriesRepository, ClientIndustryRow
from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.search import SearchRepository
from .audit import AuditService
from .client_industries import IndustryInput, prepare_industry_replace
from .client_profiles import _immediate_transaction
from .clients import UpdateClientInput, prepare_client_update


class RegistryClientService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clients_repo: ClientsRepository,
        industries_repo: ClientIndustriesRepository,
        audit: AuditService,
        search_repo: SearchRepository,
    ) -> None:
        dependencies = {
            "clients_repo": clients_repo.connection,
            "industries_repo": industries_repo.connection,
            "audit": audit.connection,
            "search_repo": search_repo.connection,
        }
        mismatched = [name for name, dependency in dependencies.items() if dependency is not conn]
        if mismatched:
            raise ValueError("registry_client.connection.mismatch: " + ", ".join(mismatched))
        self._conn = conn
        self._clients_repo = clients_repo
        self._industries_repo = industries_repo
        self._audit = audit
        self._search_repo = search_repo

    def apply_to_existing(
        self,
        client_id: int,
        payload: UpdateClientInput,
        *,
        industries: Sequence[IndustryInput] | None,
        source: str | None,
        source_version: str | None,
    ) -> tuple[ClientRow, tuple[ClientIndustryRow, ...]]:
        prepared_industries = None
        if industries is not None:
            prepared_industries = prepare_industry_replace(
                industries, source or "", source_version, allow_no_primary=True
            )
        with _immediate_transaction(self._conn):
            values, _detail = prepare_client_update(client_id, payload, self._clients_repo)
            client = self._clients_repo.update(client_id, **values)
            if client is None:
                raise RuntimeError("registry.apply.client_not_found")
            self._search_repo.update_client(
                client.id,
                client_code=client.client_code,
                client_name=client.client_name,
                tax_id=client.tax_id,
                short_name=client.short_name,
                contact_name=client.contact_name,
                note=client.note,
            )
            self._audit.record(
                action="client.update",
                target_type="client",
                target_id=str(client_id),
                detail=_detail,
            )
            if prepared_industries is not None:
                normalized, normalized_source, normalized_version = prepared_industries
                self._industries_repo.delete_for_client(client_id)
                industry_rows = tuple(
                    self._industries_repo.insert_many(
                        client_id,
                        normalized,
                        source=normalized_source,
                        source_version=normalized_version,
                        applied_at=now_iso(),
                    )
                )
                self._audit.record(
                    action="client.industries.replace",
                    target_type="client",
                    target_id=str(client_id),
                    detail={
                        "count": len(industry_rows),
                        "source": normalized_source,
                        "source_version": normalized_version or "",
                    },
                )
            else:
                industry_rows = tuple(self._industries_repo.list_for_client(client_id))
            self._audit.record(
                action="client.registry.apply",
                target_type="client",
                target_id=str(client_id),
                detail={
                    "fields_updated": True,
                    "industries_updated": prepared_industries is not None,
                    "industry_count": len(industry_rows),
                    "source": source or "",
                    "source_version": source_version or "",
                },
            )
        return client, industry_rows
