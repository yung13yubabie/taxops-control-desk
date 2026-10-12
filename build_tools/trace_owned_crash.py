"""Bounded, isolated crash trace for an existing exact onefile EXE.

A trace is not application acceptance. It never changes the requested exit 77
or infers the actual child exit code from an outer bootloader exit code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from build_tools.owned_process_cleanup import terminate_owned_tree
from build_tools.verify_windows_bundle import isolated_environment


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_recorded(
    command: list[str],
    *,
    cwd: Path,
    env: dict,
    prefix: Path,
    timeout: int,
    expected_exit: int,
    ready: Path | None = None,
    release: Path | None = None,
) -> dict:
    """Save raw streams and the owned outer process result before any assertion."""
    receipt = {
        "schema": 1,
        "status": "failed",
        "command": command,
        "expected_exit_code": expected_exit,
        "bootloader_pid": None,
        "bootloader_exit_code": None,
        "child_exit_code": None,
        "child_exit_code_observed": False,
        "normal_cleanup": False,
        "scope": "owned outer process trace; not full onefile acceptance",
        "stream_capture_scope": "Raw redirected streams; windowed bootloaders may suppress output. Empty streams do not prove absence of errors.",
    }
    process = None
    stdout_path, stderr_path = (
        prefix.with_suffix(".stdout.bin"),
        prefix.with_suffix(".stderr.bin"),
    )
    receipt_path = prefix.with_suffix(".process.json")
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                command, cwd=cwd, env=env, stdout=stdout, stderr=stderr
            )
            receipt["bootloader_pid"] = process.pid
            try:
                if release is not None:
                    deadline = time.monotonic() + timeout
                    while not ready.is_file():
                        if process.poll() is not None:
                            raise RuntimeError(
                                "Owned initialization exited before GUI ready"
                            )
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "Owned initialization did not reach GUI ready"
                            )
                        time.sleep(0.05)
                    release.write_text(
                        "Close the owned synthetic initialization normally\n",
                        encoding="utf-8",
                    )
                receipt["bootloader_exit_code"] = process.wait(timeout=timeout)
                receipt["status"] = (
                    "matched_expected_exit"
                    if process.returncode == expected_exit
                    else "failed"
                )
            finally:
                receipt["exit_code_before_forced_cleanup"] = process.poll()
                if process.poll() is None:
                    receipt["forced_cleanup"] = terminate_owned_tree(
                        process, prefix.with_suffix(".forced-cleanup.json")
                    )
                receipt["bootloader_exit_code"] = process.poll()
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        code = receipt["bootloader_exit_code"]
        receipt["bootloader_exit_code_hex"] = (
            f"0x{code & 0xFFFFFFFF:08x}" if code is not None else None
        )
        for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            if path.is_file():
                receipt[label] = {
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "text_utf8_with_replacement": path.read_bytes().decode(
                        "utf-8", errors="replace"
                    ),
                }
        if ready is not None and ready.is_file():
            try:
                payload = json.loads(ready.read_text(encoding="utf-8"))
                receipt["child_pid_reported"] = payload.get(
                    "process_id", payload.get("loaded_modules", {}).get("process_id")
                )
                receipt["child_parent_pid_reported"] = payload.get("parent_process_id")
                receipt["ready_file"] = ready.name
                receipt["ready_sha256"] = sha256(ready)
                receipt["child_requested_exit_code"] = payload.get(
                    "requested_crash_exit_code"
                )
            except (OSError, ValueError, TypeError) as exc:
                receipt["ready_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                receipt["status"] = "failed"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return receipt


def trace(exe: Path, expected_sha256: str, output: Path, *, timeout: int = 180) -> dict:
    if sys.platform != "win32":
        raise ValueError("Exact onefile crash tracing requires Windows")
    if sha256(exe) != expected_sha256:
        raise ValueError("Refusing to run a different EXE SHA-256")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": 1,
        "status": "failed",
        "exe_sha256": expected_sha256,
        "scope": "isolated single crash reproduction; not full acceptance",
    }
    try:
        relocated = output / "Only EXE 中文"
        relocated.mkdir()
        actual = relocated / "TaxOpsControlDesk.exe"
        shutil.copyfile(exe, actual)
        if sha256(actual) != expected_sha256:
            raise ValueError("Relocated EXE hash mismatch")
        profile = output / "Synthetic profile 中文"
        env = isolated_environment(profile)
        token = uuid.uuid4().hex
        (profile / ".taxops-onefile-gate").write_text(token, encoding="ascii")
        instance = "TaxOpsControlDesk.CrashTrace." + uuid.uuid4().hex
        record = output / "synthetic-client.json"
        for label, extra, expected in (
            ("initialize", ["--initialize-persistence"], 0),
            ("owned-crash", ["--crash-after-ready"], 77),
        ):
            ready, release = output / f"{label}-ready.json", output / f"{label}-release"
            command = [
                str(actual),
                "--onefile-probe",
                "--report",
                str(output / f"{label}.json"),
                "--ready",
                str(ready),
                "--release",
                str(release),
                "--instance-name",
                instance,
                "--profile-root",
                str(profile),
                "--profile-token",
                token,
                "--persistent-record",
                str(record),
                *extra,
            ]
            observed = run_recorded(
                command,
                cwd=actual.parent,
                env=env,
                prefix=output / label,
                timeout=timeout,
                expected_exit=expected,
                ready=ready,
                release=release if label == "initialize" else None,
            )
            result[label] = observed
            if observed["status"] != "matched_expected_exit" or not ready.is_file():
                raise RuntimeError(
                    f"{label} exit mismatch or missing readiness: {observed['bootloader_exit_code']}"
                )
        result["status"] = "matched_expected_exit"
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["preserved_extraction_directories"] = [
            str(p.relative_to(output))
            for p in output.glob("Synthetic profile */temp/_MEI*")
        ]
        (output / "crash-trace.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--exe-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    result = trace(
        args.exe.resolve(), args.exe_sha256, args.output.resolve(), timeout=args.timeout
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "matched_expected_exit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
