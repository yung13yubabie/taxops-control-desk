"""Settings service.

Wraps the app settings repository, validates known keys, and writes audit
entries for setting changes.
"""

from __future__ import annotations

from ..core.text import sanitize_user_text
from ..repositories.app_settings import (
    AppSettingsRepository,
    DEFAULT_SETTINGS,
    VALID_QUERY_MODES,
)
from .audit import AuditService


class SettingsValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Settings key registry: only declared keys can be written via the service.
ALLOWED_KEYS: tuple[str, ...] = tuple(key for key, _ in DEFAULT_SETTINGS)


class SettingsService:
    def __init__(
        self,
        repo: AppSettingsRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._audit = audit

    def get(self, key: str) -> str | None:
        return self._repo.get(key)

    def get_all(self) -> dict[str, str]:
        return self._repo.get_all()

    def set_setting(self, key: str, value: str) -> str:
        if key not in ALLOWED_KEYS:
            raise SettingsValidationError("settings.save.failed")
        cleaned = sanitize_user_text(value, max_length=500)
        if key == "tax_cache.query_mode" and cleaned not in VALID_QUERY_MODES:
            raise SettingsValidationError("settings.save.failed")
        if key == "display.local_user_name" and not cleaned:
            cleaned = "local_user"
        self._repo.upsert(key, cleaned)
        self._audit.record(
            action="settings.update",
            target_type="setting",
            target_id=key,
            detail={"value": cleaned},
        )
        return cleaned
