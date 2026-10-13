"""Synthetic receipt adversaries are not actual Windows loader observations."""

from __future__ import annotations
import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from build_tools import shell_module_baseline as baseline
from build_tools import shell_icon_probe as probe
from build_tools.windows_loaded_modules import LoadedModuleError

ROOTS = {"system32": r"C:\Windows\System32", "winsxs": r"C:\Windows\WinSxS"}
EXE = r"C:\Python\python.exe"
EXTERNAL = r"C:\Installed Shell\extension.dll"
INPUT = r"C:\Synthetic\inputs\synthetic.txt"
HASH = "1" * 64


def row(path, number=1):
    return {
        "path": path,
        "loader_path": path,
        "sha256": HASH,
        "bytes": 12,
        "status": "observed",
        "handle": number,
    }


def snap(rows):
    return {"status": "observed", "attempt": 1, "modules": rows}


def file_row(path):
    return {key: row(path)[key] for key in ("path", "sha256", "bytes")}


def fixture():
    before = snap([row(EXE), row(ROOTS["system32"] + r"\kernel32.dll", 2)])
    after = snap(
        before["modules"]
        + [row(EXTERNAL, 3), row(ROOTS["system32"] + r"\msvcp140.dll", 4)]
    )
    calls = []
    previous = before
    for path in (INPUT, r"C:\Synthetic\inputs\synthetic folder"):
        calls.append(
            {
                "path": path,
                "flags": probe.FLAGS,
                "file_attributes_argument": 0,
                "status": "observed",
                "return_value": 7,
                "hicon": 8,
                "destroy_icon": {"return_value": 1},
                "after": copy.deepcopy(after),
                "delta": probe.delta(previous, after),
            }
        )
        previous = after
    expected = {
        "challenge": {
            "nonce": "fresh",
            "acceptance_run_id": "new",
            "source": {"tree": "a"},
        },
        "pid": 12,
        "parent_pid": 13,
        "interpreter": file_row(EXE),
        "sources": [{"sha256": HASH}],
        "host": {"computer": "synthetic", "os_roots": ROOTS},
        "bootstrap": [file_row(EXE)],
        "input_identity": file_row(INPUT),
        "roots": ROOTS,
        "protected_names": {"msvcp140.dll"},
    }
    receipt = {
        "schema": 2,
        "status": "observed",
        "scope": probe.SCOPE,
        "challenge": expected["challenge"],
        "process_id": 12,
        "parent_process_id": 13,
        "executable": expected["interpreter"],
        "source": expected["sources"],
        "source_after": expected["sources"],
        "host": expected["host"],
        "input": expected["input_identity"],
        "python": [3, 11, 9],
        "isolated": 1,
        "no_site": 1,
        "qt_or_taxops_imported": False,
        "com": {"accepted": True, "hresult": 0, "uninitialized": True},
        "before": before,
        "calls": calls,
        "after": copy.deepcopy(after),
        "delta": probe.delta(before, after),
    }
    return copy.deepcopy(receipt), copy.deepcopy(expected)


def refresh(receipt):
    previous = receipt["before"]
    for call in receipt["calls"]:
        call["delta"] = probe.delta(previous, call["after"])
        previous = call["after"]
    receipt["after"] = copy.deepcopy(previous)
    receipt["delta"] = probe.delta(receipt["before"], previous)


def test_only_new_external_exact_identity_is_eligible_and_vc_stays_excluded():
    receipt, expected = fixture()
    result = baseline.validate_observation(receipt, **expected)
    assert [x["path"] for x in result["eligible"]] == [EXTERNAL]
    assert [x["reason"] for x in result["excluded"]] == [
        "protected_application_dependency_name"
    ]
    expected["protected_names"].add("extension.dll")
    assert baseline.validate_observation(receipt, **expected)["eligible"] == []


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "status",
        "scope",
        "challenge",
        "process_id",
        "parent_process_id",
        "executable",
        "source",
        "source_after",
        "host",
        "input",
        "python",
        "isolated",
        "no_site",
        "qt_or_taxops_imported",
        "com",
        "before",
        "calls",
        "after",
        "delta",
    ],
)
def test_missing_receipt_evidence_fails(field):
    receipt, expected = fixture()
    del receipt[field]
    with pytest.raises((LoadedModuleError, TypeError)):
        baseline.validate_observation(receipt, **expected)


