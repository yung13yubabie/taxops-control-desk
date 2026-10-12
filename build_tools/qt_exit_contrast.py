"""Three isolated source-process exit controls; never frozen EXE acceptance.

Use an existing CPython 3.11.9 x64 / PySide6 and Qt 6.10.2 environment.
No application modules, database, package installation, or alternate exit API.
"""
from __future__ import annotations

import argparse
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

CASES = (("python-exit", 77), ("qt-show-exit", 77), ("qt-close", 0))
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


def runtime_identity() -> dict:
    result = {"platform": sys.platform, "implementation": platform.python_implementation(),
              "python": platform.python_version(), "pointer_bits": struct.calcsize("P") * 8,
              "executable": file_identity(Path(sys.executable)), "prefix": sys.prefix,
              "base_prefix": sys.base_prefix, "is_virtual_environment": sys.prefix != sys.base_prefix,
              "pyside_distribution": importlib.metadata.version("PySide6"),
              "qt_version": None, "qt_loaded": False}
    return result


def validate_runtime(result: dict) -> None:
    if (result["platform"], result["implementation"], result["python"], result["pointer_bits"],
        result["pyside_distribution"], result["is_virtual_environment"]) != (
            "win32", "CPython", "3.11.9", 64, "6.10.2", True):
        raise ValueError("Requires existing Windows CPython 3.11.9 x64 / PySide6 6.10.2 venv")


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
        window = QtWidgets.QWidget()
        window.setWindowTitle("Synthetic Qt exit control")
        window.show()
        report.update(checkpoint="widget_show_returned_before_exec", window_visible=window.isVisible())
        if not report["window_visible"]:
            raise ValueError("Synthetic QWidget did not become visible")
        if case == "qt-show-exit":
            report.update(status="requesting_exit", requested_exit_code=77)
            save(directory / "child.json", report)
            os._exit(77)
        if case != "qt-close":
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


def run_case(command: list[str], directory: Path, env: dict, expected: int, timeout: int) -> dict:
    record = {"command": command, "status": "failed", "expected_exit_code": expected,
              "process_id": None, "exit_code": None, "exit_code_observed": False}
    process = None
    try:
        with (directory / "stdout.bin").open("xb") as stdout, (directory / "stderr.bin").open("xb") as stderr:
            process = subprocess.Popen(command, cwd=directory, env=env, stdout=stdout, stderr=stderr)
            record["process_id"] = process.pid
            record["exit_code"] = process.wait(timeout=timeout)
            record["exit_code_observed"] = True
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if process is not None and process.poll() is None:
            from build_tools.owned_process_cleanup import terminate_owned_tree
            record["forced_cleanup"] = terminate_owned_tree(process, directory / "forced-cleanup.json")
            record["exit_code_after_forced_cleanup"] = process.poll()
        code = record["exit_code"]
        record["exit_code_hex"] = None if code is None else f"0x{code & 0xFFFFFFFF:08x}"
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
            if (code == expected and "error" not in record and "forced_cleanup" not in record
                    and child.get("process_id") == record["process_id"]
                    and child.get("status") == ("normal_return" if expected == 0 else "requesting_exit")
                    and child.get("requested_exit_code") == expected):
                record["status"] = "matched_control"
        except (OSError, ValueError, TypeError) as exc:
            record["receipt_error"] = {"type": type(exc).__name__, "message": str(exc)}
        save(directory / "process.json", record)
    return record


def contrast(python: Path, output: Path, timeout: int = 60) -> dict:
    if sys.platform != "win32":
        raise ValueError("Native Qt exit contrast requires Windows")
    identity = file_identity(python)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": 1, "status": "failed", "scope": "three source controls; not EXE acceptance",
              "limits": "Source wheel native VC bytes may differ from the official VC replacements in the EXE. Module origins are recorded; actual loaded native DLL paths/hashes are not collected by this control. Matching versions do not establish identical binaries or explain a frozen failure.",
              "python_requested": identity, "harness": file_identity(Path(__file__)), "cases": []}
    try:
        for case, expected in CASES:
            directory = output / case
            directory.mkdir()
            token = uuid.uuid4().hex
            env = profile_environment(directory / "profile", token)
            command = [str(python), "-I", "-B", str(Path(__file__).resolve()), "--child-case", case,
                       "--output", str(directory), "--profile-token", token]
            record = run_case(command, directory, env, expected, timeout)
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
