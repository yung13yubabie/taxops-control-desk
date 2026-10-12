"""Unknown schemas fail closed; supported historical schemas remain upgradeable."""

from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from taxops.db import migrate
from taxops.db.connection import open_connection
from taxops.db.migrations import MIGRATIONS
from taxops.ui import app as app_module


@pytest.mark.parametrize("cutoff", [1, 11, 12, 15, 22, 25, 26, 27, len(MIGRATIONS)])
def test_known_historical_schema_upgrades_and_preserves_client(
    tmp_path, monkeypatch, cutoff,
) -> None:
    path = tmp_path / "舊版資料.sqlite"
    conn = open_connection(path)
    with monkeypatch.context() as m:
        m.setattr(migrate, "MIGRATIONS", MIGRATIONS[:cutoff])
        migrate.apply_migrations(conn)
    conn.execute(
        "INSERT INTO clients(client_code,client_name,created_at,updated_at) "
        "VALUES (?,?,?,?)",
        ("UPGRADE-001", "升級保留客戶", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()

    conn = open_connection(path)
    try:
        assert migrate.apply_migrations(conn) == [v for v, _ in MIGRATIONS[cutoff:]]
        assert conn.execute(
            "SELECT client_name FROM clients WHERE client_code = 'UPGRADE-001'"
        ).fetchone()[0] == "升級保留客戶"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert migrate.apply_migrations(conn) == []
    finally:
        conn.close()


@pytest.mark.parametrize("cutoff", [1, len(MIGRATIONS)])
def test_unknown_schema_refused_without_ddl_dml_or_partial_upgrade(
    tmp_path, monkeypatch, cutoff,
) -> None:
    conn = open_connection(tmp_path / "unknown.sqlite")
    try:
        with monkeypatch.context() as m:
            m.setattr(migrate, "MIGRATIONS", MIGRATIONS[:cutoff])
            migrate.apply_migrations(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)",
            ("9999_future_schema", "2026-01-01"),
        )
        conn.commit()
        before = tuple(conn.iterdump())
        before_changes = conn.total_changes
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        with pytest.raises(migrate.UnsupportedSchemaError) as error:
            migrate.apply_migrations(conn)

        conn.set_trace_callback(None)
        assert error.value.versions == ("9999_future_schema",)
        assert "未執行資料遷移" in str(error.value)
        assert "升級前的備份" in str(error.value)
        assert conn.total_changes == before_changes
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        assert tuple(conn.iterdump()) == before
        assert not conn.in_transaction
    finally:
        conn.close()


def test_reading_versions_does_not_initialize_empty_database() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        assert migrate.applied_versions(conn) == set()
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        conn.close()


@pytest.mark.parametrize("stage", ["apply_migrations", "build_container"])
def test_bootstrap_closes_connection_if_setup_fails(
    temp_paths, monkeypatch, stage,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(app_module, "open_connection", lambda _path: conn)
    failure = RuntimeError("synthetic setup failure")

    def fail(*_args):
        raise failure

    monkeypatch.setattr(app_module, stage, fail)

    with pytest.raises(RuntimeError) as error:
        app_module.bootstrap(temp_paths)

    assert error.value is failure
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_run_shows_clear_schema_error_and_exits_nonzero(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    error = migrate.UnsupportedSchemaError({"9999_future_schema"})

    def fail():
        raise error

    monkeypatch.setattr(app_module, "bootstrap", fail)
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: messages.append(args))

    assert app_module.run() == 1
    assert len(messages) == 1
    assert messages[0][1] == "資料版本不相容"
    assert "較新版本" in messages[0][2]
    assert "不要刪除或覆蓋" in messages[0][2]
    assert "9999_future_schema" not in messages[0][2]
    assert "資料遷移" not in messages[0][2]
    assert QApplication.instance() is app
