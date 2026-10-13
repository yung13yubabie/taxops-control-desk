"""Synthetic contracts; these do not claim Windows artifact acceptance."""

from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from build_tools import windows_system_runtime as runtime
from build_tools import windows_pe_dependencies as pe


def fixture(tmp_path, monkeypatch):
    manifest = json.loads(
        (runtime.NOTICE_SOURCE / "manifest.json").read_text(encoding="utf-8")
    )
    binaries = []
    for row in (
        manifest["excluded_windows_system_binaries"]
        + manifest["reviewed_microsoft_binaries"]
    ):
        name = row["bundle_path"].removeprefix("_internal/")
        path = tmp_path / "sources" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        binaries.append((name, str(path), "BINARY"))
    for relative in sorted(runtime.REQUIRED_NATIVE_PATHS):
        name = relative.removeprefix("_internal/")
        path = tmp_path / "sources" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
        binaries.append((name, str(path), "BINARY"))
    # These fixtures are synthetic contracts, never native Windows acceptance.
    monkeypatch.setattr(runtime, "_excluded_pe", lambda *args: None)
    from build_tools import windows_package_environment as environment
    receipt = tmp_path / "package-environment.json"
    receipt.write_text(json.dumps({"schema": 1, "status": "passed"}), encoding="utf-8")
    monkeypatch.setattr(environment, "package_receipt", lambda: runtime._link(receipt))
    def native_proof(rows, identity, input_path, output, **kwargs):
        input_path.write_text(json.dumps({"schema": 1, "files": rows,
            "source_commit": identity["source_commit"], "source_tree": identity["source_tree"],
            "package_environment_sha256": identity["package_environment"]["sha256"]}), encoding="utf-8")
        inventory = []
        for row in rows:
            path = Path(row["source_path"])
            parsed = pe.read_pe(path, path.parent)
            parsed["path"] = runtime._path_key(row["bundle_path"])
            inventory.append(parsed)
        os_resolutions = []
        class ProofResolver:
            def resolve(self, dll, symbols):
                result = {"kind": "windows_system", "module_path": r"C:\Windows\System32\kernel32.dll",
                          "symbols": [{**symbol, "provider": r"C:\Windows\System32\kernel32.dll"} for symbol in symbols]}
                os_resolutions.append({"dll": dll, "requested_symbols": symbols, "resolution": result})
                return result
        graph = pe.inspect_dependencies(inventory, ProofResolver())
        output.write_text(json.dumps({"schema": 1, "status": "passed", "inventory": inventory,
            "input_sha256": runtime.sha256(input_path), "source_commit": identity["source_commit"],
            "source_tree": identity["source_tree"], "os_resolutions": os_resolutions,
            "system_directory": r"C:\Windows\System32",
            "package_environment_sha256": identity["package_environment"]["sha256"],
            **graph}), encoding="utf-8")
        return {"input": runtime._link(input_path), "report": runtime._link(output)}
    monkeypatch.setattr(runtime, "_native_proof", native_proof)
    monkeypatch.setattr(pe, "read_pe", lambda path, root, **kwargs: {
        "path": path.name, "sha256": runtime.sha256(path), "machine": "AMD64", "imports": [], "exports": []})
    def final_environment(*, report_path):
        report_path.write_text(json.dumps({"schema": 1, "status": "passed"}), encoding="utf-8")
        return {}, {}
    monkeypatch.setattr(environment, "prepare_environment", final_environment)
    monkeypatch.setattr(
        runtime,
        "source_identity",
        lambda: {
            "source_commit": "synthetic",
            "source_tree": "tree",
            "notice_manifest_sha256": runtime.sha256(
                runtime.NOTICE_SOURCE / "manifest.json"
            ),
        },
    )
    return manifest, binaries


def test_real_policy_is_exact_43_and_ten_vc():
    excluded, retained = runtime.reviewed_policy()
    assert len(excluded) == 43 and len(retained) == 10
    assert sum("api-ms-win-crt-" in p for p in excluded) == 13
    assert sum("api-ms-win-core-" in p for p in excluded) == 29
    assert "_internal/ucrtbase.dll" in excluded
    assert sum("/pyside6/" in p or "/shiboken6/" in p for p in retained) == 8


