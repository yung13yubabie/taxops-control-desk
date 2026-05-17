"""System log service.

Used to record technical failures (sanitized) and unexpected enum values.
Raw exception text never reaches the UI; it is captured here instead.
"""

from __future__ import annotations

import traceback
from typing import Any

from ..repositories.system_logs import SystemLogRepository


class SystemLogService:
    def __init__(self, repo: SystemLogRepository) -> None:
        self._repo = repo

    def info(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        self._repo.append(level="INFO", message=message, detail=detail)

    def warn(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        self._repo.append(level="WARN", message=message, detail=detail)

    def error(
        self,
        message: str,
        *,
        exc: BaseException | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = dict(detail or {})
        if exc is not None:
            payload["exc_type"] = type(exc).__name__
            payload["traceback"] = traceback.format_exc(limit=8)
        self._repo.append(level="ERROR", message=message, detail=payload or None)
