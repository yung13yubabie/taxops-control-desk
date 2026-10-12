"""Fail-closed onefile gate contracts, not a bootloader execution substitute."""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from build_tools import verify_onefile as gate
from build_tools import onefile_runtime_probe as probe


def report_fixture(tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    database = tmp_path / "local/TaxOpsControlDesk/taxops.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"synthetic")
    report = {"meipass": str(temp / "_MEI123"), "frozen": True, "platform": "win32", "normal_exit": True,
              "exit_code": 0, "native_files": {"a.dll": "hash"}, "bootstrap_calls": 1, "guard_acquired": True,
              "window_shown": True, "migration_count": 28, "db_path": str(database)}
    return temp, database, report


@pytest.mark.parametrize("fault", [None, "remains", "outside", "not_frozen", "wrong_bytes", "db_in_mei", "missing_migration", "twice"])
def test_normal_cleanup_requires_exact_actual_mei_absent_and_db_separate(tmp_path, fault):
    temp, database, report = report_fixture(tmp_path)
    if fault == "remains":
        Path(report["meipass"]).mkdir()
    elif fault == "outside":
        report["meipass"] = str(tmp_path / "outside")
    elif fault == "not_frozen":
        report["frozen"] = False
    elif fault == "wrong_bytes":
        report["native_files"]["a.dll"] = "wrong"
    elif fault == "db_in_mei":
        report["db_path"] = str(Path(report["meipass"]) / "taxops.sqlite")
    elif fault == "missing_migration":
        report["migration_count"] = 27
    elif fault == "twice":
        report["bootstrap_calls"] = 2
    if fault:
        with pytest.raises(gate.BundleVerificationError):
            gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=True)
    else:
        gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=True)


def test_duplicate_instance_must_not_bootstrap(tmp_path):
    temp, database, report = report_fixture(tmp_path)
    report.update(bootstrap_calls=0, guard_acquired=False, window_shown=False)
    gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=False)
    report["bootstrap_calls"] = 1
    with pytest.raises(gate.BundleVerificationError):
        gate.check_lifecycle_report(report, temp=temp, database=database, expected_native={"a.dll": "hash"}, primary=False)


def test_probe_does_not_claim_source_execution_is_bootloader_proof(tmp_path):
    path = tmp_path / "report.json"
    args = ["--report", str(path), "--ready", str(tmp_path / "ready"), "--release", str(tmp_path / "release"), "--instance-name", "synthetic", "--profile-root", str(tmp_path), "--profile-token", "synthetic", "--persistent-record", str(tmp_path / "record")]
    assert probe.main(args) == 1
    assert json.loads(path.read_text())["normal_exit"] is False


def test_gate_refuses_non_windows_before_creating_any_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(gate.BundleVerificationError, match="Windows"):
        gate.verify(tmp_path / "app.exe", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("fault", [None, "skip", "partial", "coverage", "unrun"])
def test_source_gate_requires_complete_zero_skip_unrounded_coverage(tmp_path, monkeypatch, fault):
    from build_tools import run_test_matrix
    monkeypatch.setattr(run_test_matrix, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "source_identity", lambda _root: {"source_tree": "synthetic"})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_synthetic.py").write_text("synthetic")
    report = {"status": "passed", "source_identity": {"source_tree": "synthetic"}, "source_unchanged": True,
              "full_suite": True, "unrun_files": [], "branch_coverage": True,
              "raw_percent_covered": 90.01, "files": [{"file": "tests/test_synthetic.py", "status": "passed", "exit_code": 0, "skipped": 0}],
              "totals": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}}
    if fault == "skip":
        report["files"][0]["skipped"] = 1
    elif fault == "partial":
        report["full_suite"] = False
    elif fault == "coverage":
        report["raw_percent_covered"] = 89.9999999
    elif fault == "unrun":
        report["unrun_files"] = ["test_synthetic.py"]
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(report))
    if fault:
        with pytest.raises(gate.BundleVerificationError):
            gate.check_source_matrix(path)
    else:
        assert gate.check_source_matrix(path)["raw_branch_coverage"] == 90.01


def test_probe_refuses_profile_environment_escape_before_importing_app(tmp_path, monkeypatch):
    (tmp_path / ".taxops-onefile-gate").write_text("synthetic")
    for key, name in {"LOCALAPPDATA":"local", "APPDATA":"roaming", "USERPROFILE":"user", "HOME":"user", "TEMP":"temp", "TMP":"temp"}.items():
        monkeypatch.setenv(key, str(tmp_path / name))
    monkeypatch.delenv("TAXOPS_DEV", raising=False)
    probe.require_isolated_profile(tmp_path, "synthetic")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path.parent / "outside"))
    with pytest.raises(ValueError, match="LOCALAPPDATA"):
        probe.require_isolated_profile(tmp_path, "synthetic")


def test_real_service_fixture_survives_database_close_and_reopen(tmp_path):
    from taxops.ui.app import bootstrap
    from taxops.core.paths import resolve_paths
    paths = resolve_paths(override_root=tmp_path / "profile")
    record = tmp_path / "record.json"
    container = bootstrap(paths)
    expected = probe.persistent_client(container, record, initialize=True)
    container.close()
    container = bootstrap(paths)
    try:
        assert probe.persistent_client(container, record, initialize=False) == expected
        with pytest.raises(ValueError, match="already exist"):
            probe.persistent_client(container, record, initialize=True)
        container.conn.execute("DELETE FROM clients WHERE id=?", (expected["id"],))
        container.conn.commit()
        with pytest.raises(ValueError, match="survive"):
            probe.persistent_client(container, record, initialize=False)
    finally:
        container.close()


@pytest.mark.parametrize("code", [77, 0, 1, -1, 3221225477])
def test_owned_crash_actual_outer_code_is_preserved_before_strict_77_assertion(code):
    provenance = {}
    if code == 77:
        gate.check_owned_crash_exit(code, 1234, provenance)
    else:
        with pytest.raises(gate.BundleVerificationError, match=f"observed outer bootloader {code}"):
            gate.check_owned_crash_exit(code, 1234, provenance)
    assert provenance["owned_crash_process"] == {
        "bootloader_pid": 1234, "bootloader_exit_code": code,
        "bootloader_exit_code_hex": f"0x{code & 0xffffffff:08x}",
        "requested_child_exit_code": 77, "child_exit_code": None,
        "child_exit_code_observed": False,
    }
