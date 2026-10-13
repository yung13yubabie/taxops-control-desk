"""Validate complete, version-matched inputs before executing an existing EXE.

Build receipts are assertions, not a replacement for checking payload bytes or
Windows trust. Signature commands stored in a receipt are never executed.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath

from build_tools.dependency_licenses import NOTICE_SOURCE, sha256, validate_notice_tree
from build_tools.official_vc_runtime import SOURCE, microsoft_signature

STAGING_INPUT_FILES = {
    "system_runtime_receipt": "windows-system-runtime.json",
    "official_vc_receipt": "official-vc.json",
    "package_environment_receipt": "package-environment.json",
    "staging_inventory_receipt": "windows-staging-input.json",
    "staging_dependencies_receipt": "windows-staging-dependencies.json",
}


class AcceptanceInputError(RuntimeError):
    """The supplied acceptance materials are incomplete or inconsistent."""


def preflight_files(exe: Path, matrix: Path, staging: Path) -> dict:
    paths = {
        "exe": exe,
        "source_matrix": matrix,
        **{key: staging / name for key, name in STAGING_INPUT_FILES.items()},
    }
    invalid, records = [], {}
    for name, path in paths.items():
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("missing, not a regular file, or symbolic link")
            records[name] = {"path": str(path.resolve()), "sha256": sha256(path),
                             "bytes": path.stat().st_size}
            if records[name]["bytes"] == 0:
                raise OSError("empty file")
        except OSError as exc:
            invalid.append(f"{name}: {path} ({exc})")
    if invalid:
        raise AcceptanceInputError(
            "驗收材料缺少或無法讀取，尚未啟動 EXE：\n- " + "\n- ".join(invalid)
            + "\n請從同一份建置產物取得 EXE、source-tests/matrix.json，及 "
              "完整 build-staging 目錄（" + ", ".join(STAGING_INPUT_FILES.values()) + "）。"
              "以 --source-matrix 指定矩陣，--build-staging 指定五份收據所在目錄；"
              "使用相符的乾淨原始碼版本，不要混用其他建置的收據。"
        )
    return records


def assert_inputs_unchanged(records: dict) -> None:
    for name, row in records.items():
        path = Path(row["path"])
        if (path.is_symlink() or not path.is_file()
                or path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]):
            raise AcceptanceInputError(f"Acceptance input changed during verification: {name}")


def _signature_record(signature: object) -> None:
    if not isinstance(signature, dict):
        raise AcceptanceInputError("Official VC receipt has no signature evidence")
    process = signature.get("process", {})
    if (signature.get("status") != "Valid"
            or not isinstance(signature.get("subject"), str)
            or not re.search(r"(?:^|,\s*)O=Microsoft Corporation(?:,|$)", signature["subject"])
            or not isinstance(signature.get("thumbprint"), str)
            or not signature["thumbprint"].strip()
            or not isinstance(process, dict)
            or type(process.get("returncode")) is not int
            or process["returncode"] != 0 or process.get("timed_out") is not False):
        raise AcceptanceInputError("Official VC receipt lacks successful Microsoft trust evidence")
    try:
        raw = base64.b64decode(process["stdout_base64"], validate=True)
        observed = json.loads(raw.decode("utf-8-sig"))
        stderr = base64.b64decode(process["stderr_base64"], validate=True)
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise AcceptanceInputError("Official VC signature process evidence is malformed") from exc
    if (observed != {key: value for key, value in signature.items() if key != "process"}
            or process.get("stdout") != raw.decode("utf-8", errors="replace")
            or process.get("stderr") != stderr.decode("utf-8", errors="replace")):
        raise AcceptanceInputError("Official VC signature record differs from captured process output")


def validate_official_receipt(bundle: Path, receipt_path: Path) -> dict:
    """Bind the old receipt to pinned bytes and recheck those bytes on this host."""
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    manifest = validate_notice_tree(NOTICE_SOURCE)
    receipt_hash = sha256(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    package = source["package"]["payloads"][0]
    if (not isinstance(receipt, dict) or type(receipt.get("schema")) is not int or receipt["schema"] != 1
            or receipt.get("status") != "passed"
            or receipt.get("package_sha256") != package["sha256"]
            or receipt.get("observed_archive_sha256") != package["sha256"]
            or receipt.get("package_url") != package["url"]
            or receipt.get("expected_package_bytes") != source["observed_package_bytes"]
            or receipt.get("observed_archive_bytes") != source["observed_package_bytes"]):
        raise AcceptanceInputError("Official VC receipt differs from the pinned archive identity")
    expected = {row["name"]: row for row in source["files"]}
    rows = receipt.get("files")
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(row, dict) for row in rows)
            or {row.get("name") for row in rows} != set(expected)):
        raise AcceptanceInputError("Official VC receipt must contain exactly the five pinned members")
    for row in rows:
        if any(row.get(key) != value for key, value in expected[row["name"]].items()):
            raise AcceptanceInputError("Official VC member metadata or hash differs from the pin")
        _signature_record(row.get("authenticode"))
    destinations = {row["bundle_path"].removeprefix("_internal/").casefold(): row
                    for row in manifest["reviewed_microsoft_binaries"]
                    if "prior_wheel_sha256" in row}
    mapped = receipt.get("destinations")
    if (len(destinations) != 8 or not isinstance(mapped, list)
            or len(mapped) != 8 or any(not isinstance(item, str) for item in mapped)
            or set(mapped) != set(destinations)):
        raise AcceptanceInputError("Official VC receipt must map exactly eight unique reviewed destinations")
    verified = {}
    for destination, row in destinations.items():
        name = PurePosixPath(destination).name
        member = expected.get(name)
        path = bundle / row["bundle_path"]
        if (member is None or row["sha256"] != member["sha256"]
                or path.is_symlink() or not path.is_file()
                or path.stat().st_size != member["bytes"]
                or sha256(path) != member["sha256"]):
            raise AcceptanceInputError(f"Extracted official VC payload differs: {destination}")
        if name not in verified:
            signature = microsoft_signature(path)
            _signature_record(signature)
            if sha256(path) != member["sha256"] or path.stat().st_size != member["bytes"]:
                raise AcceptanceInputError("Official VC payload changed during signature verification")
            verified[name] = {"payload_path": row["bundle_path"], "sha256": member["sha256"],
                              "bytes": member["bytes"], "authenticode": signature}
    if len(verified) != 5 or sha256(receipt_path) != receipt_hash:
        raise AcceptanceInputError("Official VC receipt changed or member coverage is incomplete")
    return {"official_vc_receipt_sha256": receipt_hash,
            "official_vc_current_host_signatures": verified,
            "official_vc_destinations": sorted(destinations)}
