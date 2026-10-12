"""Synthetic ABI/orchestration contracts; actual Shell observations need Windows."""
from __future__ import annotations

import ctypes
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_tools import shell_icon_probe as probe


@pytest.fixture
def last_error(monkeypatch):
    state = [0]
    monkeypatch.setattr(ctypes, "set_last_error", lambda value: state.__setitem__(0, value), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: state[0], raising=False)
    return state


@pytest.mark.parametrize("result,hicon,destroy,expected", [(0, 0, 1, "failed"), (0, 19, 1, "failed"),
                                                         (123, 0, 1, "failed"), (123, 19, 0, "failed"),
                                                         (123, 19, 1, "observed")])
def test_shell_query_exact_flags_and_owned_icon_only(last_error, result, hicon, destroy, expected):
    calls = []
    def query(path, attributes, pointer, size, flags):
        assert (path, attributes, size, flags) == ("synthetic.txt", 0, ctypes.sizeof(probe.SHFILEINFOW), 0x4161)
        ctypes.cast(pointer, ctypes.POINTER(probe.SHFILEINFOW)).contents.hIcon = hicon
        last_error[0] = 1234
        return result
    def destroy_icon(handle):
        calls.append(handle)
        last_error[0] = 5678
        return destroy
    api = object.__new__(probe.ShellAPI)
    api.shell = SimpleNamespace(SHGetFileInfoW=query)
    api.user = SimpleNamespace(DestroyIcon=destroy_icon)
    row = api.query(Path("synthetic.txt"))
    assert row["status"] == expected and row["last_error"] == 1234
    assert row["return_value"] == result and calls == ([hicon] if hicon else [])
    assert 123 not in calls  # Never destroy the returned image list.
    if hicon:
        assert row["destroy_icon"] == {"return_value": destroy, "last_error": 5678}


def test_native_structure_field_types_and_alignment():
    fields = probe.SHFILEINFOW._fields_
    assert fields[:3] == [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int32), ("dwAttributes", ctypes.c_uint32)]
    assert fields[3][1]._length_ == 260 and fields[4][1]._length_ == 80
    assert fields[3][1]._type_ == fields[4][1]._type_ == ctypes.c_wchar
    assert probe.SHFILEINFOW.iIcon.offset == ctypes.sizeof(ctypes.c_void_p)
    assert probe.SHFILEINFOW.dwAttributes.offset == ctypes.sizeof(ctypes.c_void_p) + 4


@pytest.mark.parametrize("result,accepted", [(0, True), (1, True), (-2147417850, False)])
def test_com_exact_mta_hresult(last_error, result, accepted):
    calls = []
    api = object.__new__(probe.ShellAPI)
    api.ole = SimpleNamespace(CoInitializeEx=lambda pointer, flags: calls.append((pointer, flags)) or result)
    record = api.initialize()
    assert calls == [(None, 0)] and record["accepted"] is accepted
    assert record["hresult"] == result and record["hresult_hex"] == f"0x{result & 0xffffffff:08x}"


def test_full_snapshot_does_not_hide_external_or_unreadable_paths(tmp_path):
    dll = tmp_path / "unreviewed.dll"
    dll.write_bytes(b"synthetic")
    missing = tmp_path / "missing.dll"
    api = SimpleNamespace(handles=lambda: (1, 2), path=lambda handle: str(dll if handle == 1 else missing))
    report = probe.snapshot(api)
    assert report["status"] == "failed" and len(report["modules"]) == 2
    assert report["modules"][0]["sha256"] == hashlib.sha256(b"synthetic").hexdigest()
    assert report["modules"][1]["loader_path"] == str(missing)
    assert report["modules"][1]["error"]["type"] == "FileNotFoundError"
    assert all("location" not in row and "trusted" not in row for row in report["modules"])


def test_delta_retains_added_removed_changed_without_allowlisting():
    def row(path, value): return {"path": path, "sha256": value, "bytes": 3, "status": "observed"}
    before = {"status": "observed", "modules": [row("a", "1"), row("b", "2")]}
    after = {"status": "observed", "modules": [row("b", "3"), row("c", "4")]}
    change = probe.delta(before, after)
    assert change["added"] == [after["modules"][1]]
    assert change["removed"] == [before["modules"][0]]
    assert change["changed"] == [{"before": before["modules"][1], "after": after["modules"][0]}]
    assert change["complete"]
    after["status"] = "failed"
    assert not probe.delta(before, after)["complete"]