@pytest.mark.parametrize("value", ["", "../a", "/a", "C:/a", "a//b", "./a"])
def test_unsafe_destinations_rejected(value):
    with pytest.raises(runtime.SystemRuntimeError):
        runtime._path_key(value)


def test_windows_case_and_separators():
    assert runtime._path_key("PySide6\\VCRUNTIME140.dll") == "pyside6/vcruntime140.dll"


@pytest.mark.parametrize("change", ["missing", "extra", "vc", "duplicate", "hash"])
def test_policy_cannot_expand_silently(tmp_path, monkeypatch, change):
    manifest, _ = fixture(tmp_path, monkeypatch)
    rows = manifest["excluded_windows_system_binaries"]
    if change == "missing":
        rows.pop()
    elif change == "extra":
        rows.append({**rows[0], "bundle_path": "_internal/new.dll"})
    elif change == "vc":
        manifest["reviewed_microsoft_binaries"].pop()
    elif change == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows[0]["sha256"] = "invalid"
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.reviewed_policy(manifest)


def test_filter_exact_bytes_order_and_ordinary_names_preserved(tmp_path, monkeypatch):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    for name in (
        "Qt6Pdf.dll",
        "qwindows.dll",
    ):
        path = tmp_path / name
        path.write_bytes(b"synthetic")
        binaries.append((name, str(path), "BINARY"))
    report = tmp_path / "staging.json"
    assert (
        runtime.filter_system_runtime(
            binaries, [], report_path=report, manifest=manifest
        )
        == binaries[43:]
    )
    result = json.loads(report.read_text(encoding="utf-8"))
    assert (
        result["status"] == "passed"
        and len(result["excluded"]) == 43
        and len(result["retained"]) == 10
    )
    assert len(result["before"]) - len(result["after"]) == 43
    assert all(Path(row["source_path"]).is_file() for row in result["before"])


@pytest.mark.parametrize(
    "change",
    ["bytes", "type", "duplicate", "folder", "data", "missing_vc", "source", "core"],
)
def test_filter_failure_replaces_old_success(tmp_path, monkeypatch, change):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    name, source, kind = binaries[0]
    datas = []
    if change == "bytes":
        Path(source).write_bytes(b"changed")
    elif change == "type":
        binaries[0] = (name, source, "DATA")
    elif change == "core":
        binaries = [b for b in binaries if b[0].casefold() != "python311.dll"]
    elif change == "missing_vc":
        binaries.pop(43)
    elif change == "duplicate":
        binaries.append(binaries[0])
    elif change == "folder":
        binaries[0] = ("elsewhere/" + name, source, kind)
    elif change == "source":
        Path(source).unlink()
    else:
        datas.append((name, source, "DATA"))
    report = tmp_path / "staging.json"
    report.write_text('{"status":"passed"}', encoding="utf-8")
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.filter_system_runtime(
            binaries, datas, manifest=manifest, report_path=report
        )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed" and payload["error"]


def bundle_fixture(tmp_path, binaries):
    bundle = tmp_path / "bundle"
    for name, source, _ in binaries[43:]:
        target = bundle / "_internal" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())
    return bundle


@pytest.mark.parametrize("change", [None, "missing", "changed", "reintroduced"])
def test_bundle_exact_ten_and_no_shims(tmp_path, monkeypatch, change):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    bundle = bundle_fixture(tmp_path, binaries)
    target = bundle / "_internal" / binaries[43][0]
    if change == "missing":
        target.unlink()
    elif change == "changed":
        target.write_bytes(b"changed")
    elif change == "reintroduced":
        (bundle / "UCRTBASE.DLL").write_bytes(b"shim")
    files = [p for p in bundle.rglob("*") if p.is_file()]
    if change is None:
        assert (
            runtime.validate_system_runtime_bundle(bundle, files, manifest=manifest)[
                "retained_vc_dll_count"
            ]
            == 10
        )
    else:
        with pytest.raises(runtime.SystemRuntimeError):
            runtime.validate_system_runtime_bundle(bundle, files, manifest=manifest)


