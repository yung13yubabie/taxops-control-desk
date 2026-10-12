"""Inventory normal/delay PE imports and prove OS providers on this Windows host.

Hosted-runner loader checks are not clean-machine or manual GUI acceptance.
No bundled binary is executed by this module; only system libraries are loaded.
"""

from __future__ import annotations

import ctypes
import json
import ntpath
import platform
import sys
from collections import defaultdict
from pathlib import Path

from build_tools.dependency_licenses import sha256
from build_tools.windows_system_runtime import SystemRuntimeError

_SYMBOL_LIMIT = 100000
_ZERO_ENTRY_WARNINGS = frozenset(
    {
        "SizeOfHeaders is smaller than AddressOfEntryPoint: this file cannot run under Windows 8.",
        "AddressOfEntryPoint lies outside the sections' boundaries. AddressOfEntryPoint: 0x0",
    }
)


def read_pe(path: Path, bundle: Path) -> dict:
    """Reject invalid/non-x64 images and incomplete parsing, including limit warnings."""
    import pefile

    old_limit = pefile.MAX_IMPORT_SYMBOLS
    pefile.MAX_IMPORT_SYMBOLS = _SYMBOL_LIMIT
    pe = None
    try:
        pe = pefile.PE(str(path), fast_load=True, max_symbol_exports=_SYMBOL_LIMIT)
        if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
            raise SystemRuntimeError(f"Expected x64 PE: {path.name}")
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY[name]
                for name in (
                    "IMAGE_DIRECTORY_ENTRY_IMPORT",
                    "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT",
                    "IMAGE_DIRECTORY_ENTRY_EXPORT",
                )
            ]
        )
        imports = []
        for kind, attribute in (
            ("normal", "DIRECTORY_ENTRY_IMPORT"),
            ("delay", "DIRECTORY_ENTRY_DELAY_IMPORT"),
        ):
            for entry in getattr(pe, attribute, []):
                dll = entry.dll.decode("ascii")
                if not dll or ntpath.basename(dll) != dll or ":" in dll:
                    raise SystemRuntimeError("PE import contains an unsafe DLL name")
                imports.append(
                    {
                        "kind": kind,
                        "dll": dll,
                        "symbols": [
                            {
                                "name": item.name.decode("ascii")
                                if item.name
                                else None,
                                "ordinal": item.ordinal,
                            }
                            for item in entry.imports
                        ],
                    }
                )
        directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        exports = (
            [
                {
                    "name": item.name.decode("ascii") if item.name else None,
                    "ordinal": item.ordinal,
                    "forwarder": item.forwarder.decode("ascii")
                    if item.forwarder
                    else None,
                }
                for item in directory.symbols
            ]
            if directory
            else []
        )
        if (
            directory
            and sum(item["name"] is not None for item in exports)
            != directory.struct.NumberOfNames
        ):
            raise SystemRuntimeError(f"Incomplete PE export parsing: {path.name}")
        warnings = pe.get_warnings()
        forwarder_only = (
            path.name.casefold() == "python3.dll"
            and pe.OPTIONAL_HEADER.AddressOfEntryPoint == 0
            and exports
            and all(item["forwarder"] for item in exports)
        )
        if warnings and not (
            forwarder_only and set(warnings).issubset(_ZERO_ENTRY_WARNINGS)
        ):
            raise SystemRuntimeError(f"PE parser warning for {path.name}: {warnings}")
        return {
            "path": path.relative_to(bundle).as_posix(),
            "sha256": sha256(path),
            "machine": "AMD64",
            "imports": imports,
            "exports": exports,
            "reviewed_parser_warnings": warnings,
        }
    finally:
        pefile.MAX_IMPORT_SYMBOLS = old_limit
        if pe is not None:
            pe.close()


