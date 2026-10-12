from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from taxops.ui import app as app_module


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bootstrap_initializes_current_schema(temp_paths) -> None:
    container = app_module.bootstrap(temp_paths)
    try:
        applied = {
            row["version"]
            for row in container.conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        assert "0026_fix_payment_template_semantics" in applied
        assert container.paths.db_path.is_file()
    finally:
        container.close()


def test_activate_window_restores_minimized_window(qapp) -> None:
    window = QWidget()
    window.setWindowState(Qt.WindowState.WindowMinimized)

    app_module._activate_window(window)

    assert not window.windowState() & Qt.WindowState.WindowMinimized
    assert window.isVisible()
    window.close()


def test_run_existing_instance_never_opens_database(qapp, monkeypatch) -> None:
    events = []
    def forbidden_bootstrap():
        raise AssertionError("Existing instance must not open or migrate the database")
    monkeypatch.setattr(app_module, "bootstrap", forbidden_bootstrap)
    monkeypatch.setattr("taxops.ui.single_instance.SingleInstanceGuard.acquire", lambda _self: False)
    monkeypatch.setattr("taxops.ui.single_instance.SingleInstanceGuard.notify_existing", lambda _self: (events.append("notify"), True)[1])
    monkeypatch.setattr("taxops.ui.single_instance.SingleInstanceGuard.release", lambda _self: events.append("release"))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args: events.append("message"))
    assert app_module.run() == 0
    assert events == ["notify", "message", "release"]


@pytest.mark.parametrize("failure", ["guard", "bootstrap", "schema", "window", "close"])
def test_run_releases_guard_on_every_early_failure(qapp, monkeypatch, failure):
    from types import SimpleNamespace
    from taxops.db.migrate import UnsupportedSchemaError
    events = []
    def acquire(_self):
        events.append("acquire")
        if failure == "guard":
            raise RuntimeError("guard")
        return True
    def close():
        events.append("close")
        if failure == "close":
            raise RuntimeError("close")
    def bootstrap():
        events.append("bootstrap")
        if failure == "bootstrap":
            raise RuntimeError("bootstrap")
        if failure == "schema":
            raise UnsupportedSchemaError("synthetic")
        return SimpleNamespace(close=close)
    def window(_container):
        events.append("window")
        if failure == "window":
            raise RuntimeError("window")
        return SimpleNamespace(show=lambda: None)
    monkeypatch.setattr("taxops.ui.single_instance.SingleInstanceGuard.acquire", acquire)
    monkeypatch.setattr("taxops.ui.single_instance.SingleInstanceGuard.release", lambda _self: events.append("release"))
    monkeypatch.setattr(app_module, "bootstrap", bootstrap)
    monkeypatch.setattr("taxops.ui.main_window.MainWindow", window)
    monkeypatch.setattr(QApplication, "exec", lambda _self: 0)
    messages = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical", lambda *args: messages.append(args))
    if failure == "schema":
        assert app_module.run() == 1
        assert messages[0][1] == "資料版本不相容"
    else:
        with pytest.raises(RuntimeError, match=failure):
            app_module.run()
    assert events[-1] == "release" and events.count("release") == 1
    assert events.count("bootstrap") == (0 if failure == "guard" else 1)
    assert events.count("close") == (1 if failure in {"window", "close"} else 0)


def test_run_constructs_real_main_window_releases_guard_and_closes_db(
    qapp,
    temp_paths,
    monkeypatch,
) -> None:
    monkeypatch.setattr(app_module, "resolve_paths", lambda **_kwargs: temp_paths)
    monkeypatch.setattr(
        "taxops.ui.single_instance.SingleInstanceGuard.acquire",
        lambda _self: True,
    )
    released = []
    monkeypatch.setattr(
        "taxops.ui.single_instance.SingleInstanceGuard.release",
        lambda _self: released.append(True),
    )
    monkeypatch.setattr(QApplication, "exec", lambda _self: 7)

    assert app_module.run() == 7
    assert released == [True]


def test_main_entrypoint_exits_with_run_code(monkeypatch) -> None:
    from taxops import __main__ as main_module

    monkeypatch.setattr(main_module, "run", lambda: 23)

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 23
