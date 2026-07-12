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


def test_run_notifies_existing_instance_and_closes_container(
    qapp,
    temp_paths,
    monkeypatch,
) -> None:
    container = app_module.bootstrap(temp_paths)
    closed = []
    original_close = container.close

    def close() -> None:
        original_close()
        closed.append(True)

    monkeypatch.setattr(container, "close", close)
    monkeypatch.setattr(app_module, "bootstrap", lambda: container)
    monkeypatch.setattr(
        "taxops.ui.single_instance.SingleInstanceGuard.acquire",
        lambda _self: False,
    )
    notified = []
    monkeypatch.setattr(
        "taxops.ui.single_instance.SingleInstanceGuard.notify_existing",
        lambda _self: notified.append(True),
    )
    messages = []
    monkeypatch.setattr(
        "taxops.ui.app.QMessageBox" if hasattr(app_module, "QMessageBox") else
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args: messages.append(args),
        raising=False,
    )

    assert app_module.run() == 0
    assert notified == [True]
    assert closed == [True]


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