@pytest.mark.parametrize(
    "fault",
    [
        "old_nonce",
        "old_run",
        "source_tree",
        "source_helper",
        "source_after",
        "interpreter",
        "host",
        "not_direct",
        "wrong_parent",
        "site",
        "qt_import",
        "com_failed",
        "com_unbalanced",
        "candidate_before",
        "unknown_before",
        "native_qt_before",
        "native_qt_after",
        "changed",
        "removed",
        "duplicate",
        "case_duplicate",
        "loader_alias",
        "bad_hash",
        "bad_size",
        "failed_snapshot",
        "failed_query",
        "wrong_flags",
        "bad_target",
        "zero_return",
        "zero_icon",
        "failed_destroy",
        "forged_delta",
        "forged_query_delta",
        "lost_after",
    ],
)
def test_receipt_adversaries_fail_closed(fault):
    receipt, expected = fixture()
    if fault in {"old_nonce", "old_run", "source_tree"}:
        key = {
            "old_nonce": "nonce",
            "old_run": "acceptance_run_id",
            "source_tree": "source",
        }[fault]
        receipt["challenge"][key] = "different"
    elif fault in {"source_helper", "source_after", "interpreter", "host"}:
        receipt[
            {"source_helper": "source", "interpreter": "executable"}.get(fault, fault)
        ] = {}
    elif fault in {"not_direct", "wrong_parent"}:
        receipt["process_id" if fault == "not_direct" else "parent_process_id"] = 99
    elif fault == "site":
        receipt["no_site"] = 0
    elif fault == "qt_import":
        receipt["qt_or_taxops_imported"] = True
    elif fault == "com_failed":
        receipt["com"]["hresult"] = -1
    elif fault == "com_unbalanced":
        receipt["com"]["uninitialized"] = False
    elif fault in {"candidate_before", "unknown_before", "native_qt_before"}:
        path = (
            EXTERNAL
            if fault == "candidate_before"
            else r"C:\Injected\other.dll"
            if fault == "unknown_before"
            else ROOTS["system32"] + r"\Qt6Core.dll"
        )
        receipt["before"]["modules"].append(row(path, 9))
        refresh(receipt)
    elif fault == "native_qt_after":
        for call in receipt["calls"]:
            call["after"]["modules"].append(row(ROOTS["system32"] + r"\Qt6Core.dll", 9))
        refresh(receipt)
    elif fault in {
        "changed",
        "removed",
        "duplicate",
        "case_duplicate",
        "loader_alias",
        "bad_hash",
        "bad_size",
        "failed_snapshot",
    }:
        sample = receipt["calls"][0]["after"]
        if fault == "changed":
            sample["modules"][0]["sha256"] = "2" * 64
        elif fault == "removed":
            sample["modules"].pop(0)
        elif fault in {"duplicate", "case_duplicate"}:
            duplicate = copy.deepcopy(sample["modules"][0])
            if fault == "case_duplicate":
                duplicate["path"] = duplicate["path"].upper()
            sample["modules"].append(duplicate)
        elif fault == "loader_alias":
            sample["modules"][0]["loader_path"] = r"C:\Other\python.exe"
        elif fault == "bad_hash":
            sample["modules"][0]["sha256"] = "invalid"
        elif fault == "bad_size":
            sample["modules"][0]["bytes"] = True
        else:
            sample["status"] = "failed"
        refresh(receipt)
    elif fault in {
        "failed_query",
        "wrong_flags",
        "bad_target",
        "zero_return",
        "zero_icon",
        "failed_destroy",
    }:
        key, value = {
            "failed_query": ("status", "failed"),
            "wrong_flags": ("flags", 0),
            "bad_target": ("path", r"C:\Real\file.txt"),
            "zero_return": ("return_value", 0),
            "zero_icon": ("hicon", 0),
            "failed_destroy": ("destroy_icon", {"return_value": 0}),
        }[fault]
        receipt["calls"][0][key] = value
    elif fault == "forged_delta":
        receipt["delta"]["added"] = []
    elif fault == "forged_query_delta":
        receipt["calls"][0]["delta"]["added"] = []
    elif fault == "lost_after":
        receipt["after"]["modules"].pop()
    with pytest.raises(LoadedModuleError):
        baseline.validate_observation(receipt, **expected)