class WindowsSystemResolver:
    """Resolve contract names/functions using only Windows system search locations."""

    def __init__(self) -> None:
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise SystemRuntimeError(
                "Native OS dependency resolution requires 64-bit Windows"
            )
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.LoadLibraryExW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self.kernel.LoadLibraryExW.restype = wintypes.HMODULE
        self.kernel.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
        self.kernel.GetProcAddress.restype = ctypes.c_void_p
        self.kernel.GetModuleFileNameW.argtypes = [
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.kernel.GetModuleFileNameW.restype = wintypes.DWORD
        self.kernel.GetModuleHandleExW.argtypes = [
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.HMODULE),
        ]
        self.kernel.GetModuleHandleExW.restype = wintypes.BOOL
        self.kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        self.kernel.GetSystemDirectoryW.restype = wintypes.UINT
        self.kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
        self.kernel.FreeLibrary.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        length = self.kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise SystemRuntimeError("Cannot identify Windows System32 directory")
        self.system_directory = ntpath.normcase(ntpath.normpath(buffer.value))
        self.winsxs_directory = ntpath.join(
            ntpath.dirname(self.system_directory), "winsxs"
        )
        self.handles = {}
        self.resolutions = {}

    def module_path(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        length = self.kernel.GetModuleFileNameW(handle, buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise SystemRuntimeError("Cannot identify loaded system module")
        path = ntpath.normcase(ntpath.normpath(buffer.value))
        if ntpath.dirname(path) != self.system_directory and not path.startswith(
            self.winsxs_directory + "\\"
        ):
            raise SystemRuntimeError(
                f"OS import resolved outside Windows system locations: {buffer.value}"
            )
        return buffer.value

    def resolve(self, dll: str, symbols: list[dict]) -> dict:
        from ctypes import wintypes

        key = dll.casefold()
        if key not in self.handles:
            handle = self.kernel.LoadLibraryExW(
                dll, None, 0x00000800
            )  # LOAD_LIBRARY_SEARCH_SYSTEM32
            if not handle:
                raise SystemRuntimeError(
                    f"Windows cannot resolve required OS DLL/contract: {dll}"
                )
            self.handles[key] = handle
        handle = self.handles[key]
        module = self.module_path(handle)
        resolved = []
        for symbol in symbols:
            identifier = (
                symbol["name"] if symbol["name"] is not None else symbol["ordinal"]
            )
            cached = self.resolutions.get((key, identifier))
            if cached is None:
                if isinstance(identifier, str):
                    name = ctypes.c_char_p(identifier.encode("ascii"))
                    argument = ctypes.cast(name, ctypes.c_void_p)
                elif isinstance(identifier, int) and 0 < identifier <= 65535:
                    argument = ctypes.c_void_p(identifier)
                else:
                    raise SystemRuntimeError("Invalid PE import symbol")
                address = self.kernel.GetProcAddress(handle, argument)
                if not address:
                    raise SystemRuntimeError(
                        f"Unresolved required OS symbol: {dll}!{identifier}"
                    )
                provider = wintypes.HMODULE()
                # FROM_ADDRESS | UNCHANGED_REFCOUNT: also identify forwarded exports.
                if not self.kernel.GetModuleHandleExW(
                    0x6, address, ctypes.byref(provider)
                ):
                    raise SystemRuntimeError(
                        f"Cannot locate symbol provider: {dll}!{identifier}"
                    )
                cached = {**symbol, "provider": self.module_path(provider)}
                self.resolutions[(key, identifier)] = cached
            resolved.append(cached)
        return {"kind": "windows_system", "module_path": module, "symbols": resolved}

    def close(self) -> None:
        for handle in self.handles.values():
            self.kernel.FreeLibrary(handle)
        self.handles.clear()


def inspect_dependencies(inventory: list[dict], resolver) -> dict:
    """Check every import, including delayed imports and bundled export forwarding."""
    by_name = defaultdict(list)
    for row in inventory:
        by_name[Path(row["path"]).name.casefold()].append(row)
    exports = {
        row["path"]: {
            ("name", e["name"])
            if e["name"] is not None
            else ("ordinal", e["ordinal"]): e
            for e in row["exports"]
        }
        for row in inventory
    }
    # Named exports are also legal ordinal targets.
    for row in inventory:
        exports[row["path"]].update(
            {("ordinal", e["ordinal"]): e for e in row["exports"]}
        )

    def resolve(dll, symbols, active):
        if dll.casefold() not in by_name:
            return resolver.resolve(dll, symbols)
        paths = []
        forwarded = []
        for target in by_name[dll.casefold()]:
            paths.append(target["path"])
            for symbol in symbols:
                key = (
                    ("name", symbol["name"])
                    if symbol["name"] is not None
                    else ("ordinal", symbol["ordinal"])
                )
                entry = exports[target["path"]].get(key)
                if entry is None:
                    raise SystemRuntimeError(
                        f"Missing bundled export: {target['path']}!{key[1]}"
                    )
                forwarder = entry["forwarder"]
                if not forwarder:
                    continue
                identity = (target["path"], key)
                if identity in active:
                    raise SystemRuntimeError("Cyclic PE export forwarder")
                library, name = forwarder.rsplit(".", 1)
                forwarded_symbol = {
                    "name": None if name.startswith("#") else name,
                    "ordinal": int(name[1:]) if name.startswith("#") else None,
                }
                forwarded.append(
                    {
                        "from": target["path"],
                        "symbol": symbol,
                        "forwarder": forwarder,
                        "resolution": resolve(
                            library + ".dll", [forwarded_symbol], active | {identity}
                        ),
                    }
                )
        return {"kind": "bundle", "candidates": paths, "forwarders": forwarded}

    results = []
    for row in inventory:
        for entry in row["imports"]:
            results.append(
                {
                    "importer": row["path"],
                    **entry,
                    "resolution": resolve(entry["dll"], entry["symbols"], set()),
                }
            )
    return {
        "pe_count": len(inventory),
        "normal_import_edges": sum(r["kind"] == "normal" for r in results),
        "delay_import_edges": sum(r["kind"] == "delay" for r in results),
        "imported_symbol_count": sum(len(r["symbols"]) for r in results),
        "dependencies": results,
    }


def verify_pe_dependencies(bundle: Path, output: Path) -> dict:
    """Write failure evidence too; return success only after native resolution."""
    report = {
        "schema": 1,
        "status": "failed",
        "host_platform": platform.platform(),
        "scope": "PE and OS-loader checks on this host; not clean-OS/manual GUI acceptance",
    }
    resolver = None
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        files = sorted(
            p
            for p in bundle.rglob("*")
            if p.suffix.casefold() in {".exe", ".dll", ".pyd"}
        )
        if not files:
            raise SystemRuntimeError("No PE files found")
        inventory = [read_pe(path, bundle) for path in files]
        report["inventory"] = inventory
        resolver = WindowsSystemResolver()
        report["system_directory"] = resolver.system_directory
        report.update(inspect_dependencies(inventory, resolver))
        report["status"] = "passed"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if resolver is not None:
            resolver.close()
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {
        "pe_dependency_report_sha256": sha256(output),
        "pe_files_checked": report["pe_count"],
        "normal_import_edges": report["normal_import_edges"],
        "delay_import_edges": report["delay_import_edges"],
    }
