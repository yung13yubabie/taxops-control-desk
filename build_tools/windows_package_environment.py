"""Bound PyInstaller's child PATH without modifying compiler or parent settings.

This is input separation, not a hermetic-build or installed-tool trust claim.
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_tools.dependency_licenses import ROOT, sha256

RECEIPT = ROOT / "artifacts/build-staging/package-environment.json"
_IMPORT_VARIABLES = frozenset({
    "PYTHONPATH", "PYTHONHOME", "QTDIR", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QML_IMPORT_PATH", "QML2_IMPORT_PATH",
})


def windows_directories() -> tuple[Path, Path]:
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError("Windows packaging requires 64-bit Windows")
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    result = []
    for name in ("GetSystemDirectoryW", "GetWindowsDirectoryW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        function.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise RuntimeError(f"Cannot identify Windows directory with {name}")
        result.append(Path(buffer.value).resolve())
    return tuple(result)


def _file(path: Path) -> dict:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"Missing or symlinked package tool: {path}")
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def release_inputs() -> tuple[list[Path], dict]:
    """Require imports from the release venv, never a compilation SDK."""
    prefix = Path(sys.prefix).resolve()
    if prefix == Path(sys.base_prefix).resolve():
        raise RuntimeError("Windows packaging requires a separate release virtual environment")
    executable = Path(sys.executable).resolve()
    base = Path(sys._base_executable).resolve()
    if executable.parent != prefix / "Scripts":
        raise RuntimeError("Release Python must be the virtual environment's Scripts/python.exe")
    packages = {}
    site = prefix / "Lib/site-packages"
    for name in ("PySide6", "shiboken6", "PyInstaller"):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Missing release package: {name}")
        origin = Path(spec.origin).resolve()
        if not origin.is_relative_to(site):
            raise RuntimeError(f"Release package resolved outside pinned virtual environment: {name}")
        packages[name] = _file(origin)
    return [executable.parent, base.parent], {
        "release_python": _file(executable), "base_python": _file(base),
        "release_prefix": str(prefix), "packages": packages,
    }


def git_launcher(parent_path: str) -> Path:
    discovered = shutil.which("git.exe", path=parent_path)
    if not discovered:
        raise RuntimeError("Git launcher is missing from the existing build environment")
    candidate = Path(discovered).resolve()
    # Git for Windows exposes cmd/git.exe; its mingw64/bin search directory is
    # deliberately not retained, since that also contains unrelated libraries.
    if candidate.parent.name.casefold() == "cmd":
        root = candidate.parent.parent
    elif (candidate.parent.name.casefold() == "bin"
          and candidate.parent.parent.name.casefold() == "mingw64"):
        root = candidate.parent.parent.parent
    else:
        raise RuntimeError("Git must resolve to an existing Git for Windows cmd launcher")
    launcher = root / "cmd/git.exe"
    _file(launcher)
    _file(root / "mingw64/bin/git.exe")
    if any(p.suffix.casefold() in {".dll", ".pyd"} for p in launcher.parent.iterdir()):
        raise RuntimeError("Git cmd launcher directory contains unexpected native libraries")
    return launcher.resolve()


def prepare_environment(*, report_path: Path = RECEIPT) -> tuple[dict[str, str], dict]:
    """Return a child copy and a lossless PATH-selection receipt; fail closed."""
    report = {"schema": 1, "status": "failed", "scope": "PyInstaller children only; parent/compiler unchanged"}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        parent = dict(os.environ)
        path_keys = [key for key in parent if key.upper() == "PATH"]
        values = {parent[key] for key in path_keys}
        if len(values) > 1:
            raise RuntimeError("Conflicting case-insensitive PATH values in build environment")
        inherited = next(iter(values), "")
        system, windows = windows_directories()
        python_dirs, identity = release_inputs()
        git = git_launcher(inherited)
        powershell = system / "WindowsPowerShell/v1.0/powershell.exe"
        tools = {"git": _file(git), "powershell": _file(powershell)}
        paths = []
        for directory in [*python_dirs, system, windows, powershell.parent, git.parent]:
            directory = directory.resolve()
            if not directory.is_absolute() or not directory.is_dir() or ";" in str(directory):
                raise RuntimeError(f"Invalid package search directory: {directory}")
            if str(directory).casefold() not in {str(p).casefold() for p in paths}:
                paths.append(directory)
        child = {key: value for key, value in parent.items()
                 if key.upper() != "PATH" and key.upper() not in _IMPORT_VARIABLES}
        child["PATH"] = ";".join(str(p) for p in paths)
        child["PYTHONNOUSERSITE"] = "1"
        report.update(identity, tools=tools, inherited_path_keys=path_keys,
                      inherited_path=inherited, child_path=child["PATH"],
                      removed_path_entries=[p for p in inherited.split(";")
                                            if p.casefold() not in {str(d).casefold() for d in paths}],
                      removed_import_variables=sorted(key for key in parent if key.upper() in _IMPORT_VARIABLES))
        version = subprocess.run([str(git), "--version"], env=child, check=True,
                                 capture_output=True, text=True, timeout=30).stdout.strip()
        if not version.startswith("git version ") or "windows" not in version.casefold():
            raise RuntimeError("Existing Git launcher did not identify Git for Windows")
        report["git_version"] = version
        report["status"] = "passed"
        child["TAXOPS_PACKAGE_ENV_RECEIPT"] = str(report_path.resolve())
        return child, report
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def package_receipt() -> dict:
    """Bind the spec's actual process environment to the prepared child receipt."""
    path = Path(os.environ.get("TAXOPS_PACKAGE_ENV_RECEIPT", ""))
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("Use python -m build_tools.package_windows for controlled package inputs")
    report = json.loads(path.read_text(encoding="utf-8"))
    path_values = [value for key, value in os.environ.items() if key.upper() == "PATH"]
    if (report.get("schema") != 1 or report.get("status") != "passed"
            or path_values != [report.get("child_path")]
            or any(key.upper() in _IMPORT_VARIABLES for key in os.environ)
            or report.get("release_python") != _file(Path(sys.executable).resolve())):
        raise RuntimeError("Package child environment differs from its receipt")
    _, current = release_inputs()
    if any(report.get(key) != value for key, value in current.items()):
        raise RuntimeError("Package release inputs differ from their receipt")
    for row in report.get("tools", {}).values():
        if row != _file(Path(row["path"])):
            raise RuntimeError("Package tool bytes differ from their receipt")
    return {"filename": path.name, "sha256": sha256(path)}
