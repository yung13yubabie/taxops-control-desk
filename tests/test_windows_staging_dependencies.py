"""Synthetic fresh-process staging contracts; no Windows acceptance claim."""
from __future__ import annotations
import json
import pytest
from build_tools import windows_staging_dependencies as staged
from build_tools import windows_system_runtime as runtime


def fixture(tmp_path, monkeypatch):
    paths = [tmp_path / "release/importer.pyd", tmp_path / "modified/wrapper.dll"]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"synthetic staged bytes")
    rows = [{"bundle_path": "_internal/" + path.name, "source_path": str(path),
             "sha256": runtime.sha256(path), "bytes": path.stat().st_size, "type": "BINARY"} for path in paths]
    source = tmp_path / "windows-staging-input.json"
    source.write_text(json.dumps({"schema": 1, "source_commit": "synthetic", "source_tree": "tree",
                                 "package_environment_sha256": "1" * 64, "files": rows}), encoding="utf-8")
    symbol = {"name": "Function", "ordinal": None}
    calls, closed = [], []
    class Resolver:
        system_directory = r"C:\Windows\System32"
        def resolve(self, name, symbols):
            calls.append((name, symbols))
            if symbols[0]["name"] == "AbsentSymbol":
                raise runtime.SystemRuntimeError("Unresolved required OS symbol")
            return {"kind": "windows_system", "module_path": r"C:\Windows\System32\kernel32.dll",
                    "symbols": [{**s, "provider": r"C:\Windows\System32\kernel32.dll"} for s in symbols]}
        def close(self):
            closed.append(True)
    def parse(path, root):
        assert root == path.parent
        row = {"path": path.name, "sha256": runtime.sha256(path), "machine": "AMD64", "imports": [], "exports": []}
        if path.name == "importer.pyd":
            row["imports"] = [{"kind": "normal", "dll": "wrapper.dll", "symbols": [symbol]},
                              {"kind": "delay", "dll": "WINMM.dll", "symbols": [symbol]}]
        else:
            row["exports"] = [{**symbol, "ordinal": 1, "forwarder": "kernel32.Function"}]
        return row
    monkeypatch.setattr(staged, "read_pe", parse)
    monkeypatch.setattr(staged, "WindowsSystemResolver", Resolver)
    return paths, rows, source, calls, closed


def test_complete_normal_delay_forwarder_inventory_logical_paths_and_close(tmp_path, monkeypatch):
    paths, rows, source, calls, closed = fixture(tmp_path, monkeypatch)
    output = tmp_path / "windows-staging-dependencies.json"
    report = staged.inspect_staged(source, output)
    assert report["status"] == "passed" and report["pe_count"] == 2
    assert report["normal_import_edges"] == 1 and report["delay_import_edges"] == 1
    assert {r["path"] for r in report["inventory"]} == {r["bundle_path"] for r in rows}
    assert calls == [("kernel32.dll", [{"name": "Function", "ordinal": None}]),
                     ("WINMM.dll", [{"name": "Function", "ordinal": None}])]
    assert len(report["os_resolutions"]) == 2 and closed == [True]
    assert report["input_sha256"] == runtime.sha256(source)
    assert paths[0].read_bytes() == b"synthetic staged bytes" and not (tmp_path / "_internal").exists()


@pytest.mark.parametrize("change", ["empty", "duplicate", "source_bytes", "source_missing", "non_native", "unsafe_destination", "missing_symbol", "missing_bundled_export", "architecture", "native_unavailable"])
def test_failures_stay_failed_and_sources_never_executed(tmp_path, monkeypatch, change):
    paths, rows, source, calls, closed = fixture(tmp_path, monkeypatch)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if change == "empty":
        payload["files"] = []
    elif change == "duplicate":
        payload["files"].append(dict(rows[0]))
    elif change == "source_bytes":
        paths[0].write_bytes(b"changed")
    elif change == "source_missing":
        paths[0].unlink()
    elif change == "non_native":
        payload["files"][0]["bundle_path"] = "_internal/other.txt"
    elif change == "unsafe_destination":
        payload["files"][0]["bundle_path"] = "../shadow.dll"
    elif change == "native_unavailable":
        def fail():
            raise runtime.SystemRuntimeError("Requires native Windows")
        monkeypatch.setattr(staged, "WindowsSystemResolver", fail)
    else:
        parse = staged.read_pe
        def changed(path, root):
            row = parse(path, root)
            if change == "missing_symbol" and path.name == "wrapper.dll":
                row["exports"][0]["forwarder"] = "kernel32.AbsentSymbol"
            elif change == "missing_bundled_export" and path.name == "wrapper.dll":
                row["exports"] = []
            elif change == "architecture":
                raise runtime.SystemRuntimeError("Expected x64 PE")
            return row
        monkeypatch.setattr(staged, "read_pe", changed)
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "proof.json"
    output.write_text('{"status":"passed"}', encoding="utf-8")
    with pytest.raises((runtime.SystemRuntimeError, FileNotFoundError)):
        staged.inspect_staged(source, output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["error"]
    if change in {"missing_symbol", "missing_bundled_export"}:
        assert closed == [True]