def test_all_pe_import_kinds_and_export_forwarders_are_protected():
    report = {
        "status": "passed",
        "dependencies": [
            {
                "kind": "normal",
                "resolution": {
                    "kind": "windows_system",
                    "module_path": ROOTS["system32"] + r"\normal.dll",
                    "symbols": [],
                },
            }
        ],
        "inventory": [
            {
                "path": "pkg/core.dll",
                "imports": [
                    {"kind": "normal", "dll": "normal.dll"},
                    {"kind": "delay", "dll": "delay.dll"},
                ],
                "exports": [{"forwarder": "forwarded.symbol"}, {"forwarder": None}],
            }
        ],
    }
    assert baseline.required_dependency_names(report) == {
        "core.dll",
        "normal.dll",
        "delay.dll",
        "forwarded.dll",
    }
    report["status"] = "failed"
    with pytest.raises(LoadedModuleError):
        baseline.required_dependency_names(report)


def test_saved_receipt_cannot_create_live_context():
    with pytest.raises(LoadedModuleError, match="saved"):
        baseline.LiveShellBaseline(
            {},
            run_id="new",
            source={},
            helpers=[],
            host={},
            bootstrap=[],
            interpreter={},
            classification={},
            report_path=Path("old.json"),
            report_hash=HASH,
            protected_names=set(),
        )


def test_collection_is_windows_only_and_refuses_invalid_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(LoadedModuleError):
        baseline.collect(tmp_path / "new", run_id="a" * 32, protected_names=set())
    monkeypatch.setattr(baseline, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(LoadedModuleError):
        baseline.collect(tmp_path / "new", run_id="old", protected_names=set())
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize(
    "fault", [None, "nonzero", "timeout", "source_changed", "one_level_child"]
)
def test_collection_retains_direct_process_fresh_challenge_and_failure_artifacts(
    tmp_path, monkeypatch, fault
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic interpreter")
    monkeypatch.setattr(
        baseline,
        "sys",
        SimpleNamespace(
            platform="win32", _base_executable=str(executable), version_info=(3, 11, 9)
        ),
    )

    def identity(path):
        return {"path": str(path), "sha256": HASH, "bytes": 12}

    monkeypatch.setattr(probe, "file_identity", identity)
    monkeypatch.setattr(probe, "source_identity", lambda: [])
    monkeypatch.setattr(probe, "host_identity", lambda: {"os_roots": ROOTS})
    source_calls = []

    def source(_root):
        source_calls.append(1)
        return {
            "tree": "changed"
            if fault == "source_changed" and len(source_calls) > 1
            else "fixed"
        }

    monkeypatch.setattr(baseline, "source_identity", source)
    monkeypatch.setattr(baseline, "helper_identities", lambda: [])
    cleanup, validation = [], []
    output = tmp_path / "fresh"

    class Process:
        pid = 88
        returncode = None

        def __init__(self, command, **kwargs):
            assert command[:3] == [str(executable), "-I", "-S"]
            assert kwargs["cwd"] == output and kwargs["stdin"] == subprocess.PIPE
            assert (
                "PYTHONPATH" not in kwargs["env"]
                and kwargs["env"]["PATH"] == ROOTS["system32"]
            )
            self.stdout, self.stderr = kwargs["stdout"], kwargs["stderr"]

        def communicate(self, data, timeout):
            challenge = json.loads(data)
            assert (
                challenge["acceptance_run_id"] == "a" * 32
                and len(challenge["nonce"]) == 64
            )
            self.stdout.write(b"out\xff")
            self.stderr.write(b"err\xfe")
            if fault == "timeout":
                raise subprocess.TimeoutExpired("child", timeout)
            self.returncode = 7 if fault == "nonzero" else 0
            probe.save(
                output / "child.json",
                {"process_id": 99 if fault == "one_level_child" else self.pid},
            )

        def poll(self):
            return self.returncode

    def validate(receipt, **kwargs):
        validation.append(kwargs)
        assert kwargs["pid"] == 88 and kwargs["parent_pid"] == baseline.os.getpid()
        if receipt["process_id"] != kwargs["pid"]:
            raise LoadedModuleError("direct child mismatch")
        return {"eligible": [], "excluded": []}

    monkeypatch.setattr(
        baseline, "subprocess", SimpleNamespace(Popen=Process, PIPE=subprocess.PIPE)
    )
    # This fake belongs only to the collector; unrelated source/host subprocesses
    # must retain the real stdlib Popen, including on Windows.
    import sys

    assert (
        subprocess.check_output(
            [sys.executable, "-c", 'print("real subprocess")']
        ).strip()
        == b"real subprocess"
    )
    monkeypatch.setattr(baseline, "validate_observation", validate)
    monkeypatch.setattr(
        baseline,
        "terminate_owned_tree",
        lambda process, path: cleanup.append(process.pid) or {"status": "forced"},
    )
    if fault:
        with pytest.raises((LoadedModuleError, subprocess.TimeoutExpired)):
            baseline.collect(output, run_id="a" * 32, protected_names=set())
    else:
        live = baseline.collect(output, run_id="a" * 32, protected_names=set())
        assert live.run_id == "a" * 32 and live.pid == baseline.os.getpid()
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == ("failed" if fault else "observed")
    assert (output / "stdout.bin").read_bytes() == b"out\xff"
    assert (output / "stderr.bin").read_bytes() == b"err\xfe"
    assert cleanup == ([88] if fault == "timeout" else [])


def test_missing_interpreter_preflight_preserves_failure_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        baseline,
        "sys",
        SimpleNamespace(
            platform="win32", _base_executable=str(tmp_path / "missing.exe")
        ),
    )
    root = tmp_path / "fresh"
    with pytest.raises(FileNotFoundError):
        baseline.collect(root, run_id="a" * 32, protected_names=set())
    receipt = json.loads((root / "report.json").read_text())
    assert (
        receipt["status"] == "failed"
        and receipt["error"]["type"] == "FileNotFoundError"
    )
    assert "child" not in receipt and not (root / "stdout.bin").exists()


def test_existing_observation_directory_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "sys", SimpleNamespace(platform="win32"))
    (tmp_path / "keep").write_text("original")
    with pytest.raises(FileExistsError):
        baseline.collect(tmp_path, run_id="a" * 32, protected_names=set())
    assert (tmp_path / "keep").read_text() == "original"


