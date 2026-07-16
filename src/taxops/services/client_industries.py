"""Atomic application of a registry industry list to one active client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.clock import now_iso
from ..core.text import sanitize_user_text
from ..repositories.client_industries import (
    ClientIndustriesRepository,
    ClientIndustryRow,
)
from .audit import AuditService


class ClientIndustryValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IndustryInput:
    industry_code: str
    industry_name: str
    is_primary: bool = False


ClientIndustryInput = IndustryInput


class ClientIndustriesService:
    def __init__(self, repo: ClientIndustriesRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit
        self._conn = repo._conn

    @staticmethod
    def _bounded(value: str | None, *, maximum: int, field: str) -> str:
        cleaned = sanitize_user_text(value, max_length=maximum + 1)
        if len(cleaned) > maximum:
            raise ClientIndustryValidationError(f"client_industry.{field}.too_long")
        return cleaned

    def replace_from_registry(
        self,
        client_id: int,
        industries: Sequence[IndustryInput | tuple[str, str] | tuple[str, str, bool]],
        source: str,
        source_version: str | None,
    ) -> list[ClientIndustryRow]:
        if not self._repo.active_client_exists(client_id):
            raise ClientIndustryValidationError("client_industry.client_not_found")
        normalized_source = self._bounded(source, maximum=100, field="source")
        if not normalized_source:
            raise ClientIndustryValidationError("client_industry.source.required")
        normalized_version = (
            self._bounded(source_version, maximum=100, field="source_version") or None
        )
        normalized: list[dict[str, object]] = []
        seen_codes: set[str] = set()
        primary_count = 0
        for item in industries:
            if isinstance(item, IndustryInput):
                raw_code, raw_name, raw_primary = (
                    item.industry_code,
                    item.industry_name,
                    item.is_primary,
                )
            elif isinstance(item, tuple) and len(item) in (2, 3):
                raw_code = item[0]
                raw_name = item[1]
                raw_primary = item[2] if len(item) == 3 else False
            else:
                raise ClientIndustryValidationError("client_industry.item.invalid")
            code = self._bounded(raw_code, maximum=20, field="code").upper()
            name = self._bounded(raw_name, maximum=200, field="name")
            if not code:
                raise ClientIndustryValidationError("client_industry.code.required")
            if not name:
                raise ClientIndustryValidationError("client_industry.name.required")
            if code in seen_codes:
                raise ClientIndustryValidationError("client_industry.code.duplicate")
            seen_codes.add(code)
            if not isinstance(raw_primary, bool):
                raise ClientIndustryValidationError("client_industry.primary.invalid")
            is_primary = raw_primary
            primary_count += int(is_primary)
            normalized.append(
                {
                    "industry_code": code,
                    "industry_name": name,
                    "is_primary": is_primary,
                }
            )
        if primary_count > 1:
            raise ClientIndustryValidationError("client_industry.primary.invalid")
        if normalized and primary_count == 0:
            normalized[0]["is_primary"] = True

        with self._conn:
            self._repo.delete_for_client(client_id)
            rows = self._repo.insert_many(
                client_id,
                normalized,
                source=normalized_source,
                source_version=normalized_version,
                applied_at=now_iso(),
            )
            self._audit.record(
                action="client.industries.replace",
                target_type="client",
                target_id=str(client_id),
                detail={
                    "count": len(rows),
                    "source": normalized_source,
                    "source_version": normalized_version or "",
                },
            )
        return rows

    def list_for_client(self, client_id: int) -> list[ClientIndustryRow]:
        return self._repo.list_for_client(client_id)
