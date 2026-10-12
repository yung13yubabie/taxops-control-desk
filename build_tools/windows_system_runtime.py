"""Exact Windows 10+ system-runtime exclusions, applied before PyInstaller COLLECT.

This build-only policy is not a runtime restriction on library replacement.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from build_tools.dependency_licenses import (
    NOTICE_SOURCE,
    ROOT,
    sha256,
    validate_notice_tree,
)

SYSTEM_DLLS = frozenset(
    {
        "api-ms-win-core-console-l1-1-0.dll",
        "api-ms-win-core-datetime-l1-1-0.dll",
        "api-ms-win-core-debug-l1-1-0.dll",
        "api-ms-win-core-errorhandling-l1-1-0.dll",
        "api-ms-win-core-fibers-l1-1-0.dll",
        "api-ms-win-core-fibers-l1-1-1.dll",
        "api-ms-win-core-file-l1-1-0.dll",
        "api-ms-win-core-file-l1-2-0.dll",
        "api-ms-win-core-file-l2-1-0.dll",
        "api-ms-win-core-handle-l1-1-0.dll",
        "api-ms-win-core-heap-l1-1-0.dll",
        "api-ms-win-core-interlocked-l1-1-0.dll",
        "api-ms-win-core-kernel32-legacy-l1-1-1.dll",
        "api-ms-win-core-libraryloader-l1-1-0.dll",
        "api-ms-win-core-localization-l1-2-0.dll",
        "api-ms-win-core-memory-l1-1-0.dll",
        "api-ms-win-core-namedpipe-l1-1-0.dll",
        "api-ms-win-core-processenvironment-l1-1-0.dll",
        "api-ms-win-core-processthreads-l1-1-0.dll",
        "api-ms-win-core-processthreads-l1-1-1.dll",
        "api-ms-win-core-profile-l1-1-0.dll",
        "api-ms-win-core-rtlsupport-l1-1-0.dll",
        "api-ms-win-core-string-l1-1-0.dll",
        "api-ms-win-core-synch-l1-1-0.dll",
        "api-ms-win-core-synch-l1-2-0.dll",
        "api-ms-win-core-sysinfo-l1-1-0.dll",
        "api-ms-win-core-sysinfo-l1-2-0.dll",
        "api-ms-win-core-timezone-l1-1-0.dll",
        "api-ms-win-core-util-l1-1-0.dll",
        "api-ms-win-crt-conio-l1-1-0.dll",
        "api-ms-win-crt-convert-l1-1-0.dll",
        "api-ms-win-crt-environment-l1-1-0.dll",
        "api-ms-win-crt-filesystem-l1-1-0.dll",
        "api-ms-win-crt-heap-l1-1-0.dll",
        "api-ms-win-crt-locale-l1-1-0.dll",
        "api-ms-win-crt-math-l1-1-0.dll",
        "api-ms-win-crt-process-l1-1-0.dll",
        "api-ms-win-crt-runtime-l1-1-0.dll",
        "api-ms-win-crt-stdio-l1-1-0.dll",
        "api-ms-win-crt-string-l1-1-0.dll",
        "api-ms-win-crt-time-l1-1-0.dll",
        "api-ms-win-crt-utility-l1-1-0.dll",
        "ucrtbase.dll",
    }
)
RETAINED_VC_PATHS = frozenset(
    {
        "_internal/vcruntime140.dll",
        "_internal/vcruntime140_1.dll",
        "_internal/pyside6/msvcp140.dll",
        "_internal/pyside6/msvcp140_1.dll",
        "_internal/pyside6/msvcp140_2.dll",
        "_internal/pyside6/vcruntime140.dll",
        "_internal/pyside6/vcruntime140_1.dll",
        "_internal/shiboken6/msvcp140.dll",
        "_internal/shiboken6/vcruntime140.dll",
        "_internal/shiboken6/vcruntime140_1.dll",
    }
)
STAGING_REPORT = ROOT / "artifacts/build-staging/windows-system-runtime.json"


class SystemRuntimeError(RuntimeError):
    """Packaging departed from the reviewed Windows runtime policy."""


def _path_key(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(p in {"", ".", ".."} for p in normalized.split("/"))
        or ":" in normalized
    ):
        raise SystemRuntimeError(f"Unsafe runtime destination: {value}")
    return path.as_posix().casefold()


def _records(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        key = _path_key(row["bundle_path"])
        if key in result or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise SystemRuntimeError("Duplicate runtime record or invalid SHA-256")
        result[key] = row
    return result


def _staging_records(rows: list[dict], *, reviewed: bool = False) -> dict[str, dict]:
    records = _records(rows)
    for row in records.values():
        source = row.get("source_path")
        size = row.get("bytes")
        kind = row.get("type")
        if (
            not isinstance(source, str)
            or "\x00" in source
            or not (
                PurePosixPath(source).is_absolute()
                or PureWindowsPath(source).is_absolute()
            )
            or ".." in PurePosixPath(source.replace("\\", "/")).parts
            or type(size) is not int
            or size <= 0
            or kind not in ({"BINARY"} if reviewed else {"BINARY", "EXTENSION"})
        ):
            raise SystemRuntimeError(
                "Invalid or incomplete build-staging source metadata"
            )
    return records


def reviewed_policy(manifest: dict | None = None) -> tuple[dict, dict]:
    if manifest is None:
        manifest = validate_notice_tree(NOTICE_SOURCE)
    excluded = _records(manifest["excluded_windows_system_binaries"])
    retained = _records(manifest["reviewed_microsoft_binaries"])
    if set(excluded) != {"_internal/" + name for name in SYSTEM_DLLS}:
        raise SystemRuntimeError(
            "System-runtime policy must name exactly the reviewed 43 DLLs"
        )
    if set(retained) != RETAINED_VC_PATHS:
        raise SystemRuntimeError("Runtime policy must retain the reviewed ten VC DLLs")
    return excluded, retained


def source_identity() -> dict:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    commit, tree = process.stdout.split()
    return {
        "source_commit": commit,
        "source_tree": tree,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "notice_manifest_sha256": sha256(NOTICE_SOURCE / "manifest.json"),
    }


def filter_system_runtime(
    binaries: list[tuple],
    datas: list[tuple],
    *,
    report_path: Path = STAGING_REPORT,
    manifest: dict | None = None,
) -> list[tuple]:
    """Exclude only exact reviewed destinations/bytes; keep a build-time receipt."""
    report = {
        "schema": 1,
        "status": "failed",
        "supported_target": "Windows 10 1809+ / Windows 11 x64",
        "excluded": [],
        "retained": [],
        "before": [],
        "after": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Replace stale success before any operation which could fail.
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        excluded, retained = reviewed_policy(manifest)
        report.update(source_identity())
        for destination, _source, _kind in datas:
            if PurePosixPath(_path_key(destination)).name in SYSTEM_DLLS:
                raise SystemRuntimeError("Excluded system DLL was collected as data")
        seen = set()
        result = []
        for entry in binaries:
            destination, source, kind = entry
            relative = "_internal/" + _path_key(destination)
            if relative in seen:
                raise SystemRuntimeError(f"Duplicate binary destination: {destination}")
            seen.add(relative)
            path = Path(source)
            if not path.is_file() or path.is_symlink():
                raise SystemRuntimeError(
                    f"Missing or symlinked binary source: {destination}"
                )
            row = {
                "bundle_path": "_internal/" + destination.replace("\\", "/"),
                "source_path": str(path.resolve()),
                "type": kind,
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            report["before"].append(row)
            expected = excluded.get(relative) or retained.get(relative)
            if expected and (row["sha256"] != expected["sha256"] or kind != "BINARY"):
                raise SystemRuntimeError(
                    f"Changed reviewed Windows runtime: {destination}"
                )
            if relative in excluded:
                row["pe_file_version"] = excluded[relative]["pe_file_version"]
                report["excluded"].append(row)
                continue
            if PurePosixPath(relative).name in SYSTEM_DLLS:
                raise SystemRuntimeError(
                    f"System DLL in unexpected destination: {destination}"
                )
            result.append(entry)
            report["after"].append(row)
            if relative in retained:
                report["retained"].append(row)
        if not set(excluded).issubset(seen) or not set(retained).issubset(seen):
            raise SystemRuntimeError("Missing reviewed system/VC DLLs in build staging")
        report["status"] = "passed"
        return result
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def validate_system_runtime_bundle(
    bundle: Path, files: list[Path], *, manifest: dict | None = None
) -> dict:
    """The archive must not reintroduce exclusions or omit retained VC binaries."""
    _, retained = reviewed_policy(manifest)
    actual = {_path_key(p.relative_to(bundle).as_posix()): p for p in files}
    for path in files:
        if path.name.casefold() in SYSTEM_DLLS:
            raise SystemRuntimeError(
                f"OS-provided DLL reappeared in bundle: {path.name}"
            )
    for relative, row in retained.items():
        path = actual.get(relative)
        if path is None or sha256(path) != row["sha256"]:
            raise SystemRuntimeError(f"Missing or changed retained VC DLL: {relative}")
    return {
        "excluded_system_dll_count": len(SYSTEM_DLLS),
        "retained_vc_dll_count": len(retained),
    }


def validate_staging_report(bundle: Path, report_path: Path = STAGING_REPORT) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    excluded, retained = reviewed_policy()
    if report.get("schema") != 1 or report.get("status") != "passed":
        raise SystemRuntimeError("Build-staging runtime report is absent or failed")
    if report.get("notice_manifest_sha256") != sha256(NOTICE_SOURCE / "manifest.json"):
        raise SystemRuntimeError("Build-staging notice manifest is stale")
    current = source_identity()
    if any(report.get(key) != current[key] for key in ("source_commit", "source_tree")):
        raise SystemRuntimeError("Build-staging source commit/tree is stale")
    removed = _staging_records(report["excluded"], reviewed=True)
    kept = _staging_records(report["retained"], reviewed=True)
    if {k: v["sha256"] for k, v in removed.items()} != {
        k: v["sha256"] for k, v in excluded.items()
    } or {k: v["sha256"] for k, v in kept.items()} != {
        k: v["sha256"] for k, v in retained.items()
    }:
        raise SystemRuntimeError(
            "Build-staging runtime identities differ from the policy"
        )
    before = _staging_records(report["before"])
    after = _staging_records(report["after"])
    if any(
        row != before.get(key)
        or row.get("pe_file_version") != excluded[key]["pe_file_version"]
        for key, row in removed.items()
    ):
        raise SystemRuntimeError(
            "Excluded receipt rows differ from original build staging"
        )
    if any(row != after.get(key) for key, row in kept.items()):
        raise SystemRuntimeError(
            "Retained receipt rows differ from final build staging"
        )
    if set(before) - set(after) != set(excluded) or set(after) - set(before):
        raise SystemRuntimeError("Build-staging excluded more or fewer than 43 files")
    expected_native = {
        key for key in after if PurePosixPath(key).suffix in {".dll", ".pyd", ".exe"}
    }
    actual_native = {
        _path_key(path.relative_to(bundle).as_posix())
        for path in bundle.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".dll", ".pyd", ".exe"}
    } - {"taxopscontroldesk.exe"}
    if actual_native != expected_native:
        raise SystemRuntimeError("Packaged native inventory differs from build staging")
    for relative, row in after.items():
        if (
            row != before[relative]
            or sha256(bundle / row["bundle_path"]) != row["sha256"]
            or (bundle / row["bundle_path"]).stat().st_size != row["bytes"]
        ):
            raise SystemRuntimeError(
                f"Packaged binary differs from staging: {relative}"
            )
    return {
        "build_staging_sha256": sha256(report_path),
        "build_source_commit": report["source_commit"],
        "build_source_tree": report["source_tree"],
    }
