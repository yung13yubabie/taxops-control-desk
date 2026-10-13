"""Bounded Windows 10+ system-runtime exclusions, applied before EXE creation.

This build-only policy is not a runtime restriction on library replacement.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import subprocess
import sys
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
    from build_tools.source_materials import source_identity as identify_materials
    return {
        **identify_materials(ROOT),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "notice_manifest_sha256": sha256(NOTICE_SOURCE / "manifest.json"),
    }


# Required native destinations from the existing frozen payload gate, plus qgif.
# This pre-EXE check cannot replace the full frozen/archive/Qt inventory gates.
REQUIRED_NATIVE_PATHS = frozenset({
    "_internal/python311.dll", "_internal/_ssl.pyd", "_internal/sqlite3.dll",
    "_internal/pyside6/qt6core.dll", "_internal/pyside6/qt6gui.dll",
    "_internal/pyside6/qt6widgets.dll", "_internal/pyside6/qt6pdf.dll",
    "_internal/pyside6/qt6pdfwidgets.dll", "_internal/pyside6/qt6printsupport.dll",
    "_internal/pyside6/qtpdf.pyd", "_internal/pyside6/qtpdfwidgets.pyd",
    "_internal/pyside6/qtprintsupport.pyd",
    "_internal/pyside6/plugins/platforms/qwindows.dll",
    "_internal/pyside6/plugins/imageformats/qjpeg.dll",
    "_internal/pyside6/plugins/imageformats/qico.dll",
    "_internal/pyside6/plugins/imageformats/qgif.dll",
})


def _contract_candidate(name: str) -> bool:
    return name.startswith(("api-", "ext-")) and name.endswith(".dll")


def _excluded_pe(path: Path, relative: str) -> None:
    from build_tools.windows_pe_dependencies import read_pe
    # Called only AFTER matching the fixed reviewed destination/hash. The narrow
    # parser warning exception still requires a zero-entrypoint forwarder-only PE.
    read_pe(path, path.parent, reviewed_system_forwarder=relative != "_internal/ucrtbase.dll")


def _link(path: Path) -> dict:
    return {"filename": path.name, "sha256": sha256(path)}


def _read_link(link: dict, expected: Path) -> dict:
    if (not isinstance(link, dict) or link.get("filename") != expected.name
            or expected.is_symlink() or link.get("sha256") != sha256(expected)):
        raise SystemRuntimeError("Staging receipt link is missing, relocated or changed")
    return json.loads(expected.read_text(encoding="utf-8"))


def _native_proof(rows: list[dict], identity: dict, input_path: Path, output: Path, *, env: dict | None = None) -> dict:
    payload = {"schema": 1, "source_commit": identity["source_commit"],
               "source_tree": identity["source_tree"], "files": rows,
               "package_environment_sha256": identity["package_environment"]["sha256"]}
    input_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # This process has not imported PySide or SDK libraries. Candidate binaries
    # are parsed only; WindowsSystemResolver loads bare OS names, system-only.
    subprocess.run([str(Path(sys.executable).resolve()), "-m",
                    "build_tools.windows_staging_dependencies", "--input", str(input_path.resolve()),
                    "--output", str(output.resolve())], cwd=ROOT, check=True, timeout=180,
                   env=env)
    return {"input": _link(input_path), "report": _link(output)}


def _validate_proof(proof: dict, rows: dict, identity: dict, input_path: Path, output: Path, *, reparse_sources: bool = False) -> dict:
    payload = _read_link(proof["input"], input_path)
    report = _read_link(proof["report"], output)
    if (payload.get("schema") != 1 or _staging_records(payload["files"]) != rows
            or report.get("schema") != 1 or report.get("status") != "passed"
            or report.get("input_sha256") != sha256(input_path)
            or report.get("package_environment_sha256") != identity["package_environment"]["sha256"]
            or payload.get("package_environment_sha256") != identity["package_environment"]["sha256"]
            or any(payload.get(key) != identity[key] or report.get(key) != identity[key]
                   for key in ("source_commit", "source_tree"))):
        raise SystemRuntimeError("Native proof does not bind complete staged inputs and source")
    inventory = report.get("inventory", [])
    inventory_rows = {}
    for row in inventory:
        key = _path_key(row["path"])
        if key in inventory_rows or row.get("machine") != "AMD64":
            raise SystemRuntimeError("Duplicate or non-x64 staged-native proof")
        inventory_rows[key] = row["sha256"]
    if inventory_rows != {key: row["sha256"] for key, row in rows.items()}:
        raise SystemRuntimeError("Native proof inventory differs from complete kept staging")
    if reparse_sources:
        from build_tools.windows_pe_dependencies import read_pe
        reparsed = []
        for key, row in rows.items():
            path = Path(row["source_path"])
            parsed = read_pe(path, path.parent)
            parsed["path"] = key
            reparsed.append(parsed)
        if reparsed != inventory:
            raise SystemRuntimeError("Native proof imports/exports differ from actual staged PEs")
    system = ntpath.normcase(ntpath.normpath(report.get("system_directory", "")))
    if not ntpath.isabs(system) or ntpath.basename(system) != "system32":
        raise SystemRuntimeError("Invalid recorded Windows system directory")
    winsxs = ntpath.join(ntpath.dirname(system), "winsxs")
    for item in report.get("os_resolutions", []):
        resolution = item["resolution"]
        for provider in [resolution["module_path"], *[s["provider"] for s in resolution["symbols"]]]:
            provider = ntpath.normcase(ntpath.normpath(provider))
            if (not ntpath.isabs(provider) or (ntpath.dirname(provider) != system
                    and not provider.startswith(winsxs + "\\"))):
                raise SystemRuntimeError("Recorded OS provider is outside Windows system roots")
    # Structural graph recomputation is followed by actual staged parsing here
    # and by full final-payload parsing/native resolution in artifact validation.
    from build_tools.windows_pe_dependencies import inspect_dependencies
    class RecordedResolver:
        def __init__(self):
            self.index = 0
        def resolve(self, dll, symbols):
            calls = report.get("os_resolutions", [])
            if self.index >= len(calls):
                raise SystemRuntimeError("Missing recorded OS DLL/symbol resolution")
            call = calls[self.index]
            self.index += 1
            resolution = call["resolution"]
            if (call["dll"].casefold() != dll.casefold() or call["requested_symbols"] != symbols
                    or resolution.get("kind") != "windows_system"
                    or [{"name": s["name"], "ordinal": s["ordinal"]} for s in resolution["symbols"]] != symbols):
                raise SystemRuntimeError("Recorded OS resolution call/symbols differ from actual graph")
            return resolution
    resolver = RecordedResolver()
    graph = inspect_dependencies(inventory, resolver)
    if resolver.index != len(report.get("os_resolutions", [])) or any(report.get(key) != value for key, value in graph.items()):
        raise SystemRuntimeError("Staged-native dependency graph is incomplete or changed")
    return report


def filter_system_runtime(
    binaries: list[tuple], datas: list[tuple], *,
    report_path: Path = STAGING_REPORT, manifest: dict | None = None,
) -> list[tuple]:
    """Remove exact reviewed present bytes; permit absent files only with OS proof."""
    report = {"schema": 2, "status": "failed",
              "supported_target": "Windows 10 1809+ / Windows 11 x64",
              "scope": "Bounded absent-file portability; present different hashes remain rejected",
              "excluded": [], "absent": [], "retained": [], "before": [], "after": []}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        excluded, retained = reviewed_policy(manifest)
        report.update(source_identity())
        from build_tools.windows_package_environment import package_receipt
        report["package_environment"] = package_receipt()
        if report["package_environment"]["filename"] != "package-environment.json":
            raise SystemRuntimeError("Package environment receipt must be beside staging")
        for destination, _source, _kind in datas:
            name = PurePosixPath(_path_key(destination)).name
            if PurePosixPath(name).suffix in {".dll", ".pyd", ".exe"}:
                raise SystemRuntimeError("Native/system/API DLL was collected as data")
        seen, result = set(), []
        for entry in binaries:
            destination, source, kind = entry
            relative = "_internal/" + _path_key(destination)
            if relative in seen:
                raise SystemRuntimeError(f"Duplicate binary destination: {destination}")
            seen.add(relative)
            path = Path(source)
            if not path.is_file() or path.is_symlink() or kind not in {"BINARY", "EXTENSION"}:
                raise SystemRuntimeError(f"Missing, symlinked or invalid binary source: {destination}")
            row = {"bundle_path": "_internal/" + destination.replace("\\", "/"),
                   "source_path": str(path.resolve()), "type": kind,
                   "sha256": sha256(path), "bytes": path.stat().st_size}
            report["before"].append(row)
            expected = excluded.get(relative) or retained.get(relative)
            if expected and (row["sha256"] != expected["sha256"] or kind != "BINARY"):
                raise SystemRuntimeError(f"Changed reviewed Windows runtime: {destination}")
            if relative in excluded:
                _excluded_pe(path, relative)
                row["pe_file_version"] = excluded[relative]["pe_file_version"]
                report["excluded"].append(row)
                continue
            name = PurePosixPath(relative).name
            if name in SYSTEM_DLLS or _contract_candidate(name):
                raise SystemRuntimeError(f"Unreviewed system/API DLL destination: {destination}")
            result.append(entry)
            report["after"].append(row)
            if relative in retained:
                report["retained"].append(row)
        if not set(retained).issubset(seen):
            raise SystemRuntimeError("Missing reviewed VC DLLs in build staging")
        if not REQUIRED_NATIVE_PATHS.issubset(seen):
            raise SystemRuntimeError("Missing required Python/Qt/core native staging input")
        report["absent"] = sorted(set(excluded) - seen)
        after = _staging_records(report["after"])
        native = {key: row for key, row in after.items()
                  if PurePosixPath(key).suffix in {".dll", ".pyd", ".exe"}}
        if len(native) != len(after):
            raise SystemRuntimeError("Staged binaries contain unexpected non-native destinations")
        report["native_proof"] = _native_proof(list(native.values()), report,
                    report_path.with_name("windows-staging-input.json"),
                    report_path.with_name("windows-staging-dependencies.json"))
        _validate_proof(report["native_proof"], native, report,
                    report_path.with_name("windows-staging-input.json"),
                    report_path.with_name("windows-staging-dependencies.json"), reparse_sources=True)
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


def validate_staging_report(
    bundle: Path, report_path: Path = STAGING_REPORT, *, proof_output: Path,
) -> dict:
    """Read immutable build inputs; place this host's proof in a fresh directory."""
    proof_output = proof_output.resolve()
    if proof_output.is_relative_to(report_path.parent.resolve()) or proof_output.exists():
        raise SystemRuntimeError("Final native proof requires a fresh directory outside build-staging inputs")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    excluded, retained = reviewed_policy()
    if report.get("schema") != 2 or report.get("status") != "passed":
        raise SystemRuntimeError("Build-staging runtime report is absent, failed or historical")
    if report.get("notice_manifest_sha256") != sha256(NOTICE_SOURCE / "manifest.json"):
        raise SystemRuntimeError("Build-staging notice manifest is stale")
    current = source_identity()
    if any(report.get(key) != current[key] for key in ("source_commit", "source_tree")):
        raise SystemRuntimeError("Build-staging source commit/tree is stale")
    environment = _read_link(report["package_environment"], report_path.parent / "package-environment.json")
    if environment.get("schema") != 1 or environment.get("status") != "passed":
        raise SystemRuntimeError("Package environment receipt is failed")
    removed = _staging_records(report["excluded"], reviewed=True)
    kept = _staging_records(report["retained"], reviewed=True)
    absent = report["absent"]
    if (not isinstance(absent, list) or any(not isinstance(p, str) for p in absent)
            or len(absent) != len(set(absent)) or any(p != _path_key(p) for p in absent)
            or set(removed) & set(absent) or set(removed) | set(absent) != set(excluded)):
        raise SystemRuntimeError("Removed/absent DLLs must exactly partition the 43-name policy")
    if (any(row["sha256"] != excluded[key]["sha256"] for key, row in removed.items())
            or {k: v["sha256"] for k, v in kept.items()} != {k: v["sha256"] for k, v in retained.items()}):
        raise SystemRuntimeError("Build-staging runtime identities differ from the policy")
    before = _staging_records(report["before"])
    after = _staging_records(report["after"])
    if any(row != before.get(key) or row.get("pe_file_version") != excluded[key]["pe_file_version"]
           for key, row in removed.items()):
        raise SystemRuntimeError("Excluded receipt rows differ from original build staging")
    if any(row != after.get(key) for key, row in kept.items()):
        raise SystemRuntimeError("Retained receipt rows differ from final build staging")
    if (set(before) - set(after) != set(removed) or set(after) - set(before)
            or set(absent) & (set(before) | set(after))
            or not REQUIRED_NATIVE_PATHS.issubset(after)):
        raise SystemRuntimeError("Build-staging before/after/absence inventories disagree")
    if any(PurePosixPath(key).name in SYSTEM_DLLS or _contract_candidate(PurePosixPath(key).name)
           for key in after):
        raise SystemRuntimeError("System/API DLL was kept in staging")
    staging_proof = _validate_proof(report["native_proof"], after, report,
                    report_path.with_name("windows-staging-input.json"),
                    report_path.with_name("windows-staging-dependencies.json"))
    actual_native = {_path_key(path.relative_to(bundle).as_posix())
                     for path in bundle.rglob("*") if path.is_file()
                     and path.suffix.casefold() in {".dll", ".pyd", ".exe"}} - {"taxopscontroldesk.exe"}
    if actual_native != set(after):
        raise SystemRuntimeError("Packaged native inventory differs from build staging")
    final_rows = []
    for relative, row in after.items():
        path = bundle / row["bundle_path"]
        if (row != before[relative] or path.is_symlink() or sha256(path) != row["sha256"]
                or path.stat().st_size != row["bytes"]):
            raise SystemRuntimeError(f"Packaged binary differs from staging: {relative}")
        final_rows.append({**row, "source_path": str(path.resolve())})
    from build_tools.windows_package_environment import prepare_environment
    proof_output.mkdir(parents=True, exist_ok=False)
    final_env_path = proof_output / "windows-final-package-environment.json"
    final_env, _ = prepare_environment(report_path=final_env_path)
    final_identity = {**report, "package_environment": _link(final_env_path)}
    final = _native_proof(final_rows, final_identity,
                proof_output / "windows-final-staging-input.json",
                proof_output / "windows-final-staging-dependencies.json", env=final_env)
    final_proof = _validate_proof(final, _staging_records(final_rows), final_identity,
                proof_output / "windows-final-staging-input.json",
                proof_output / "windows-final-staging-dependencies.json")
    if final_proof["inventory"] != staging_proof["inventory"]:
        raise SystemRuntimeError("Final native imports/exports differ from original staging proof")
    return {"build_staging_sha256": sha256(report_path),
            "build_source_commit": report["source_commit"], "build_source_tree": report["source_tree"],
            "package_environment_sha256": report["package_environment"]["sha256"],
            "staging_native_proof_sha256": report["native_proof"]["report"]["sha256"],
            "final_staging_native_proof_sha256": final["report"]["sha256"],
            "final_package_environment_sha256": sha256(final_env_path),
            "removed_system_dll_count": len(removed), "absent_system_dll_count": len(absent)}
