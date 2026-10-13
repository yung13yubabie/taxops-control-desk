"""Exact Windows-integrated VC++ 11 STL provider, separate from Shell additions."""

from __future__ import annotations

import ntpath
import re
from pathlib import Path

from build_tools.official_vc_runtime import microsoft_signature
from build_tools.shell_icon_probe import file_identity
from build_tools.windows_loaded_modules import LoadedModuleError, _path

NAME = "msvcp110_win.dll"
SOURCE = "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/validation-os-release-notes/2510?view=windows-11"


def verify_inbox_runtime(row: dict, *, roots: dict, protected_names: set) -> dict:
    path = _path(row.get("path"))
    expected = ntpath.join(_path(roots["system32"]), NAME)
    if (
        path != expected
        or _path(row.get("loader_path")) != path
        or NAME in protected_names
        or row.get("location") != "windows_system32"
    ):
        raise LoadedModuleError(
            "Windows-integrated runtime path or dependency collision"
        )
    before = file_identity(Path(row["path"]))
    if (
        before["sha256"] != row.get("sha256")
        or before["bytes"] != row.get("bytes")
        or _path(before["path"]) != path
    ):
        raise LoadedModuleError(
            "Windows-integrated runtime differs from loaded snapshot"
        )
    signature = microsoft_signature(Path(row["path"]))
    after = file_identity(Path(row["path"]))
    # The existing signature helper validates these too. Keep the acceptance
    # boundary explicit and retain its complete raw process evidence.
    process = signature.get("process", {})
    if (
        before != after
        or signature.get("status") != "Valid"
        or not isinstance(signature.get("subject"), str)
        or not re.search(
            r"(?:^|,\s*)O=Microsoft Corporation(?:,|$)", signature["subject"]
        )
        or not signature.get("thumbprint")
        or not isinstance(signature.get("original_filename"), str)
        or signature["original_filename"].casefold() != NAME
        or process.get("returncode") != 0
        or process.get("timed_out") is not False
        or not all(
            key in process for key in ("command", "stdout_base64", "stderr_base64")
        )
    ):
        raise LoadedModuleError(
            "Windows-integrated runtime signature or stable-file verification failed",
            diagnostics=process,
        )
    return {
        "classification": "verified_windows_integrated_runtime",
        **after,
        "authenticode": signature,
        "documentation": SOURCE,
        "scope": "Exact current-host System32 provider; not clean-OS acceptance",
    }