@pytest.mark.parametrize(
    "change",
    [
        None,
        "bytes",
        "status",
        "manifest",
        "identity",
        "additional_removal",
        "source_identity",
        "extra_native",
    ],
)
def test_staging_bound_to_scope_manifest_and_actual_bytes(
    tmp_path, monkeypatch, change
):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    bundle = bundle_fixture(tmp_path, binaries)
    report = tmp_path / "staging.json"
    runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    payload = json.loads(report.read_text(encoding="utf-8"))
    if change == "bytes":
        next(bundle.rglob("*.dll")).write_bytes(b"changed")
    elif change == "status":
        payload["status"] = "failed"
    elif change == "manifest":
        payload["notice_manifest_sha256"] = "0" * 64
    elif change == "identity":
        payload["excluded"][0]["sha256"] = "0" * 64
    elif change == "additional_removal":
        payload["after"].pop()
    elif change == "source_identity":
        payload["source_commit"] = "stale"
    elif change == "extra_native":
        (bundle / "unexpected.dll").write_bytes(b"unreviewed")
    report.write_text(json.dumps(payload), encoding="utf-8")
    if change is None:
        assert (
            runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))["build_source_commit"]
            == "synthetic"
        )
    else:
        with pytest.raises(runtime.SystemRuntimeError):
            runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))


class Resolver:
    def __init__(self):
        self.calls = []

    def resolve(self, dll, symbols):
        self.calls.append((dll, symbols))
        if dll == "absent.dll":
            raise runtime.SystemRuntimeError("missing synthetic OS contract")
        return {"kind": "synthetic_os"}


def symbol(name="Function", ordinal=None):
    return {"name": name, "ordinal": ordinal}


def image(path, imports=(), exports=()):
    return {"path": path, "imports": list(imports), "exports": list(exports)}


def test_normal_delay_forwarder_and_ordinal_resolution():
    rows = [
        image(
            "app.exe",
            [
                {"kind": "normal", "dll": "wrapper.dll", "symbols": [symbol(None, 7)]},
                {
                    "kind": "delay",
                    "dll": "WINMM.dll",
                    "symbols": [symbol("timeGetTime")],
                },
            ],
        ),
        image(
            "wrapper.dll",
            exports=[{**symbol("NamedExport", 7), "forwarder": "target.Function"}],
        ),
        image(
            "target.dll", exports=[{**symbol("Function", 2), "forwarder": "system.#12"}]
        ),
    ]
    resolver = Resolver()
    result = pe.inspect_dependencies(rows, resolver)
    assert result["normal_import_edges"] == result["delay_import_edges"] == 1
    assert resolver.calls == [
        ("system.dll", [symbol(None, 12)]),
        ("WINMM.dll", [symbol("timeGetTime")]),
    ]


@pytest.mark.parametrize("change", ["export", "cycle", "os", "duplicate"])
def test_missing_dependency_never_becomes_empty_success(change):
    library = "absent.dll" if change == "os" else "wrapper.dll"
    exports = (
        []
        if change == "export"
        else [
            {
                **symbol("Function", 1),
                "forwarder": "wrapper.Function" if change == "cycle" else None,
            }
        ]
    )
    rows = [
        image("app.exe", [{"kind": "delay", "dll": library, "symbols": [symbol()]}]),
        image("wrapper.dll", exports=exports),
    ]
    if change == "duplicate":
        rows.append(image("other/wrapper.dll"))
    with pytest.raises(runtime.SystemRuntimeError):
        pe.inspect_dependencies(rows, Resolver())


