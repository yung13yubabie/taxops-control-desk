"""Synthetic ABI and stable-byte tests; no Windows acceptance is claimed."""

import ctypes
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from build_tools import shell_icon_probe as probe


@pytest.fixture
def last_error(monkeypatch):
    state = [0]
    monkeypatch.setattr(
        ctypes,
        "set_last_error",
        lambda value: state.__setitem__(0, value),
        raising=False,
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: state[0], raising=False)
    return state


@pytest.mark.parametrize(
    "result,hicon,destroy,expected",
    [
        (0, 0, 1, "failed"),
        (0, 19, 1, "failed"),
        (123, 0, 1, "failed"),
        (123, 19, 0, "failed"),
        (123, 19, 1, "observed"),
    ],
)
def test_shell_query_exact_flags_and_owned_icon_only(
    last_error, result, hicon, destroy, expected
):
    calls = []

    def query(path, attributes, pointer, size, flags):
        assert (path, attributes, size, flags) == (
            "synthetic.txt",
            0,
            ctypes.sizeof(probe.SHFILEINFOW),
            0x4161,
        )
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
    assert fields[:3] == [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int32),
        ("dwAttributes", ctypes.c_uint32),
    ]
    assert fields[3][1]._length_ == 260 and fields[4][1]._length_ == 80
    assert fields[3][1]._type_ == fields[4][1]._type_ == ctypes.c_wchar
    assert probe.SHFILEINFOW.iIcon.offset == ctypes.sizeof(ctypes.c_void_p)
    assert probe.SHFILEINFOW.dwAttributes.offset == ctypes.sizeof(ctypes.c_void_p) + 4


@pytest.mark.parametrize(
    "result,accepted", [(0, True), (1, True), (-2147417850, False)]
)
def test_com_exact_mta_hresult(last_error, result, accepted):
    calls = []
    api = object.__new__(probe.ShellAPI)
    api.ole = SimpleNamespace(
        CoInitializeEx=lambda pointer, flags: calls.append((pointer, flags)) or result
    )
    record = api.initialize()
    assert calls == [(None, 0)] and record["accepted"] is accepted
    assert (
        record["hresult"] == result
        and record["hresult_hex"] == f"0x{result & 0xFFFFFFFF:08x}"
    )


def test_full_snapshot_does_not_hide_external_or_unreadable_paths(tmp_path):
    dll = tmp_path / "unreviewed.dll"
    dll.write_bytes(b"synthetic")
    missing = tmp_path / "missing.dll"
    api = SimpleNamespace(
        handles=lambda: (1, 2), path=lambda handle: str(dll if handle == 1 else missing)
    )
    report = probe.snapshot(api)
    assert report["status"] == "failed" and len(report["modules"]) == 2
    assert report["modules"][0]["sha256"] == hashlib.sha256(b"synthetic").hexdigest()
    assert report["modules"][1]["loader_path"] == str(missing)
    assert report["modules"][1]["error"]["type"] == "FileNotFoundError"
    assert all(
        "location" not in row and "trusted" not in row for row in report["modules"]
    )


def test_delta_retains_added_removed_changed_without_allowlisting():
    def row(path, value):
        return {"path": path, "sha256": value, "bytes": 3, "status": "observed"}

    before = {"status": "observed", "modules": [row("a", "1"), row("b", "2")]}
    after = {"status": "observed", "modules": [row("b", "3"), row("c", "4")]}
    change = probe.delta(before, after)
    assert change["added"] == [after["modules"][1]]
    assert change["removed"] == [before["modules"][0]]
    assert change["changed"] == [
        {"before": before["modules"][1], "after": after["modules"][0]}
    ]
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


