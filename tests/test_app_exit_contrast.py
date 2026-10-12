"""Source app-control contracts, not frozen or native-Windows acceptance."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_tools import app_exit_contrast as control


def ready(directory):
    return {"bootstrap_calls": 1, "guard_acquired": True, "window_shown": True,
            "ready": True, "migration_count": 28, "shown_messages": [],
            "persistent_client": {"id": 1},
            "db_path": str(directory / "profile/local/TaxOpsControlDesk/taxops.sqlite")}


@pytest.mark.parametrize("key,value", [("bootstrap_calls", 0), ("guard_acquired", False),
    ("window_shown", False), ("ready", False), ("migration_count", 27),
    ("persistent_client", {}), ("db_path", "/other/real.sqlite"),
    ("shown_messages", [{"kind": "critical"}])])
def test_not_ready_or_nonisolated_application_evidence_rejected(tmp_path, key, value):
    evidence = ready(tmp_path)
    control.validate_app_report(evidence, tmp_path)
    evidence[key] = value
    with pytest.raises(ValueError, match="owned ready"):
        control.validate_app_report(evidence, tmp_path)


def test_exact_source_required_before_launch(monkeypatch):
    monkeypatch.setattr(control, "source_identity", lambda root: {"source_tree": "fixed"})
    assert control.require_source("fixed") == {"source_tree": "fixed"}
    with pytest.raises(ValueError, match="Source tree"):
        control.require_source("different")


def test_two_new_profiles_exact_cases_pinned_source_and_retained_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(control, "require_source", lambda tree: {"source_tree": tree})
    monkeypatch.setattr(control.common, "configured_runtime", lambda python: {"synthetic": "identity"})
    calls = []
    def run(command, directory, env, expected, timeout, **kwargs):
        calls.append(command)
        token = command[command.index("--profile-token") + 1]
        assert (directory / "profile/.taxops-onefile-gate").read_text() == token
        assert Path(env["LOCALAPPDATA"]) == directory / "profile/local"
        assert kwargs["expected_runtime"] == {"synthetic": "identity"}
        assert kwargs["expected_case"] == command[command.index("--child-case") + 1]
        return {"status": "matched_control", "child": ready(directory)}
    monkeypatch.setattr(control.common, "run_case", run)
    output = tmp_path / "new source controls"
    result = control.contrast(tmp_path / "python.exe", output, "fixed")
    assert result["status"] == "matched_controls" and len(calls) == 2
    assert [command[5] for command in calls] == ["taxops-close", "taxops-exit"]
    assert calls[0][-1] != calls[1][-1]  # Unique synthetic singleton names.
    assert result["source_after"] == result["source_identity"]
    assert json.loads((output / "app-contrast.json").read_text()) == result
    with pytest.raises(FileExistsError):
        control.contrast(tmp_path / "python.exe", output, "fixed")


def test_source_change_after_execution_preserves_failure_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "sys", SimpleNamespace(platform="win32"))
    identities = iter([{"source_tree": "fixed"}, ValueError("synthetic changed source")])
    def identity(tree):
        result = next(identities)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(control, "require_source", identity)
    monkeypatch.setattr(control.common, "configured_runtime", lambda python: {})
    monkeypatch.setattr(control.common, "run_case", lambda command, directory, *a, **kw:
                        {"status": "matched_control", "child": ready(directory)})
    result = control.contrast(tmp_path / "python.exe", tmp_path / "out", "fixed")
    assert result["status"] == "failed" and result["error"]["type"] == "ValueError"


def test_nonwindows_or_inside_source_output_refused_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(ValueError, match="Windows"):
        control.contrast(tmp_path / "python.exe", tmp_path / "out", "fixed")
    assert not (tmp_path / "out").exists()
    monkeypatch.setattr(control, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(ValueError, match="outside"):
        control.contrast(tmp_path / "python.exe", control.ROOT / "synthetic out", "fixed")


def test_child_profile_failure_precedes_runtime_or_application_import(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("Runtime must not be inspected before profile validation")
    monkeypatch.setattr(control.common, "runtime_identity", forbidden)
    assert control.run_child("taxops-exit", tmp_path, "wrong", "fixed", "synthetic") == 1
    assert "error" in json.loads((tmp_path / "child.json").read_text())


@pytest.mark.parametrize("case", ["taxops-close", "taxops-exit"])
def test_real_entry_instrumentation_ready_before_original_crt_exit_and_restores_hooks(tmp_path, monkeypatch, case):
    events, timers = [], []
    evidence = {"bootstrap_calls": 0, "window_shown": False, "shown_messages": []}
    db = tmp_path / "profile/local/TaxOpsControlDesk/taxops.sqlite"
    container = SimpleNamespace(paths=SimpleNamespace(db_path=db),
        conn=SimpleNamespace(execute=lambda sql: SimpleNamespace(fetchone=lambda: (28,))))
    class Guard:
        def acquire(self):
            events.append("guard")
            return True
    class Window:
        def __init__(self, value):
            self._container = value
        def show(self):
            events.append("show")
        def close(self):
            events.append("close")
    def bootstrap():
        events.append("bootstrap")
        return container
    app = SimpleNamespace(bootstrap=bootstrap, resolve_paths=lambda: container.paths,
                          _SINGLE_INSTANCE_NAME="original production name")
    def run():
        assert app._SINGLE_INSTANCE_NAME == "synthetic instance"
        assert Guard().acquire()
        window = Window(app.bootstrap())
        window.show()
        events.append("exec")
        for timer in timers:
            timer()
        return 0
    app.run = run
    def message(*args, **kwargs):
        return None
    widgets = SimpleNamespace(QApplication=SimpleNamespace(instance=lambda: SimpleNamespace(platformName=lambda: "windows")),
                              QMessageBox=SimpleNamespace(critical=message, information=message))
    core = SimpleNamespace(QTimer=SimpleNamespace(singleShot=lambda delay, callback: timers.append(callback)))
    class ExitRequested(BaseException):
        pass
    def abrupt(code):
        assert code == 77
        child = json.loads((tmp_path / "child.json").read_text())
        assert child["ready"] and child["persistent_client"] == {"id": 1}
        events.append("os._exit77")
        raise ExitRequested
    monkeypatch.setattr(control, "os", SimpleNamespace(_exit=abrupt))
    originals = (app.bootstrap, Window.show, Guard.acquire)
    args = (case, tmp_path, "synthetic instance", evidence, app, SimpleNamespace(MainWindow=Window),
            Guard, core, widgets, lambda *a, **kw: {"id": 1})
    if case == "taxops-exit":
        with pytest.raises(ExitRequested):
            control.run_application(*args)
        assert events == ["guard", "bootstrap", "show", "os._exit77"] and not timers
    else:
        assert control.run_application(*args) == 0
        assert events == ["guard", "bootstrap", "show", "exec", "close"]
    assert (app.bootstrap, Window.show, Guard.acquire) == originals
    assert app._SINGLE_INSTANCE_NAME == "original production name"
