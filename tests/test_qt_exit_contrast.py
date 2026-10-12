"""Source exit-control contracts; no Linux test claims Windows Qt evidence."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from build_tools import qt_exit_contrast as contrast


def pinned_runtime():
    return {"platform": "win32", "implementation": "CPython", "python": "3.11.9",
            "pointer_bits": 64, "pyside_distribution": "6.10.2", "is_virtual_environment": True,
            "qt_loaded": False, "qt_version": None}


@pytest.mark.parametrize("key,value", [("platform", "linux"), ("python", "3.11.10"),
    ("implementation", "PyPy"), ("pointer_bits", 32), ("pyside_distribution", "6.10.1"),
    ("is_virtual_environment", False)])
def test_runtime_requires_exact_existing_windows_pins(key, value):
    contrast.validate_runtime(pinned_runtime())
    wrong = pinned_runtime()
    wrong[key] = value
    with pytest.raises(ValueError, match="existing Windows"):
        contrast.validate_runtime(wrong)


def test_fresh_profile_exact_keys_token_and_no_parent_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("qt_plugin_path", "untrusted synthetic path")
    monkeypatch.setenv("pythonpath", "untrusted synthetic path")
    monkeypatch.setenv("localappdata", "not owned")
    before = dict(os.environ)
    root = tmp_path / "synthetic profile 中文"
    env = contrast.profile_environment(root, "token")
    assert dict(os.environ) == before
    assert "qt_plugin_path" not in env and "pythonpath" not in env
    assert "localappdata" not in env
    monkeypatch.setattr(contrast, "os", SimpleNamespace(environ=env))
    contrast.require_profile(root, "token")
    with pytest.raises(ValueError, match="token"):
        contrast.require_profile(root, "wrong")
    env["HOME"] = str(tmp_path)
    with pytest.raises(ValueError, match="HOME"):
        contrast.require_profile(root, "token")
    with pytest.raises(FileExistsError):
        contrast.profile_environment(root, "token")


@pytest.mark.parametrize("code", [77, 0, 1])
def test_actual_owned_source_returncode_and_lossless_streams(tmp_path, code):
    child = tmp_path / "child.json"
    script = ("import json,os;from pathlib import Path;"
              f"Path({str(child)!r}).write_text(json.dumps({{'process_id':os.getpid(),"
              "'status':'requesting_exit','requested_exit_code':77}));"
              "os.write(1,b'out\\xff');os.write(2,b'err\\xfe');"
              f"os._exit({code})")
    result = contrast.run_case([sys.executable, "-I", "-c", script], tmp_path, dict(os.environ), 77, 15)
    assert result["exit_code_observed"] and result["exit_code"] == code
    assert result["exit_code_hex"] == f"0x{code:08x}"
    assert result["status"] == ("matched_control" if code == 77 else "failed")
    assert (tmp_path / "stdout.bin").read_bytes() == b"out\xff"
    assert (tmp_path / "stderr.bin").read_bytes() == b"err\xfe"
    assert result == json.loads((tmp_path / "process.json").read_text())


@pytest.mark.parametrize("invalid", [[], {}, {"process_id": -5, "requested_exit_code": 77,
                                        "status": "requesting_exit"}])
def test_exit_77_without_matching_child_receipt_fails(tmp_path, invalid):
    (tmp_path / "child.json").write_text(json.dumps(invalid))
    record = contrast.run_case([sys.executable, "-I", "-c", "import os;os._exit(77)"],
                               tmp_path, dict(os.environ), 77, 15)
    assert record["exit_code"] == 77 and record["status"] == "failed"


def test_timeout_only_cleans_exact_retained_owned_process(tmp_path, monkeypatch):
    class Process:
        pid = 125
        returncode = None
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            raise contrast.subprocess.TimeoutExpired("synthetic owned", timeout)
    process = Process()
    monkeypatch.setattr(contrast, "subprocess", SimpleNamespace(
        Popen=lambda *a, **kw: process, TimeoutExpired=contrast.subprocess.TimeoutExpired))
    from build_tools import owned_process_cleanup
    def cleanup(actual, path):
        assert actual is process and path == tmp_path / "forced-cleanup.json"
        process.returncode = 9
        return {"status": "synthetic owned cleanup"}
    monkeypatch.setattr(owned_process_cleanup, "terminate_owned_tree", cleanup)
    result = contrast.run_case(["synthetic.exe"], tmp_path, {}, 77, 1)
    assert result["status"] == "failed" and result["exit_code"] is None
    assert result["exit_code_after_forced_cleanup"] == 9
    assert result["exit_code_observed"] is False


def test_source_contrast_three_cases_continue_after_actual_code_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    python = tmp_path / "synthetic python.exe"
    python.write_bytes(b"not executed")
    calls = []
    def record(command, directory, env, expected, timeout):
        assert command[:3] == [str(python), "-I", "-B"]
        assert Path(command[3]) == Path(contrast.__file__).resolve()
        assert Path(env["LOCALAPPDATA"]) == directory / "profile" / "local"
        calls.append(command[5])
        return {"status": "failed" if expected == 77 else "matched_control",
                "exit_code": 0xC0000005 if expected == 77 else 0,
                "child": {"status": "requesting_exit"}}
    monkeypatch.setattr(contrast, "run_case", record)
    output = tmp_path / "new output"
    result = contrast.contrast(python, output)
    assert calls == [name for name, _ in contrast.CASES]
    assert result["status"] == "failed" and len(result["cases"]) == 3
    assert "may differ" in result["limits"]
    assert json.loads((output / "contrast.json").read_text()) == result
    with pytest.raises(FileExistsError):
        contrast.contrast(python, output)


def test_wrong_runtime_stops_before_additional_injections(tmp_path, monkeypatch):
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    python = tmp_path / "synthetic python.exe"
    python.write_bytes(b"not executed")
    calls = []
    def record(*args):
        calls.append(args)
        return {"status": "failed", "child": {"error": {"type": "ValueError"}}}
    monkeypatch.setattr(contrast, "run_case", record)
    assert contrast.contrast(python, tmp_path / "out")["status"] == "failed"
    assert len(calls) == 1


def test_linux_rejected_before_output_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(ValueError, match="Windows"):
        contrast.contrast(tmp_path / "missing.exe", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_wrong_child_version_records_identity_without_qt_import_or_exit(tmp_path, monkeypatch):
    wrong = pinned_runtime()
    wrong["python"] = "3.11.10"
    monkeypatch.setattr(contrast, "require_profile", lambda *args: None)
    monkeypatch.setattr(contrast, "runtime_identity", lambda: wrong)
    assert contrast.run_child("python-exit", tmp_path, "token") == 1
    child = json.loads((tmp_path / "child.json").read_text())
    assert child["runtime"]["python"] == "3.11.10"
    assert "requested_exit_code" not in child and "error" in child


@pytest.mark.parametrize("case", ["python-exit", "qt-show-exit", "qt-close"])
def test_child_phase_sequence_and_original_exit_77_contract(tmp_path, monkeypatch, case):
    events = []
    class ExitRequested(BaseException):
        pass
    def abrupt(code):
        events.append(("os._exit", code))
        raise ExitRequested
    monkeypatch.setattr(contrast, "require_profile", lambda *args: None)
    monkeypatch.setattr(contrast, "runtime_identity", pinned_runtime)
    monkeypatch.setattr(contrast, "os", SimpleNamespace(
        getpid=os.getpid, getppid=os.getppid, _exit=abrupt))
    class App:
        def __init__(self, argv):
            events.append("app")
        def platformName(self):
            return "windows"
        def exec(self):
            events.append("exec")
            return 0
    class Widget:
        def setWindowTitle(self, title):
            pass
        def show(self):
            events.append("show")
        def isVisible(self):
            return True
        def close(self):
            events.append("close")
    core = SimpleNamespace(qVersion=lambda: "6.10.2", __file__=__file__,
        QTimer=SimpleNamespace(singleShot=lambda delay, close: events.append("schedule_close")))
    widgets = SimpleNamespace(QApplication=App, QWidget=Widget, __file__=__file__)
    if case == "python-exit":
        # A module-local sys view keeps the no-Qt control independent of pytest-qt imports.
        monkeypatch.setattr(contrast, "sys", SimpleNamespace(modules={}))
    else:
        monkeypatch.setitem(sys.modules, "PySide6", SimpleNamespace(QtCore=core, QtWidgets=widgets, __version__="6.10.2", __file__=__file__))
    if case == "qt-close":
        assert contrast.run_child(case, tmp_path, "token") == 0
        assert events == ["app", "show", "schedule_close", "exec"]
    else:
        with pytest.raises(ExitRequested):
            contrast.run_child(case, tmp_path, "token")
        assert events == ([] if case == "python-exit" else ["app", "show"]) + [("os._exit", 77)]
    child = json.loads((tmp_path / "child.json").read_text())
    assert child["requested_exit_code"] == (0 if case == "qt-close" else 77)
    assert child["runtime"]["qt_loaded"] == (case != "python-exit")


@pytest.mark.parametrize("pyside,qt", [("6.10.1", "6.10.2"), ("6.10.2", "6.10.1")])
def test_actual_qt_or_pyside_wrong_version_stops_before_qapplication(tmp_path, monkeypatch, pyside, qt):
    monkeypatch.setattr(contrast, "require_profile", lambda *args: None)
    monkeypatch.setattr(contrast, "runtime_identity", pinned_runtime)
    module = SimpleNamespace(__version__=pyside, __file__=__file__,
        QtCore=SimpleNamespace(qVersion=lambda: qt, __file__=__file__),
        QtWidgets=SimpleNamespace(__file__=__file__))
    monkeypatch.setitem(sys.modules, "PySide6", module)
    assert contrast.run_child("qt-show-exit", tmp_path, "token") == 1
    child = json.loads((tmp_path / "child.json").read_text())
    assert child["runtime"]["qt_version"] == qt
    assert child["runtime"]["pyside_version"] == pyside
    assert child["error"]["message"] == "Actual PySide6 and Qt runtime must both be 6.10.2"
    assert "requested_exit_code" not in child


def test_spawn_error_preserves_unknown_exit_without_cleanup(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic start failure")
    monkeypatch.setattr(contrast, "subprocess", SimpleNamespace(Popen=fail))
    record = contrast.run_case(["synthetic.exe"], tmp_path, {}, 77, 1)
    assert record["process_id"] is None and record["exit_code"] is None
    assert record["exit_code_observed"] is False and "forced_cleanup" not in record
    assert record["error"]["type"] == "OSError"