def parser(warnings=(), machine=0x8664, count=1, forwarder=None, entrypoint=1):
    instance = SimpleNamespace(
        FILE_HEADER=SimpleNamespace(Machine=machine),
        OPTIONAL_HEADER=SimpleNamespace(Magic=0x20B, AddressOfEntryPoint=entrypoint),
        DIRECTORY_ENTRY_EXPORT=SimpleNamespace(
            struct=SimpleNamespace(NumberOfNames=count),
            symbols=[SimpleNamespace(name=b"Function", ordinal=1, forwarder=forwarder)],
        ),
        DIRECTORY_ENTRY_IMPORT=[
            SimpleNamespace(
                dll=b"KERNEL32.dll",
                imports=[SimpleNamespace(name=b"Function", ordinal=None)],
            )
        ],
        DIRECTORY_ENTRY_DELAY_IMPORT=[
            SimpleNamespace(
                dll=b"WINMM.dll",
                imports=[SimpleNamespace(name=b"timeGetTime", ordinal=None)],
            )
        ],
        parse_data_directories=lambda **kwargs: None,
        get_warnings=lambda: list(warnings),
        close=lambda: None,
    )
    observed = {}

    def factory(path, **kwargs):
        observed.update(kwargs)
        return instance

    module = SimpleNamespace(
        MAX_IMPORT_SYMBOLS=8192,
        PE=factory,
        DIRECTORY_ENTRY={
            name: i
            for i, name in enumerate(
                (
                    "IMAGE_DIRECTORY_ENTRY_IMPORT",
                    "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT",
                    "IMAGE_DIRECTORY_ENTRY_EXPORT",
                )
            )
        },
    )
    return module, observed


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"warnings": ["Excessive number of imports 8193 (>8192)"]},
        {"warnings": ["unknown malformed PE warning"]},
        {"machine": 0x14C},
        {"count": 2},
    ],
)
def test_parser_limits_complete_inventory_and_fail_closed(
    tmp_path, monkeypatch, options
):
    module, observed = parser(**options)
    monkeypatch.setitem(sys.modules, "pefile", module)
    path = tmp_path / "synthetic.dll"
    path.write_bytes(b"synthetic facade, not a PE executable")
    if options:
        with pytest.raises(runtime.SystemRuntimeError):
            pe.read_pe(path, tmp_path)
    else:
        result = pe.read_pe(path, tmp_path)
        assert [i["kind"] for i in result["imports"]] == ["normal", "delay"]
        assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (
        observed["max_symbol_exports"] == 100000 and module.MAX_IMPORT_SYMBOLS == 8192
    )


def test_narrow_forwarder_only_python3_warning_exception(tmp_path, monkeypatch):
    module, _ = parser(
        warnings=pe._ZERO_ENTRY_WARNINGS, forwarder=b"python311.Function", entrypoint=0
    )
    monkeypatch.setitem(sys.modules, "pefile", module)
    for name in ("python3.dll", "other.dll"):
        path = tmp_path / name
        path.write_bytes(b"synthetic")
        if name == "python3.dll":
            assert pe.read_pe(path, tmp_path)["reviewed_parser_warnings"]
        else:
            with pytest.raises(runtime.SystemRuntimeError):
                pe.read_pe(path, tmp_path)


