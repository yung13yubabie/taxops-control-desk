"""Verify the exact zipped Windows bundle by running its extracted EXE.

This gate needs Windows. It is not clean-machine or manually tested UI evidence.
Uses pinned pefile for static imports; application checks run inside the EXE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from build_tools.dependency_licenses import NOTICE_SOURCE, LicenseAssetError, validate_bundle_licenses
from build_tools.windows_system_runtime import validate_system_runtime_bundle, validate_staging_report
from build_tools.windows_pe_dependencies import verify_pe_dependencies

EXPECTED_CHECKS = frozenset({
    "offline_third_party_notices_view_and_export",
    "qt_traditional_chinese_widgets_and_fallback",
    "qt_application_and_icon", "image_codecs", "qt_pdf_and_pdf_widgets", "ssl_runtime",
    "all_migrations", "main_window_construct_show_close", "client_case_document_task_and_fts",
    "attachment_upload_accept_readback", "workflow_and_canvas_assets", "xlsx_roundtrip",
    "full_backup", "full_restore_reopen_assets_fts_and_audit", "temporary_data_cleanup",
    "client_addresses_lease_and_lease_attachment",
    "annual_profile_generation_linked_task_and_transactions", "client_lease_and_annual_full_restore",
})
_REQUIRED_FILES = frozenset({
    "taxopscontroldesk.exe", "python311.dll", "_ssl.pyd", "sqlite3.dll",
    "qwindows.dll", "qjpeg.dll", "qico.dll", "qtpdf.pyd", "qtpdfwidgets.pyd", "app_icon.ico",
    "qtbase_zh_tw.qm", "qt6core.dll", "qt6gui.dll", "qt6widgets.dll",
    "qt6pdf.dll", "qt6pdfwidgets.dll", "qt6printsupport.dll", "qtprintsupport.pyd",
})
_FORBIDDEN_DIRS = frozenset({".git", ".ai", "tests", "__pycache__", "attachments", "taxopsbackups"})


class BundleVerificationError(RuntimeError):
    pass


def archive_bundle(bundle: Path, archive: Path) -> dict:
    """Fail on unexpected developer/user files, then fully read back the ZIP."""
    entries = sorted(bundle.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise BundleVerificationError("Symlinks are not permitted in a release bundle")
    files = [p for p in entries if p.is_file()]
    names = {p.name.lower() for p in files}
    missing = _REQUIRED_FILES - names
    if missing:
        raise BundleVerificationError(f"Required Windows files missing: {sorted(missing)}")
    if not (bundle / "TaxOpsControlDesk.exe").is_file():
        raise BundleVerificationError("Executable must be at the bundle root")
    for path in files:
        relative = path.relative_to(bundle)
        if path.is_symlink() or _FORBIDDEN_DIRS.intersection(p.lower() for p in relative.parts):
            raise BundleVerificationError(f"Unexpected directory or symlink in bundle: {relative}")
        if path.suffix.lower() in {".sqlite", ".py", ".pyc", ".pyo"} or path.name.lower().endswith((".sqlite-wal", ".sqlite-shm", ".taxops.zip")):
            raise BundleVerificationError(f"Unexpected source or user data in bundle: {relative}")
    try:
        license_metadata = validate_bundle_licenses(bundle, files)
    except (LicenseAssetError, OSError, ValueError, KeyError) as exc:
        raise BundleVerificationError(f"Third-party license gate: {exc}") from exc
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in files:
            zipped.write(path, Path("TaxOpsControlDesk") / path.relative_to(bundle))
    with zipfile.ZipFile(archive) as zipped:
        bad = zipped.testzip()
        if bad:
            raise BundleVerificationError(f"ZIP readback failed: {bad}")
    return {"file_count": len(files), "bytes": archive.stat().st_size,
            "sha256": _sha256(archive), **license_metadata}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_report(report: dict) -> None:
    if report.get("schema") != 1 or report.get("status") != "passed":
        raise BundleVerificationError("Frozen self-test did not report success")
    if report.get("frozen") is not True or report.get("platform") != "win32":
        raise BundleVerificationError("Report is not from a frozen Windows executable")
    if report.get("qt_platform") != "windows":
        raise BundleVerificationError("Self-test did not load the native Windows Qt platform")
    if report.get("network_attempts") != []:
        raise BundleVerificationError("Self-test recorded a network attempt")
    checks = report.get("checks", [])
    passed = {c.get("name") for c in checks if c.get("status") == "passed"}
    if not EXPECTED_CHECKS.issubset(passed) or any(c.get("status") != "passed" for c in checks):
        raise BundleVerificationError("Required artifact checks are absent, failed, or skipped")
    language = next(c for c in checks if c.get("name") == "qt_traditional_chinese_widgets_and_fallback")
    if (language.get("catalogue_loaded") is not True or language.get("initial_locale") != "en_US"
            or language.get("locale") != "zh_TW"
            or language.get("missing_catalogue", {}).get("fully_localized") is not False):
        raise BundleVerificationError("Complete Qt translation and partial fallback evidence required")
    notices = next(c for c in checks if c.get("name") == "offline_third_party_notices_view_and_export")
    manifest = (NOTICE_SOURCE / "manifest.json").read_bytes()
    export_hash = notices.get("export_sha256")
    if (notices.get("entry") != "settings"
            or notices.get("displayed_text_verified") is not True
            or notices.get("export_bytes_verified") is not True
            or type(notices.get("file_count")) is not int
            or notices["file_count"] != len(json.loads(manifest)["files"]) + 1
            or notices.get("manifest_sha256") != hashlib.sha256(manifest).hexdigest()
            or not isinstance(export_hash, str) or len(export_hash) != 64
            or any(c not in "0123456789abcdef" for c in export_hash)):
        raise BundleVerificationError("Complete offline notice viewing/export evidence required")
    if report.get("clean_os_verified") is not False or report.get("manual_gui_verified") is not False:
        raise BundleVerificationError("Automated report overstates clean-OS/manual acceptance")


def isolated_environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                 "QML2_IMPORT_PATH", "QT_QPA_PLATFORM", "TAXOPS_DEV"):
        env.pop(name, None)
    for key, directory in {"LOCALAPPDATA": "local", "APPDATA": "roaming",
                           "USERPROFILE": "user", "HOME": "user", "TEMP": "temp", "TMP": "temp"}.items():
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    return env


def verify_native_dependencies(bundle: Path, output: Path) -> dict:
    """Check the extracted ZIP against staging and this host's OS providers."""
    files = [p for p in bundle.rglob("*") if p.is_file()]
    return {**validate_system_runtime_bundle(bundle, files), **validate_staging_report(bundle),
            **verify_pe_dependencies(bundle, output / "pe-dependencies.json")}


