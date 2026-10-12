"""Five isolated source-process exit controls; never frozen EXE acceptance.

Use an existing CPython 3.11.9 x64 / PySide6 and Qt 6.10.2 environment.
No application modules, database, package installation, or alternate exit API.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import uuid

CASES = (("python-exit", 77), ("qt-show-exit", 77), ("qt-close", 0),
         ("qt-bound-exit", 77), ("qt-bound-close", 0))
BOUND_CASES = {"qt-bound-exit", "qt-bound-close"}
PROFILE_KEYS = {"LOCALAPPDATA": "local", "APPDATA": "roaming", "USERPROFILE": "user",
                "HOME": "user", "TEMP": "temp", "TMP": "temp"}


def file_identity(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}


def save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def profile_environment(root: Path, token: str) -> dict:
    root.mkdir(exist_ok=False)
    (root / ".qt-exit-control").write_text(token, encoding="ascii")
    excluded = {"pythonpath", "pythonhome", "qt_plugin_path", "qt_qpa_platform_plugin_path",
                "qml2_import_path", "qt_qpa_platform", "taxops_dev", "path",
                *(key.casefold() for key in PROFILE_KEYS)}
    env = {k: v for k, v in os.environ.items() if k.casefold() not in excluded}
    for key, name in PROFILE_KEYS.items():
        (root / name).mkdir(exist_ok=True)
        env[key] = str(root / name)
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    return env


def require_profile(root: Path, token: str) -> None:
    if not token or (root / ".qt-exit-control").read_text(encoding="ascii") != token:
        raise ValueError("A new harness-owned profile token is required")
    for key, name in PROFILE_KEYS.items():
        if not os.environ.get(key) or Path(os.environ[key]).resolve() != root / name:
            raise ValueError("Refusing non-isolated profile: " + key)


def current_image_path() -> Path:
    """Read this process image only; NULL HMODULE never opens another PID."""
    if sys.platform != "win32":
        raise ValueError("Current Windows process image requires Windows")
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    get_filename = kernel32.GetModuleFileNameW
    get_filename.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    get_filename.restype = wintypes.DWORD
    for size in (1024, 4096, 32768):
        buffer = ctypes.create_unicode_buffer(size)
        count = get_filename(None, buffer, size)
        if count == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if count < size:
            return Path(buffer.value).resolve()
    raise ValueError("Current process image path exceeded the bounded buffer")


def configured_runtime(python: Path) -> dict:
    """Bind the requested launcher to its own venv config and expected base image."""
    if python.name.casefold() != "python.exe" or python.parent.name.casefold() != "scripts":
        raise ValueError("Specify the existing venv Scripts/python.exe")
    root = python.parent.parent
    config = root / "pyvenv.cfg"
    fields = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip().casefold()
        if separator and key in {"home", "version"}:
            if key in fields:
                raise ValueError("Duplicate pinned venv configuration field: " + key)
            fields[key] = value.strip()
    home = Path(fields.get("home", ""))
    if fields.get("version") != "3.11.9" or not home.is_absolute():
        raise ValueError("Venv config requires version 3.11.9 and an absolute home")
    home = home.resolve()
    base = home / "python.exe"
    if base.resolve() == python.resolve():
        raise ValueError("Venv launcher and base image must be distinct")
    return {"launcher": file_identity(python), "base_image": file_identity(base),
            "base_prefix": str(home), "venv_prefix": str(root.resolve()),
            "configuration": file_identity(config)}


def require_runtime_binding(runtime: dict, expected: dict | None) -> None:
    if expected is None:
        raise ValueError("Launcher relationship requires the configured image identities")
    for actual_key, expected_key in (("executable", "launcher"),
                                     ("base_executable", "base_image"),
                                     ("process_image", "base_image")):
        actual, wanted = runtime[actual_key], expected[expected_key]
        if (Path(actual["path"]) != Path(wanted["path"])
                or actual["sha256"] != wanted["sha256"] or actual["bytes"] != wanted["bytes"]):
            raise ValueError("Runtime image does not match the configured venv: " + actual_key)
    for actual_key, expected_key in (("prefix", "venv_prefix"), ("base_prefix", "base_prefix")):
        if Path(runtime[actual_key]) != Path(expected[expected_key]):
            raise ValueError("Runtime prefix does not match the configured venv: " + actual_key)


def runtime_identity() -> dict:
    result = {"platform": sys.platform, "implementation": platform.python_implementation(),
              "python": platform.python_version(), "pointer_bits": struct.calcsize("P") * 8,
              "executable": file_identity(Path(sys.executable)), "prefix": sys.prefix,
              "base_executable": file_identity(Path(sys._base_executable)),
              "process_image": file_identity(current_image_path()) if sys.platform == "win32" else None,
              "base_prefix": sys.base_prefix, "is_virtual_environment": sys.prefix != sys.base_prefix,
              "pyside_distribution": importlib.metadata.version("PySide6"),
              "qt_version": None, "qt_loaded": False}
    return result


def validate_runtime(result: dict) -> None:
    if (result["platform"], result["implementation"], result["python"], result["pointer_bits"],
        result["pyside_distribution"], result["is_virtual_environment"]) != (
            "win32", "CPython", "3.11.9", 64, "6.10.2", True):
        raise ValueError("Requires existing Windows CPython 3.11.9 x64 / PySide6 6.10.2 venv")


def make_bound_window(widgets):
    """Keep a real Python bound-method connection alive until process exit."""
    class BoundWindow(widgets.QWidget):
        def __init__(self):
            super().__init__()
            self.callback_count = 0
            self.button = widgets.QPushButton("Synthetic signal control", self)
            self.connection = self.button.clicked.connect(self.on_clicked)

        # Intentionally no @Slot decorator, matching ordinary UI connections.
        def on_clicked(self, checked=False):
            self.callback_count += 1

    return BoundWindow()


def bound_signal_evidence(window) -> dict:
    window.button.click()  # A real synchronous emit to the Python bound method.
    evidence = {"sender": "QPushButton.clicked", "receiver": "BoundWindow.on_clicked",
                "decorated_slot": False, "callback_count": window.callback_count,
                "connection_valid": bool(window.connection),
                "sender_retained": window.button.parent() is window,
                "receiver_retained": window.on_clicked.__self__ is window,
                "ready": True}
    validate_bound_evidence(evidence)
    return evidence


def validate_bound_evidence(evidence: dict) -> None:
    if (type(evidence.get("callback_count")) is not int or evidence["callback_count"] != 1
            or evidence.get("decorated_slot") is not False
            or any(evidence.get(key) is not True for key in
                   ("connection_valid", "sender_retained", "receiver_retained", "ready"))):
        raise ValueError("Bound-method control requires one real callback and retained sender/receiver")


def run_child(case: str, directory: Path, token: str) -> int:
    report = {"schema": 1, "case": case, "status": "failed", "process_id": os.getpid(),
              "parent_process_id": os.getppid(), "scope": "source native-Qt control; no TaxOps/DB"}
    try:
        require_profile(directory / "profile", token)
        report["runtime"] = runtime_identity()
        validate_runtime(report["runtime"])
        if case == "python-exit":
            if any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules):
                raise ValueError("No-Qt control unexpectedly imported PySide6")
            report.update(status="requesting_exit", requested_exit_code=77, checkpoint="before_qt_import")
            save(directory / "child.json", report)
            os._exit(77)
        import PySide6
        from PySide6 import QtCore, QtWidgets, __version__

        report["runtime"].update(qt_loaded=True, qt_version=QtCore.qVersion(),
                                  pyside_version=__version__,
                                  pyside_package=file_identity(Path(PySide6.__file__)),
                                  qtcore_extension=file_identity(Path(QtCore.__file__)),
                                  qtwidgets_extension=file_identity(Path(QtWidgets.__file__)))
        if __version__ != "6.10.2" or QtCore.qVersion() != "6.10.2":
            raise ValueError("Actual PySide6 and Qt runtime must both be 6.10.2")
        app = QtWidgets.QApplication(["TaxOps synthetic exit control"])
        report["qt_platform"] = app.platformName()
        if report["qt_platform"] != "windows":
            raise ValueError("Requires native Windows Qt platform")
        window = make_bound_window(QtWidgets) if case in BOUND_CASES else QtWidgets.QWidget()
        window.setWindowTitle("Synthetic Qt exit control")
        window.show()
        report.update(checkpoint="widget_show_returned_before_exec", window_visible=window.isVisible())
        if not report["window_visible"]:
            raise ValueError("Synthetic QWidget did not become visible")
        if case in BOUND_CASES:
            report["bound_signal"] = bound_signal_evidence(window)
        if case in {"qt-show-exit", "qt-bound-exit"}:
            report.update(status="requesting_exit", requested_exit_code=77)
            save(directory / "child.json", report)
            os._exit(77)
        if case not in {"qt-close", "qt-bound-close"}:
            raise ValueError("Unknown diagnostic case")
        save(directory / "child.json", report)
        QtCore.QTimer.singleShot(100, window.close)
        code = app.exec()
        report.update(status="normal_return", requested_exit_code=0, event_loop_exit_code=code,
                      checkpoint="event_loop_returned")
        save(directory / "child.json", report)
        return code
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        save(directory / "child.json", report)
        return 1


def process_relation(outer_pid: int, child: dict, harness_pid: int, expected_runtime: dict | None = None) -> str:
    """Check only the exact owned PID or one self-reported venv launcher edge.

    No lookup of exited/reused PIDs and no inference of an inner exit value.
    """
    child_pid, parent_pid = child.get("process_id"), child.get("parent_process_id")
    if any(type(pid) is not int or not 0 < pid <= 0xFFFFFFFF
           for pid in (outer_pid, child_pid, parent_pid, harness_pid)):
        raise ValueError("Process receipt requires positive integer PIDs")
    if outer_pid == harness_pid or child_pid == harness_pid or child_pid == parent_pid:
        raise ValueError("Invalid owned process relationship")
    if expected_runtime is not None:
        require_runtime_binding(child["runtime"], expected_runtime)
    if child_pid == outer_pid and parent_pid == harness_pid:
        return "direct_popen_process"
    if child_pid != outer_pid and parent_pid == outer_pid:
        # CPython 3.11.9 PC/launcher.c built with VENV_REDIRECT creates one
        # interpreter child and forwards its code. Only this pinned Windows
        # virtual-environment contract may use the extra reported edge.
        validate_runtime(child.get("runtime", {}))
        require_runtime_binding(child["runtime"], expected_runtime)
        return "single_level_windows_venv_launcher"
    raise ValueError("Child PID/parent PID does not match the owned process")


def run_case(command: list[str], directory: Path, env: dict, expected: int, timeout: int, *, expected_runtime: dict | None = None, expected_case: str | None = None) -> dict:
    record = {"schema": 2, "command": command, "status": "failed", "expected_exit_code": expected,
              "outer_process_id": None, "outer_exit_code": None, "outer_exit_code_observed": False,
              "child_exit_code": None, "child_exit_code_observed": False,
              "process_relation_evidence": "child self-reported PID/PPID in a new owned profile; no external process query"}
    process = None
    try:
        with (directory / "stdout.bin").open("xb") as stdout, (directory / "stderr.bin").open("xb") as stderr:
            process = subprocess.Popen(command, cwd=directory, env=env, stdout=stdout, stderr=stderr)
            record["outer_process_id"] = process.pid
            record["outer_exit_code"] = process.wait(timeout=timeout)
            record["outer_exit_code_observed"] = True
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if process is not None and process.poll() is None:
            from build_tools.owned_process_cleanup import terminate_owned_tree
            record["forced_cleanup"] = terminate_owned_tree(process, directory / "forced-cleanup.json")
            record["outer_exit_code_after_forced_cleanup"] = process.poll()
        code = record["outer_exit_code"]
        record["outer_exit_code_hex"] = None if code is None else f"0x{code & 0xFFFFFFFF:08x}"
        for name in ("stdout", "stderr"):
            path = directory / (name + ".bin")
            if path.is_file():
                record[name] = file_identity(path)
        try:
            child = json.loads((directory / "child.json").read_text(encoding="utf-8"))
            if not isinstance(child, dict):
                raise ValueError("Child receipt must be an object")
            record["child"] = child
            record["child_receipt"] = file_identity(directory / "child.json")
            if expected_case is not None and child.get("case") != expected_case:
                raise ValueError("Child receipt case does not match the requested control")
            if expected_case in BOUND_CASES:
                validate_bound_evidence(child.get("bound_signal", {}))
            relation = process_relation(record["outer_process_id"], child, os.getpid(), expected_runtime)
            record["process_relation"] = relation
            if relation == "direct_popen_process" and record["outer_exit_code_observed"]:
                record["child_exit_code"] = code
                record["child_exit_code_observed"] = True
            if (code == expected and "error" not in record and "forced_cleanup" not in record
                    and child.get("status") == ("normal_return" if expected == 0 else "requesting_exit")
                    and child.get("requested_exit_code") == expected):
                record["status"] = "matched_control"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            record["receipt_error"] = {"type": type(exc).__name__, "message": str(exc)}
        save(directory / "process.json", record)
    return record


def contrast(python: Path, output: Path, timeout: int = 60) -> dict:
    if sys.platform != "win32":
        raise ValueError("Native Qt exit contrast requires Windows")
    identity = file_identity(python)
    expected_runtime = configured_runtime(python)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": 2, "status": "failed", "scope": "five source controls; not EXE acceptance",
              "limits": "Source wheel native VC bytes may differ from the official VC replacements in the EXE. Module origins are recorded; actual loaded native DLL paths/hashes are not collected by this control. Matching versions do not establish identical binaries or explain a frozen failure.",
              "expected_runtime": expected_runtime, "python_requested": identity, "harness": file_identity(Path(__file__)), "cases": []}
    try:
        for case, expected in CASES:
            directory = output / case
            directory.mkdir()
            token = uuid.uuid4().hex
            env = profile_environment(directory / "profile", token)
            command = [str(python), "-I", "-B", str(Path(__file__).resolve()), "--child-case", case,
                       "--output", str(directory), "--profile-token", token]
            record = run_case(command, directory, env, expected, timeout, expected_runtime=expected_runtime, expected_case=case)
            result["cases"].append(record)
            # A mismatch is preserved while the remaining controls still run.
            # A setup/version error stops before any further exit injection.
            if record.get("child", {}).get("error") or "receipt_error" in record or "error" in record:
                break
        if len(result["cases"]) == len(CASES) and all(r["status"] == "matched_control" for r in result["cases"]):
            result["status"] = "matched_controls"
    finally:
        save(output / "contrast.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--child-case", choices=[name for name, _ in CASES], help=argparse.SUPPRESS)
    parser.add_argument("--profile-token", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if args.child_case:
        return run_child(args.child_case, args.output.resolve(), args.profile_token)
    if args.python is None:
        parser.error("--python must identify an existing pinned environment")
    result = contrast(args.python.resolve(), args.output.resolve(), args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "matched_controls" else 1


if __name__ == "__main__":
    raise SystemExit(main())
