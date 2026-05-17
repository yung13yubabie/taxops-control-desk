"""Search service: FTS5-backed full-text search for clients and engagements."""

from __future__ import annotations

from ..repositories.clients import ClientRow, ClientsRepository
from ..repositories.engagements import EngagementRow, EngagementsRepository
from ..repositories.search import SearchRepository

_FTS_MIN_QUERY_LEN = 3
_MAX_RESULTS = 200


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
        ids = self._repo.search_client_ids(query.strip(), limit=limit)
        result: list[ClientRow] = []
        for client_id in ids:
            row = self._clients_repo.get(client_id)
            if row is not None:
                result.append(row)
        return result

    def search_engagements(
        self, query: str, *, limit: int = _MAX_RESULTS
    ) -> list[EngagementRow]:
        ids = self._repo.search_engagement_ids(query.strip(), limit=limit)
        result: list[EngagementRow] = []
        for engagement_id in ids:
            row = self._engagements_repo.get(engagement_id)
            if row is not None:
                result.append(row)
        return result

    def rebuild_index(self) -> None:
        clients = self._clients_repo.list_clients(limit=100_000)
        self._repo.rebuild_clients(clients)

        engagements = self._engagements_repo.list_all(limit=100_000)
        self._repo.rebuild_engagements(engagements)
