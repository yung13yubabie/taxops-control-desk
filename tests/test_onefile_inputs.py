"""Portable acceptance materials; synthetic signatures are unit contracts only."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from build_tools import onefile_inputs as inputs
from build_tools import verify_onefile as gate


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def signature():
    value = {"status": "Valid", "subject": "CN=Synthetic Test, O=Microsoft Corporation, C=US",
             "thumbprint": "synthetic-unit-test-not-real-trust"}
    raw = json.dumps(value).encode("utf-8")
    return {**value, "process": {"returncode": 0, "timed_out": False,
                                "stdout": raw.decode(), "stdout_base64": base64.b64encode(raw).decode(),
                                "stderr": "", "stderr_base64": ""}}


@pytest.fixture
def official(tmp_path, monkeypatch):
    names = ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"]
    rows, data = [], {}
    for name in names:
        content = ("synthetic " + name).encode()
        data[name] = content
        rows.append({"name": name, "source_member": "Contents/VC/" + name, "bytes": len(content),
                     "sha256": hashlib.sha256(content).hexdigest(), "pe_file_version": "1.2.3.4",
                     "internal_manifest_hash_matches": True})
    source = {"package": {"payloads": [{"sha256": "a" * 64, "url": "https://example.invalid/unit-only.vsix"}]},
              "observed_package_bytes": 1234, "files": rows}
    source_file = tmp_path / "source.json"
    write_json(source_file, source)
    monkeypatch.setattr(inputs, "SOURCE", source_file)
    manifest = {"reviewed_microsoft_binaries": []}
    for directory, selected in (("PySide6", names), ("shiboken6", [names[0], names[3], names[4]])):
        for name in selected:
            content = data[name]
            rel = "_internal/" + directory + "/" + name
            path = tmp_path / "bundle" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            manifest["reviewed_microsoft_binaries"].append({"bundle_path": rel,
                "sha256": hashlib.sha256(content).hexdigest(), "prior_wheel_sha256": "b" * 64})
    monkeypatch.setattr(inputs, "validate_notice_tree", lambda _path: copy.deepcopy(manifest))
    receipt = {"schema": 1, "status": "passed", "package_sha256": "a" * 64,
               "observed_archive_sha256": "a" * 64, "package_url": source["package"]["payloads"][0]["url"],
               "expected_package_bytes": 1234, "observed_archive_bytes": 1234,
               "files": [{**r, "staged_path": "Z:/old-host-gone/" + r["name"], "authenticode": signature()} for r in rows],
               "destinations": sorted(r["bundle_path"].removeprefix("_internal/").casefold()
                                      for r in manifest["reviewed_microsoft_binaries"])}
    receipt_path = tmp_path / "official-vc.json"
    write_json(receipt_path, receipt)
    calls = []
    def trust(path):
        assert path.is_file()
        assert "old-host-gone" not in str(path)
        calls.append(path)
        return signature()
    monkeypatch.setattr(inputs, "microsoft_signature", trust)
    return tmp_path / "bundle", receipt_path, receipt, calls


def test_official_receipt_binds_eight_payload_locations_and_rechecks_five_bytes(official):
    bundle, path, _, calls = official
    result = inputs.validate_official_receipt(bundle, path)
    assert len(calls) == len(result["official_vc_current_host_signatures"]) == 5
    assert len(result["official_vc_destinations"]) == 8
    assert result["official_vc_receipt_sha256"] == inputs.sha256(path)
    assert all(item.is_relative_to(bundle) for item in calls)


@pytest.mark.parametrize("fault", ["failed", "schema", "package_hash", "observed_hash", "package_size", "observed_size", "url",
                                   "member_missing", "member_duplicate", "member_hash", "member_size", "member_version",
                                   "map_missing", "map_duplicate", "map_foreign", "signature_status", "signature_subject",
                                   "signature_thumbprint", "signature_rc", "signature_timeout", "signature_raw",
                                   "signature_json", "signature_text", "signature_stderr"])
def test_receipt_tampering_rejected_before_any_signature_command(official, fault):
    bundle, path, receipt, calls = official
    if fault in {"failed", "schema", "package_hash", "observed_hash", "package_size", "observed_size", "url"}:
        key, value = {"failed": ("status", "failed"), "schema": ("schema", 2),
                      "package_hash": ("package_sha256", "0" * 64), "observed_hash": ("observed_archive_sha256", "0" * 64),
                      "package_size": ("expected_package_bytes", 123), "observed_size": ("observed_archive_bytes", 123),
                      "url": ("package_url", "https://example.invalid/wrong")}[fault]
        receipt[key] = value
    elif fault == "member_missing":
        receipt["files"].pop()
    elif fault == "member_duplicate":
        receipt["files"][-1] = copy.deepcopy(receipt["files"][0])
    elif fault.startswith("member_"):
        key = {"member_hash": "sha256", "member_size": "bytes", "member_version": "pe_file_version"}[fault]
        receipt["files"][0][key] = "wrong"
    elif fault == "map_missing":
        receipt["destinations"].pop()
    elif fault == "map_duplicate":
        receipt["destinations"][-1] = receipt["destinations"][0]
    elif fault == "map_foreign":
        receipt["destinations"][-1] = "other/msvcp140.dll"
    else:
        s = receipt["files"][0]["authenticode"]
        key = fault.removeprefix("signature_")
        if key in {"status", "subject", "thumbprint"}:
            s[key] = "" if key == "thumbprint" else "wrong"
        else:
            k, value = {"rc": ("returncode", 1), "timeout": ("timed_out", True),
                        "raw": ("stdout_base64", "!!!"), "json": ("stdout_base64", base64.b64encode(b"[]").decode()),
                        "text": ("stdout", "changed"), "stderr": ("stderr", "not the raw bytes")}[key]
            s["process"][k] = value
    write_json(path, receipt)
    with pytest.raises(inputs.AcceptanceInputError):
        inputs.validate_official_receipt(bundle, path)
    assert calls == []


@pytest.mark.parametrize("fault", ["missing", "changed", "directory", "changed_during_trust", "trust_failure", "receipt_changed"])
def test_legal_receipt_cannot_hide_different_payload_or_current_trust_failure(official, monkeypatch, fault):
    bundle, path, _, _ = official
    target = bundle / "_internal/PySide6/msvcp140.dll"
    if fault == "missing":
        target.unlink()
    elif fault == "changed":
        target.write_bytes(b"wrong payload")
    elif fault == "directory":
        target.unlink()
        target.mkdir()
    else:
        def trust(checked):
            if fault == "changed_during_trust":
                checked.write_bytes(b"changed while checked")
            elif fault == "trust_failure":
                raise RuntimeError("synthetic OS trust rejected")
            elif fault == "receipt_changed":
                path.write_bytes(path.read_bytes() + b" ")
            return signature()
        monkeypatch.setattr(inputs, "microsoft_signature", trust)
    with pytest.raises((inputs.AcceptanceInputError, RuntimeError)):
        inputs.validate_official_receipt(bundle, path)


def input_files(tmp_path):
    exe, matrix, staging = tmp_path / "app.exe", tmp_path / "matrix.json", tmp_path / "staging"
    staging.mkdir()
    for path in (exe, matrix, *(staging / name for name in inputs.STAGING_INPUT_FILES.values())):
        path.write_bytes(b"synthetic")
    return exe, matrix, staging


def test_preflight_reports_all_missing_inputs_and_keeps_failed_json_without_exe_start(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(gate, "inspect_payload", lambda *_: pytest.fail("must fail before payload extraction"))
    output = tmp_path / "output"
    with pytest.raises(inputs.AcceptanceInputError) as caught:
        gate.verify(tmp_path / "missing.exe", output, source_matrix=tmp_path / "matrix.json", build_staging=tmp_path / "staging")
    message = str(caught.value)
    for name in ("missing.exe", "matrix.json", *inputs.STAGING_INPUT_FILES.values(), "--build-staging", "--source-matrix"):
        assert name in message
    report = json.loads((output / "onefile-provenance.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["source_exe_sha256"] is None
    assert report["error"]["type"] == "AcceptanceInputError"
    assert [p.name for p in output.iterdir()] == ["onefile-provenance.json"]


@pytest.mark.parametrize("fault", ["missing", "directory", "empty", "changed"])
def test_inputs_must_be_complete_nonempty_and_immutable(tmp_path, fault):
    exe, matrix, staging = input_files(tmp_path)
    original = {p: p.read_bytes() for p in (exe, matrix, *staging.iterdir())}
    records = inputs.preflight_files(exe, matrix, staging)
    inputs.assert_inputs_unchanged(records)
    if fault == "missing":
        matrix.unlink()
    elif fault == "directory":
        matrix.unlink()
        matrix.mkdir()
    elif fault == "empty":
        matrix.write_bytes(b"")
    else:
        matrix.write_bytes(b"same size")
    with pytest.raises(inputs.AcceptanceInputError):
        inputs.assert_inputs_unchanged(records)
    if fault != "changed":
        with pytest.raises(inputs.AcceptanceInputError):
            inputs.preflight_files(exe, matrix, staging)
    assert all(p.read_bytes() == data for p, data in original.items() if p != matrix)


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    exe, matrix, staging = input_files(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "onefile-provenance.json"
    sentinel.write_bytes(b"old evidence")
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(FileExistsError):
        gate.verify(exe, output, source_matrix=matrix, build_staging=staging)
    assert sentinel.read_bytes() == b"old evidence"


@pytest.mark.parametrize("fault", ["matrix_json", "receipt_json", "receipt_failed", "payload_mismatch", None])
def test_complete_static_preflight_finishes_before_any_exe_boundary(tmp_path, monkeypatch, official, fault):
    bundle, receipt_path, receipt, _ = official
    exe, matrix, staging = input_files(tmp_path)
    # Keep source/receipt files real; only archive extraction and host OS calls
    # are synthetic here. The Windows artifact gate still executes them for real.
    import shutil
    shutil.copyfile(receipt_path, staging / "official-vc.json")
    write_json(matrix, {"synthetic": True})
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="win32"))
    events = []
    def check_matrix(path):
        events.append("matrix")
        json.loads(path.read_text(encoding="utf-8"))
        return {"source_matrix_sha256": inputs.sha256(path)}
    monkeypatch.setattr(gate, "check_source_matrix", check_matrix)
    def extract(_exe, destination):
        events.append("extract")
        shutil.copytree(bundle, destination)
        return {"entries": {}}
    monkeypatch.setattr(gate, "inspect_payload", extract)
    def native(_bundle, _output, *, staging_report):
        assert staging_report == staging / "windows-system-runtime.json"
        events.append("native")
        return {"build_staging_sha256": inputs.sha256(staging_report)}
    monkeypatch.setattr(gate, "verify_native_dependencies", native)
    def boundary(*_args, **_kwargs):
        events.append("exe_boundary")
        raise RuntimeError("synthetic stop before EXE launch")
    monkeypatch.setattr(gate, "verify_unusable_temp", boundary)
    if fault == "matrix_json":
        matrix.write_bytes(b"{")
    elif fault == "receipt_json":
        (staging / "official-vc.json").write_bytes(b"{")
    elif fault == "receipt_failed":
        receipt["status"] = "failed"
        write_json(staging / "official-vc.json", receipt)
    elif fault == "payload_mismatch":
        (bundle / "_internal/PySide6/msvcp140.dll").write_bytes(b"wrong")
    output = tmp_path / "gate-output"
    with pytest.raises((RuntimeError, ValueError)):
        gate.verify(exe, output, source_matrix=matrix, build_staging=staging)
    saved = json.loads((output / "onefile-provenance.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
    assert saved["acceptance_inputs"]["official_vc_receipt"]["path"] == str((staging / "official-vc.json").resolve())
    if fault is None:
        assert events == ["matrix", "extract", "native", "exe_boundary"]
        assert len(saved["official_vc_current_host_signatures"]) == 5
    else:
        assert "exe_boundary" not in events and "native" not in events


@pytest.mark.parametrize('missing', list(inputs.STAGING_INPUT_FILES.values()))
def test_each_schema_two_receipt_is_required_from_selected_directory(tmp_path, missing):
    exe, matrix, staging = input_files(tmp_path)
    (staging / missing).unlink()
    other = tmp_path / 'unrelated-checkout' / 'artifacts' / 'build-staging'
    other.mkdir(parents=True)
    (other / missing).write_bytes(b'not an authorized fallback')
    with pytest.raises(inputs.AcceptanceInputError, match=missing.replace('.', r'\.')):
        inputs.preflight_files(exe, matrix, staging)


@pytest.mark.parametrize("external_staging", [False, True])
def test_native_proof_is_routed_to_new_acceptance_output(tmp_path, monkeypatch, external_staging):
    from build_tools import verify_windows_bundle as bundle_gate
    bundle = tmp_path / "payload"
    bundle.mkdir()
    output = tmp_path / "new-acceptance"
    output.mkdir()
    report = tmp_path / "original-artifact" / "windows-system-runtime.json"
    report.parent.mkdir()
    report.write_bytes(b"original evidence")
    sentinel = report.parent / "windows-final-staging-dependencies.json"
    sentinel.write_bytes(b"previous host must stay unchanged")
    calls = []
    monkeypatch.setattr(bundle_gate, "validate_system_runtime_bundle", lambda *_: {})
    def validate(actual_bundle, *args, proof_output):
        assert actual_bundle == bundle
        assert args == ((report,) if external_staging else ())
        assert proof_output == output / "current-host-native-proof"
        assert not proof_output.exists()
        proof_output.mkdir()
        (proof_output / "proof.json").write_bytes(b"new host evidence")
        calls.append(proof_output)
        return {"proof_output": str(proof_output)}
    monkeypatch.setattr(bundle_gate, "validate_staging_report", validate)
    monkeypatch.setattr(bundle_gate, "verify_pe_dependencies", lambda *_: {})
    kwargs = {"staging_report": report} if external_staging else {}
    result = bundle_gate.verify_native_dependencies(bundle, output, **kwargs)
    assert calls == [output / "current-host-native-proof"]
    assert result["proof_output"] == str(calls[0])
    assert report.read_bytes() == b"original evidence"
    assert sentinel.read_bytes() == b"previous host must stay unchanged"
