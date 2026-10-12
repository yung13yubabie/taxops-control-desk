"""Fail-closed onefile gate contracts, not a bootloader execution substitute."""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from build_tools import verify_onefile as gate
from build_tools import onefile_runtime_probe as probe


def report_fixture(tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    database = tmp_path / "local/TaxOpsControlDesk/taxops.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"synthetic")
    report = {"meipass": str(temp / "_MEI123"), "frozen": True, "platform": "win32", "normal_exit": True,
              "exit_code": 0, "native_files": {"a.dll": "hash"}, "bootstrap_calls": 1, "guard_acquired": True,
              "window_shown": True, "migration_count": 28, "db_path": str(database)}
    return temp, database, report


@pytest.mark.parametrize("fault", [None, "remains", "outside", "not_frozen", "wrong_bytes", "db_in_mei", "missing_migration", "twice"])
def test_normal_cleanup_requires_exact_actual_mei_absent_and_db_separate(tmp_path, fault):
    temp, database, report = report_fixture(tmp_path)
    if fault == "remains":
        Path(report["meipass"]).mkdir()
    elif fault == "outside":
        report["meipass"] = str(tmp_path / "outside")
    elif fault == "not_frozen":
        report["frozen"] = False
    elif fault == "wrong_bytes":
        report["native_files"]["a.dll"] = "wrong"
    elif fault == "db_in_mei":
        report["db_path"] = str(Path(report["meipass"]) / "taxops.sqlite")
    elif fault == "missing_migration":
        report["migration_count"] = 27
    elif fault == "twice":
        report["bootstrap_calls"] = 2
    if fault:
        with pytest.raises(gate.BundleVerificationError):
            gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=True)
    else:
        gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=True)


def test_duplicate_instance_must_not_bootstrap(tmp_path):
    temp, database, report = report_fixture(tmp_path)
    report.update(bootstrap_calls=0, guard_acquired=False, window_shown=False)
    gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=False)
    report["bootstrap_calls"] = 1
    with pytest.raises(gate.BundleVerificationError):
        gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=False)


def test_probe_does_not_claim_source_execution_is_bootloader_proof(tmp_path):
    path = tmp_path / "report.json"
    args = ["--report", str(path), "--ready", str(tmp_path / "ready"), "--release", str(tmp_path / "release"), "--instance-name", "synthetic", "--profile-root", str(tmp_path), "--profile-token", "synthetic", "--persistent-record", str(tmp_path / "record")]
    assert probe.main(args) == 1
    assert json.loads(path.read_text())["normal_exit"] is False


def test_gate_refuses_non_windows_before_creating_any_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(gate.BundleVerificationError, match="Windows"):
        gate.verify(tmp_path / "app.exe", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("fault", [None, "skip", "partial", "coverage", "unrun"])
def test_source_gate_requires_complete_zero_skip_unrounded_coverage(tmp_path, monkeypatch, fault):
    from build_tools import run_test_matrix
    monkeypatch.setattr(run_test_matrix, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "source_identity", lambda _root: {"source_tree": "synthetic"})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_synthetic.py").write_text("synthetic")
    report = {"status": "passed", "source_identity": {"source_tree": "synthetic"}, "source_unchanged": True,
              "full_suite": True, "unrun_files": [], "branch_coverage": True,
              "raw_percent_covered": 90.01, "files": [{"file": "tests/test_synthetic.py", "status": "passed", "exit_code": 0, "skipped": 0}],
              "totals": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}}
    if fault == "skip":
        report["files"][0]["skipped"] = 1
    elif fault == "partial":
        report["full_suite"] = False
    elif fault == "coverage":
        report["raw_percent_covered"] = 89.9999999
    elif fault == "unrun":
        report["unrun_files"] = ["test_synthetic.py"]
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(report))
    if fault:
        with pytest.raises(gate.BundleVerificationError):
            gate.check_source_matrix(path)
    else:
        assert gate.check_source_matrix(path)["raw_branch_coverage"] == 90.01


def test_probe_refuses_profile_environment_escape_before_importing_app(tmp_path, monkeypatch):
    (tmp_path / ".taxops-onefile-gate").write_text("synthetic")
    for key, name in {"LOCALAPPDATA":"local", "APPDATA":"roaming", "USERPROFILE":"user", "HOME":"user", "TEMP":"temp", "TMP":"temp"}.items():
        monkeypatch.setenv(key, str(tmp_path / name))
    monkeypatch.delenv("TAXOPS_DEV", raising=False)
    probe.require_isolated_profile(tmp_path, "synthetic")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path.parent / "outside"))
    with pytest.raises(ValueError, match="LOCALAPPDATA"):
        probe.require_isolated_profile(tmp_path, "synthetic")


