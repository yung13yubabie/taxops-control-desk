"""Failure-only cleanup for a still-owned Windows Popen process tree.

The live Popen handle remains open throughout. Never scan or kill by image name,
never delete extraction directories, and never count this as normal cleanup.
"""
from __future__ import annotations
import ctypes
import json
import subprocess
import sys
from pathlib import Path


def system_taskkill() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Owned Windows process-tree cleanup requires Windows")
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel32.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise RuntimeError("Windows system directory could not be verified")
    executable = Path(buffer.value) / "taskkill.exe"
    if not executable.is_file():
        raise RuntimeError("Verified System32 taskkill is missing")
    return executable


def terminate_owned_tree(process: subprocess.Popen, evidence: Path) -> dict:
    """Retain failure evidence even if an owned descendant cannot be terminated."""
    record = {"pid": process.pid, "normal_cleanup": False, "scope": "this retained Popen handle and its process tree",
              "status": "failed", "descendant_cleanup_verified": False}
    try:
        if process.poll() is not None:
            record["status"] = "parent_already_exited_children_unverified"
            return record
        # On Windows Popen owns a process handle, which remains retained while
        # addressing this PID. Do not close it or substitute a PID from a log.
        if getattr(process, "_handle", None) is None:
            raise RuntimeError("No retained Windows Popen process handle")
        command = [str(system_taskkill()), "/PID", str(process.pid), "/T", "/F"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        record.update({"taskkill_exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        try:
            record["parent_exit_code"] = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            record["parent_still_running"] = True
            return record
        if result.returncode == 0:
            record["status"] = "owned_tree_termination_requested"
        else:
            record["status"] = "tree_termination_failed_or_parent_exited_during_request"
        # Taskkill success is recorded, not elevated to proof about arbitrary
        # escaped descendants. Gate acceptance remains failed in this path.
        return record
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return record
    finally:
        existing = json.loads(evidence.read_text(encoding="utf-8")) if evidence.is_file() else []
        existing.append(record)
        evidence.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
