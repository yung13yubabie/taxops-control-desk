"""Bound PyInstaller's child PATH without modifying compiler or parent settings.

This is input separation, not a hermetic-build or installed-tool trust claim.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
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
_GIT_IMPLEMENTATIONS = ("mingw64", "ucrt64")
_GIT_VERSION = r"git version [0-9]+\.[0-9]+\.[0-9]+\.windows\.[0-9]+"
_RECEIPT_VARIABLES = {"TAXOPS_PACKAGE_ENV_RECEIPT", "TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"}


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


def git_launcher(discovered: str | None, diagnostics: dict) -> Path:
    """Normalize only existing Git for Windows entry-point layouts to cmd."""
    if not discovered:
        raise RuntimeError("Git launcher is missing from the existing build environment")
    original = Path(discovered)
    diagnostics["discovered_file"] = _file(original)
    candidate = original.resolve()
    if candidate.name.casefold() != "git.exe":
        raise RuntimeError("Discovered Git entry point is not git.exe")
    # Official root/bin and cmd wrappers ultimately launch mingw64/ucrt64 Git.
    # Only cmd is retained; neither implementation/bin nor root/bin enters PATH.
    # https://gitforwindows.org/git-wrapper.html
    if candidate.parent.name.casefold() == "cmd":
        root = candidate.parent.parent
    elif (candidate.parent.name.casefold() == "bin"
          and candidate.parent.parent.name.casefold() in _GIT_IMPLEMENTATIONS):
        root = candidate.parent.parent.parent
    elif candidate.parent.name.casefold() == "bin":
        root = candidate.parent.parent
    else:
        raise RuntimeError("Git must resolve to a supported Git for Windows entry point")
    diagnostics["root"] = str(root)
    launcher = root / "cmd/git.exe"
    diagnostics["cmd_launcher"] = _file(launcher)
    if diagnostics["cmd_launcher"]["path"].casefold() != str(launcher).casefold():
        raise RuntimeError("Git cmd launcher is redirected outside the fixed root layout")
    implementations = []
    for name in _GIT_IMPLEMENTATIONS:
        path = root / name / "bin/git.exe"
        if path.exists() or path.is_symlink():
            row = {"layout": name, **_file(path)}
            if row["path"].casefold() != str(path).casefold():
                raise RuntimeError("Git implementation is redirected outside the fixed root layout")
            implementations.append(row)
    diagnostics["implementation_candidates"] = implementations
    if not implementations:
        raise RuntimeError("Git for Windows implementation is missing (mingw64/bin or ucrt64/bin)")
    if any(p.suffix.casefold() in {".dll", ".pyd"} for p in launcher.parent.iterdir()):
        raise RuntimeError("Git cmd launcher directory contains unexpected native libraries")
    return launcher.resolve()


def _selected_git_implementation(git: Path, candidates: list[dict], exec_path: str) -> dict:
    if (not isinstance(exec_path, str) or not exec_path
            or any(c in exec_path for c in "\x00\r\n") or not Path(exec_path).is_absolute()):
        raise RuntimeError("Git returned an invalid implementation exec path")
    root = git.parent.parent
    selected = []
    for row in candidates:
        expected = root / row["layout"] / "libexec/git-core"
        if (str(Path(exec_path).resolve()).casefold() == str(expected.resolve()).casefold()
                and expected.is_dir()
                and str(expected.resolve()).casefold() == str(expected).casefold()):
            selected.append(row)
    if len(selected) != 1:
        raise RuntimeError("Git exec path does not select one existing same-root implementation")
    return selected[0]


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
        report.update(identity)
        discovered = shutil.which("git.exe", path=inherited)
        report["git_discovery"] = {"discovered_path": discovered}
        # Save the observed entry point even when layout validation then fails.
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        git = git_launcher(discovered, report["git_discovery"])
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
                 if key.upper() not in {"PATH", "GIT_EXEC_PATH", *_RECEIPT_VARIABLES}
                 and key.upper() not in _IMPORT_VARIABLES}
        child["PATH"] = ";".join(str(p) for p in paths)
        child["PYTHONNOUSERSITE"] = "1"
        report.update(identity, tools=tools, inherited_path_keys=path_keys,
                      inherited_path=inherited, child_path=child["PATH"],
                      removed_path_entries=[p for p in inherited.split(";")
                                            if p.casefold() not in {str(d).casefold() for d in paths}],
                      removed_import_variables=sorted(key for key in parent if key.upper() in _IMPORT_VARIABLES))
        report["removed_git_override_variables"] = sorted(key for key in parent if key.upper() == "GIT_EXEC_PATH")
        version = subprocess.run([str(git), "--version"], env=child, check=True,
                                 capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30).stdout.strip()
        if not re.fullmatch(_GIT_VERSION, version):
            raise RuntimeError("Existing Git launcher did not identify Git for Windows")
        report["git_version"] = version
        exec_path = subprocess.run([str(git), "--exec-path"], env=child, check=True,
                                  capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30).stdout.strip()
        report["git_exec_path"] = exec_path
        selected = _selected_git_implementation(git, report["git_discovery"]["implementation_candidates"], exec_path)
        report["git_discovery"]["selected_implementation"] = selected
        report["tools"]["git_implementation"] = {
            key: selected[key] for key in ("path", "sha256", "bytes")}
        report["status"] = "passed"
        child["TAXOPS_PACKAGE_ENV_RECEIPT"] = str(report_path.resolve())
        return child, report
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt_bytes = (json.dumps(report, indent=2) + "\n").encode("utf-8")
        report_path.write_bytes(receipt_bytes)
        if report["status"] == "passed":
            # The returned child receives the anchor only after completed bytes are written.
            child["TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"] = hashlib.sha256(receipt_bytes).hexdigest()


def package_receipt() -> dict:
    """Bind the spec's actual process environment to the prepared child receipt."""
    path = Path(os.environ.get("TAXOPS_PACKAGE_ENV_RECEIPT", ""))
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("Use python -m build_tools.package_windows for controlled package inputs")
    receipt_bytes = path.read_bytes()
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    if os.environ.get("TAXOPS_PACKAGE_ENV_RECEIPT_SHA256") != receipt_hash:
        raise RuntimeError("Package environment receipt differs from its prepared child anchor")
    report = json.loads(receipt_bytes.decode("utf-8"))
    path_items = [(key, value) for key, value in os.environ.items() if key.upper() == "PATH"]
    path_values = [value for _key, value in path_items]
    overrides = sorted(key for key in os.environ if key.upper() in _IMPORT_VARIABLES or key.upper() == "GIT_EXEC_PATH")
    python = _file(Path(sys.executable).resolve())
    matches = {"schema": report.get("schema") == 1, "status": report.get("status") == "passed",
               "PATH": path_values == [report.get("child_path")], "import_overrides": not overrides,
               "release_python": report.get("release_python") == python}
    if not all(matches.values()):
        # Unknown PATH/override values may contain private data. Report only names,
        # counts and hashes, sufficient to identify the failed comparison.
        expected_path = report.get("child_path")
        def path_identity(value):
            return {"sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    "entries": len(value.split(";"))} if isinstance(value, str) else None
        expected_python = report.get("release_python")
        if not isinstance(expected_python, dict):
            expected_python = {}
        expected_hash = expected_python.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            expected_hash = None
        expected_size = expected_python.get("bytes")
        if type(expected_size) is not int or expected_size < 0:
            expected_size = None
        comparisons = {"matches": matches,
                       "PATH": {"expected": path_identity(expected_path),
                                "observed": [{"key": key, **path_identity(value)} for key, value in path_items]},
                       "import_overrides": {"expected": [], "observed": overrides},
                       "release_python": {"expected": {"sha256": expected_hash, "bytes": expected_size},
                                          "observed": {key: python[key] for key in ("sha256", "bytes")}}}
        raise RuntimeError("Package child environment differs from its receipt: " + json.dumps(comparisons, sort_keys=True))
    _, current = release_inputs()
    if any(report.get(key) != value for key, value in current.items()):
        raise RuntimeError("Package release inputs differ from their receipt")
    tools = report.get("tools")
    if not isinstance(tools, dict) or set(tools) != {"git", "powershell", "git_implementation"}:
        raise RuntimeError("Package receipt omits or adds mandatory tool identities")
    for row in tools.values():
        if row != _file(Path(row["path"])):
            raise RuntimeError("Package tool bytes differ from their receipt")
    discovery = report.get("git_discovery")
    if not isinstance(discovery, dict) or not isinstance(discovery.get("discovered_path"), str):
        raise RuntimeError("Package receipt omits Git discovery identity")
    observed = {"discovered_path": discovery["discovered_path"]}
    git = git_launcher(discovery["discovered_path"], observed)
    selected = _selected_git_implementation(git, observed["implementation_candidates"], report.get("git_exec_path"))
    observed["selected_implementation"] = selected
    version = report.get("git_version")
    if (discovery != observed or tools["git"] != observed["cmd_launcher"]
            or tools["git_implementation"] != {key: selected[key] for key in ("path", "sha256", "bytes")}
            or not isinstance(version, str) or not re.fullmatch(_GIT_VERSION, version)):
        raise RuntimeError("Package Git selection differs from its receipt")
    return {"filename": path.name, "sha256": receipt_hash}


def _query_qt_translation(expected_package: str) -> dict:
    """Executed only by PyInstaller's isolated child; return scalar asset data."""
    import hashlib
    from pathlib import Path
    import PySide6
    from PySide6.QtCore import QLibraryInfo

    package = Path(PySide6.__file__).resolve().parent
    if package != Path(expected_package).resolve():
        raise RuntimeError("Isolated Qt package differs from the pinned release origin")
    source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / "qtbase_zh_TW.qm"
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("Required Traditional Chinese Qt catalogue is missing or symlinked")
    source = source.resolve()
    if not source.is_relative_to(package):
        raise RuntimeError("Qt catalogue is outside the pinned release package")
    payload = source.read_bytes()
    return {"path": str(source), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            "target": str(Path("PySide6") / source.parent.relative_to(package))}


def _qt_isolation():
    from PyInstaller import isolated
    return isolated.Python(strict_mode=True)


def qt_translation_input() -> dict:
    """Query Qt without importing it in the build process or accepting PATH drift.

    Strict mode bounds child shutdown, not a blocked import/function call. The
    optional CLI probe additionally has an outer subprocess timeout.
    """
    package_receipt()
    _, identity = release_inputs()
    package = Path(identity["packages"]["PySide6"]["path"]).parent
    try:
        with _qt_isolation() as child:
            result = child.call(_query_qt_translation, str(package))
    finally:
        # Validate on success, import failure and failed child shutdown alike.
        package_receipt()
    if (not isinstance(result, dict) or set(result) != {"path", "sha256", "bytes", "target"}
            or not isinstance(result["path"], str) or not isinstance(result["target"], str)
            or not isinstance(result["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["sha256"])
            or type(result["bytes"]) is not int or result["bytes"] <= 0):
        raise RuntimeError("Isolated Qt catalogue result has an invalid schema")
    try:
        source = Path(result["path"])
        canonical = source.resolve()
        if (source.name != "qtbase_zh_TW.qm" or not source.is_absolute()
                or not canonical.is_relative_to(package)):
            raise RuntimeError("Isolated Qt catalogue is outside the pinned release package")
        asset = _file(source)
        expected = {**asset, "target": str(Path("PySide6") / canonical.parent.relative_to(package))}
    except (OSError, ValueError, RuntimeError):
        raise RuntimeError("Isolated Qt catalogue path or bytes are invalid") from None
    if result != expected:
        raise RuntimeError("Isolated Qt catalogue identity differs from the actual release asset")
    return expected


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Preflight the current venv's package input selection, without building an EXE")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-qt-translation", action="store_true",
                        help="Also run the spec's isolated Qt query in a prepared child (120-second wait plus bounded failure cleanup)")
    args = parser.parse_args(argv)
    child, _ = prepare_environment(report_path=args.output)
    if args.probe_qt_translation:
        command = [str(Path(sys.executable).resolve()), "-c",
                   "import json; from build_tools.windows_package_environment import qt_translation_input; "
                   "print(json.dumps(qt_translation_input(), sort_keys=True))"]
        # Keep the original Windows launcher handle live during failure cleanup.
        # A Popen context manager could wait indefinitely if tree cleanup fails.
        process = subprocess.Popen(command, env=child)
        try:
            code = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            from build_tools.owned_process_cleanup import terminate_owned_tree
            terminate_owned_tree(process, args.output.parent / "package-qt-probe-cleanup.json")
            raise
        if code:
            raise subprocess.CalledProcessError(code, command)
    print("Input-selection preflight passed; no PyInstaller build or EXE acceptance was performed.")


if __name__ == "__main__":
    main()