def test_real_service_fixture_survives_database_close_and_reopen(tmp_path):
    from taxops.ui.app import bootstrap
    from taxops.core.paths import resolve_paths
    paths = resolve_paths(override_root=tmp_path / "profile")
    record = tmp_path / "record.json"
    container = bootstrap(paths)
    expected = probe.persistent_client(container, record, initialize=True)
    container.close()
    container = bootstrap(paths)
    try:
        assert probe.persistent_client(container, record, initialize=False) == expected
        with pytest.raises(ValueError, match="already exist"):
            probe.persistent_client(container, record, initialize=True)
        container.conn.execute("DELETE FROM clients WHERE id=?", (expected["id"],))
        container.conn.commit()
        with pytest.raises(ValueError, match="survive"):
            probe.persistent_client(container, record, initialize=False)
    finally:
        container.close()


@pytest.mark.parametrize("code", [77, 0, 1, -1, 3221225477])
def test_owned_crash_actual_outer_code_is_preserved_before_strict_77_assertion(code):
    provenance = {}
    if code == 77:
        gate.check_owned_crash_exit(code, 1234, provenance)
    else:
        with pytest.raises(gate.BundleVerificationError, match=f"observed outer bootloader {code}"):
            gate.check_owned_crash_exit(code, 1234, provenance)
    assert provenance["owned_crash_process"] == {
        "bootloader_pid": 1234, "bootloader_exit_code": code,
        "bootloader_exit_code_hex": f"0x{code & 0xffffffff:08x}",
        "requested_child_exit_code": 77, "child_exit_code": None,
        "child_exit_code_observed": False,
    }


def owned_profile(tmp_path, monkeypatch):
    token = "synthetic-self-termination"
    (tmp_path / ".taxops-onefile-gate").write_text(token)
    for key, name in {"LOCALAPPDATA":"local", "APPDATA":"roaming", "USERPROFILE":"user",
                      "HOME":"user", "TEMP":"temp", "TMP":"temp"}.items():
        monkeypatch.setenv(key, str(tmp_path / name))
    monkeypatch.delenv("TAXOPS_DEV", raising=False)
    return token


@pytest.mark.parametrize("fault", ["token", "environment", "dev", "not_frozen", "not_windows"])
def test_self_termination_refuses_boundary_failure_before_native_api(tmp_path, monkeypatch, fault):
    token = owned_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(frozen=True, platform="win32"))
    if fault == "token":
        token = "wrong"
    elif fault == "environment":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path.parent))
    elif fault == "dev":
        monkeypatch.setenv("TAXOPS_DEV", "1")
    elif fault == "not_frozen":
        monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32"))
    else:
        monkeypatch.setattr(probe, "sys", SimpleNamespace(frozen=True, platform="linux"))
    def forbidden():
        pytest.fail("Native API must not load outside isolated frozen Windows diagnostics")
    monkeypatch.setattr(probe, "_termination_api", forbidden)
    with pytest.raises(ValueError):
        probe.terminate_isolated_current_process(tmp_path, token)


@pytest.mark.parametrize("result", [0, 1, "raise", "invalid_handle"])
def test_self_termination_uses_exact_pointer_sized_handle_77_and_fails_if_it_returns(tmp_path, monkeypatch, result):
    from ctypes import wintypes
    token = owned_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(frozen=True, platform="win32"))
    calls = []
    own_handle = 0xFEDCBA9876543210
    class Function:
        def __init__(self, operation):
            self.operation = operation
        def __call__(self, *args):
            assert getter.argtypes == [] and getter.restype is wintypes.HANDLE
            assert terminate.argtypes == [wintypes.HANDLE, wintypes.UINT]
            assert terminate.restype is wintypes.BOOL
            calls.append((self.operation, args))
            if self.operation == "get":
                return 0 if result == "invalid_handle" else own_handle
            if result == "raise":
                raise OSError("synthetic native error")
            return result
    getter, terminate = Function("get"), Function("terminate")
    def last_error():
        calls.append(("last_error", ()))
        return 5
    fake_ctypes = SimpleNamespace(get_last_error=last_error, WinError=lambda code: OSError(code, "synthetic denied"))
    monkeypatch.setattr(probe, "_termination_api", lambda: (fake_ctypes, wintypes,
        SimpleNamespace(GetCurrentProcess=getter, TerminateProcess=terminate)))
    with pytest.raises((OSError, RuntimeError)):
        probe.terminate_isolated_current_process(tmp_path, token)
    assert calls[0] == ("get", ())
    if result == "invalid_handle":
        assert len(calls) == 1
    else:
        assert calls[1] == ("terminate", (own_handle, 77))
        assert calls[2:] == ([("last_error", ())] if result == 0 else [])


@pytest.mark.parametrize("marker", [None, {}, {"api": "os._exit", "target": "current_process_pseudo_handle", "requested_exit_code": 77},
    {"api": "TerminateProcess", "target": "external_pid", "requested_exit_code": 77},
    {"api": "TerminateProcess", "target": "current_process_pseudo_handle", "requested_exit_code": 1}])
def test_crash_gate_rejects_missing_old_or_wrong_injection_marker(marker):
    with pytest.raises(gate.BundleVerificationError, match="self-only"):
        gate.check_crash_injection({"crash_injection": marker})