def test_non_windows_is_not_native_acceptance(monkeypatch):
    monkeypatch.setattr(pe, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(runtime.SystemRuntimeError, match="64-bit Windows"):
        pe.WindowsSystemResolver()


def test_native_failure_persisted(tmp_path, monkeypatch):
    (tmp_path / "app.exe").write_bytes(b"synthetic")
    monkeypatch.setattr(pe, "read_pe", lambda p, root: image("app.exe"))

    def fail():
        raise runtime.SystemRuntimeError("synthetic failure")

    monkeypatch.setattr(pe, "WindowsSystemResolver", fail)
    output = tmp_path / "report.json"
    with pytest.raises(runtime.SystemRuntimeError):
        pe.verify_pe_dependencies(tmp_path, output)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"


def test_spec_filter_and_native_extracted_artifact_gate_are_wired():
    spec = (runtime.ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")
    assert (
        spec.index("a = Analysis(")
        < spec.index("a.binaries = filter_system_runtime(a.binaries, a.datas)")
        < spec.index("exe = EXE(")
    )
    assert "coll = COLLECT(" not in spec
    assert "exclude_binaries=False" in spec
    assert (
        "verify_native_dependencies(exe.parent, output)"
        in (runtime.ROOT / "build_tools/verify_windows_bundle.py").read_text(encoding="utf-8")
    )


class NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


def native_kernel(monkeypatch, failure=None):
    calls = []

    def directory(buffer, size):
        buffer.value = r"C:\Windows\System32"
        return 0 if failure == "directory" else len(buffer.value)

    def library(name, reserved, flags):
        calls.append(("load", name, reserved, flags))
        return 0 if failure == "library" else 11

    def module_path(handle, buffer, size):
        handle = handle.value if hasattr(handle, "value") else handle
        buffer.value = (
            r"C:\untrusted\runtime.dll"
            if failure == "path"
            else r"C:\Windows\System32\ucrtbase.dll"
        )
        return size if failure == "truncated_path" else len(buffer.value)

    def proc(handle, argument):
        calls.append(("symbol", handle))
        return 0 if failure == "symbol" else 99999

    def provider(flags, address, output):
        assert flags == 6
        output._obj.value = 22
        return failure != "provider"

    kernel = SimpleNamespace(
        **{
            name: NativeCall(function)
            for name, function in {
                "GetSystemDirectoryW": directory,
                "LoadLibraryExW": library,
                "GetModuleFileNameW": module_path,
                "GetProcAddress": proc,
                "GetModuleHandleExW": provider,
                "FreeLibrary": lambda handle: calls.append(("free", handle)) or True,
            }.items()
        }
    )
    monkeypatch.setattr(pe, "sys", SimpleNamespace(platform="win32"))
    local_ctypes = SimpleNamespace(
        **{
            name: getattr(pe.ctypes, name)
            for name in dir(pe.ctypes)
            if name != "WinDLL"
        }
    )
    local_ctypes.WinDLL = lambda name, **kwargs: kernel
    monkeypatch.setattr(pe, "ctypes", local_ctypes)
    return calls


def test_native_resolver_uses_system_only_flags_symbol_provider_and_caching(
    monkeypatch,
):
    calls = native_kernel(monkeypatch)
    resolver = pe.WindowsSystemResolver()
    result = resolver.resolve("api-ms-win-crt-runtime-l1-1-0.dll", [symbol()])
    assert result["module_path"] == r"C:\Windows\System32\ucrtbase.dll"
    assert result["symbols"][0]["provider"] == result["module_path"]
    assert resolver.resolve("API-MS-WIN-CRT-RUNTIME-L1-1-0.DLL", [symbol()]) == result
    resolver.resolve("api-ms-win-crt-runtime-l1-1-0.dll", [symbol(None, 12)])
    resolver.close()
    assert calls == [
        ("load", "api-ms-win-crt-runtime-l1-1-0.dll", None, 0x800),
        ("symbol", 11),
        ("symbol", 11),
        ("free", 11),
    ]


@pytest.mark.parametrize(
    "failure",
    ["directory", "library", "path", "truncated_path", "symbol", "provider", "ordinal"],
)
def test_native_resolver_failures_are_explicit(monkeypatch, failure):
    native_kernel(monkeypatch, failure)
    resolver = None
    try:
        with pytest.raises(runtime.SystemRuntimeError):
            resolver = pe.WindowsSystemResolver()
            resolver.resolve(
                "KERNEL32.dll", [symbol(None, 0) if failure == "ordinal" else symbol()]
            )
    finally:
        if resolver is not None:
            resolver.close()


def test_native_success_report_is_hashed_and_resolver_closed(tmp_path, monkeypatch):
    (tmp_path / "app.exe").write_bytes(b"synthetic")
    monkeypatch.setattr(
        pe,
        "read_pe",
        lambda p, root: image(
            "app.exe",
            [{"kind": "delay", "dll": "WINMM.dll", "symbols": [symbol("timeGetTime")]}],
        ),
    )
    resolver = Resolver()
    resolver.system_directory = "synthetic-system32"
    closed = []
    resolver.close = lambda: closed.append(True)
    monkeypatch.setattr(pe, "WindowsSystemResolver", lambda: resolver)
    output = tmp_path / "report.json"
    result = pe.verify_pe_dependencies(tmp_path, output)
    assert result["pe_dependency_report_sha256"] == runtime.sha256(output)
    assert result["pe_files_checked"] == 1 and result["delay_import_edges"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed" and closed == [True]


@pytest.mark.parametrize("group", ["excluded", "retained", "before", "after"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("source_path", None),
        ("source_path", "relative/runtime.dll"),
        ("source_path", "/absolute/different-source.dll"),
        ("bytes", None),
        ("bytes", -1),
        ("bytes", True),
        ("bytes", 999999),
        ("type", None),
        ("type", "DATA"),
        ("type", "EXTENSION"),
        ("sha256", "0" * 64),
    ],
)
def test_staging_receipt_complete_rows_cannot_disagree(
    tmp_path, monkeypatch, group, field, value
):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    bundle = bundle_fixture(tmp_path, binaries)
    report = tmp_path / "staging.json"
    runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    payload = json.loads(report.read_text(encoding="utf-8"))
    if value is None:
        payload[group][0].pop(field)
    else:
        payload[group][0][field] = value
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))


@pytest.mark.parametrize(
    "field,value",
    [("bytes", 99999), ("type", "EXTENSION"), ("pe_file_version", [0, 0, 0, 0])],
)
def test_consistent_tampering_cannot_change_reviewed_receipt_facts(
    tmp_path, monkeypatch, field, value
):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    bundle = bundle_fixture(tmp_path, binaries)
    report = tmp_path / "staging.json"
    runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    payload = json.loads(report.read_text(encoding="utf-8"))
    groups = (
        ("excluded", "before")
        if field == "pe_file_version"
        else ("retained", "before", "after")
    )
    name = payload[groups[0]][0]["bundle_path"]
    for group in groups:
        next(row for row in payload[group] if row["bundle_path"] == name)[field] = value
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))