def test_unstable_loader_list_is_bounded():
    calls = []
    def handles():
        calls.append(1)
        return () if len(calls) % 2 else (1,)
    with pytest.raises(RuntimeError, match="stabilize"):
        probe.snapshot(SimpleNamespace(handles=handles))
    assert len(calls) == 6


@pytest.mark.parametrize("bad", ["token", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"])
def test_child_rejects_missing_token_or_profile_escape(tmp_path, monkeypatch, bad):
    for key, suffix in (("USERPROFILE", "profile"), ("LOCALAPPDATA", "profile/local"),
                        ("APPDATA", "profile/roaming"), ("TEMP", "temp"), ("TMP", "temp")):
        monkeypatch.setenv(key, str(tmp_path / suffix))
    monkeypatch.setenv("TAXOPS_SHELL_PROBE_TOKEN", "synthetic-token")
    if bad == "token":
        monkeypatch.delenv("TAXOPS_SHELL_PROBE_TOKEN")
    else:
        monkeypatch.setenv(bad, str(tmp_path.parent))
    with pytest.raises(RuntimeError):
        probe.validate_profile(tmp_path, "synthetic-token")


def test_unsupported_platform_is_not_native_success(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(RuntimeError, match="unsupported"):
        probe.run(tmp_path / "new")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("fault", ["none", "returncode", "timeout", "source", "parent", "child-failed"])
def test_parent_retains_raw_streams_identity_and_failures(tmp_path, monkeypatch, fault):
    real_platform = probe.sys.platform
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    sources = [{"path": "fixed", "bytes": 1, "sha256": "a" * 64}]
    monkeypatch.setattr(probe, "source_identity", lambda: sources)
    monkeypatch.setattr(probe, "exception_record", lambda exc: {"type": type(exc).__name__, "message": str(exc)})
    cleanup = []
    root = tmp_path / "new 中文"
    class Process:
        pid = 123
        alive = True
        def __init__(self, command, **kwargs):
            assert command[:3] == [sys.executable, "-m", "build_tools.shell_icon_probe"]
            assert "shell" not in kwargs and kwargs["env"]["TEMP"] == str(root / "temp")
            assert kwargs["env"]["USERPROFILE"] == str(root / "profile")
            assert (root / "inputs/synthetic.txt").read_bytes() == probe.CONTENT
            kwargs["stdout"].write(b"raw out\xff")
            kwargs["stderr"].write(b"raw error\xfe")
            probe.save(root / "child.json", {"process_id": 234, "parent_process_id": 999 if fault == "parent" else 123,
                       "source": [] if fault == "source" else sources,
                       "input": probe.file_identity(root / "inputs/synthetic.txt"),
                       "status": "failed" if fault == "child-failed" else "observed"})
        def wait(self, timeout):
            if fault == "timeout":
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.alive = False
            return 7 if fault == "returncode" else 0
        def poll(self): return None if self.alive else 0
    monkeypatch.setattr(probe, "subprocess", SimpleNamespace(Popen=Process))
    monkeypatch.setattr(probe, "terminate_owned_tree", lambda process, path: cleanup.append(process.pid) or {"normal_cleanup": False})
    report = probe.run(root)
    assert report["status"] == ("observed" if fault == "none" else "failed")
    assert report["child_exit_directly_observed"] is False
    assert (root / "stdout.bin").read_bytes() == b"raw out\xff"
    assert (root / "stderr.bin").read_bytes() == b"raw error\xfe"
    assert json.loads((root / "report.json").read_text(encoding="utf-8")) == report
    assert cleanup == ([123] if fault == "timeout" else [])
    assert sys.platform == real_platform


def test_existing_output_is_never_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32"))
    (tmp_path / "keep").write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        probe.run(tmp_path)
    assert (tmp_path / "keep").read_bytes() == b"existing"


def test_shell_api_declares_complete_win64_prototypes(monkeypatch):
    libraries = {}
    class Function:
        pass
    def load(name, **kwargs):
        assert kwargs == {"use_last_error": True}
        library = SimpleNamespace(**{method: Function() for method in
                                  ("SHGetFileInfoW", "DestroyIcon", "CoInitializeEx", "CoUninitialize")})
        libraries[name] = library
        return library
    # The real WCHAR structure is tested above; this host may have 4-byte wchar_t.
    structure = type("SyntheticWin64Layout", (ctypes.Structure,), {"_fields_": [("bytes", ctypes.c_char * 696)]})
    monkeypatch.setattr(probe, "SHFILEINFOW", structure)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    probe.ShellAPI()
    query = libraries["shell32"].SHGetFileInfoW
    assert query.argtypes == [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(structure), ctypes.c_uint32, ctypes.c_uint32]
    assert query.restype is ctypes.c_size_t
    assert libraries["user32"].DestroyIcon.argtypes == [ctypes.c_void_p]
    assert libraries["user32"].DestroyIcon.restype is ctypes.c_int32
    assert libraries["ole32"].CoInitializeEx.argtypes == [ctypes.c_void_p, ctypes.c_uint32]
    assert libraries["ole32"].CoInitializeEx.restype is ctypes.c_int32
    assert libraries["ole32"].CoUninitialize.argtypes == []
    assert libraries["ole32"].CoUninitialize.restype is None


@pytest.mark.parametrize("fault", ["none", "com-sfalse", "com-failed", "query", "snapshot", "input", "qt"])
def test_child_evidence_and_balanced_com_precedes_teardown(tmp_path, monkeypatch, fault):
    events = []
    (tmp_path / "inputs/synthetic folder").mkdir(parents=True)
    (tmp_path / "inputs/synthetic.txt").write_bytes(b"wrong" if fault == "input" else probe.CONTENT)
    monkeypatch.setattr(probe, "validate_profile", lambda root, token: events.append("profile"))
    monkeypatch.setattr(probe, "source_identity", lambda: [])
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", version="synthetic", executable="synthetic",
                       modules={"PySide6": object()} if fault == "qt" else {}))
    monkeypatch.setattr(probe, "exception_record", lambda exc: {"type": type(exc).__name__, "message": str(exc)})
    class Shell:
        def __init__(self):
            self.ole = SimpleNamespace(CoUninitialize=lambda: events.append("uninitialize"))
        def initialize(self):
            events.append("initialize")
            return {"hresult": 1 if fault == "com-sfalse" else 0,
                    "accepted": fault != "com-failed"}
        def query(self, path):
            events.append(path.name)
            return {"status": "failed" if fault == "query" else "observed", "return_value": 0 if fault == "query" else 123}
    def capture(api):
        events.append("snapshot")
        return {"status": "failed" if fault == "snapshot" else "observed", "modules": []}
    monkeypatch.setattr(probe, "ShellAPI", Shell)
    monkeypatch.setattr(probe, "_WindowsModuleAPI", lambda: object())
    monkeypatch.setattr(probe, "snapshot", capture)
    result = probe.child(tmp_path, "synthetic-token")
    assert result == (0 if fault in ("none", "com-sfalse") else 1)
    receipt = json.loads((tmp_path / "child.json").read_text(encoding="utf-8"))
    assert receipt["status"] == ("observed" if result == 0 else "failed")
    if fault in ("qt", "input"):
        assert events == ["profile"]
    elif fault == "com-failed":
        assert events == ["profile", "initialize"]
    else:
        assert events == ["profile", "initialize", "snapshot", "synthetic.txt", "snapshot",
                          "synthetic folder", "snapshot", "uninitialize"]
        assert receipt["com"]["uninitialized"] and len(receipt["calls"]) == 2
        assert "before" in receipt and "after" in receipt and "delta" in receipt


@pytest.mark.parametrize("failure", ["query", "destroy"])
def test_query_exception_preserves_failure_and_icon_cleanup(last_error, failure):
    calls = []
    def query(path, attrs, pointer, size, flags):
        ctypes.cast(pointer, ctypes.POINTER(probe.SHFILEINFOW)).contents.hIcon = 19
        if failure == "query":
            raise OSError("synthetic query failure")
        return 123
    def destroy(handle):
        calls.append(handle)
        if failure == "destroy":
            raise OSError("synthetic cleanup failure")
        return 1
    api = object.__new__(probe.ShellAPI)
    api.shell = SimpleNamespace(SHGetFileInfoW=query)
    api.user = SimpleNamespace(DestroyIcon=destroy)
    row = api.query(Path("synthetic.txt"))
    assert row["status"] == "failed" and calls == [19]
    error = row["error"] if failure == "query" else row["destroy_icon"]["error"]
    assert error["type"] == "OSError"
