"""Synthetic source/staging checks; Windows trust is deliberately not simulated as proof."""
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from build_tools import official_vc_runtime as vc


def source_fixture(tmp_path, monkeypatch):
    path = tmp_path / "source.vsix"
    rows = []
    with zipfile.ZipFile(path, "w") as z:
        for name in ["msvcp140.dll", "vcruntime140.dll"]:
            content = ("synthetic " + name).encode()
            z.writestr("Contents/" + name, content)
            rows.append({"name": name, "source_member": "Contents/" + name,
                         "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    spec = tmp_path / "source.json"
    spec.write_text(json.dumps({"package": {"payloads": [{"sha256": vc.sha256(path), "url": "https://example.invalid/synthetic.vsix"}]}, "files": rows,
                               "observed_package_bytes": path.stat().st_size,
                               "catalog_verification_note": "unverified catalog"}))
    monkeypatch.setattr(vc, "SOURCE", spec)
    return path, spec


def test_stage_verifies_every_member_signature_and_keeps_receipt(tmp_path, monkeypatch):
    path, _ = source_fixture(tmp_path, monkeypatch)
    checked = []
    monkeypatch.setattr(vc, "microsoft_signature", lambda p: checked.append(p.name) or {"status": "synthetic"})
    receipt = vc.stage_archive(path, tmp_path / "out")
    assert len(checked) == 2 and receipt["status"] == "passed"
    assert receipt["catalog_verification_note"] == "unverified catalog"
    assert (tmp_path / "out/receipt.json").is_file()


@pytest.mark.parametrize("fault", ["archive_hash", "size", "member_hash", "signature"])
def test_any_integrity_or_signature_failure_blocks_adoption(tmp_path, monkeypatch, fault):
    path, spec = source_fixture(tmp_path, monkeypatch)
    data = json.loads(spec.read_text())
    if fault == "archive_hash":
        data["package"]["payloads"][0]["sha256"] = "0" * 64
    elif fault == "size":
        data["observed_package_bytes"] += 1
    elif fault == "member_hash":
        data["files"][0]["sha256"] = "0" * 64
    spec.write_text(json.dumps(data))
    def invalid(_path):
        raise RuntimeError("Invalid signature")
    monkeypatch.setattr(vc, "microsoft_signature", invalid)
    with pytest.raises((ValueError, RuntimeError)):
        vc.stage_archive(path, tmp_path / "out")
    receipt = tmp_path / "out/receipt.json"
    if receipt.exists():
        assert json.loads(receipt.read_text())["status"] == "failed"


@pytest.mark.parametrize("status,subject", [("HashMismatch", "O=Microsoft Corporation"), ("Valid", "O=Other"), ("Valid", "O=Microsoft Corporation Evil")])
def test_authenticode_rejects_bad_status_or_publisher(tmp_path, monkeypatch, status, subject):
    monkeypatch.setattr(vc, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(vc, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(returncode=0, stderr=b"", stdout=json.dumps({"status":status,"subject":subject,"thumbprint":"test"}).encode())))
    with pytest.raises(RuntimeError):
        vc.microsoft_signature(tmp_path / "test.dll")


def test_nonwindows_cannot_claim_authenticode(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(RuntimeError, match="Windows"):
        vc.microsoft_signature(tmp_path / "test.dll")


def test_real_manifest_keeps_ten_locations_and_historical_wheel_hashes():
    manifest = vc.validate_notice_tree(vc.NOTICE_SOURCE)
    rows = manifest["reviewed_microsoft_binaries"]
    assert len(rows) == 10
    assert sum("prior_wheel_sha256" in row for row in rows) == 8
    assert len({row["sha256"] for row in rows if "prior_wheel_sha256" in row}) == 5


@pytest.mark.parametrize("fault", [None, "changed", "missing", "duplicate", "type"])
def test_analysis_replaces_only_reviewed_eight_without_mutating_sources(tmp_path, monkeypatch, fault):
    archive = tmp_path / "source.vsix"
    archive.write_bytes(b"synthetic")
    rows, binaries = [], []
    for index in range(8):
        name = f"pyside6/file{index}.dll"
        original = tmp_path / f"original{index}"
        original.write_bytes(f"original{index}".encode())
        rows.append({"bundle_path": "_internal/" + name, "prior_wheel_sha256": vc.sha256(original),
                     "sha256": hashlib.sha256(b"replacement").hexdigest()})
        binaries.append((name, str(original), "BINARY"))
    monkeypatch.setattr(vc, "RECEIPT", tmp_path / "receipts/vc.json")
    monkeypatch.setattr(vc, "validate_notice_tree", lambda _: {"reviewed_microsoft_binaries": rows})
    def stage(_archive, destination):
        destination.mkdir()
        for index in range(8):
            (destination / f"file{index}.dll").write_bytes(b"replacement")
        return {"status": "passed"}
    monkeypatch.setattr(vc, "stage_archive", stage)
    if fault == "changed":
        Path(binaries[0][1]).write_bytes(b"bad")
    elif fault == "missing":
        binaries.pop()
    elif fault == "duplicate":
        binaries.append(binaries[0])
    elif fault == "type":
        binaries[0] = (*binaries[0][:2], "DATA")
    if fault:
        with pytest.raises(ValueError):
            vc.stage_analysis(binaries, archive=archive)
        assert json.loads(vc.RECEIPT.read_text())["status"] == "failed"
    else:
        extra = ("vcruntime140.dll", "unchanged", "BINARY")
        result = vc.stage_analysis(binaries + [extra], archive=archive)
        assert result[-1] == extra
        assert all(Path(p).read_bytes().startswith(b"original") for _, p, _ in binaries)
        assert all(Path(p).read_bytes() == b"replacement" for _, p, _ in result[:-1])


def test_raw_vendor_package_and_staging_members_are_not_artifact_upload_inputs():
    source = (vc.ROOT / "build_tools/official_vc_runtime.py").read_text()
    workflow = (vc.ROOT / ".github/workflows/windows-candidate.yml").read_text()
    assert 'mkdtemp(prefix="taxops-official-vc-")' in source
    assert 'Join-Path $env:RUNNER_TEMP "TaxOps-Microsoft.VC.fixed.vsix"' in workflow
    assert "artifacts/source-inputs" not in workflow


def signature_process(monkeypatch, *, code=0, stdout=None, stderr=b"", error=None):
    """Synthetic subprocess contract; no Windows trust result is asserted here."""
    import subprocess
    calls = []
    if stdout is None:
        stdout = json.dumps({"status": "Valid", "subject": "CN=Microsoft, O=Microsoft Corporation", "thumbprint": "test"}).encode()
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if error is not None:
            raise error
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(vc, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(vc, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    return calls


def test_signature_success_records_exact_command_and_process_bytes(tmp_path, monkeypatch):
    import base64
    calls = signature_process(monkeypatch, stderr=b"synthetic warning")
    path = tmp_path / "synthetic.dll"
    report = vc.microsoft_signature(path)
    command, options = calls[0]
    assert command == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                       str(vc.ROOT / "build_tools/verify_microsoft_signature.ps1"), "-LiteralPath", str(path.resolve())]
    assert options == {"check": False, "capture_output": True, "timeout": 60}
    assert len(calls) == 1 and report["status"] == "Valid"
    assert report["process"]["returncode"] == 0
    assert base64.b64decode(report["process"]["stderr_base64"]) == b"synthetic warning"


@pytest.mark.parametrize("fault", ["nonzero", "json", "encoding", "array", "thumbprint"])
def test_failed_signature_retains_stdout_stderr_and_returncode(tmp_path, monkeypatch, fault):
    import base64
    stdout = {"nonzero": b"", "json": b"not json", "encoding": b"\xff\xfeinvalid", "array": b"[]",
              "thumbprint": b'{"status":"Valid","subject":"O=Microsoft Corporation","thumbprint":""}'}[fault]
    stderr = b"synthetic diagnostic \xa4\xa4\xff"
    code = 1 if fault == "nonzero" else 0
    signature_process(monkeypatch, code=code, stdout=stdout, stderr=stderr)
    with pytest.raises(vc.SignatureValidationError) as failure:
        vc.microsoft_signature(tmp_path / "synthetic.dll")
    details = failure.value.diagnostics
    assert details["returncode"] == code and details["timed_out"] is False
    assert base64.b64decode(details["stdout_base64"]) == stdout
    assert base64.b64decode(details["stderr_base64"]) == stderr
    assert details["stderr"].startswith("synthetic diagnostic")


@pytest.mark.parametrize("fault", ["timeout", "spawn"])
def test_unfinished_signature_is_failed_with_partial_diagnostics(tmp_path, monkeypatch, fault):
    import subprocess
    error = subprocess.TimeoutExpired("synthetic", 60, output=b"partial stdout", stderr=b"partial stderr") if fault == "timeout" else OSError("synthetic spawn error")
    signature_process(monkeypatch, error=error)
    with pytest.raises(vc.SignatureValidationError) as failure:
        vc.microsoft_signature(tmp_path / "synthetic.dll")
    details = failure.value.diagnostics
    assert details["returncode"] is None
    assert details["timed_out"] is (fault == "timeout")
    if fault == "timeout":
        assert details["stdout"] == "partial stdout" and details["stderr"] == "partial stderr"


def test_build_failure_publishes_receipt_but_no_vendor_bytes(tmp_path, monkeypatch):
    path, _ = source_fixture(tmp_path, monkeypatch)
    original_hash = vc.sha256(path)
    signature_process(monkeypatch, code=1, stderr=b"synthetic script failure")
    artifact = tmp_path / "artifacts/build-staging/official-vc.json"
    monkeypatch.setattr(vc, "RECEIPT", artifact)
    staging = tmp_path / "temporary-members"
    monkeypatch.setattr(vc, "tempfile", SimpleNamespace(mkdtemp=lambda **kwargs: str(staging)))
    with pytest.raises(vc.SignatureValidationError):
        vc.stage_analysis([], archive=path)
    receipt = json.loads(artifact.read_text())
    assert receipt["status"] == "failed"
    assert receipt["error"]["process"]["returncode"] == 1
    assert receipt["error"]["process"]["stderr"] == "synthetic script failure"
    assert receipt["active_member"] == "Contents/msvcp140.dll"
    assert receipt["files"][0]["authenticode"]["status"] == "failed"
    assert receipt["package_sha256"] == receipt["observed_archive_sha256"] == original_hash
    assert (staging / "members/msvcp140.dll").is_file()
    assert list((tmp_path / "artifacts").rglob("*.*")) == [artifact]
    assert vc.sha256(path) == original_hash


@pytest.mark.parametrize("code", [0, 1])
def test_signature_only_uses_same_stage_and_returns_failure_code(tmp_path, monkeypatch, capsys, code):
    path, _ = source_fixture(tmp_path, monkeypatch)
    calls = signature_process(monkeypatch, code=code, stderr=b"synthetic stderr")
    receipt = tmp_path / "diagnostics/official-vc.json"
    assert vc.main(["--signature-only", "--archive", str(path), "--receipt", str(receipt)]) == code
    document = json.loads(receipt.read_text())
    assert document["status"] == ("passed" if code == 0 else "failed")
    assert document["scope"] == "signature-only diagnostic; not application acceptance"
    assert json.loads(capsys.readouterr().out) == document
    assert len(calls) == (2 if code == 0 else 1)


def test_quick_signature_diagnostic_preserves_failure_and_only_uploads_evidence():
    workflow = (vc.ROOT / ".github/workflows/windows-candidate.yml").read_text()
    quick = workflow.split("  windows-ui-diagnostics:", 1)[1]
    diagnostic = quick.split("      - name: Diagnose the same fixed Microsoft signature stage separately", 1)[1].split("      - name: Upload synthetic UI diagnostics", 1)[0]
    assert "if: always()" in diagnostic
    assert "Get-Content build_tools/vc_redist_source.json" in diagnostic
    assert 'Join-Path $env:RUNNER_TEMP "TaxOps-Microsoft.VC.diagnostic.vsix"' in diagnostic
    assert "Invoke-WebRequest -Uri $payload.url -OutFile $vsix" in diagnostic
    assert "python -m build_tools.official_vc_runtime --signature-only" in diagnostic
    assert '"$directory/process.log"' in diagnostic and '"$directory/official-vc.json"' in diagnostic
    assert "$code = $LASTEXITCODE" in diagnostic and "if ($code -ne 0) { exit $code }" in diagnostic
    assert "throw" in diagnostic and "continue-on-error" not in diagnostic
    assert "ExecutionPolicy" not in diagnostic and "Bypass" not in diagnostic and "Unrestricted" not in diagnostic
    assert "path: artifacts/windows-ui-diagnostics/" in quick
