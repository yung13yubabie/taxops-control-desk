"""Stage exact Microsoft VC redistributables without changing installed wheels."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from build_tools.dependency_licenses import ROOT, NOTICE_SOURCE, sha256, validate_notice_tree

SOURCE = ROOT / "build_tools/vc_redist_source.json"
RECEIPT = ROOT / "artifacts/build-staging/official-vc.json"


class SignatureValidationError(RuntimeError):
    """A failed trust check with lossless process diagnostics, never a pass."""

    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


def _process_diagnostics(command: list[str], returncode: int | None, stdout: bytes | None,
                         stderr: bytes | None, *, timed_out: bool = False) -> dict:
    report = {"command": command, "returncode": returncode, "timed_out": timed_out,
              "display_encoding": "utf-8 with replacement; base64 fields retain exact process bytes"}
    for name, content in (("stdout", stdout), ("stderr", stderr)):
        content = content or b""
        report[name] = content.decode("utf-8", errors="replace")
        report[name + "_base64"] = base64.b64encode(content).decode("ascii")
    return report


def _error_record(exc: Exception) -> dict:
    record = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, SignatureValidationError):
        record["process"] = exc.diagnostics
    return record


def microsoft_signature(path: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Microsoft Authenticode validation requires Windows")
    script = ROOT / "build_tools/verify_microsoft_signature.ps1"
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
               str(script), "-LiteralPath", str(path.resolve())]
    try:
        result = subprocess.run(command, check=False, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise SignatureValidationError("Microsoft Authenticode process timed out",
            _process_diagnostics(command, None, exc.stdout, exc.stderr, timed_out=True)) from exc
    except OSError as exc:
        raise SignatureValidationError("Microsoft Authenticode process could not start: " + str(exc),
            _process_diagnostics(command, None, None, None)) from exc
    diagnostics = _process_diagnostics(command, result.returncode, result.stdout, result.stderr)
    if result.returncode != 0:
        raise SignatureValidationError(f"Microsoft Authenticode process exited {result.returncode}", diagnostics)
    try:
        signature = json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise SignatureValidationError("Microsoft Authenticode returned invalid UTF-8 JSON", diagnostics) from exc
    if (not isinstance(signature, dict) or signature.get("status") != "Valid"
            or not isinstance(signature.get("subject"), str)
            or not re.search(r"(?:^|,\s*)O=Microsoft Corporation(?:,|$)", signature["subject"])
            or not signature.get("thumbprint")):
        raise SignatureValidationError("Redistributable lacks valid Microsoft Authenticode trust", diagnostics)
    return {**signature, "process": diagnostics}


def stage_archive(archive: Path, destination: Path) -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = source["package"]["payloads"][0]
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": 1, "status": "failed", "package_sha256": payload["sha256"],
               "package_url": payload["url"], "expected_package_bytes": source["observed_package_bytes"], "files": [],
               "catalog_verification_note": source["catalog_verification_note"]}
    try:
        receipt["observed_archive_sha256"] = sha256(archive)
        receipt["observed_archive_bytes"] = archive.stat().st_size
        if receipt["observed_archive_sha256"] != payload["sha256"]:
            raise ValueError("Microsoft VSIX SHA-256 mismatch")
        if receipt["observed_archive_bytes"] != source["observed_package_bytes"]:
            raise ValueError("Microsoft VSIX measured size mismatch")
        with zipfile.ZipFile(archive) as zipped:
            for item in source["files"]:
                receipt["active_member"] = item["source_member"]
                member = zipped.getinfo(item["source_member"])
                if member.file_size != item["bytes"]:
                    raise ValueError("Redistributable member size mismatch")
                content = zipped.read(member)
                path = destination / item["name"]
                path.write_bytes(content)
                if sha256(path) != item["sha256"]:
                    raise ValueError("Redistributable member SHA-256 mismatch")
                row = {**item, "staged_path": str(path.resolve()), "authenticode": {"status": "failed"}}
                receipt["files"].append(row)
                row["authenticode"] = microsoft_signature(path)
        receipt["status"] = "passed"
        return receipt
    except Exception as exc:
        receipt["error"] = _error_record(exc)
        raise
    finally:
        (destination / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def _failed_stage_receipt(root: Path | None, receipt: dict, exc: Exception) -> dict:
    local = root / "receipt.json" if root is not None else None
    if local is not None and local.is_file():
        receipt = json.loads(local.read_text(encoding="utf-8"))
    return {**receipt, "status": "failed", "error": _error_record(exc)}


def _write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def stage_analysis(binaries: list[tuple], *, archive: Path | None = None) -> list[tuple]:
    """Replace exactly eight known wheel locations, retaining ten total VC DLLs."""
    receipt = {"schema": 1, "status": "failed"}
    _write_receipt(RECEIPT, receipt)
    root = None
    try:
        selected = archive or Path(os.environ.get("TAXOPS_VC_REDIST_VSIX", ""))
        if not selected.is_file():
            raise ValueError("Set TAXOPS_VC_REDIST_VSIX to the fixed official Microsoft VSIX")
        root = Path(tempfile.mkdtemp(prefix="taxops-official-vc-")) / "members"
        receipt = stage_archive(selected, root)
        # Signature success is not destination-mapping success.
        receipt["status"] = "failed"
        manifest = validate_notice_tree(NOTICE_SOURCE)
        replacements = {r["bundle_path"].removeprefix("_internal/").casefold(): r
                        for r in manifest["reviewed_microsoft_binaries"] if "prior_wheel_sha256" in r}
        if len(replacements) != 8:
            raise ValueError("Expected exactly eight reviewed Qt/Shiboken VC destinations")
        result, mapped = [], []
        for destination, original, kind in binaries:
            key = destination.replace("\\", "/").casefold()
            row = replacements.get(key)
            if row is None:
                result.append((destination, original, kind))
                continue
            if (key in mapped or kind != "BINARY" or Path(original).is_symlink()
                    or sha256(Path(original)) != row["prior_wheel_sha256"]):
                raise ValueError("Original wheel VC input changed or was duplicated")
            replacement = root / PurePosixPath(key).name
            if sha256(replacement) != row["sha256"]:
                raise ValueError("Official staged VC identity differs from reviewed manifest")
            result.append((destination, str(replacement.resolve()), kind))
            mapped.append(key)
        if set(mapped) != set(replacements):
            raise ValueError("Missing expected Qt/Shiboken VC destination")
        receipt.update(status="passed", destinations=sorted(mapped))
        return result
    except Exception as exc:
        receipt = _failed_stage_receipt(root, receipt, exc)
        raise
    finally:
        # Only JSON crosses into the uploaded artifact tree. Raw VSIX/members
        # stay in their original source location and the dedicated TEMP tree.
        _write_receipt(RECEIPT, receipt)


def signature_diagnostic(archive: Path, receipt_path: Path) -> int:
    """Run the identical hash/size/Authenticode stage without building an EXE."""
    receipt = {"schema": 1, "status": "failed", "scope": "signature-only diagnostic; not application acceptance"}
    root = Path(tempfile.mkdtemp(prefix="taxops-official-vc-")) / "members"
    code = 1
    try:
        receipt.update(stage_archive(archive, root))
        code = 0
    except Exception as exc:
        receipt = _failed_stage_receipt(root, receipt, exc)
    finally:
        receipt["scope"] = "signature-only diagnostic; not application acceptance"
        _write_receipt(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostic-only invocation of the unchanged Microsoft trust gate")
    parser.add_argument("--signature-only", action="store_true", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    return signature_diagnostic(args.archive, args.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
