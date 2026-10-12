"""Synthetic policy/API contracts. These do not execute a Windows onefile EXE."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from build_tools import windows_loaded_modules as modules
from build_tools import verify_onefile as onefile


MEI = r"C:\Synthetic 中文 profile\temp\_MEI123"
EXE = r"C:\Only EXE 中文\TaxOpsControlDesk.exe"
ROOTS = {"system32": r"C:\Windows\System32", "winsxs": r"C:\Windows\WinSxS"}
HASH = "1" * 64


def fixture():
    inventory = {name: HASH for name in modules.CORE_PATHS}
    inventory.update(
        {
            "vcruntime140.dll": "2" * 64,
            "pyside6/vcruntime140.dll": "3" * 64,
            "pyside6/vcruntime140_1.dll": HASH,
            "pyside6/msvcp140.dll": HASH,
            "pyside6/plugins/imageformats/qgif.dll": HASH,
        }
    )

    def row(path, digest, location):
        return {
            "path": path,
            "loader_path": path,
            "sha256": digest,
            "bytes": 123,
            "location": location,
        }

    loaded = set(inventory) - {"pyside6/plugins/imageformats/qgif.dll"}
    report = {
        "schema": 1,
        "status": "observed",
        "platform": "win32",
        "frozen": True,
        "phase": "gui_ready",
        "process_id": 123,
        "meipass": MEI,
        "executable": EXE,
        "os_roots": ROOTS.copy(),
        "clean_os_verified": False,
        "scope": modules.LIMITATION,
        "modules": [
            row(EXE, HASH, "executable"),
            row(ROOTS["system32"] + r"\kernel32.dll", HASH, "windows_system32"),
        ]
        + [
            row(MEI + "\\" + name.replace("/", "\\"), inventory[name], "extraction")
            for name in sorted(loaded)
        ],
    }
    return report, inventory


def validate(report, inventory):
    return modules.validate_loaded_modules(
        report,
        expected_native=inventory,
        meipass=MEI,
        executable=EXE,
        executable_sha256=HASH,
        os_roots=ROOTS,
        phase="gui_ready",
    )


def test_contract_keeps_distinct_vc_paths_and_unobserved_plugins():
    report, inventory = fixture()
    result = validate(report, inventory)
    assert "vcruntime140.dll" in result["loaded_embedded"]
    assert "pyside6/vcruntime140.dll" in result["loaded_embedded"]
    assert result["not_observed_embedded"] == ["pyside6/plugins/imageformats/qgif.dll"]
    assert result["clean_os_verified"] is False


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "status",
        "phase",
        "platform",
        "frozen",
        "process_id",
        "meipass",
        "executable",
        "os_roots",
        "modules",
        "clean_os_verified",
        "scope",
    ],
)
def test_missing_evidence_is_not_a_pass(field):
    report, inventory = fixture()
    del report[field]
    with pytest.raises(modules.LoadedModuleError):
        validate(report, inventory)


@pytest.mark.parametrize(
    "field", ["path", "loader_path", "sha256", "bytes", "location"]
)
def test_missing_module_fields_are_rejected(field):
    report, inventory = fixture()
    del report["modules"][0][field]
    with pytest.raises(modules.LoadedModuleError):
        validate(report, inventory)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "case_duplicate",
        "missing_core",
        "missing_vc",
        "missing_exe",
        "missing_os",
        "empty",
        "hash",
        "exe_hash",
        "wrong_mei",
        "extra_file",
        "outside",
        "qt_system32",
        "vc_system32",
        "unknown_system_subdir",
        "spoofed_root",
        "pretend_location",
        "wrong_phase",
    ],
)
def test_loaded_module_negative_contracts(fault):
    report, inventory = fixture()
    rows = report["modules"]
    row = next(item for item in rows if item["path"].lower().endswith("python311.dll"))
    if fault in {"duplicate", "case_duplicate"}:
        duplicate = copy.deepcopy(row)
        if fault == "case_duplicate":
            duplicate["path"] = duplicate["path"].upper()
        rows.append(duplicate)
    elif fault == "missing_core":
        rows.remove(row)
    elif fault == "missing_vc":
        rows[:] = [
            item for item in rows if not item["path"].lower().endswith("msvcp140.dll")
        ]
    elif fault == "missing_exe":
        rows.pop(0)
    elif fault == "missing_os":
        rows.pop(1)
    elif fault == "empty":
        rows.clear()
    elif fault == "hash":
        row["sha256"] = "f" * 64
    elif fault == "exe_hash":
        rows[0]["sha256"] = "f" * 64
    elif fault == "wrong_mei":
        report["meipass"] += "wrong"
    elif fault == "extra_file":
        row["path"] = MEI + r"\unlisted.dll"
    elif fault == "outside":
        row.update(path=r"C:\Other\python311.dll", location="external")
    elif fault == "qt_system32":
        row.update(
            path=ROOTS["system32"] + r"\Qt6Core.dll", location="windows_system32"
        )
    elif fault == "vc_system32":
        row.update(
            path=ROOTS["system32"] + r"\MSVCP140.dll", location="windows_system32"
        )
    elif fault == "unknown_system_subdir":
        row.update(
            path=ROOTS["system32"] + r"\unreviewed\other.dll", location="external"
        )
    elif fault == "spoofed_root":
        report["os_roots"]["system32"] = r"C:\Other"
    elif fault == "pretend_location":
        row["location"] = "windows_system32"
    elif fault == "wrong_phase":
        report["phase"] = "before_qt_import"
    with pytest.raises(modules.LoadedModuleError):
        validate(report, inventory)


def test_inventory_core_is_required_and_os_winsxs_location_is_explicit():
    report, inventory = fixture()
    row = report["modules"][1]
    row.update(
        path=ROOTS["winsxs"] + r"\component\comctl32.dll", location="windows_winsxs"
    )
    assert validate(report, inventory)["os_location_module_count"] == 1
    del inventory["python311.dll"]
    with pytest.raises(modules.LoadedModuleError, match="inventory"):
        validate(report, inventory)


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "relative.dll",
        r"C:relative.dll",
        r"\\server\share\a.dll",
        r"C:\root\..\a.dll",
        r"C:\root\a.dll:stream",
        "C:\\a\x00.dll",
    ],
)
def test_windows_paths_fail_closed(value):
    with pytest.raises(modules.LoadedModuleError):
        modules._path(value)


def test_extended_windows_drive_path_and_case_normalization():
    assert modules._path(r"\\?\C:\APP\A.DLL") == r"c:\app\a.dll"


def test_source_or_other_platform_does_not_claim_native_pass(monkeypatch):
    for platform, frozen in (("linux", True), ("win32", False)):
        monkeypatch.setattr(
            modules, "sys", SimpleNamespace(platform=platform, frozen=frozen)
        )
        report = modules.capture_loaded_modules("after_18_checks")
        assert report["status"] == "unsupported" and "modules" not in report
    monkeypatch.setattr(modules, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(modules.LoadedModuleError, match="Windows"):
        modules.windows_system_roots()


def test_onefile_external_gate_rejects_absent_actual_process_evidence(tmp_path):
    with pytest.raises(onefile.BundleVerificationError, match="loaded-module"):
        onefile.check_module_report(
            {}, inventory={}, exe=tmp_path / "app.exe", temp=tmp_path, phase="gui_ready"
        )


class Function:
    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action(*args)


class KernelFixture:
    """Synthetic ctypes API contract, deliberately not native execution evidence."""

    def __init__(self, *, fault=None):
        import ctypes
        from ctypes import wintypes

        self.calls = 0
        self.fault = fault
        self.GetCurrentProcess = Function(lambda: 7)
        self.GetModuleFileNameW = Function(self.path)
        self.GetSystemDirectoryW = Function(
            lambda buffer, size: self.string(buffer, size, ROOTS["system32"])
        )
        self.GetWindowsDirectoryW = Function(
            lambda buffer, size: self.string(buffer, size, r"C:\Windows")
        )

        def enumerate_(process, buffer, size, needed, flags):
            assert process == 7 and flags == 3
            self.calls += 1
            count = 300 if self.fault == "grow" and self.calls == 1 else 2
            if self.fault == "never_fit":
                count = 70000
            if self.fault == "empty":
                count = 0
            needed._obj.value = count * ctypes.sizeof(wintypes.HMODULE)
            if self.fault == "unaligned":
                needed._obj.value += 1
            if count <= len(buffer):
                buffer[0] = 1
                buffer[1] = 1 if self.fault == "duplicate" else 2
            return self.fault != "failed"

        self.K32EnumProcessModulesEx = Function(enumerate_)

    def string(self, buffer, size, value):
        if self.fault == "truncated":
            return size
        if self.fault == "no_path":
            return 0
        buffer.value = value
        return len(value)

    def path(self, handle, buffer, size):
        assert handle == 1
        return self.string(buffer, size, EXE)


def api_fixture(monkeypatch, fault=None):
    kernel = KernelFixture(fault=fault)
    monkeypatch.setattr(
        modules.ctypes, "WinDLL", lambda name, **kw: kernel, raising=False
    )
    return modules._WindowsModuleAPI(), kernel


def test_winapi_binding_has_full_signatures_and_bounded_resize(monkeypatch):
    api, kernel = api_fixture(monkeypatch, "grow")
    assert api.handles() == (1, 2) and kernel.calls == 2
    assert api.path(1) == EXE
    for name in (
        "GetCurrentProcess",
        "K32EnumProcessModulesEx",
        "GetModuleFileNameW",
        "GetSystemDirectoryW",
        "GetWindowsDirectoryW",
    ):
        function = getattr(kernel, name)
        assert isinstance(function.argtypes, list) and function.restype is not None
    assert kernel.GetCurrentProcess.argtypes == []
    assert not hasattr(kernel, "OpenProcess")


@pytest.mark.parametrize(
    "fault", ["failed", "empty", "unaligned", "duplicate", "never_fit"]
)
def test_native_enumeration_failures_are_not_empty_success(monkeypatch, fault):
    api, _kernel = api_fixture(monkeypatch, fault)
    with pytest.raises(modules.LoadedModuleError):
        api.handles()


@pytest.mark.parametrize("fault", ["truncated", "no_path"])
def test_truncated_or_missing_module_and_root_path_fails(monkeypatch, fault):
    api, _kernel = api_fixture(monkeypatch, fault)
    with pytest.raises(modules.LoadedModuleError):
        api.path(1)
    with pytest.raises(modules.LoadedModuleError):
        api.roots()


def test_capture_hashes_observed_files_only_and_rejects_changing_list(
    tmp_path, monkeypatch
):
    exe, mei = tmp_path / "app.exe", tmp_path / "_MEI123"
    exe.write_bytes(b"synthetic executable bytes")
    mei.mkdir()
    calls = []

    class API:
        def roots(self):
            return ROOTS

        def handles(self):
            calls.append("enumerate")
            return (1,)

        def path(self, handle):
            assert handle == 1
            return str(exe)

    monkeypatch.setattr(modules, "_WindowsModuleAPI", API)
    monkeypatch.setattr(
        modules,
        "sys",
        SimpleNamespace(
            platform="win32", frozen=True, _MEIPASS=str(mei), executable=str(exe)
        ),
    )
    # Host-path adaptation is for this byte-read unit contract only.
    monkeypatch.setattr(modules, "_path", lambda value: value)
    snapshot = modules.capture_loaded_modules("gui_ready")
    assert snapshot["status"] == "observed" and len(snapshot["modules"]) == 1
    assert (
        snapshot["modules"][0]["sha256"]
        == modules.hashlib.sha256(exe.read_bytes()).hexdigest()
    )
    assert snapshot["modules"][0]["path"] == str(exe)
    assert calls == ["enumerate", "enumerate"]

    class ChangingAPI(API):
        def handles(self):
            calls.append("enumerate")
            return (1,) if len(calls) % 2 else (2,)

    monkeypatch.setattr(modules, "_WindowsModuleAPI", ChangingAPI)
    with pytest.raises(modules.LoadedModuleError, match="changed"):
        modules.capture_loaded_modules("gui_ready")
    assert len(calls) == 8
