"""Source exit-control contracts; no Linux test claims Windows Qt evidence."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from build_tools import qt_exit_contrast as contrast


def binding():
    return {"launcher": {"path": "/synthetic/venv/Scripts/python.exe", "sha256": "1" * 64, "bytes": 100},
            "base_image": {"path": "/synthetic/base/python.exe", "sha256": "2" * 64, "bytes": 200},
            "base_prefix": "/synthetic/base", "venv_prefix": "/synthetic/venv"}


def pinned_runtime():
    return {"platform": "win32", "implementation": "CPython", "python": "3.11.9",
            "pointer_bits": 64, "pyside_distribution": "6.10.2", "is_virtual_environment": True,
            "qt_loaded": False, "qt_version": None, "executable": binding()["launcher"],
            "base_executable": binding()["base_image"], "process_image": binding()["base_image"],
            "prefix": binding()["venv_prefix"], "base_prefix": binding()["base_prefix"]}


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
    setup = ("import importlib.util;"
             f"spec=importlib.util.spec_from_file_location('exit_control',{contrast.__file__!r});"
             "module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);")
    script = (setup + "import json,os;from pathlib import Path;"
              f"Path({str(child)!r}).write_text(json.dumps({{'process_id':os.getpid(),"
              "'parent_process_id':os.getppid(),'runtime':"
              "module.runtime_identity(),"
              "'status':'requesting_exit','requested_exit_code':77}));"
              "os.write(1,b'out\\xff');os.write(2,b'err\\xfe');"
              f"os._exit({code})")
    result = contrast.run_case([sys.executable, "-I", "-c", script], tmp_path, dict(os.environ), 77, 15,
        expected_runtime=contrast.configured_runtime(Path(sys.executable)) if sys.platform == "win32" else None)
    assert result["outer_exit_code_observed"] and result["outer_exit_code"] == code
    assert result["outer_exit_code_hex"] == f"0x{code:08x}"
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
    assert record["outer_exit_code"] == 77 and record["status"] == "failed"


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
    assert result["status"] == "failed" and result["outer_exit_code"] is None
    assert result["outer_exit_code_after_forced_cleanup"] == 9
    assert result["outer_exit_code_observed"] is False


def test_source_contrast_five_cases_continue_after_actual_code_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    python = tmp_path / "synthetic python.exe"
    python.write_bytes(b"not executed")
    calls = []
    monkeypatch.setattr(contrast, "configured_runtime", lambda python: binding())
    def record(command, directory, env, expected, timeout, **kwargs):
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
    assert result["status"] == "failed" and len(result["cases"]) == 5
    assert "may differ" in result["limits"]
    assert json.loads((output / "contrast.json").read_text()) == result
    with pytest.raises(FileExistsError):
        contrast.contrast(python, output)


def test_wrong_runtime_stops_before_additional_injections(tmp_path, monkeypatch):
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    python = tmp_path / "synthetic python.exe"
    python.write_bytes(b"not executed")
    calls = []
    monkeypatch.setattr(contrast, "configured_runtime", lambda python: binding())
    def record(*args, **kwargs):
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


@pytest.mark.parametrize("case", [name for name, _ in contrast.CASES])
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
    class Button:
        def __init__(self, text, parent):
            self.owner = parent
            self.clicked = SimpleNamespace(connect=self.connect)
        def connect(self, callback):
            events.append("connect")
            self.callback = callback
            return True
        def parent(self):
            return self.owner
        def click(self):
            events.append("click")
            self.callback(False)
    widgets = SimpleNamespace(QApplication=App, QWidget=Widget, QPushButton=Button, __file__=__file__)
    if case == "python-exit":
        # A module-local sys view keeps the no-Qt control independent of pytest-qt imports.
        monkeypatch.setattr(contrast, "sys", SimpleNamespace(modules={}))
    else:
        monkeypatch.setitem(sys.modules, "PySide6", SimpleNamespace(QtCore=core, QtWidgets=widgets, __version__="6.10.2", __file__=__file__))
    prefix = ["app", "connect", "show", "click"] if case in contrast.BOUND_CASES else ["app", "show"]
    if case in {"qt-close", "qt-bound-close"}:
        assert contrast.run_child(case, tmp_path, "token") == 0
        assert events == prefix + ["schedule_close", "exec"]
    else:
        with pytest.raises(ExitRequested):
            contrast.run_child(case, tmp_path, "token")
        assert events == ([] if case == "python-exit" else prefix) + [("os._exit", 77)]
    child = json.loads((tmp_path / "child.json").read_text())
    assert child["requested_exit_code"] == (0 if case in {"qt-close", "qt-bound-close"} else 77)
    assert child["runtime"]["qt_loaded"] == (case != "python-exit")
    if case in contrast.BOUND_CASES:
        contrast.validate_bound_evidence(child["bound_signal"])
        assert child["bound_signal"]["callback_count"] == 1


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
    assert record["outer_process_id"] is None and record["outer_exit_code"] is None
    assert record["outer_exit_code_observed"] is False and "forced_cleanup" not in record
    assert record["error"]["type"] == "OSError"


@pytest.mark.parametrize("child_pid,parent_pid,relation", [
    (123, 90, "direct_popen_process"),
    (456, 123, "single_level_windows_venv_launcher"),
])
def test_only_exact_direct_or_single_level_venv_relationship(child_pid, parent_pid, relation):
    child = {"process_id": child_pid, "parent_process_id": parent_pid, "runtime": pinned_runtime()}
    assert contrast.process_relation(123, child, 90, binding()) == relation


@pytest.mark.parametrize("pid,ppid", [
    (456, 999), (123, 999), (456, 90), (90, 123), (456, 456),
    (0, 123), (-1, 123), (True, 123), ("456", 123), (456, None),
    (456, "123"), (456, True), (2**32, 123),
])
def test_wrong_missing_reused_shape_or_noninteger_pid_relationship_fails(pid, ppid):
    with pytest.raises(ValueError):
        contrast.process_relation(123, {"process_id": pid, "parent_process_id": ppid,
                                       "runtime": pinned_runtime()}, 90)


@pytest.mark.parametrize("runtime", [{}, {**pinned_runtime(), "platform": "linux"},
                                    {**pinned_runtime(), "python": "3.11.10"},
                                    {**pinned_runtime(), "is_virtual_environment": False}])
def test_single_level_relation_requires_pinned_windows_venv(runtime):
    with pytest.raises((ValueError, KeyError)):
        contrast.process_relation(123, {"process_id": 456, "parent_process_id": 123,
                                       "runtime": runtime}, 90)


@pytest.mark.parametrize("code,expected_status", [(77, "matched_control"), (0xC0000005, "failed")])
def test_venv_outer_code_is_observed_but_inner_exit_remains_unknown(tmp_path, monkeypatch, code, expected_status):
    child = {"process_id": 20420, "parent_process_id": 26984, "runtime": pinned_runtime(),
             "status": "requesting_exit", "requested_exit_code": 77}
    (tmp_path / "child.json").write_text(json.dumps(child))
    process = SimpleNamespace(pid=26984, poll=lambda: code, wait=lambda timeout: code)
    monkeypatch.setattr(contrast, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: process))
    result = contrast.run_case(["synthetic pinned python.exe"], tmp_path, {}, 77, 1, expected_runtime=binding())
    assert result["status"] == expected_status
    assert result["outer_process_id"] == 26984 and result["outer_exit_code"] == code
    assert result["outer_exit_code_observed"] is True
    assert result["process_relation"] == "single_level_windows_venv_launcher"
    assert result["child_exit_code"] is None and result["child_exit_code_observed"] is False
    assert result["schema"] == 2


def test_config_binds_only_requested_venv_and_base_image(tmp_path):
    venv, base = tmp_path / "venv", tmp_path / "base"
    (venv / "Scripts").mkdir(parents=True)
    base.mkdir()
    python = venv / "Scripts" / "python.exe"
    python.write_bytes(b"synthetic launcher")
    (base / "python.exe").write_bytes(b"synthetic base")
    config = venv / "pyvenv.cfg"
    config.write_text(f"home = {base}\nversion = 3.11.9\ninclude-system-site-packages = false\n")
    expected = contrast.configured_runtime(python)
    assert expected["launcher"] == contrast.file_identity(python)
    assert expected["base_image"] == contrast.file_identity(base / "python.exe")
    assert expected["configuration"] == contrast.file_identity(config)
    assert expected["base_prefix"] == str(base)
    config.write_text(f"home = {base}\nversion = 3.11.10\n")
    with pytest.raises(ValueError, match="version"):
        contrast.configured_runtime(python)
    config.write_text(f"home = {base}\nhome = {base}\nversion = 3.11.9\n")
    with pytest.raises(ValueError, match="Duplicate"):
        contrast.configured_runtime(python)
    config.write_text("home = relative\nversion = 3.11.9\n")
    with pytest.raises(ValueError, match="absolute home"):
        contrast.configured_runtime(python)
    with pytest.raises(ValueError, match="Scripts/python.exe"):
        contrast.configured_runtime(base / "python.exe")


@pytest.mark.parametrize("field,member,value", [
    ("executable", "path", "/other/python.exe"),
    ("executable", "sha256", "9" * 64),
    ("base_executable", "path", "/other/python.exe"),
    ("base_executable", "bytes", 900),
    ("process_image", "path", "/other/python.exe"),
    ("process_image", "sha256", "9" * 64),
    ("process_image", "bytes", 900),
])
def test_single_level_parent_match_is_not_enough_without_image_identity(field, member, value):
    runtime = pinned_runtime()
    runtime[field] = {**runtime[field], member: value}
    with pytest.raises(ValueError, match="Runtime image"):
        contrast.process_relation(123, {"process_id": 456, "parent_process_id": 123,
                                       "runtime": runtime}, 90, binding())


@pytest.mark.parametrize("field", ["prefix", "base_prefix"])
def test_runtime_prefixes_must_match_configured_base_and_venv(field):
    runtime = pinned_runtime()
    runtime[field] = "/other/root"
    with pytest.raises(ValueError, match="Runtime prefix"):
        contrast.require_runtime_binding(runtime, binding())


def test_self_image_api_only_uses_null_module_and_explicit_abi(monkeypatch, tmp_path):
    from ctypes import wintypes
    image = tmp_path / "python.exe"
    calls = []
    class Function:
        def __call__(self, module, buffer, size):
            calls.append((module, size))
            buffer.value = str(image)
            return len(buffer.value)
    function = Function()
    def load(name, **kwargs):
        assert name == "kernel32.dll" and kwargs == {"use_last_error": True}
        return SimpleNamespace(GetModuleFileNameW=function)
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(contrast, "ctypes", SimpleNamespace(
        WinDLL=load, create_unicode_buffer=contrast.ctypes.create_unicode_buffer))
    assert contrast.current_image_path() == image
    assert calls == [(None, 1024)]
    assert function.argtypes == [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    assert function.restype is wintypes.DWORD


@pytest.mark.parametrize("returned", [0, "truncated"])
def test_self_image_read_failure_or_oversized_path_fails_closed(monkeypatch, returned):
    calls = []
    class Function:
        def __call__(self, module, buffer, size):
            calls.append((module, size))
            return size if returned == "truncated" else 0
    monkeypatch.setattr(contrast, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(contrast, "ctypes", SimpleNamespace(
        WinDLL=lambda *a, **kw: SimpleNamespace(GetModuleFileNameW=Function()),
        create_unicode_buffer=contrast.ctypes.create_unicode_buffer,
        get_last_error=lambda: 5, WinError=lambda error: OSError(error, "synthetic")))
    with pytest.raises((OSError, ValueError)):
        contrast.current_image_path()
    assert calls == ([(None, 1024)] if returned == 0 else [(None, 1024), (None, 4096), (None, 32768)])


def test_real_qt_bound_method_connection_emit_and_retained_references(qtbot):
    from PySide6 import QtWidgets
    window = contrast.make_bound_window(QtWidgets)
    qtbot.addWidget(window)
    window.show()
    assert window.callback_count == 0
    evidence = contrast.bound_signal_evidence(window)
    assert evidence["callback_count"] == 1 and evidence["ready"] is True
    assert window.button.parent() is window and window.on_clicked.__self__ is window
    assert evidence["decorated_slot"] is False
    window.close()


@pytest.mark.parametrize("field,value", [("callback_count", 0), ("callback_count", 2),
    ("callback_count", True), ("connection_valid", False), ("sender_retained", False),
    ("receiver_retained", False), ("ready", False), ("decorated_slot", True)])
def test_bound_connection_evidence_rejects_missing_emit_or_released_references(field, value):
    evidence = {"callback_count": 1, "connection_valid": True, "sender_retained": True,
                "receiver_retained": True, "ready": True, "decorated_slot": False}
    contrast.validate_bound_evidence(evidence)
    evidence[field] = value
    with pytest.raises(ValueError, match="one real callback"):
        contrast.validate_bound_evidence(evidence)


@pytest.mark.parametrize("child_case", ["qt-bound-exit", "qt-show-exit"])
def test_outer_77_cannot_pass_a_bound_case_without_requested_case_and_callback(tmp_path, monkeypatch, child_case):
    code = 77
    child = {"process_id": 20420, "parent_process_id": 26984, "runtime": pinned_runtime(),
             "status": "requesting_exit", "requested_exit_code": 77, "case": child_case}
    (tmp_path / "child.json").write_text(json.dumps(child))
    process = SimpleNamespace(pid=26984, poll=lambda: code, wait=lambda timeout: code)
    monkeypatch.setattr(contrast, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: process))
    result = contrast.run_case(["synthetic pinned python.exe"], tmp_path, {}, 77, 1,
                              expected_runtime=binding(), expected_case="qt-bound-exit")
    assert result["status"] == "failed" and "receipt_error" in result
