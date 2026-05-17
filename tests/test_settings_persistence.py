"""Settings persistence: defaults seeded, updates survive reopen."""

from __future__ import annotations

from pathlib import Path

import pytest

from taxops.core.paths import AppPaths, resolve_paths
from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.services.container import ServiceContainer, build_container
from taxops.services.settings import SettingsValidationError


def _open_container(paths: AppPaths) -> ServiceContainer:
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


def test_defaults_seeded_on_first_run(container: ServiceContainer) -> None:
    settings = container.settings.get_all()
    assert settings.get("tax_cache.query_mode") == "local_only"
    assert (
        settings.get("tax_cache.dataset_url")
        == "https://data.gov.tw/dataset/9400"
    )
    assert (
        settings.get("tax_cache.download_url")
        == "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    )
    assert (
        settings.get("tax_cache.gcis_swagger_url")
        == "https://data.gcis.nat.gov.tw/resources/swagger/swagger.json"
    )
    assert settings.get("display.local_user_name") == "local_user"


def test_settings_save_display_name_persists_across_reopen(tmp_path: Path) -> None:
    paths = resolve_paths(override_root=tmp_path / "Persist")
    c1 = _open_container(paths)
    try:
        c1.settings.set_setting("display.local_user_name", "美玲")
    finally:
        c1.close()

    c2 = _open_container(paths)
    try:
        assert c2.settings.get("display.local_user_name") == "美玲"
    finally:
        c2.close()


def test_settings_save_query_mode_validates(container: ServiceContainer) -> None:
    container.settings.set_setting("tax_cache.query_mode", "allow_online")
    assert container.settings.get("tax_cache.query_mode") == "allow_online"

    with pytest.raises(SettingsValidationError):
        container.settings.set_setting("tax_cache.query_mode", "anything_else")


def test_unknown_setting_key_rejected(container: ServiceContainer) -> None:
    with pytest.raises(SettingsValidationError):
        container.settings.set_setting("not.a.real.key", "x")
