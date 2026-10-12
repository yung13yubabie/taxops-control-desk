"""Isolated Windows Shell icon experiment, never a bundle acceptance policy."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from build_tools.owned_process_cleanup import terminate_owned_tree
from build_tools.windows_loaded_modules import _WindowsModuleAPI

FLAGS = 0x4161  # ICON | SMALLICON | SYSICONINDEX | ADDOVERLAYS | OVERLAYINDEX
CONTENT = b"Synthetic Shell icon experiment. No business data.\n"
SCOPE = (
    "Current-process on-disk module observations, not mapped-memory integrity or "
    "signature verification. Deltas do not establish trusted extensions, causation, "
    "or permission to omit missing bundle dependencies. A query without additions is "
    "inconclusive, not complete Shell/Qt coverage. No acceptance gate is changed."
)


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int32),
        ("dwAttributes", ctypes.c_uint32), ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def file_identity(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve(strict=True)), "bytes": path.stat().st_size, "sha256": digest}


def source_identity() -> list[dict]:
    directory = Path(__file__).resolve().parent
    return [file_identity(directory / name) for name in
            ("shell_icon_probe.py", "windows_loaded_modules.py", "owned_process_cleanup.py", "__init__.py")]


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def exception_record(exc: Exception) -> dict:
    return {"type": type(exc).__name__, "message": str(exc), "winerror": getattr(exc, "winerror", None),
            "last_error": ctypes.get_last_error() if sys.platform == "win32" else None}


class ShellAPI:
    def __init__(self):
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("This experiment requires 64-bit Windows")
        if ctypes.sizeof(SHFILEINFOW) != 696:
            raise RuntimeError("Unexpected Windows SHFILEINFOW ABI")
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.ole = ctypes.WinDLL("ole32", use_last_error=True)
        self.shell.SHGetFileInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                             ctypes.POINTER(SHFILEINFOW), ctypes.c_uint32, ctypes.c_uint32]
        self.shell.SHGetFileInfoW.restype = ctypes.c_size_t
        self.user.DestroyIcon.argtypes = [ctypes.c_void_p]
        self.user.DestroyIcon.restype = ctypes.c_int32
        self.ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.ole.CoInitializeEx.restype = ctypes.c_int32
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None

    def initialize(self) -> dict:
        ctypes.set_last_error(0)
        result = self.ole.CoInitializeEx(None, 0)  # Qt's MTA worker model
        return {"hresult": result, "hresult_hex": f"0x{result & 0xffffffff:08x}",
                "last_error": ctypes.get_last_error(), "accepted": result in (0, 1)}

    def query(self, path: Path) -> dict:
        info = SHFILEINFOW()
        record = {"path": str(path), "flags": FLAGS, "flags_hex": f"0x{FLAGS:x}",
                  "file_attributes_argument": 0, "status": "failed"}
        try:
            ctypes.set_last_error(0)
            result = self.shell.SHGetFileInfoW(str(path), 0, ctypes.byref(info), ctypes.sizeof(info), FLAGS)
            record.update(return_value=int(result), last_error=ctypes.get_last_error(),
                          hicon=int(info.hIcon or 0), icon_index=info.iIcon,
                          file_attributes=info.dwAttributes, display_name=info.szDisplayName,
                          type_name=info.szTypeName)
            if result and info.hIcon:
                record["status"] = "observed"
        except Exception as exc:
            record["error"] = exception_record(exc)
        finally:
            if info.hIcon:
                try:
                    ctypes.set_last_error(0)
                    destroyed = self.user.DestroyIcon(info.hIcon)
                    record["destroy_icon"] = {"return_value": int(destroyed), "last_error": ctypes.get_last_error()}
                    if not destroyed:
                        record["status"] = "failed"
                except Exception as exc:
                    record["destroy_icon"] = {"error": exception_record(exc)}
                    record["status"] = "failed"
            else:
                record["destroy_icon"] = {"not_required": True}
        return record  # The returned system image-list handle is never destroyed.


def snapshot(api) -> dict:
    for attempt in range(3):
        handles = api.handles()
        rows = []
        for handle in handles:
            row = {"handle": int(handle), "status": "failed"}
            try:
                path = api.path(handle)
                row["loader_path"] = path
                row.update(**file_identity(Path(path)), status="observed")
            except Exception as exc:
                row["error"] = exception_record(exc)
            rows.append(row)
        if set(api.handles()) == set(handles):
            paths = [os.path.normcase(row["path"]) for row in rows if "path" in row]
            valid = all(row["status"] == "observed" for row in rows) and len(set(paths)) == len(paths)
            return {"status": "observed" if valid else "failed", "modules": rows, "attempt": attempt + 1}
    raise RuntimeError("Current-process module list did not stabilize")


def delta(before: dict, after: dict) -> dict:
    def index(report):
        return {os.path.normcase(row["path"]): row for row in report["modules"] if row["status"] == "observed"}
    old, new = index(before), index(after)
    return {"added": [new[key] for key in sorted(new.keys() - old.keys())],
            "removed": [old[key] for key in sorted(old.keys() - new.keys())],
            "changed": [{"before": old[key], "after": new[key]} for key in sorted(old.keys() & new.keys())
                        if (old[key]["sha256"], old[key]["bytes"]) != (new[key]["sha256"], new[key]["bytes"])],
            "complete": before["status"] == after["status"] == "observed"}


def validate_profile(root: Path, token: str) -> None:
    if not token or os.environ.get("TAXOPS_SHELL_PROBE_TOKEN") != token:
        raise RuntimeError("Missing isolated Shell experiment token")
    for name, relative in (("USERPROFILE", "profile"), ("LOCALAPPDATA", "profile/local"),
                           ("APPDATA", "profile/roaming"), ("TEMP", "temp"), ("TMP", "temp")):
        if Path(os.environ.get(name, "")).resolve() != (root / relative).resolve():
            raise RuntimeError(f"Invalid isolated {name}")


def child(root: Path, token: str) -> int:
    validate_profile(root, token)
    report = {"schema": 1, "status": "failed", "scope": SCOPE, "process_id": os.getpid(),
              "parent_process_id": os.getppid(), "python": sys.version, "executable": sys.executable,
              "source": source_identity(), "calls": [], "qt_or_taxops_imported": False}
    path = root / "child.json"
    initialized = False
    try:
        if sys.platform != "win32":
            raise RuntimeError("Windows Shell observation is unsupported on this platform")
        if any(name == "taxops" or name.startswith(("taxops.", "PySide6", "shiboken6")) for name in sys.modules):
            raise RuntimeError("This experiment must not import TaxOps or Qt")
        targets = (root / "inputs" / "synthetic.txt", root / "inputs" / "synthetic folder")
        if targets[0].read_bytes() != CONTENT or not targets[1].is_dir() or any(targets[1].iterdir()):
            raise RuntimeError("Synthetic Shell inputs changed")
        if any(target.resolve(strict=True).parent != (root / "inputs").resolve(strict=True) for target in targets):
            raise RuntimeError("Synthetic input escaped its isolated root")
        report["input"] = file_identity(targets[0])
        shell, modules = ShellAPI(), _WindowsModuleAPI()
        # Preload the collector, hash implementation and required system DLLs.
        hashlib.sha256(CONTENT).hexdigest()
        report["com"] = shell.initialize()
        if not report["com"]["accepted"]:
            raise RuntimeError("CoInitializeEx did not accept the requested MTA")
        initialized = True
        report["before"] = snapshot(modules)
        save(path, report)
        previous = report["before"]
        for target in targets:
            result = shell.query(target)
            report["calls"].append(result)
            save(path, report)
            current = snapshot(modules)
            result.update(after=current, delta=delta(previous, current))
            previous = current
            save(path, report)
        report["after"] = previous
        report["delta"] = delta(report["before"], previous)
        report["qt_or_taxops_imported"] = any(
            name == "taxops" or name.startswith(("taxops.", "PySide6", "shiboken6")) for name in sys.modules)
        if (report["before"]["status"] == "observed" and not report["qt_or_taxops_imported"]
                and all(row["status"] == row["after"]["status"] == "observed" for row in report["calls"])):
            report["status"] = "observed"
    except Exception as exc:
        report["error"] = exception_record(exc)
    finally:
        # All snapshots precede COM teardown; balance S_OK and S_FALSE once each.
        if initialized:
            shell.ole.CoUninitialize()
            report["com"]["uninitialized"] = True
        save(path, report)
    return 0 if report["status"] == "observed" else 1


def run(output: Path, timeout: float = 90) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Windows Shell observation is unsupported on this platform")
    if not 1 <= timeout <= 180:
        raise ValueError("Child timeout must be between 1 and 180 seconds")
    root = output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for relative in ("profile/local", "profile/roaming", "temp", "inputs/synthetic folder"):
        (root / relative).mkdir(parents=True)
    (root / "inputs" / "synthetic.txt").write_bytes(CONTENT)
    token = secrets.token_hex(32)
    env = os.environ.copy()
    for key, relative in (("USERPROFILE", "profile"), ("LOCALAPPDATA", "profile/local"),
                          ("APPDATA", "profile/roaming"), ("TEMP", "temp"), ("TMP", "temp")):
        env[key] = str(root / relative)
    env["TAXOPS_SHELL_PROBE_TOKEN"] = token
    # These are per-child process variables, not Windows account or registry changes.
    drive, home = os.path.splitdrive(env["USERPROFILE"])
    env["HOMEDRIVE"], env["HOMEPATH"] = drive, home
    source = source_identity()
    report = {"schema": 1, "status": "failed", "scope": SCOPE, "source": source,
              "input": file_identity(root / "inputs" / "synthetic.txt"), "flags": FLAGS,
              "interpreter": file_identity(Path(sys.executable)), "timeout_seconds": timeout,
              "child_exit_directly_observed": False}
    command = [sys.executable, "-m", "build_tools.shell_icon_probe", "--child", "--output", str(root), "--token", token]
    process = None
    try:
        with (root / "stdout.bin").open("wb") as stdout, (root / "stderr.bin").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent.parent,
                                       env=env, stdout=stdout, stderr=stderr)
            report["retained_popen_pid"] = process.pid
            result = process.wait(timeout=timeout)
            report.update(outer_returncode=result, outer_returncode_hex=f"0x{result & 0xffffffff:08x}")
        receipt = json.loads((root / "child.json").read_text(encoding="utf-8"))
        report["child"] = receipt
        direct = receipt["process_id"] == process.pid
        parent_matches = receipt["parent_process_id"] == process.pid
        report["child_exit_directly_observed"] = direct
        report["pid_relation"] = "direct" if direct else "one_level_child" if parent_matches else "unmatched"
        if result != 0 or receipt["status"] != "observed" or not (direct or parent_matches):
            raise RuntimeError("Shell experiment child failed or identity relation mismatched")
        if source_identity() != source or receipt["source"] != source:
            raise RuntimeError("Experiment source identity changed")
        if receipt["input"] != report["input"] or file_identity(root / "inputs" / "synthetic.txt") != report["input"]:
            raise RuntimeError("Synthetic input identity changed")
        report["status"] = "observed"
    except Exception as exc:
        report["error"] = exception_record(exc)
    finally:
        if process is not None and process.poll() is None:
            report["forced_cleanup"] = terminate_owned_tree(process, root / "owned-cleanup.json")
        save(root / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New experiment directory; never an existing profile")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--token", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.output.resolve(), args.token)
    return 0 if run(args.output, args.timeout)["status"] == "observed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
