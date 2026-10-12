"""Verify the exact standalone EXE, embedded payload and bootloader lifecycle.

The inspection tree is a synthetic logical onedir view for existing A gates;
it is never shipped or executed. Normal GUI runs execute only the original EXE.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

from build_tools.dependency_licenses import sha256, validate_bundle_licenses
from build_tools.source_materials import source_identity
from build_tools.owned_process_cleanup import terminate_owned_tree
from build_tools.windows_loaded_modules import validate_loaded_modules, windows_system_roots
from build_tools.recombine_probe import verify_runtime_versions
from build_tools.verify_windows_bundle import (
    BundleVerificationError, _REQUIRED_FILES, isolated_environment,
    validate_report, verify_native_dependencies,
)


def inspect_payload(exe: Path, destination: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    if destination.exists():
        raise BundleVerificationError("Use a new payload inspection directory")
    destination.mkdir(parents=True)
    pyz_names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    if len(pyz_names) != 1:
        raise BundleVerificationError("Expected one embedded Python module archive")
    pyz = archive.open_embedded_archive(pyz_names[0])
    support = pyz.toc.get("PySide6.support")
    # PyInstaller 6.11.1 PYZ_ITEM_PKG is 1. The build uses exact pinned tooling.
    if support is None or support[0] != 1 or "PySide6.support.deprecated" not in pyz.toc:
        raise BundleVerificationError("Embedded PySide6.support must remain a package with its submodule")
    inventory = {}
    for name, entry in archive.toc.items():
        kind = entry[-1]
        normalized = name.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in normalized.split("/")) or ":" in normalized:
            raise BundleVerificationError("Unsafe embedded path")
        if kind in {"n", "d"}:
            raise BundleVerificationError("Standalone EXE must not depend on external archive entries or symlinks")
        if kind not in {"b", "x", "Z"}:
            continue
        key = relative.as_posix().casefold()
        if key in inventory:
            raise BundleVerificationError("Duplicate case-insensitive embedded destination")
        content = archive.extract(name)
        if len(content) != entry[2]:
            raise BundleVerificationError("Embedded payload size mismatch")
        target = destination / "_internal" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        inventory[key] = {"bytes": len(content), "sha256": sha256(target), "kind": kind}
    shutil.copyfile(exe, destination / "TaxOpsControlDesk.exe")
    embedded_notice = destination / "_internal/third_party_licenses/README.txt"
    shutil.copyfile(embedded_notice, destination / "THIRD_PARTY_NOTICES.txt")
    files = [p for p in destination.rglob("*") if p.is_file()]
    if not _REQUIRED_FILES.issubset({p.name.casefold() for p in files}):
        raise BundleVerificationError("Standalone EXE is missing required embedded runtime/assets")
    notices = validate_bundle_licenses(destination, files)
    return {"entries": inventory, **notices}


def read_report(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise BundleVerificationError(f"Frozen process did not pass: {path.name}")
    return report


def check_lifecycle_report(report: dict, *, temp: Path, database: Path,
                           expected_native: dict, primary: bool) -> Path:
    mei = Path(report.get("meipass", "")).resolve()
    if (mei.parent != temp.resolve() or not mei.name.startswith("_MEI")
            or report.get("frozen") is not True or report.get("platform") != "win32"
            or report.get("normal_exit") is not True or report.get("exit_code") != 0):
        raise BundleVerificationError("Invalid normal frozen lifecycle identity")
    if mei.exists():
        raise BundleVerificationError("Bootloader extraction directory survived normal process exit")
    if report.get("native_files") != expected_native:
        raise BundleVerificationError("Executed extraction bytes differ from the inspected EXE payload")
    if primary:
        if (report.get("bootstrap_calls") != 1 or report.get("guard_acquired") is not True
                or report.get("window_shown") is not True or report.get("migration_count") != 28
                or Path(report.get("db_path", "")).resolve() != database.resolve()
                or not database.is_file() or database.is_relative_to(mei)):
            raise BundleVerificationError("Primary GUI/database isolation contract failed")
    elif (report.get("bootstrap_calls") != 0 or report.get("guard_acquired") is not False
          or report.get("window_shown") is not False):
        raise BundleVerificationError("Duplicate instance opened the database or a second main window")
    return mei


def check_module_report(report: dict, *, inventory: dict, exe: Path, temp: Path, phase: str) -> dict:
    snapshot = report.get("loaded_modules", {})
    mei = Path(snapshot.get("meipass", "")).resolve()
    if mei.parent != temp.resolve() or not mei.name.startswith("_MEI"):
        raise BundleVerificationError("Actual loaded-module evidence is outside the owned extraction TEMP")
    if phase == "gui_ready" and str(mei) != report.get("meipass"):
        raise BundleVerificationError("GUI and loaded-module extraction identity differ")
    native = {key: row["sha256"] for key, row in inventory.items()
              if PurePosixPath(key).suffix in {".dll", ".pyd", ".exe"}}
    return validate_loaded_modules(snapshot, expected_native=native, meipass=str(mei),
                                   executable=str(exe.resolve()), executable_sha256=sha256(exe),
                                   os_roots=windows_system_roots(), phase=phase)


def wait_ready(process: subprocess.Popen, ready: Path, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while not ready.is_file():
        if process.poll() is not None:
            raise BundleVerificationError("Primary EXE exited before its real window was shown")
        if time.monotonic() >= deadline:
            raise BundleVerificationError("Timed out waiting for the normal GUI window")
        time.sleep(0.1)


def dismiss_owned_error_dialogs(pid: int) -> list[str]:
    """Close only windows owned by this gate's failed bootloader process."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    titles = []
    @callback_type
    def inspect(window, _parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(1024)
            user32.GetWindowTextW(window, title, len(title))
            titles.append(title.value)
            user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE on owned failed process only.
        return True
    user32.EnumWindows(inspect, 0)
    return titles


def verify_unusable_temp(exe: Path, output: Path, *, timeout: int) -> dict:
    profile = output / "unusable-temp-profile"
    env = isolated_environment(profile)
    blocked = profile / "temporary path is a file"
    blocked.write_text("synthetic blocker; no permissions are changed", encoding="utf-8")
    env["TEMP"] = env["TMP"] = str(blocked)
    process = subprocess.Popen([str(exe)], cwd=exe.parent, env=env)
    deadline, titles = time.monotonic() + timeout, []
    try:
        while process.poll() is None and time.monotonic() < deadline:
            titles.extend(dismiss_owned_error_dialogs(process.pid))
            time.sleep(0.1)
        if process.poll() is None:
            raise BundleVerificationError("Unusable TEMP did not produce a bounded bootloader failure")
        database = Path(env["LOCALAPPDATA"]) / "TaxOpsControlDesk/taxops.sqlite"
        if process.returncode == 0 or database.exists():
            raise BundleVerificationError("Unusable TEMP unexpectedly succeeded or opened the database")
        return {"unusable_temp_exit_code": process.returncode,
                "unusable_temp_no_database": True, "owned_bootloader_dialog_titles": titles}
    finally:
        if process.poll() is None:
            terminate_owned_tree(process, output / "forced-process-cleanup.json")


def verify_unusable_profile(exe: Path, output: Path, inventory: dict, *, timeout: int) -> dict:
    profile = output / "unusable-data-profile"
    env = isolated_environment(profile)
    token = uuid.uuid4().hex
    (profile / ".taxops-onefile-gate").write_text(token, encoding="ascii")
    blocked = Path(env["LOCALAPPDATA"]) / "TaxOpsControlDesk"
    content = b"synthetic path conflict; no disk permissions changed"
    blocked.write_bytes(content)
    expected_native = {key: row["sha256"] for key, row in inventory.items()
                       if PurePosixPath(key).suffix in {".dll", ".pyd", ".exe"}}
    record = output / "storage-recovery-client.json"
    instance = "TaxOpsControlDesk.StorageGate." + uuid.uuid4().hex
    def command(label):
        return [str(exe), "--onefile-probe", "--report", str(output / f"{label}.json"),
                "--ready", str(output / f"{label}-ready.json"), "--release", str(output / f"{label}-release"),
                "--instance-name", instance, "--profile-root", str(profile), "--profile-token", token,
                "--persistent-record", str(record), "--initialize-persistence"]
    process = subprocess.Popen(command("blocked-data"), cwd=exe.parent, env=env)
    try:
        if process.wait(timeout=timeout) != 1:
            raise BundleVerificationError("Blocked data path must produce an explicit failed startup")
        report = json.loads((output / "blocked-data.json").read_text(encoding="utf-8"))
        mei = Path(report.get("meipass", "")).resolve()
        if (report.get("normal_exit") is not True or report.get("bootstrap_calls") != 0
                or report.get("window_shown") is not False or report.get("native_files") != expected_native
                or not any(m.get("kind") == "critical" and m.get("title") == "無法開啟程式" and "資料夾" in m.get("text", "") for m in report.get("shown_messages", []))
                or blocked.read_bytes() != content or record.exists()
                or mei.parent != Path(env["TEMP"]).resolve() or mei.exists()):
            raise BundleVerificationError("Storage failure was silent, modified data, or failed normal extraction cleanup")
    finally:
        if process.poll() is None:
            terminate_owned_tree(process, output / "forced-process-cleanup.json")
    # Preserve the test-owned blocker under another name, then retry exactly
    # the same profile/name without changing permissions or deleting anything.
    blocked.rename(blocked.with_name("blocked-data-root-preserved.txt"))
    process = subprocess.Popen(command("after-storage-error"), cwd=exe.parent, env=env)
    try:
        wait_ready(process, output / "after-storage-error-ready.json", timeout)
        (output / "after-storage-error-release").write_text("Close normally\n", encoding="utf-8")
        if process.wait(timeout=timeout):
            raise BundleVerificationError("Same profile did not recover after the storage path was repaired")
        report = read_report(output / "after-storage-error.json")
        check_lifecycle_report(report, temp=Path(env["TEMP"]), database=blocked / "taxops.sqlite",
                               expected_native=expected_native, primary=True)
    finally:
        if process.poll() is None:
            terminate_owned_tree(process, output / "forced-process-cleanup.json")
    loaded = check_module_report(report, inventory=inventory, exe=exe, temp=Path(env["TEMP"]), phase="gui_ready")
    return {"storage_recovery_loaded_modules": loaded, "blocked_data_path_visible_chinese_error": True, "blocked_data_path_no_bootstrap": True,
            "same_profile_recovered_after_storage_error": True}


def verify_lifecycle(exe: Path, output: Path, inventory: dict, *, timeout: int) -> dict:
    profile = output / "隔離使用者 空白"
    env = isolated_environment(profile)
    profile_token = uuid.uuid4().hex
    (profile / ".taxops-onefile-gate").write_text(profile_token, encoding="ascii")
    persistent_record = output / "persistent-synthetic-client.json"
    temp = Path(env["TEMP"])
    expected_native = {key: row["sha256"] for key, row in inventory.items()
                       if PurePosixPath(key).suffix in {".dll", ".pyd", ".exe"}}
    database = Path(env["LOCALAPPDATA"]) / "TaxOpsControlDesk/taxops.sqlite"
    reports = []
    instance = "TaxOpsControlDesk.OnefileGate." + uuid.uuid4().hex
    def command(label, *extra):
        return [str(exe), "--onefile-probe", "--report", str(output / f"{label}.json"),
                "--ready", str(output / f"{label}-ready.json"), "--release", str(output / f"{label}-release"),
                "--instance-name", instance, "--profile-root", str(profile), "--profile-token", profile_token,
                "--persistent-record", str(persistent_record), *extra]
    for sequence in range(2):
        label = f"primary-{sequence}"
        extra = ["--initialize-persistence"] if sequence == 0 else []
        process = subprocess.Popen(command(label, *extra), cwd=exe.parent, env=env)
        try:
            wait_ready(process, output / f"{label}-ready.json", timeout)
            if sequence == 0:
                secondary = subprocess.run(command("secondary"), cwd=exe.parent, env=env, timeout=timeout, check=False)
                if secondary.returncode:
                    raise BundleVerificationError("Second EXE process failed")
                report = read_report(output / "secondary.json")
                check_lifecycle_report(report, temp=temp, database=database, expected_native=expected_native, primary=False)
                reports.append(report)
            (output / f"{label}-release").write_text("Close normally via QWidget.close()\n", encoding="utf-8")
            if process.wait(timeout=timeout):
                raise BundleVerificationError("Primary EXE returned an error")
            report = read_report(output / f"{label}.json")
            check_lifecycle_report(report, temp=temp, database=database, expected_native=expected_native, primary=True)
            if sequence == 0 and report.get("activation_count", 0) < 1:
                raise BundleVerificationError("Second launch did not activate the original window")
            reports.append(report)
        finally:
            if process.poll() is None:
                # Failure only: terminate this owned process, retain all leftovers
                # as evidence. This is not normal-cleanup acceptance.
                terminate_owned_tree(process, output / "forced-process-cleanup.json")
    # Start both warmed frozen children at the same acquire boundary. Waiting
    # for an already-ready primary would not exercise the lock creation race.
    barrier = output / "race-start"
    children = {}
    try:
        for label in ("race-a", "race-b"):
            children[label] = subprocess.Popen(command(label, "--start-barrier", str(barrier),
                                                        "--arrived", str(output / f"{label}-arrived")),
                                               cwd=exe.parent, env=env)
        deadline = time.monotonic() + timeout
        while not all((output / f"{label}-arrived").is_file() for label in children):
            if any(child.poll() is not None for child in children.values()) or time.monotonic() >= deadline:
                raise BundleVerificationError("Both simultaneous launches did not reach the real acquire barrier")
            time.sleep(0.05)
        barrier.write_text("Release both real acquisitions together\n", encoding="utf-8")
        winner = None
        while winner is None:
            ready = [label for label in children if (output / f"{label}-ready.json").is_file()]
            if len(ready) > 1:
                raise BundleVerificationError("Both simultaneous launches opened a main window")
            if ready:
                winner = ready[0]
            elif all(child.poll() is not None for child in children.values()) or time.monotonic() >= deadline:
                raise BundleVerificationError("Simultaneous launches produced no primary window")
            time.sleep(0.05)
        loser = next(label for label in children if label != winner)
        if children[loser].wait(timeout=timeout):
            raise BundleVerificationError("Simultaneous duplicate launch did not exit successfully")
        secondary_report = read_report(output / f"{loser}.json")
        check_lifecycle_report(secondary_report, temp=temp, database=database, expected_native=expected_native, primary=False)
        (output / f"{winner}-release").write_text("Close race winner normally\n", encoding="utf-8")
        if children[winner].wait(timeout=timeout):
            raise BundleVerificationError("Simultaneous primary launch failed")
        primary_report = read_report(output / f"{winner}.json")
        check_lifecycle_report(primary_report, temp=temp, database=database, expected_native=expected_native, primary=True)
        if primary_report.get("activation_count", 0) < 1:
            raise BundleVerificationError("Race loser did not activate the winning window")
        reports.extend([primary_report, secondary_report])
    finally:
        for child in children.values():
            if child.poll() is None:
                terminate_owned_tree(child, output / "forced-process-cleanup.json")

    # Crash only the owned, isolated Python child after a real window/DB open.
    # Do not infer or promise outer-bootloader force-kill cleanup from this test.
    crashed = subprocess.Popen(command("owned-crash", "--crash-after-ready"), cwd=exe.parent, env=env)
    try:
        if crashed.wait(timeout=timeout) != 77:
            raise BundleVerificationError("Owned crash probe did not exit with the requested code")
    finally:
        if crashed.poll() is None:
            terminate_owned_tree(crashed, output / "forced-process-cleanup.json")
    crash_report = json.loads((output / "owned-crash-ready.json").read_text(encoding="utf-8"))
    crash_mei = Path(crash_report["meipass"]).resolve()
    if (crash_mei.parent != temp.resolve() or not crash_mei.name.startswith("_MEI")
            or crash_report.get("bootstrap_calls") != 1 or crash_report.get("guard_acquired") is not True
            or crash_report.get("window_shown") is not True
            or Path(crash_report.get("db_path", "")).resolve() != database.resolve()
            or crash_report.get("native_files") != expected_native):
        raise BundleVerificationError("Owned crash did not exercise the expected real application")
    recovered = subprocess.Popen(command("after-crash"), cwd=exe.parent, env=env)
    try:
        wait_ready(recovered, output / "after-crash-ready.json", timeout)
        (output / "after-crash-release").write_text("Close recovered app normally\n", encoding="utf-8")
        if recovered.wait(timeout=timeout):
            raise BundleVerificationError("A fresh normal launch could not recover after the owned crash")
        report = read_report(output / "after-crash.json")
        check_lifecycle_report(report, temp=temp, database=database, expected_native=expected_native, primary=True)
        reports.append(report)
    finally:
        if recovered.poll() is None:
            terminate_owned_tree(recovered, output / "forced-process-cleanup.json")
    leftovers = {p.resolve() for p in temp.glob("_MEI*")}
    if leftovers - {crash_mei}:
        raise BundleVerificationError("Unaccounted extraction directory remains in the dedicated test TEMP")
    loaded = [check_module_report(report, inventory=inventory, exe=exe, temp=temp, phase="gui_ready")
              for report in reports + [crash_report] if report.get("window_shown")]
    expected_client = json.loads(persistent_record.read_text(encoding="utf-8"))
    for report in reports + [crash_report]:
        if report.get("window_shown") and report.get("persistent_client") != expected_client:
            raise BundleVerificationError("Synthetic business record changed across real normal launches")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT id, client_code, client_name FROM clients WHERE id=?", (expected_client["id"],)).fetchone()
    if row != (expected_client["id"], expected_client["client_code"], expected_client["client_name"]):
        raise BundleVerificationError("Synthetic business record was lost after the last normal exit")
    paths = [r["meipass"] for r in reports] + [str(crash_mei)]
    if len(paths) != len(set(paths)):
        raise BundleVerificationError("Distinct process evidence reused an extraction path")
    return {"lifecycle_loaded_modules": loaded, "normal_gui_launches": 4, "duplicate_launches": 2,
            "simultaneous_start_one_winner": True, "owned_child_crash_exit_code": 77,
            "normal_start_after_crash": True, "recorded_crash_extraction_remaining": crash_mei.exists(),
            "persistent_client_id": expected_client["id"], "persistent_business_record_verified": True,
            "normal_bootloader_cleanup_verified": True, "database": str(database),
            "extraction_paths": paths, "forced_termination_cleanup_claimed": False}


def check_source_matrix(path: Path) -> dict:
    from build_tools.run_test_matrix import ROOT, coverage_meets_gate
    report = json.loads(path.read_text(encoding="utf-8"))
    names = {"tests/" + p.name for p in (ROOT / "tests").glob("test_*.py")}
    results = report.get("files", [])
    if (report.get("source_identity") != source_identity(ROOT) or report.get("source_unchanged") is not True
            or report.get("status") != "passed" or report.get("full_suite") is not True
            or report.get("unrun_files") != []
            or len(results) != len(names) or {r.get("file") for r in results} != names
            or any(r.get("status") != "passed" or r.get("exit_code") != 0 or r.get("skipped") != 0 for r in results)
            or any(report.get("totals", {}).get(key) != 0 for key in ("failures", "errors", "skipped"))
            or not coverage_meets_gate({"meta": {"branch_coverage": report.get("branch_coverage")},
                                       "totals": {"percent_covered": report.get("raw_percent_covered")}})):
        raise BundleVerificationError("Complete source matrix, zero skips and raw 90% branch coverage are required")
    return {"source_matrix_sha256": sha256(path), "source_test_count": report["totals"]["tests"],
            "source_file_count": len(results), "raw_branch_coverage": report["raw_percent_covered"]}


def verify(exe: Path, output: Path, *, timeout: int = 180, recombined: bool = False, source_matrix: Path | None = None) -> dict:
    if sys.platform != "win32":
        raise BundleVerificationError("Onefile acceptance requires Windows")
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": 1, "status": "failed", "single_file": True,
              "clean_os_verified": False, "manual_gui_verified": False,
              "source_exe_sha256": sha256(exe), "recombined": recombined}
    try:
        result.update(check_source_matrix(source_matrix or Path("artifacts/source-tests/matrix.json")))
        relocated = output / "只有一個程式 中文 空白"
        relocated.mkdir()
        actual = relocated / "TaxOpsControlDesk.exe"
        shutil.copyfile(exe, actual)
        inspected = output / "payload-inspection"
        payload = inspect_payload(actual, inspected)
        result.update({k: v for k, v in payload.items() if k != "entries"})
        result.update(verify_native_dependencies(inspected, output))
        (output / "embedded-inventory.json").write_text(json.dumps(payload["entries"], indent=2) + "\n", encoding="utf-8")
        result.update(verify_unusable_temp(actual, output, timeout=timeout))
        result.update(verify_unusable_profile(actual, output, payload["entries"], timeout=timeout))
        result.update(verify_lifecycle(actual, output, payload["entries"], timeout=timeout))
        result["normal_temp_retry_after_failure"] = True
        environment = isolated_environment(output / "selftest-profile")
        report = output / "frozen-self-test.json"
        process = subprocess.run([str(actual), "--self-test", "--require-frozen", "--report", str(report)],
                                 cwd=actual.parent, env=environment, timeout=timeout, check=False)
        if process.returncode:
            raise BundleVerificationError("Full frozen self-test failed")
        frozen_report = read_report(report)
        validate_report(frozen_report)
        result["selftest_loaded_modules"] = check_module_report(
            frozen_report, inventory=payload["entries"], exe=actual,
            temp=Path(environment["TEMP"]), phase="after_18_checks")
        if recombined:
            report = output / "frozen-recombine.json"
            process = subprocess.run([str(actual), "--recombine-probe", "--require-frozen", "--require-support", "--report", str(report)],
                                     cwd=actual.parent, env=environment, timeout=timeout, check=False)
            if process.returncode:
                raise BundleVerificationError("Real LGPL recombination probe failed")
            recombined_report = read_report(report)
            verify_runtime_versions(recombined_report.get("pyside_runtime_version"), recombined_report.get("qt_runtime_version"))
        if list(Path(environment["TEMP"]).glob("_MEI*")):
            raise BundleVerificationError("Self-test extraction survived a normal exit")
        if [p.name for p in actual.parent.iterdir()] != ["TaxOpsControlDesk.exe"]:
            raise BundleVerificationError("Normal use unexpectedly required/wrote sidecar files")
        result["status"] = "passed"
        # Keep the user artifact exactly one file; evidence stays separately.
        shutil.copyfile(actual, output / "TaxOpsControlDesk.exe")
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        (output / "onefile-provenance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path("dist/TaxOpsControlDesk.exe"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/windows-onefile"))
    parser.add_argument("--recombined", action="store_true")
    parser.add_argument("--source-matrix", type=Path, default=Path("artifacts/source-tests/matrix.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.exe.resolve(), args.output.resolve(), recombined=args.recombined, source_matrix=args.source_matrix.resolve()), indent=2))
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
