"""Fresh-process native OS proof for logical staged destinations, without aliases.

The input DLLs are parsed, never executed. Only bare OS dependency names are
passed to the existing system-only Windows resolver.
"""
from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from build_tools.dependency_licenses import sha256
from build_tools.windows_pe_dependencies import WindowsSystemResolver, inspect_dependencies, read_pe
from build_tools.windows_system_runtime import SystemRuntimeError, _path_key, _staging_records


def inspect_staged(input_path: Path, output: Path) -> dict:
    report = {"schema": 1, "status": "failed", "host_platform": platform.platform(),
              "scope": "Complete staged PE and native OS resolution on this host; not clean-OS acceptance"}
    resolver = None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if payload.get("schema") != 1:
            raise SystemRuntimeError("Invalid staged-native input schema")
        rows = _staging_records(payload["files"])
        if not rows or any(Path(key).suffix not in {".dll", ".pyd", ".exe"} for key in rows):
            raise SystemRuntimeError("Empty or incomplete staged-native input")
        inventory = []
        for key, row in rows.items():
            path = Path(row["source_path"])
            if (path.is_symlink() or not path.is_file() or sha256(path) != row["sha256"]
                    or path.stat().st_size != row["bytes"]):
                raise SystemRuntimeError("Staged-native bytes changed before OS resolution")
            # The source may live in any input directory. Its logical bundled
            # destination is set explicitly; no copies, links or aliases are made.
            parsed = read_pe(path, path.parent)
            parsed["path"] = _path_key(row["bundle_path"])
            inventory.append(parsed)
        report.update(input_sha256=sha256(input_path), inventory=inventory,
                      source_commit=payload["source_commit"], source_tree=payload["source_tree"],
                      package_environment_sha256=payload["package_environment_sha256"])
        resolver = WindowsSystemResolver()
        report["system_directory"] = resolver.system_directory
        class RecordingResolver:
            def resolve(self, dll, symbols):
                resolution = resolver.resolve(dll, symbols)
                report.setdefault("os_resolutions", []).append({
                    "dll": dll, "requested_symbols": symbols, "resolution": resolution})
                return resolution
        report["os_resolutions"] = []
        report.update(inspect_dependencies(inventory, RecordingResolver()))
        report["status"] = "passed"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if resolver is not None:
            resolver.close()
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect_staged(args.input, args.output)


if __name__ == "__main__":
    main()