def verify_bundle(bundle: Path, output: Path, *, timeout: int = 120) -> dict:
    if sys.platform != "win32":
        raise BundleVerificationError("Windows bundle execution must be verified on Windows")
    output.mkdir(parents=True, exist_ok=True)
    candidate = output / "TaxOpsControlDesk-windows-candidate.zip"
    pending = output / (candidate.name + ".pending")
    if candidate.exists() or pending.exists():
        raise BundleVerificationError("Use a fresh output directory; candidate ZIP already exists")
    provenance = {"status": "failed", "runner_os": platform.platform(),
                  "host_python": platform.python_version(), "architecture": platform.machine(),
                  "source_commit": os.environ.get("GITHUB_SHA", "not_recorded"),
                  "clean_os_verified": False, "manual_gui_verified": False,
                  "signing": "not performed by this build pipeline"}
    try:
        with tempfile.TemporaryDirectory(prefix="taxops_bundle_gate_") as temporary:
            root = Path(temporary)
            archive = root / candidate.name
            provenance.update(archive_bundle(bundle.resolve(), archive))
            extract = root / "移動後的程式 資料夾"
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(extract)
            exe = extract / "TaxOpsControlDesk" / "TaxOpsControlDesk.exe"
            provenance.update(verify_native_dependencies(exe.parent, output))
            report_path = root / "self-test.json"
            env = isolated_environment(root / "isolated_profile")
            process = subprocess.run(
                [str(exe), "--self-test", "--require-frozen", "--report", str(report_path)],
                cwd=str(root), env=env, timeout=timeout, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
            (output / "frozen-process.log").write_text(
                f"exit_code={process.returncode}\n{process.stdout}\n{process.stderr}", encoding="utf-8")
            if not report_path.is_file():
                raise BundleVerificationError("EXE produced no self-test report")
            shutil.copyfile(report_path, output / "frozen-self-test.json")
            if process.returncode:
                raise BundleVerificationError(f"EXE self-test failed with exit {process.returncode}")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            validate_report(report)
            provenance["app_version"] = report["app_version"]
            # Publish locally only after this very archive was extracted/tested.
            with pending.open("xb") as target, archive.open("rb") as source:
                shutil.copyfileobj(source, target)
        pending.rename(candidate)
        (output / (candidate.name + ".sha256")).write_text(
            f"{provenance['sha256']}  {candidate.name}\n", encoding="ascii")
        provenance["status"] = "passed"
    except Exception as exc:
        provenance["error"] = {"type": type(exc).__name__, "message": str(exc)}
        pending.unlink(missing_ok=True)
        raise
    finally:
        (output / "bundle-provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("dist/TaxOpsControlDesk"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/windows-candidate"))
    args = parser.parse_args()
    try:
        result = verify_bundle(args.bundle, args.output)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