@pytest.mark.parametrize("count", [0, 1, 42, 43])
def test_absent_optional_files_are_exactly_accounted_with_complete_proof(tmp_path, monkeypatch, count):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    binaries = binaries[count:]
    report = tmp_path / "staging.json"
    kept = runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert len(payload["absent"]) == count and len(payload["excluded"]) == 43 - count
    assert {row["bundle_path"].casefold() for row in payload["excluded"]} | set(payload["absent"]) == set(runtime.reviewed_policy(manifest)[0])
    bundle = tmp_path / "bundle"
    for name, source, kind in kept:
        path = bundle / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(source).read_bytes())
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    assert runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))["absent_system_dll_count"] == count


@pytest.mark.parametrize("name", ["api-ms-win-core-new.dll", "ext-ms-win-new.dll", "API-UNKNOWN.DLL", "nested/api-ms-win-crt-filesystem-l1-1-0.dll"])
@pytest.mark.parametrize("as_data", [False, True])
def test_unknown_or_nested_contract_candidates_rejected(tmp_path, monkeypatch, name, as_data):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    path = tmp_path / "shadow.dll"
    path.write_bytes(b"synthetic untrusted shadow")
    datas = [(name, str(path), "DATA")] if as_data else []
    if not as_data:
        binaries.append((name, str(path), "BINARY"))
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.filter_system_runtime(binaries, datas, manifest=manifest, report_path=tmp_path / "staging.json")


@pytest.mark.parametrize("case", ["x86", "incomplete", "non_forwarder"])
def test_removed_reviewed_bytes_still_require_complete_x64_forwarder_pe(tmp_path, monkeypatch, case):
    path = tmp_path / "api-ms-win-core-console-l1-1-0.dll"
    path.write_bytes(b"synthetic")
    module, _ = parser(warnings=pe._ZERO_ENTRY_WARNINGS,
        machine=0x14C if case == "x86" else 0x8664,
        count=2 if case == "incomplete" else 1,
        forwarder=None if case == "non_forwarder" else b"kernel32.Function", entrypoint=0)
    monkeypatch.setitem(sys.modules, "pefile", module)
    with pytest.raises(runtime.SystemRuntimeError):
        runtime._excluded_pe(path, "_internal/" + path.name)


@pytest.mark.parametrize("name", [r"C:\outside\evil.dll", r"..\evil.dll", "../evil.dll", "evil\x00.dll", ".dll", "kernel32.dll/evil.dll"])
def test_unsafe_os_names_never_call_native_loader(monkeypatch, name):
    calls = native_kernel(monkeypatch)
    resolver = pe.WindowsSystemResolver()
    with pytest.raises(runtime.SystemRuntimeError):
        resolver.resolve(name, [symbol()])
    resolver.close()
    assert calls == []


@pytest.mark.parametrize("forwarder", [r"C:\outside\evil.Function", r"..\evil.Function", "../evil.Function", "evil\x00.Function", ".Function", "evil.", "evil.#0"])
def test_unsafe_forwarders_never_reach_resolver(forwarder):
    rows = [image("app.exe", [{"kind": "normal", "dll": "wrapper.dll", "symbols": [symbol()]}]),
        image("wrapper.dll", exports=[{**symbol("Function", 1), "forwarder": forwarder}])]
    resolver = Resolver()
    with pytest.raises(runtime.SystemRuntimeError):
        pe.inspect_dependencies(rows, resolver)
    assert resolver.calls == []


