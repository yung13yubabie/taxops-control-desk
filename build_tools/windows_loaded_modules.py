"""Read-only module-origin evidence from the diagnostic process itself.

This is a point-in-time loader enumeration and on-disk file hash, not a memory
integrity scanner, signature check, all-delay-load proof, or clean-OS claim.
No process other than GetCurrentProcess() is opened or inspected.
"""

from __future__ import annotations

import ctypes
import hashlib
import ntpath
import os
import re
import sys
from pathlib import Path


class LoadedModuleError(RuntimeError):
    pass


# Names are from the reviewed x64 CPython 3.11/PySide6 6.10.2 PE inventory.
CORE_PATHS = frozenset(
    {
        "python311.dll",
        "python3.dll",
        "pyside6/pyside6.abi3.dll",
        "pyside6/qtcore.pyd",
        "pyside6/qtgui.pyd",
        "pyside6/qtwidgets.pyd",
        "pyside6/qt6core.dll",
        "pyside6/qt6gui.dll",
        "pyside6/qt6widgets.dll",
        "shiboken6/shiboken6.abi3.dll",
        "shiboken6/shiboken.pyd",
    }
)
CORE_VC_NAMES = frozenset({"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"})
LIMITATION = (
    "Current-process loader snapshot only; SHA-256 hashes the files at observed paths, "
    "not mapped memory. Unloaded plugins, data-file mappings and untriggered delay imports "
    "are not observed. OS-location classification is not clean-OS or publisher-signature proof."
)


