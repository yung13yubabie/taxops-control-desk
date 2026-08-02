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


def test_setting_update_rolls_back_when_audit_fails(
    container: ServiceContainer, monkeypatch
) -> None:
    original = container.settings.get("tax_cache.query_mode")
    monkeypatch.setattr(
        container.settings._audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        container.settings.set_setting("tax_cache.query_mode", "allow_online")

    assert container.settings.get("tax_cache.query_mode") == original


def test_setting_update_never_commits_caller_owned_transaction(
    container: ServiceContainer,
) -> None:
    original = container.settings.get("tax_cache.query_mode")
    audit_before = container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
    ).fetchone()[0]
    container.conn.execute("BEGIN")
    container.conn.execute(
        "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)",
        ("test.caller_sentinel", "must survive service rejection", "2026-07-28"),
    )

    with pytest.raises(SettingsValidationError) as caught:
        container.settings.set_setting(
            "tax_cache.query_mode", "allow_online"
        )

    assert caught.value.code == "settings.transaction.already_active"
    assert container.conn.in_transaction
    assert (
        container.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("test.caller_sentinel",),
        ).fetchone()[0]
        == "must survive service rejection"
    )
    assert container.settings.get("tax_cache.query_mode") == original
    assert (
        container.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        == audit_before
    )
    container.conn.rollback()
    assert (
        container.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("test.caller_sentinel",),
        ).fetchone()
        is None
    )