@pytest.mark.parametrize("change", ["absent_duplicate", "absent_alias", "absent_unknown", "absent_present", "missing_state", "input_link", "proof_link", "environment_link", "inventory_omission", "graph_erase", "provider_root"])
def test_schema_two_closed_receipt_graph_negative_controls(tmp_path, monkeypatch, change):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    base_parse = pe.read_pe
    def parsed(path, root, **kwargs):
        row = base_parse(path, root, **kwargs)
        row["imports"] = [{"kind": "delay", "dll": "KERNEL32.dll", "symbols": [symbol()]}]
        return row
    monkeypatch.setattr(pe, "read_pe", parsed)
    report = tmp_path / "staging.json"
    kept = runtime.filter_system_runtime(binaries[1:], [], manifest=manifest, report_path=report)
    bundle = tmp_path / "bundle"
    for name, source, _ in kept:
        path = bundle / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(source).read_bytes())
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    payload = json.loads(report.read_text(encoding="utf-8"))
    if change == "absent_duplicate":
        payload["absent"].append(payload["absent"][0])
    elif change == "absent_alias":
        payload["absent"][0] = payload["absent"][0].upper()
    elif change == "absent_unknown":
        payload["absent"][0] = "_internal/api-unknown.dll"
    elif change == "absent_present":
        payload["absent"].append(payload["excluded"][0]["bundle_path"].casefold())
    elif change == "missing_state":
        payload["absent"] = []
    elif change.endswith("_link"):
        link = payload["package_environment"] if change == "environment_link" else payload["native_proof"]["input" if change == "input_link" else "report"]
        link["filename"] = "../" + link["filename"]
    else:
        proof_path = tmp_path / "windows-staging-dependencies.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if change == "inventory_omission":
            proof["inventory"].pop()
        elif change == "graph_erase":
            for row in proof["inventory"]:
                row["imports"] = []
            proof.update(pe.inspect_dependencies(proof["inventory"], Resolver()))
            proof["os_resolutions"] = []
        else:
            proof["os_resolutions"][0]["resolution"]["symbols"][0]["provider"] = r"C:\outside\shadow.dll"
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        payload["native_proof"]["report"] = runtime._link(proof_path)
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(runtime.SystemRuntimeError):
        runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-proof"))


@pytest.mark.parametrize("origin", ["importer", "package-added", "inherited-tail"])
def test_wrong_hash_same_name_shadow_is_not_trusted_by_its_destination(tmp_path, monkeypatch, origin):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    name, source, kind = binaries[0]
    shadow = tmp_path / origin / name
    shadow.parent.mkdir()
    shadow.write_bytes(b"wrong-hash x64-looking candidate")
    binaries[0] = (name, str(shadow), kind)
    report = tmp_path / "staging.json"
    with pytest.raises(runtime.SystemRuntimeError, match="Changed reviewed"):
        runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    assert json.loads(report.read_text(encoding="utf-8"))["before"][0]["source_path"] == str(shadow.resolve())


@pytest.mark.parametrize("name", ["python311.dll", "pyside6/qt6core.dll", "pyside6/plugins/platforms/qwindows.dll"])
def test_optional_absence_cannot_hide_core_omission(tmp_path, monkeypatch, name):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    binaries = [b for b in binaries[43:] if b[0].casefold() != name]
    with pytest.raises(runtime.SystemRuntimeError, match="required Python/Qt/core"):
        runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=tmp_path / "staging.json")


def test_receipts_relocate_without_original_builder_paths(tmp_path, monkeypatch):
    import shutil
    manifest, binaries = fixture(tmp_path, monkeypatch)
    original = tmp_path / "staging.json"
    kept = runtime.filter_system_runtime(binaries[43:], [], manifest=manifest, report_path=original)
    bundle = tmp_path / "bundle"
    for name, source, _ in kept:
        path = bundle / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(source).read_bytes())
    target = tmp_path / "relocated"
    target.mkdir()
    for path in (original, tmp_path / "package-environment.json", tmp_path / "windows-staging-input.json", tmp_path / "windows-staging-dependencies.json"):
        shutil.copyfile(path, target / path.name)
    shutil.rmtree(tmp_path / "sources")
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    assert runtime.validate_staging_report(bundle, target / "staging.json", proof_output=tmp_path / "relocated-proof")["absent_system_dll_count"] == 43


