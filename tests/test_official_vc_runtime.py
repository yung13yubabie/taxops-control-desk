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
    monkeypatch.setattr(vc, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout=json.dumps({"status":status,"subject":subject,"thumbprint":"test"}))))
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