def test_shell_api_declares_complete_win64_prototypes(monkeypatch):
    libraries = {}

    class Function:
        pass

    def load(name, **kwargs):
        assert kwargs == {"use_last_error": True}
        library = SimpleNamespace(
            **{
                method: Function()
                for method in (
                    "SHGetFileInfoW",
                    "DestroyIcon",
                    "CoInitializeEx",
                    "CoUninitialize",
                )
            }
        )
        libraries[name] = library
        return library

    # The real WCHAR structure is tested above; this host may have 4-byte wchar_t.
    structure = type(
        "SyntheticWin64Layout",
        (ctypes.Structure,),
        {"_fields_": [("bytes", ctypes.c_char * 696)]},
    )
    monkeypatch.setattr(probe, "SHFILEINFOW", structure)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    probe.ShellAPI()
    query = libraries["shell32"].SHGetFileInfoW
    assert query.argtypes == [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(structure),
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    assert query.restype is ctypes.c_size_t
    assert libraries["user32"].DestroyIcon.argtypes == [ctypes.c_void_p]
    assert libraries["user32"].DestroyIcon.restype is ctypes.c_int32
    assert libraries["ole32"].CoInitializeEx.argtypes == [
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    assert libraries["ole32"].CoInitializeEx.restype is ctypes.c_int32
    assert libraries["ole32"].CoUninitialize.argtypes == []
    assert libraries["ole32"].CoUninitialize.restype is None


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


@pytest.mark.parametrize(
    "fault", [None, "profile", "input", "qt", "site", "com", "query", "snapshot"]
)
def test_child_isolation_snapshots_and_com_cleanup(tmp_path, monkeypatch, fault):
    events = []
    for key, relative in (
        ("USERPROFILE", "profile"),
        ("LOCALAPPDATA", "profile/local"),
        ("APPDATA", "profile/roaming"),
        ("TEMP", "temp"),
        ("TMP", "temp"),
    ):
        monkeypatch.setenv(key, str(tmp_path / relative))
    if fault == "profile":
        monkeypatch.setenv("APPDATA", str(tmp_path.parent))
    (tmp_path / "inputs/synthetic folder").mkdir(parents=True)
    (tmp_path / "inputs/synthetic.txt").write_bytes(
        b"wrong" if fault == "input" else probe.CONTENT
    )
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic interpreter")
    monkeypatch.setattr(
        probe,
        "sys",
        SimpleNamespace(
            platform="win32",
            executable=str(executable),
            flags=SimpleNamespace(isolated=1, no_site=0 if fault == "site" else 1),
            version_info=(3, 11, 9),
            modules={"PySide6.QtCore": object()} if fault == "qt" else {},
        ),
    )
    monkeypatch.setattr(probe, "source_identity", lambda: [])
    monkeypatch.setattr(probe, "host_identity", lambda: {})
    monkeypatch.setattr(
        probe, "exception_record", lambda exc: {"type": type(exc).__name__}
    )

    class Shell:
        def __init__(self):
            self.ole = SimpleNamespace(
                CoUninitialize=lambda: events.append("uninitialize")
            )

        def initialize(self):
            events.append("initialize")
            return {"accepted": fault != "com", "hresult": -1 if fault == "com" else 0}

        def query(self, path):
            events.append(path.name)
            return {"status": "failed" if fault == "query" else "observed"}

    def snapshot(_api):
        events.append("snapshot")
        return {
            "status": "failed" if fault == "snapshot" else "observed",
            "modules": [],
            "attempt": 1,
        }

    monkeypatch.setattr(probe, "ShellAPI", Shell)
    monkeypatch.setattr(probe, "_WindowsModuleAPI", lambda: object())
    monkeypatch.setattr(probe, "snapshot", snapshot)
    result = probe.child(tmp_path, {"nonce": "fresh"})
    assert result == (0 if fault is None else 1)
    import json

    receipt = json.loads((tmp_path / "child.json").read_text())
    assert receipt["status"] == ("observed" if fault is None else "failed")
    if fault in {"profile", "input", "qt", "site"}:
        assert events == []
    elif fault == "com":
        assert events == ["initialize"]
    else:
        assert events == [
            "initialize",
            "snapshot",
            "synthetic.txt",
            "snapshot",
            "synthetic folder",
            "snapshot",
            "uninitialize",
        ]
        assert receipt["com"]["uninitialized"] is True


def test_same_handle_reused_for_a_different_path_is_not_a_stable_snapshot(tmp_path):
    first, second = tmp_path / "first.dll", tmp_path / "second.dll"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    paths = []

    def path(_handle):
        paths.append(1)
        return str(first if len(paths) % 2 else second)

    with pytest.raises(RuntimeError, match="stabilize"):
        probe.snapshot(SimpleNamespace(handles=lambda: (1,), path=path))
    assert len(paths) == 6


@pytest.mark.parametrize("failure", [False, True])
def test_host_identity_uses_bounded_windows_api_without_socket_import(
    monkeypatch, failure
):
    import builtins

    real_import = builtins.__import__

    def import_without_network(name, *args, **kwargs):
        assert name not in {"socket", "select", "platform"}
        return real_import(name, *args, **kwargs)

    class Function:
        def __call__(self, buffer, length):
            assert self.argtypes and self.restype is not None
            buffer.value = "SYNTHETIC-HOST"
            length._obj.value = len(buffer.value)
            return 0 if failure else 1

    kernel = SimpleNamespace(GetComputerNameW=Function())
    monkeypatch.setattr(
        probe,
        "_WindowsModuleAPI",
        lambda: SimpleNamespace(kernel=kernel, roots=lambda: {"system32": "synthetic"}),
    )
    monkeypatch.setattr(
        probe,
        "sys",
        SimpleNamespace(
            getwindowsversion=lambda: SimpleNamespace(
                major=10, minor=0, build=20348, platform=2, service_pack=""
            )
        ),
    )
    monkeypatch.setattr(builtins, "__import__", import_without_network)
    if failure:
        with pytest.raises(RuntimeError, match="identify"):
            probe.host_identity()
    else:
        assert probe.host_identity() == {
            "computer": "SYNTHETIC-HOST",
            "windows": [10, 0, 20348, 2, ""],
            "pointer_bits": 64,
            "os_roots": {"system32": "synthetic"},
        }