def test_final_proof_keeps_read_only_original_receipts_and_sentinels_immutable(tmp_path, monkeypatch):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    report = tmp_path / "staging.json"
    kept = runtime.filter_system_runtime(binaries[43:], [], manifest=manifest, report_path=report)
    bundle = tmp_path / "bundle"
    for name, source, _ in kept:
        path = bundle / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(source).read_bytes())
    for name in ("windows-final-package-environment.json", "windows-final-staging-input.json", "windows-final-staging-dependencies.json"):
        (tmp_path / name).write_bytes(b"immutable existing sentinel")
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    snapshot = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    originals = [p for p in tmp_path.rglob("*") if p.is_file()]
    modes = {p: p.stat().st_mode & 0o777 for p in originals}
    try:
        for path in originals:
            path.chmod(0o444)
        tmp_path.chmod(0o555)
        proof_output = tmp_path.parent / (tmp_path.name + "-immutable-proof")
        result = runtime.validate_staging_report(bundle, report, proof_output=proof_output)
        assert result["absent_system_dll_count"] == 43
        assert {p.name for p in proof_output.iterdir()} == {
            "windows-final-package-environment.json", "windows-final-staging-input.json", "windows-final-staging-dependencies.json"}
        assert {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snapshot
    finally:
        tmp_path.chmod(0o755)
        for path, mode in modes.items():
            path.chmod(mode)


@pytest.mark.parametrize("location", ["same", "nested", "existing"])
def test_final_proof_destination_cannot_overwrite_or_enter_inputs(tmp_path, monkeypatch, location):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    report = tmp_path / "staging.json"
    runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    if location == "same":
        output = tmp_path
    elif location == "nested":
        output = tmp_path / "new-proof"
    else:
        output = tmp_path.parent / (tmp_path.name + "-existing-proof")
        output.mkdir()
        (output / "sentinel.txt").write_bytes(b"never overwrite")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(runtime.SystemRuntimeError, match="fresh directory outside"):
        runtime.validate_staging_report(tmp_path / "unused-bundle", report, proof_output=output)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    if location == "existing":
        assert (output / "sentinel.txt").read_bytes() == b"never overwrite"


def test_final_native_failure_cannot_change_original_build_receipts(tmp_path, monkeypatch):
    manifest, binaries = fixture(tmp_path, monkeypatch)
    report = tmp_path / "staging.json"
    kept = runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    bundle = tmp_path / "bundle"
    for name, source, _ in kept:
        path = bundle / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(source).read_bytes())
    monkeypatch.setattr(runtime, "validate_notice_tree", lambda _: manifest)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    def fail(*args, **kwargs):
        raise runtime.SystemRuntimeError("required OS symbol missing on this validation host")
    monkeypatch.setattr(runtime, "_native_proof", fail)
    with pytest.raises(runtime.SystemRuntimeError, match="OS symbol missing"):
        runtime.validate_staging_report(bundle, report, proof_output=tmp_path.parent / (tmp_path.name + "-failed-proof"))
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_final_proof_resolves_directory_alias_before_input_overlap_check(tmp_path, monkeypatch):
    import subprocess
    manifest, binaries = fixture(tmp_path, monkeypatch)
    report = tmp_path / "staging.json"
    runtime.filter_system_runtime(binaries, [], manifest=manifest, report_path=report)
    alias = tmp_path.parent / (tmp_path.name + "-input-alias")
    if sys.platform == "win32":
        # Real Windows CI checks a junction without changing privilege settings.
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(tmp_path)],
                       check=True, capture_output=True)
    else:
        alias.symlink_to(tmp_path, target_is_directory=True)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    try:
        assert (alias / "new-proof").resolve().is_relative_to(tmp_path.resolve())
        with pytest.raises(runtime.SystemRuntimeError, match="fresh directory outside"):
            runtime.validate_staging_report(tmp_path / "unused-bundle", report, proof_output=alias / "new-proof")
        assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    finally:
        if sys.platform == "win32":
            alias.rmdir()
        else:
            alias.unlink()
