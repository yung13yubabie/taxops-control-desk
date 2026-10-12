"""Recombination replaces actual build inputs, not a separate report marker."""
import json
from pathlib import Path
import pytest
from build_tools import recombine_inputs as inputs
from build_tools import recombine_probe


def test_single_exe_spec_embeds_native_data_and_keeps_system_gate():
    source = Path("TaxOpsControlDesk.spec").read_text()
    assert "COLLECT(" not in source and "exclude_binaries=False" in source
    exe = source.split("exe = EXE(")[1]
    assert "a.binaries," in exe and "a.datas," in exe and "a.zipfiles," in exe
    assert source.index("stage_analysis(a.binaries)") < source.index("filter_system_runtime(a.binaries, a.datas)")
    assert '(str(NOTICE_SOURCE), "third_party_licenses")' in source


def test_default_inputs_are_unchanged(monkeypatch):
    monkeypatch.delenv("TAXOPS_RECOMBINE_INPUT", raising=False)
    pure, native = [], []
    got = inputs.apply_recombination(pure, native)
    assert got[0] is pure and got[1] is native


@pytest.mark.parametrize("fault", [None, "hash", "missing", "duplicate"])
def test_real_source_and_binary_paths_replace_toc_without_original_cache(tmp_path, monkeypatch, fault):
    support, dll = tmp_path / "__init__.py", tmp_path / "qgif.dll"
    support.write_text(f'TAXOPS_RECOMBINE_MARKER = "{inputs.SUPPORT_MARKER}"\n')
    dll.write_bytes(b"synthetic DLL")
    spec = tmp_path / "inputs.json"
    spec.write_text(json.dumps({"schema": 1, "pyside_support": {"path": str(support), "sha256": inputs.sha256(support)},
                               "qgif": {"path": str(dll), "sha256": inputs.sha256(dll)}}))
    monkeypatch.setenv("TAXOPS_RECOMBINE_INPUT", str(spec))
    pure = [("PySide6.support", "original.py", "PYMODULE")]
    native = [("PySide6/plugins/imageformats/qgif.dll", "original.dll", "BINARY")]
    if fault == "hash":
        support.write_text("changed")
    elif fault == "missing":
        native.clear()
    elif fault == "duplicate":
        pure += pure
    if fault:
        with pytest.raises(ValueError):
            inputs.apply_recombination(pure, native)
    else:
        p, b = inputs.apply_recombination(pure, native)
        assert p is not pure and p[0][1] == str(support)
        assert b[0][1] == str(dll)


def test_probe_refuses_nonfrozen_and_writes_failure(tmp_path):
    out = tmp_path / "report.json"
    assert recombine_probe.main(["--require-frozen", "--report", str(out)]) == 1
    assert json.loads(out.read_text())["status"] == "failed"


def test_hashed_release_wheel_pins_match_exact_reviewed_distributions():
    from build_tools.dependency_licenses import NOTICE_SOURCE
    manifest = json.loads((NOTICE_SOURCE / "manifest.json").read_text())
    hashes = {r["name"].lower().replace("-", "_"): r["sha256"] for r in manifest["distribution_sources"] if r.get("filename", "").endswith(".whl")}
    lines = [line for line in Path("requirements-release-hashed.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert len(lines) == len(manifest["release_packages"])
    for name, version in manifest["release_packages"].items():
        assert f'{name}=={version} --hash=sha256:{hashes[name.lower().replace("-", "_")]}' in lines


def test_support_replacement_cannot_silently_become_a_plain_module(tmp_path, monkeypatch):
    support = tmp_path / "modified-pyside-support.py"
    support.write_text("synthetic")
    specification = tmp_path / "inputs.json"
    specification.write_text(json.dumps({"schema": 1, "pyside_support": {"path": str(support), "sha256": inputs.sha256(support)}}))
    monkeypatch.setenv("TAXOPS_RECOMBINE_INPUT", str(specification))
    with pytest.raises(ValueError, match="package semantics"):
        inputs.apply_recombination([], [])


@pytest.mark.parametrize("pyside,qt", [("6.10.1", "6.10.2"), ("6.10.2", "6.10.1"), (None, "6.10.2"), ("6.10.2", None)])
def test_recombine_rejects_missing_or_wrong_observed_runtime_versions(pyside, qt):
    with pytest.raises(ValueError, match="observed PySide6"):
        recombine_probe.verify_runtime_versions(pyside, qt)


def test_actual_source_qt_and_binding_versions_are_reported_separately():
    import PySide6
    from PySide6.QtCore import qVersion
    result = recombine_probe.verify_runtime_versions(PySide6.__version__, qVersion())
    assert result == {"pyside_runtime_version": "6.10.2", "qt_runtime_version": "6.10.2"}