class _WindowsModuleAPI:
    def __init__(self):
        from ctypes import wintypes

        # Kernel32 is a Windows KnownDLL; this does not load Qt or app libraries.
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetCurrentProcess.argtypes = []
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.K32EnumProcessModulesEx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        ]
        self.kernel.K32EnumProcessModulesEx.restype = wintypes.BOOL
        self.kernel.GetModuleFileNameW.argtypes = [
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.kernel.GetModuleFileNameW.restype = wintypes.DWORD
        for name in ("GetSystemDirectoryW", "GetWindowsDirectoryW"):
            function = getattr(self.kernel, name)
            function.argtypes = [wintypes.LPWSTR, wintypes.UINT]
            function.restype = wintypes.UINT
        self.process = self.kernel.GetCurrentProcess()  # borrowed pseudo-handle

    def handles(self) -> tuple[int, ...]:
        from ctypes import wintypes

        capacity = 256
        for _ in range(5):
            buffer = (wintypes.HMODULE * capacity)()
            needed = wintypes.DWORD()
            if not self.kernel.K32EnumProcessModulesEx(
                self.process, buffer, ctypes.sizeof(buffer), ctypes.byref(needed), 3
            ):
                raise LoadedModuleError("Current-process module enumeration failed")
            width = ctypes.sizeof(wintypes.HMODULE)
            if needed.value % width or not needed.value:
                raise LoadedModuleError("Invalid module enumeration size")
            if needed.value <= ctypes.sizeof(buffer):
                handles = tuple(buffer[: needed.value // width])
                if not all(handles) or len(handles) != len(set(handles)):
                    raise LoadedModuleError("Duplicate or null module handle")
                return handles
            capacity = needed.value // width + 32
            if capacity > 65536:
                break
        raise LoadedModuleError("Module enumeration did not fit the bounded buffer")

    def path(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        length = self.kernel.GetModuleFileNameW(handle, buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise LoadedModuleError("Missing or truncated current-process module path")
        return buffer.value

    def roots(self) -> dict[str, str]:
        result = {}
        for key, name in (
            ("system32", "GetSystemDirectoryW"),
            ("windows", "GetWindowsDirectoryW"),
        ):
            buffer = ctypes.create_unicode_buffer(32768)
            length = getattr(self.kernel, name)(buffer, len(buffer))
            if not 0 < length < len(buffer):
                raise LoadedModuleError("Cannot identify Windows OS roots")
            result[key] = str(Path(buffer.value).resolve(strict=True))
        return {
            "system32": result["system32"],
            "winsxs": str(Path(result["windows"]) / "WinSxS"),
        }


def windows_system_roots() -> dict[str, str]:
    if sys.platform != "win32":
        raise LoadedModuleError("Windows OS roots require Windows")
    return _WindowsModuleAPI().roots()


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise LoadedModuleError("Missing absolute Windows module path")
    # Normalize the Win32 extended drive form without permitting device/UNC paths.
    if value.startswith("\\\\?\\"):
        value = value[4:]
    drive, tail = ntpath.splitdrive(value)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith(("/", "\\")):
        raise LoadedModuleError("Expected an absolute local-drive Windows module path")
    if ":" in tail or ".." in tail.replace("\\", "/").split("/"):
        raise LoadedModuleError("Unsafe Windows module path")
    return ntpath.normcase(ntpath.normpath(value))


def _location(path: str, mei: str, executable: str, roots: dict) -> str:
    if path == executable:
        return "executable"
    if path.startswith(mei + "\\"):
        return "extraction"
    # Same narrow OS-location rule as the existing native export resolver.
    if ntpath.dirname(path) == roots["system32"]:
        return "windows_system32"
    if path.startswith(roots["winsxs"] + "\\"):
        return "windows_winsxs"
    return "external"


def capture_loaded_modules(phase: str) -> dict:
    report = {
        "schema": 1,
        "status": "unsupported",
        "phase": phase,
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "clean_os_verified": False,
        "scope": LIMITATION,
    }
    if sys.platform != "win32" or not report["frozen"]:
        report["reason"] = (
            "Actual loaded-module evidence requires a frozen Windows diagnostic process"
        )
        return report
    api = _WindowsModuleAPI()
    mei, executable = (
        str(Path(sys._MEIPASS).resolve(strict=True)),
        str(Path(sys.executable).resolve(strict=True)),
    )
    roots = api.roots()
    normalized_roots = {key: _path(value) for key, value in roots.items()}
    # A changed loader list invalidates the sample. Bounded retries do not load
    # extra app libraries, change the DLL search path, or inspect another PID.
    for _ in range(3):
        before = api.handles()
        rows = []
        for handle in before:
            reported = api.path(handle)
            path = Path(reported).resolve(strict=True)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows.append(
                {
                    "path": str(path),
                    "loader_path": reported,
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                    "location": _location(
                        _path(str(path)),
                        _path(mei),
                        _path(executable),
                        normalized_roots,
                    ),
                }
            )
        if set(before) == set(api.handles()):
            report.update(
                status="observed",
                process_id=os.getpid(),
                executable=executable,
                meipass=mei,
                os_roots=roots,
                modules=rows,
            )
            return report
    raise LoadedModuleError(
        "Current-process module list changed during every bounded sample"
    )


def validate_loaded_modules(
    snapshot: dict,
    *,
    expected_native: dict,
    meipass: str,
    executable: str,
    executable_sha256: str,
    os_roots: dict,
    phase: str,
) -> dict:
    """Pure fail-closed comparison; fixtures test policy, never native execution."""
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema") != 1
        or snapshot.get("status") != "observed"
        or snapshot.get("platform") != "win32"
        or snapshot.get("frozen") is not True
        or snapshot.get("phase") != phase
        or snapshot.get("clean_os_verified") is not False
        or snapshot.get("scope") != LIMITATION
        or type(snapshot.get("process_id")) is not int
        or snapshot["process_id"] <= 0
    ):
        raise LoadedModuleError("Missing or invalid actual-process module evidence")
    mei, executable = _path(meipass), _path(executable)
    if (
        _path(snapshot.get("meipass")) != mei
        or _path(snapshot.get("executable")) != executable
    ):
        raise LoadedModuleError("Loaded-module process identity mismatch")
    roots = {key: _path(os_roots[key]) for key in ("system32", "winsxs")}
    observed_roots = snapshot.get("os_roots")
    if (
        not isinstance(observed_roots, dict)
        or set(observed_roots) != set(roots)
        or {key: _path(value) for key, value in observed_roots.items()} != roots
    ):
        raise LoadedModuleError(
            "Reported OS roots differ from independently queried Windows roots"
        )
    if not CORE_PATHS.issubset(expected_native):
        raise LoadedModuleError(
            "Embedded inventory lacks the pinned Python/Qt/binding core"
        )
    rows = snapshot.get("modules")
    if not isinstance(rows, list) or not rows:
        raise LoadedModuleError("No actual loaded modules")
    seen, loaded, main_count, os_count = set(), set(), 0, 0
    bundled_names = {ntpath.basename(name) for name in expected_native}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
            or type(row.get("bytes")) is not int
            or row["bytes"] <= 0
        ):
            raise LoadedModuleError("Missing loaded-module path/hash/size")
        path = _path(row.get("path"))
        _path(row.get("loader_path"))
        if path in seen:
            raise LoadedModuleError("Duplicate exact loaded-module path")
        seen.add(path)
        location = _location(path, mei, executable, roots)
        if row.get("location") != location:
            raise LoadedModuleError("Loaded-module location classification mismatch")
        name = ntpath.basename(path)
        if location == "executable":
            main_count += 1
            if row["sha256"] != executable_sha256:
                raise LoadedModuleError("Loaded main EXE hash mismatch")
        elif location == "extraction":
            relative = path[len(mei) + 1 :].replace("\\", "/")
            if expected_native.get(relative) != row["sha256"]:
                raise LoadedModuleError(
                    "Loaded extraction path/hash differs from embedded inventory"
                )
            loaded.add(relative)
        else:
            required_local = (
                name in bundled_names
                or name.endswith(".pyd")
                or re.match(
                    r"(?:python\d|qt6|pyside6|shiboken6|vcruntime\d|msvcp\d|concrt\d|vcamp\d|vcomp\d)",
                    name,
                )
            )
            if required_local or location == "external":
                raise LoadedModuleError(
                    f"Loaded module outside the accepted EXE/extraction/OS scope: {row['path']}"
                )
            os_count += 1
    if (
        main_count != 1
        or not CORE_PATHS.issubset(loaded)
        or not CORE_VC_NAMES.issubset({ntpath.basename(name) for name in loaded})
        or not os_count
    ):
        raise LoadedModuleError(
            "Missing actual EXE/Python/Qt/binding/VC/OS core module"
        )
    return {
        "phase": phase,
        "process_id": snapshot["process_id"],
        "loaded_embedded": sorted(loaded),
        "not_observed_embedded": sorted(set(expected_native) - loaded),
        "os_location_module_count": os_count,
        "clean_os_verified": False,
        "scope": LIMITATION,
    }