def test_crash_gate_accepts_only_current_process_injection_and_keeps_signed_av_failure():
    gate.check_crash_injection({"crash_injection": {"api": "TerminateProcess", "target": "current_process_pseudo_handle", "requested_exit_code": 77}})
    provenance = {}
    with pytest.raises(gate.BundleVerificationError):
        gate.check_owned_crash_exit(-1073741819, 1234, provenance)
    assert provenance["owned_crash_process"]["bootloader_exit_code_hex"] == "0xc0000005"
    assert provenance["owned_crash_process"]["child_exit_code_observed"] is False


@pytest.mark.parametrize("mode", ["normal", "crash", "ready_write_failure", "injection_failure"])
def test_real_probe_control_flow_publishes_ready_before_self_injection_and_never_injects_normal(tmp_path, monkeypatch, mode):
    from taxops.ui import app, main_window
    from taxops.ui.single_instance import SingleInstanceGuard
    from PySide6 import QtCore
    from build_tools import windows_loaded_modules
    token = owned_profile(tmp_path, monkeypatch)
    mei = tmp_path / "temp/_MEIsynthetic"
    mei.mkdir(parents=True)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(frozen=True, platform="win32", _MEIPASS=str(mei)))
    events = []
    container = SimpleNamespace(paths=SimpleNamespace(db_path=tmp_path / "local/TaxOpsControlDesk/taxops.sqlite"),
        conn=SimpleNamespace(execute=lambda sql: SimpleNamespace(fetchone=lambda: (28,))))
    class Window:
        def __init__(self, value):
            self._container = value
        def show(self):
            events.append("show")
        def close(self):
            events.append("close")
    class Timer:
        def __init__(self, parent):
            events.append("timer")
            self.timeout = SimpleNamespace(connect=lambda callback: None)
        def setInterval(self, interval):
            pass
        def start(self):
            pass
    def bootstrap():
        events.append("bootstrap")
        return container
    monkeypatch.setattr(main_window, "MainWindow", Window)
    monkeypatch.setattr(QtCore, "QTimer", Timer)
    monkeypatch.setattr(app, "bootstrap", bootstrap)
    monkeypatch.setattr(SingleInstanceGuard, "acquire", lambda self: True)
    def run():
        assert SingleInstanceGuard.acquire(object())
        Window(app.bootstrap()).show()
        return 0
    monkeypatch.setattr(app, "run", run)
    def persistent(*args, **kwargs):
        events.append("persistence")
        return {"id": 1}
    monkeypatch.setattr(probe, "persistent_client", persistent)
    def capture(phase):
        events.append("loaded_modules")
        assert phase == "gui_ready"
        return {"process_id": 1234}
    monkeypatch.setattr(windows_loaded_modules, "capture_loaded_modules", capture)
    ready, report = tmp_path / "ready.json", tmp_path / "report.json"
    original_write = probe.write_report
    def write(path, payload):
        if path == ready:
            if mode == "ready_write_failure":
                raise OSError("synthetic ready publication failure")
            events.append("ready_written")
        return original_write(path, payload)
    monkeypatch.setattr(probe, "write_report", write)
    class InjectedExit(BaseException):
        pass
    def terminate(root, supplied_token):
        assert root == tmp_path and supplied_token == token
        gate.check_crash_injection(json.loads(ready.read_text()))
        assert events[-1] == "ready_written"
        events.append("self_terminate77")
        if mode == "injection_failure":
            raise RuntimeError("synthetic API failure")
        raise InjectedExit
    monkeypatch.setattr(probe, "terminate_isolated_current_process", terminate)
    args = ["--report", str(report), "--ready", str(ready), "--release", str(tmp_path / "release"),
            "--instance-name", "synthetic-self-terminate", "--profile-root", str(tmp_path),
            "--profile-token", token, "--persistent-record", str(tmp_path / "record.json")]
    if mode != "normal":
        args.append("--crash-after-ready")
    if mode == "crash":
        with pytest.raises(InjectedExit):
            probe.main(args)
    else:
        assert probe.main(args) == (0 if mode == "normal" else 1)
    before_exit = ["bootstrap", "show", "persistence", "loaded_modules"]
    if mode == "normal":
        assert events == before_exit + ["ready_written", "timer"]
        assert "crash_injection" not in json.loads(ready.read_text())
    elif mode == "ready_write_failure":
        assert events == before_exit and not ready.exists()
    else:
        assert events == before_exit + ["ready_written", "self_terminate77"]
    if mode in {"ready_write_failure", "injection_failure"}:
        payload = json.loads(report.read_text())
        assert payload["status"] == "failed" and not payload["normal_exit"]


def test_native_injector_has_no_pid_or_external_handle_argument_or_fallback():
    import inspect
    assert list(inspect.signature(probe.terminate_isolated_current_process).parameters) == ["profile_root", "profile_token"]
    source = inspect.getsource(probe.terminate_isolated_current_process)
    assert "OpenProcess" not in source and "os._exit" not in source.split('"""')[-1]
    assert "CloseHandle" not in source and "DuplicateHandle" not in source
    assert 'WinDLL("kernel32", use_last_error=True)' in inspect.getsource(probe._termination_api)
