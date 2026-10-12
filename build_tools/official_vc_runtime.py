"""Stage exact Microsoft VC redistributables without changing installed wheels."""
from __future__ import annotations

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


def microsoft_signature(path: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Microsoft Authenticode validation requires Windows")
    script = ROOT / "build_tools/verify_microsoft_signature.ps1"
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
         str(script), "-LiteralPath", str(path.resolve())],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    signature = json.loads(result.stdout.lstrip("\ufeff"))
    if (signature.get("status") != "Valid"
            or not re.search(r"(?:^|,\s*)O=Microsoft Corporation(?:,|$)", signature.get("subject", ""))
            or not signature.get("thumbprint")):
        raise RuntimeError("Redistributable lacks valid Microsoft Authenticode trust")
    return signature


def stage_archive(archive: Path, destination: Path) -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = source["package"]["payloads"][0]
    if sha256(archive) != payload["sha256"]:
        raise ValueError("Microsoft VSIX SHA-256 mismatch")
    if archive.stat().st_size != source["observed_package_bytes"]:
        raise ValueError("Microsoft VSIX measured size mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": 1, "status": "failed", "package_sha256": payload["sha256"],
               "package_url": payload["url"], "files": [],
               "catalog_verification_note": source["catalog_verification_note"]}
    try:
        with zipfile.ZipFile(archive) as zipped:
            for item in source["files"]:
                member = zipped.getinfo(item["source_member"])
                if member.file_size != item["bytes"]:
                    raise ValueError("Redistributable member size mismatch")
                content = zipped.read(member)
                path = destination / item["name"]
                path.write_bytes(content)
                if sha256(path) != item["sha256"]:
                    raise ValueError("Redistributable member SHA-256 mismatch")
                receipt["files"].append({**item, "staged_path": str(path.resolve()),
                                         "authenticode": microsoft_signature(path)})
        receipt["status"] = "passed"
        return receipt
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        (destination / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def stage_analysis(binaries: list[tuple], *, archive: Path | None = None) -> list[tuple]:
    """Replace exactly eight known wheel locations, retaining ten total VC DLLs."""
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text('{"schema":1,"status":"failed"}\n', encoding="utf-8")
    selected = archive or Path(os.environ.get("TAXOPS_VC_REDIST_VSIX", ""))
    if not selected.is_file():
        raise ValueError("Set TAXOPS_VC_REDIST_VSIX to the fixed official Microsoft VSIX")
    root = Path(tempfile.mkdtemp(prefix="taxops-official-vc-")) / "members"
    receipt = stage_archive(selected, root)
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
    receipt["destinations"] = sorted(mapped)
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return result