@pytest.mark.parametrize(
    "kind,nested",
    [("normal", False), ("delay", False), ("normal", True), ("delay", True)],
)
def test_resolved_provider_basenames_remain_protected(kind, nested):
    resolution = {
        "kind": "windows_system",
        "module_path": ROOTS["system32"] + r"\resolved-contract.dll",
        "symbols": [
            {"name": "Fn", "provider": ROOTS["system32"] + r"\final-provider.dll"}
        ],
    }
    if nested:
        resolution = {
            "kind": "bundle",
            "candidates": ["pkg/forward.dll"],
            "forwarders": [{"resolution": resolution}],
        }
    report = {
        "status": "passed",
        "inventory": [{"path": "app.dll", "imports": [], "exports": []}],
        "dependencies": [{"kind": kind, "resolution": resolution}],
    }
    names = baseline.required_dependency_names(report)
    assert {"resolved-contract.dll", "final-provider.dll"}.issubset(names)
    receipt, expected = fixture()
    expected["protected_names"] = names
    for call in receipt["calls"]:
        for module in call["after"]["modules"]:
            if module["path"] == EXTERNAL:
                module["path"] = module["loader_path"] = (
                    r"C:\Installed Shell\final-provider.dll"
                )
    refresh(receipt)
    assert baseline.validate_observation(receipt, **expected)["eligible"] == []


@pytest.mark.parametrize(
    "resolution",
    [
        {},
        {"kind": "unknown"},
        {"kind": "windows_system", "module_path": "relative.dll", "symbols": []},
        {
            "kind": "windows_system",
            "module_path": ROOTS["system32"] + r"\a.dll",
            "symbols": [{}],
        },
        {"kind": "bundle", "candidates": ["../outside.dll"], "forwarders": []},
        {
            "kind": "bundle",
            "candidates": ["good.dll"],
            "forwarders": [{"resolution": None}],
        },
    ],
)
def test_malformed_resolved_provider_evidence_fails(resolution):
    report = {
        "status": "passed",
        "inventory": [{"path": "app.dll", "imports": [], "exports": []}],
        "dependencies": [{"kind": "normal", "resolution": resolution}],
    }
    with pytest.raises(LoadedModuleError):
        baseline.required_dependency_names(report)
