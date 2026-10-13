"""Fresh stdlib-only Windows Shell observations; no persisted receipt is authority."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import types
import sys
from pathlib import Path

# Direct execution with -I -S must not add the checkout to sys.path. Load only
# this exact reviewed stdlib helper, whose bytes the parent hashes independently.
_module_path = Path(__file__).with_name("windows_loaded_modules.py")
# Compile these exact source bytes; do not let an ignored/stale __pycache__
# file substitute different collector code for the parent's reviewed hash.
_collector = types.ModuleType("_taxops_module_collector")
_collector.__file__ = str(_module_path)
exec(compile(_module_path.read_bytes(), str(_module_path), "exec"), _collector.__dict__)
_WindowsModuleAPI = _collector._WindowsModuleAPI

FLAGS = 0x4161  # ICON | SMALLICON | SYSICONINDEX | ADDOVERLAYS | OVERLAYINDEX
CONTENT = b"Synthetic Shell icon experiment. No business data.\n"
SCOPE = (
    "Same-run independently Shell-observed additions, not trusted extensions, "
    "optional dependencies, Qt causation, mapped-memory integrity, publisher "
    "verification or clean-OS acceptance. An empty delta grants no classification."
)


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int32),
        ("dwAttributes", ctypes.c_uint32),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def file_identity(path: Path) -> dict:
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    current = path.stat()

    def identity(stat):
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    if identity(before) != identity(after) or identity(after) != identity(current):
        raise RuntimeError("Observed file changed during hashing")
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def source_identity() -> list[dict]:
    directory = Path(__file__).resolve().parent
    return [
        file_identity(directory / name)
        for name in ("shell_icon_probe.py", "windows_loaded_modules.py")
    ]


def host_identity() -> dict:
    # platform.node()/machine() can import socket/select on Windows. Keep the
    # observer's bootstrap limited to its already-reviewed stdlib native files.
    from ctypes import wintypes

    api = _WindowsModuleAPI()
    api.kernel.GetComputerNameW.argtypes = [
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.kernel.GetComputerNameW.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(256)
    length = wintypes.DWORD(len(buffer))
    if not api.kernel.GetComputerNameW(
        buffer, ctypes.byref(length)
    ) or not 0 < length.value < len(buffer):
        raise RuntimeError("Cannot identify this Windows host")
    version = sys.getwindowsversion()
    return {
        "computer": buffer.value,
        "windows": [
            version.major,
            version.minor,
            version.build,
            version.platform,
            version.service_pack,
        ],
        "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "os_roots": api.roots(),
    }


def polluted_imports() -> bool:
    return any(
        name == "taxops" or name.startswith(("taxops.", "PySide6", "shiboken6"))
        for name in sys.modules
    )


def save(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def exception_record(exc: Exception) -> dict:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "winerror": getattr(exc, "winerror", None),
        "last_error": ctypes.get_last_error() if sys.platform == "win32" else None,
    }


class ShellAPI:
    def __init__(self):
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("This experiment requires 64-bit Windows")
        if ctypes.sizeof(SHFILEINFOW) != 696:
            raise RuntimeError("Unexpected Windows SHFILEINFOW ABI")
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.ole = ctypes.WinDLL("ole32", use_last_error=True)
        self.shell.SHGetFileInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(SHFILEINFOW),
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
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
        return {
            "hresult": result,
            "hresult_hex": f"0x{result & 0xFFFFFFFF:08x}",
            "last_error": ctypes.get_last_error(),
            "accepted": result in (0, 1),
        }

    def query(self, path: Path) -> dict:
        info = SHFILEINFOW()
        record = {
            "path": str(path),
            "flags": FLAGS,
            "flags_hex": f"0x{FLAGS:x}",
            "file_attributes_argument": 0,
            "status": "failed",
        }
        try:
            ctypes.set_last_error(0)
            result = self.shell.SHGetFileInfoW(
                str(path), 0, ctypes.byref(info), ctypes.sizeof(info), FLAGS
            )
            record.update(
                return_value=int(result),
                last_error=ctypes.get_last_error(),
                hicon=int(info.hIcon or 0),
                icon_index=info.iIcon,
                file_attributes=info.dwAttributes,
                display_name=info.szDisplayName,
                type_name=info.szTypeName,
            )
            if result and info.hIcon:
                record["status"] = "observed"
        except Exception as exc:
            record["error"] = exception_record(exc)
        finally:
            if info.hIcon:
                try:
                    ctypes.set_last_error(0)
                    destroyed = self.user.DestroyIcon(info.hIcon)
                    record["destroy_icon"] = {
                        "return_value": int(destroyed),
                        "last_error": ctypes.get_last_error(),
                    }
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
        normalize = _collector._path if sys.platform == "win32" else os.path.normcase
        if set(api.handles()) == set(handles) and all(
            "loader_path" in row
            and normalize(api.path(row["handle"])) == normalize(row["loader_path"])
            for row in rows
        ):
            paths = [os.path.normcase(row["path"]) for row in rows if "path" in row]
            valid = all(row["status"] == "observed" for row in rows) and len(
                set(paths)
            ) == len(paths)
            return {
                "status": "observed" if valid else "failed",
                "modules": rows,
                "attempt": attempt + 1,
            }
    raise RuntimeError("Current-process module list did not stabilize")


def delta(before: dict, after: dict) -> dict:
    def index(report):
        return {
            os.path.normcase(row["path"]): row
            for row in report["modules"]
            if row["status"] == "observed"
        }

    old, new = index(before), index(after)
    return {
        "added": [new[key] for key in sorted(new.keys() - old.keys())],
        "removed": [old[key] for key in sorted(old.keys() - new.keys())],
        "changed": [
            {"before": old[key], "after": new[key]}
            for key in sorted(old.keys() & new.keys())
            if (old[key]["sha256"], old[key]["bytes"])
            != (new[key]["sha256"], new[key]["bytes"])
        ],
        "complete": before["status"] == after["status"] == "observed",
    }


def child(root: Path, challenge: dict) -> int:
    report = {
        "schema": 2,
        "status": "failed",
        "scope": SCOPE,
        "process_id": os.getpid(),
        "parent_process_id": os.getppid(),
        "challenge": challenge,
        "python": list(sys.version_info[:3]),
        "executable": file_identity(Path(sys.executable)),
        "source": source_identity(),
        "calls": [],
        "isolated": sys.flags.isolated,
        "no_site": sys.flags.no_site,
        "qt_or_taxops_imported": polluted_imports(),
    }
    path = root / "child.json"
    initialized = False
    try:
        if (
            sys.platform != "win32"
            or not sys.flags.isolated
            or not sys.flags.no_site
            or report["qt_or_taxops_imported"]
        ):
            raise RuntimeError(
                "Shell observation requires isolated stdlib-only Windows"
            )
        for name, relative in (
            ("USERPROFILE", "profile"),
            ("LOCALAPPDATA", "profile/local"),
            ("APPDATA", "profile/roaming"),
            ("TEMP", "temp"),
            ("TMP", "temp"),
        ):
            if Path(os.environ.get(name, "")).resolve() != (root / relative).resolve():
                raise RuntimeError("Shell observation profile escaped")
        targets = (root / "inputs/synthetic.txt", root / "inputs/synthetic folder")
        if any(
            target.resolve(strict=True).parent != (root / "inputs").resolve(strict=True)
            for target in targets
        ):
            raise RuntimeError("Synthetic Shell input escaped its owned directory")
        if (
            targets[0].read_bytes() != CONTENT
            or not targets[1].is_dir()
            or any(targets[1].iterdir())
        ):
            raise RuntimeError("Synthetic Shell inputs changed")
        report["input"] = file_identity(targets[0])
        report["host"] = host_identity()
        shell, modules = ShellAPI(), _WindowsModuleAPI()
        hashlib.sha256(CONTENT).hexdigest()
        report["com"] = shell.initialize()
        if not report["com"]["accepted"]:
            raise RuntimeError("CoInitializeEx did not accept MTA")
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
        report["qt_or_taxops_imported"] = polluted_imports()
        report["source_after"] = source_identity()
        if (
            report["before"]["status"] == "observed"
            and not report["qt_or_taxops_imported"]
            and all(
                row["status"] == row["after"]["status"] == "observed"
                for row in report["calls"]
            )
        ):
            report["status"] = "observed"
    except Exception as exc:
        report["error"] = exception_record(exc)
    finally:
        if initialized:
            shell.ole.CoUninitialize()
            report["com"]["uninitialized"] = True
        save(path, report)
    return 0 if report["status"] == "observed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # The parent creates and retains this direct process. stdin binds this fresh
    # invocation; no command accepts a previously saved observation receipt.
    challenge = json.loads(sys.stdin.readline())
    return child(args.output.resolve(), challenge)


if __name__ == "__main__":
    raise SystemExit(main())
