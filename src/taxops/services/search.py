"""Search service: FTS5-backed full-text search for clients and engagements."""

from __future__ import annotations

import logging
import sqlite3

from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.engagements import EngagementRow, EngagementsRepository
from ..repositories.search import SearchRepository

_FTS_MIN_QUERY_LEN = 3
_MAX_RESULTS = 200
_log = logging.getLogger(__name__)


def _merge_ids(primary: list[int], fallback: list[int], limit: int) -> list[int]:
    merged = list(primary)
    seen = set(primary)
    for row_id in fallback:
        if row_id not in seen:
            merged.append(row_id)
            seen.add(row_id)
        if len(merged) >= limit:
            break
    return merged[:limit]


class SearchService:
    def __init__(
        self,
        repo: SearchRepository,
        clients_repo: ClientsRepository,
        engagements_repo: EngagementsRepository,
    ) -> None:
        self._repo = repo
        self._clients_repo = clients_repo
        self._engagements_repo = engagements_repo

    def is_fts_eligible(self, query: str) -> bool:
        return len(query.strip()) >= _FTS_MIN_QUERY_LEN

    def search_clients(
        self, query: str, *, limit: int = _MAX_RESULTS
    ) -> list[ClientRow]:
        term = query.strip()
        if not term:
            return []
        fts_failed = False
        try:
            fts_ids = self._repo.search_client_ids(term, limit=limit)
        except sqlite3.Error:
            fts_failed = True
            _log.warning(
                "client FTS search failed; using SQL fallback",
                exc_info=True,
            )
            fts_ids = []
        fallback_ids = self._repo.fallback_client_ids(term, limit=limit)
        if not fts_failed and any(
            row_id not in fts_ids for row_id in fallback_ids
        ):
            _log.warning("client FTS index incomplete; supplemented from SQL fallback")
        ids = _merge_ids(fts_ids, fallback_ids, limit)
        return self._clients_repo.list_by_ids(ids)

    def search_engagements(
        self, query: str, *, limit: int = _MAX_RESULTS
    ) -> list[EngagementRow]:
        term = query.strip()
        if not term:
            return []
        fts_failed = False
        try:
            fts_ids = self._repo.search_engagement_ids(term, limit=limit)
        except sqlite3.Error:
            fts_failed = True
            _log.warning(
                "engagement FTS search failed; using SQL fallback",
                exc_info=True,
            )
            fts_ids = []
        fallback_ids = self._repo.fallback_engagement_ids(term, limit=limit)
        if not fts_failed and any(
            row_id not in fts_ids for row_id in fallback_ids
        ):
            _log.warning(
                "engagement FTS index incomplete; supplemented from SQL fallback"
            )
        ids = _merge_ids(fts_ids, fallback_ids, limit)
        return self._engagements_repo.list_by_ids(ids)

    def rebuild_index(self) -> None:
        clients = self._clients_repo.list_clients(limit=100_000)
        engagements = self._engagements_repo.list_all(limit=100_000)
        with self._repo._conn:
            self._repo.rebuild_clients(clients)
            self._repo.rebuild_engagements(engagements)
