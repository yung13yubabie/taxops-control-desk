"""Verify exported source identity and reject kits mismatched to EXE evidence."""
import json
import subprocess
from types import SimpleNamespace
import zipfile

import pytest
from build_tools import make_recombine_kit as kit
from build_tools import source_materials
from build_tools import recombine


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout


def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    required = ["TaxOpsControlDesk.spec", "BUILD_RECOMBINE.txt", "requirements-release.txt", "requirements-ci.txt",
                "requirements-release-hashed.txt", "build_tools/pyinstaller_hooks/hook-PySide6.QtGui.py",
                "build_tools/qgif_rebuild/CMakeLists.txt", "assets/app_icon.ico", "assets/third_party_licenses/manifest.json",
                "assets/third_party_licenses/RECOMBINE_PERMISSION.txt", "build_tools/recombine.py"]
    for number in range(1, 29):
        required.append(f"src/taxops/db/migrations/_m{number:04}_synthetic.py")
    for name in required:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic public material\n")
    git(root, "init")
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic fixture")
    monkeypatch.setattr(kit, "ROOT", root)
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"synthetic executable")
    identity = source_materials.source_identity(root)
    evidence = {"status": "passed", "single_file": True, "source_exe_sha256": kit.sha256(exe),
                "build_source_commit": identity["source_commit"], "build_source_tree": identity["source_tree"]}
    provenance = tmp_path / "evidence.json"
    provenance.write_text(json.dumps(evidence))
    return root, exe, provenance


def test_kit_exports_exact_28_migrations_and_self_verifying_application_code(tmp_path, monkeypatch):
    root, exe, evidence = repo(tmp_path, monkeypatch)
    output = tmp_path / "kit.zip"
    result = kit.build_kit(exe, evidence, output)
    with zipfile.ZipFile(output) as z:
        z.extractall(tmp_path / "unpacked")
        assert "RECOMBINE_PERMISSION.txt" in z.namelist()
        assert len([n for n in z.namelist() if "/migrations/" in n]) == 28
    exported = tmp_path / "unpacked/source"
    identity = source_materials.source_identity(exported)
    assert identity["source_tree"] == result["source_tree"] and identity["modified_source_paths"] == []
    (exported / "src/taxops/db/migrations/_m0001_synthetic.py").write_text("recipient modification")
    identity = source_materials.source_identity(exported)
    assert identity["source_tree"].startswith("recombined-sha256:")
    assert identity["base_source_tree"] == result["source_tree"]
    assert identity["modified_source_paths"] == ["src/taxops/db/migrations/_m0001_synthetic.py"]


@pytest.mark.parametrize("fault", ["failed", "hash", "tree", "dirty"])
def test_kit_rejects_stale_or_unaccepted_exe_and_uncommitted_source(tmp_path, monkeypatch, fault):
    root, exe, evidence = repo(tmp_path, monkeypatch)
    data = json.loads(evidence.read_text())
    if fault == "failed":
        data["status"] = "failed"
    elif fault == "hash":
        exe.write_bytes(b"different executable")
    elif fault == "tree":
        data["build_source_tree"] = "wrong"
    else:
        (root / "TaxOpsControlDesk.spec").write_text("not committed")
    evidence.write_text(json.dumps(data))
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        kit.build_kit(exe, evidence, tmp_path / "kit.zip")
    assert not (tmp_path / "kit.zip").exists()


def test_recombine_requires_actual_windows_build_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(recombine, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(ValueError, match="Windows"):
        recombine.recombine(tmp_path / "work", tmp_path, tmp_path / "src", tmp_path / "vc")
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "C:/drive", "back\\slash"])
def test_source_manifest_rejects_unsafe_paths(tmp_path, unsafe):
    (tmp_path / "SOURCE_IDENTITY.json").write_text(json.dumps({"schema": 1, "files": [{"path": unsafe, "sha256": "0" * 64}]}))
    with pytest.raises(ValueError, match="Unsafe"):
        source_materials.source_identity(tmp_path)


def test_actual_repository_migration_names_match_the_kit_gate():
    import re
    names = [p.relative_to(kit.ROOT).as_posix() for p in (kit.ROOT / "src/taxops/db/migrations").glob("*.py")]
    assert len([n for n in names if re.fullmatch(r"src/taxops/db/migrations/_m[0-9]{4}_[^/]+\.py", n)]) == 28
    assert "requirements-release-hashed.txt" in (kit.ROOT / "build_tools/make_recombine_kit.py").read_text()
