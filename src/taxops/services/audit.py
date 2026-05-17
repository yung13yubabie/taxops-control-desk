"""Audit service: thin convenience wrapper around the repository."""

from __future__ import annotations

from typing import Any

from ..repositories.audit_logs import AuditLogRepository, AuditLogRow

DEFAULT_ACTOR = "local_user"


class AuditService:
    def __init__(
        self, repo: AuditLogRepository, *, actor: str = DEFAULT_ACTOR
    ) -> None:
        self._repo = repo
        self._actor = actor or DEFAULT_ACTOR

    @property
    def actor(self) -> str:
        return self._actor

    def set_actor(self, actor: str) -> None:
        self._actor = actor or DEFAULT_ACTOR

    def record(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditLogRow:
        return self._repo.append(
            actor=self._actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
