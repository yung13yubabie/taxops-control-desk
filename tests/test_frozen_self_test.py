"""Source checks and synthetic orchestrator contracts, not Windows EXE evidence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_tools import pyinstaller_entry
from build_tools import verify_windows_bundle as gate
from taxops import diagnostics

ROOT = Path(__file__).resolve().parents[1]


def _passing_windows_report():
    report = {"schema": 1, "status": "passed", "app_version": "test", "frozen": True,
            "platform": "win32", "qt_platform": "windows", "network_attempts": [],
            "clean_os_verified": False, "manual_gui_verified": False,
            "checks": [{"name": name, "status": "passed"} for name in gate.EXPECTED_CHECKS]}
    language = next(c for c in report["checks"] if c["name"] == "qt_traditional_chinese_widgets_and_fallback")
    language.update(catalogue_loaded=True, initial_locale="en_US", locale="zh_TW",
                    missing_catalogue={"fully_localized": False})
    return report


def _fake_bundle(root):
    root.mkdir()
    for name in gate._REQUIRED_FILES:
        if name == "taxopscontroldesk.exe":
            name = "TaxOpsControlDesk.exe"
        (root / name).write_bytes(b"synthetic test fixture, not executable")
    return root


def test_source_self_test_runs_real_isolated_roundtrip(tmp_path):
    report = tmp_path / "source.json"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["LOCALAPPDATA"] = str(tmp_path / "must_not_touch")
    env["USERPROFILE"] = str(tmp_path / "must_not_touch_profile")
    process = subprocess.run(
        [sys.executable, "-m", "taxops.diagnostics", "--report", str(report)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert process.returncode == 0, (payload, process.stderr)
    assert payload["status"] == "passed"
    assert payload["frozen"] is False
    assert payload["network_attempts"] == []
    assert gate.EXPECTED_CHECKS.issubset({c["name"] for c in payload["checks"]})
    untouched = [tmp_path / "must_not_touch", tmp_path / "must_not_touch_profile"]
    observed = {
        path.name: [
            {"path": str(child.relative_to(path)), "is_dir": child.is_dir(),
             "bytes": child.stat().st_size if child.is_file() else None}
            for child in path.rglob("*")
        ]
        for path in untouched if path.exists()
    }
    diagnostics_dir = os.environ.get("TAXOPS_UI_DIAGNOSTICS_DIR")
    if diagnostics_dir:
        target = Path(diagnostics_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "self-test-paths.json").write_text(
            json.dumps({"unexpected_paths": observed, "report": payload,
                        "stderr": process.stderr}, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    assert not untouched[0].exists(), observed
    assert not untouched[1].exists(), observed
    from taxops import __version__
    from taxops.db.migrations import MIGRATIONS
    assert payload["app_version"] == __version__
    assert next(c for c in payload["checks"] if c["name"] == "all_migrations")["count"] == len(MIGRATIONS)
    language = next(c for c in payload["checks"] if c["name"] == "qt_traditional_chinese_widgets_and_fallback")
    assert language["initial_locale"] == "en_US" and language["locale"] == "zh_TW"
    assert language["catalogue_loaded"] is True
    assert language["standard_buttons"] == {"Ok": "確定", "Cancel": "取消", "Save": "儲存", "Open": "開啟"}
    assert language["calendar"]["month"] == "1月"
    assert len(language["calendar"]["weekdays"]) == 7
    for kind in ("open", "save", "directory"):
        dialog = language["file_dialogs"][kind]
        assert all(dialog["labels"].values())
        assert dialog["non_native"] is True and dialog["selection_preserved"] is True
        assert dialog["folder_metadata"]["type"] == "資料夾"
        assert dialog["folder_metadata"]["name"] == "合成 English 資料夾"
    fallback = language["missing_catalogue"]
    assert fallback["catalogue_loaded"] is False and fallback["fully_localized"] is False
    assert fallback["status"] == "standard_buttons_only"
    assert fallback["standard_buttons"] == language["standard_buttons"]
    assert all(fallback["file_dialog"]["labels"].values())
    with pytest.raises(gate.BundleVerificationError, match="frozen Windows"):
        gate.validate_report(payload)


def test_source_self_test_exercises_in_process_coverage(tmp_path, qapp):
    before = set(qapp.topLevelWidgets())
    report = tmp_path / "covered-source.json"
    assert diagnostics.run_self_test(report) == 0
    assert json.loads(report.read_text())["status"] == "passed"
    assert set(qapp.topLevelWidgets()) == before


def test_self_test_rejects_source_when_frozen_is_required(tmp_path):
    report = tmp_path / "refused.json"
    assert diagnostics.run_self_test(report, require_frozen=True) == 1
    payload = json.loads(report.read_text())
    assert payload["status"] == "failed"
    assert payload["checks"] == []


def test_network_guard_blocks_audit_events_without_sending_packets():
    attempts = []
    with diagnostics._deny_python_network(attempts):
        with pytest.raises(diagnostics.SelfTestFailure, match="Network operation forbidden"):
            sys.audit("socket.connect", None, ("synthetic.invalid", 443))
    sys.audit("socket.connect", None, ("synthetic.invalid", 443))
    assert attempts == ["socket.connect"]


def test_swallowed_network_attempt_still_fails_report(tmp_path, monkeypatch):
    def swallow(root, report):
        try:
            sys.audit("socket.getaddrinfo", "synthetic.invalid", 443, 0, 0, 0)
        except diagnostics.SelfTestFailure:
            pass
    monkeypatch.setattr(diagnostics, "_run_checks", swallow)
    report = tmp_path / "swallowed.json"
    assert diagnostics.run_self_test(report) == 1
    payload = json.loads(report.read_text())
    assert payload["status"] == "failed"
    assert payload["network_attempts"] == ["socket.getaddrinfo"]


def test_self_test_failure_writes_failure_report_and_cleans_temporary_data(tmp_path, monkeypatch):
    roots = []
    def fail(root, report):
        roots.append(root)
        (root / "synthetic.txt").write_text("fixture")
        raise RuntimeError("injected failure")
    monkeypatch.setattr(diagnostics, "_run_checks", fail)
    report = tmp_path / "failed.json"
    assert diagnostics.run_self_test(report) == 1
    assert json.loads(report.read_text())["error"]["message"] == "injected failure"
    assert roots and all(not root.exists() for root in roots)


def test_frozen_entrypoint_routes_self_test_without_bootstrap(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["app.exe", "--self-test", "--report", "report.json"])
    monkeypatch.setattr(diagnostics, "main", lambda argv: calls.append(argv) or 7)
    monkeypatch.setattr("taxops.ui.app.run", lambda: pytest.fail("Normal UI bootstrap was called"))
    with pytest.raises(SystemExit) as error:
        pyinstaller_entry.main()
    assert error.value.code == 7
    assert calls == [["--report", "report.json"]]


def test_normal_frozen_entrypoint_keeps_application_route(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.exe"])
    monkeypatch.setattr("taxops.ui.app.run", lambda: 23)
    with pytest.raises(SystemExit) as error:
        pyinstaller_entry.main()
    assert error.value.code == 23


@pytest.mark.parametrize("change", [
    {"frozen": False}, {"platform": "linux"}, {"qt_platform": "offscreen"},
    {"status": "failed"}, {"checks": []}, {"network_attempts": ["socket.connect"]},
    {"clean_os_verified": True}, {"manual_gui_verified": True},
])
def test_gate_rejects_incomplete_or_overstated_reports(change):
    report = _passing_windows_report()
    report.update(change)
    with pytest.raises(gate.BundleVerificationError):
        gate.validate_report(report)


def test_gate_requires_every_check_to_pass():
    report = _passing_windows_report()
    report["checks"][0]["status"] = "skipped"
    with pytest.raises(gate.BundleVerificationError, match="absent, failed, or skipped"):
        gate.validate_report(report)


@pytest.mark.parametrize("change", [
    {"catalogue_loaded": False}, {"initial_locale": "zh_TW"}, {"locale": "en_US"},
    {"missing_catalogue": {"fully_localized": True}}, {"missing_catalogue": {}},
])
def test_gate_rejects_partial_or_unexercised_qt_translation(change):
    report = _passing_windows_report()
    language = next(c for c in report["checks"] if c["name"] == "qt_traditional_chinese_widgets_and_fallback")
    language.update(change)
    with pytest.raises(gate.BundleVerificationError, match="Complete Qt translation"):
        gate.validate_report(report)


def test_archive_roundtrip_and_user_data_rejection(tmp_path):
    bundle = _fake_bundle(tmp_path / "bundle")
    archive = tmp_path / "candidate.zip"
    metadata = gate.archive_bundle(bundle, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert "TaxOpsControlDesk/TaxOpsControlDesk.exe" in zipped.namelist()
    assert metadata["sha256"] == gate._sha256(archive)
    (bundle / "customer.sqlite").write_bytes(b"private data must not ship")
    with pytest.raises(gate.BundleVerificationError, match="user data"):
        gate.archive_bundle(bundle, tmp_path / "rejected.zip")
    assert not (tmp_path / "rejected.zip").exists()


def test_archive_requires_native_runtime_files(tmp_path):
    bundle = _fake_bundle(tmp_path / "bundle")
    (bundle / "qtpdf.pyd").unlink()
    with pytest.raises(gate.BundleVerificationError, match="Required Windows files missing"):
        gate.archive_bundle(bundle, tmp_path / "rejected.zip")


def test_isolated_profile_removes_host_python_and_qt_paths(tmp_path, monkeypatch):
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                 "QML2_IMPORT_PATH", "QT_QPA_PLATFORM", "TAXOPS_DEV"):
        monkeypatch.setenv(name, "must_not_inherit")
    env = gate.isolated_environment(tmp_path)
    assert "must_not_inherit" not in env.values()
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "TEMP", "TMP"):
        assert Path(env[name]).is_dir()
        assert Path(env[name]).is_relative_to(tmp_path)


def test_gate_executes_extracted_artifact_and_preserves_tested_zip(tmp_path, monkeypatch):
    bundle = _fake_bundle(tmp_path / "bundle")
    output = tmp_path / "output"
    launched = []
    stdlib_run = subprocess.run
    # Windows platform.platform() may use subprocess.check_output("ver").
    # Exercise a real stdlib probe while only the gate's EXE launcher is mocked.
    def platform_probe():
        return subprocess.check_output(
            [sys.executable, "-c", "print('synthetic-platform-probe')"], text=True,
        ).strip()
    monkeypatch.setattr(gate, "platform", SimpleNamespace(
        platform=platform_probe, python_version=gate.platform.python_version,
        machine=gate.platform.machine,
    ))
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="win32"))
    def fake_run(argv, **kwargs):
        exe = Path(argv[0])
        assert exe != bundle / "TaxOpsControlDesk.exe"
        assert "移動後的程式 資料夾" in str(exe)
        assert exe.is_file()
        assert "--require-frozen" in argv
        launched.append(exe)
        Path(argv[-1]).write_text(json.dumps(_passing_windows_report()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(gate, "subprocess", SimpleNamespace(run=fake_run))
    assert subprocess.run is stdlib_run
    result = gate.verify_bundle(bundle, output)
    assert result["runner_os"] == "synthetic-platform-probe"
    assert len(launched) == 1
    candidate = output / "TaxOpsControlDesk-windows-candidate.zip"
    assert result["sha256"] == gate._sha256(candidate)
    assert not launched[0].exists()
    assert json.loads((output / "bundle-provenance.json").read_text())["status"] == "passed"


@pytest.mark.parametrize("failure", ["missing_report", "timeout"])
def test_gate_failure_never_publishes_candidate(tmp_path, monkeypatch, failure):
    bundle = _fake_bundle(tmp_path / "bundle")
    output = tmp_path / "output"
    monkeypatch.setattr(gate, "sys", SimpleNamespace(platform="win32"))
    def fake_run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(gate, "subprocess", SimpleNamespace(run=fake_run))
    with pytest.raises((gate.BundleVerificationError, subprocess.TimeoutExpired)):
        gate.verify_bundle(bundle, output)
    assert not (output / "TaxOpsControlDesk-windows-candidate.zip").exists()
    assert json.loads((output / "bundle-provenance.json").read_text())["status"] == "failed"


def test_windows_workflow_is_nonpublishing_and_pinned():
    workflow = (ROOT / ".github/workflows/windows-candidate.yml").read_text()
    assert "pull_request:" in workflow and "workflow_dispatch:" in workflow
    assert "pull_request_target" not in workflow
    assert "contents: read" in workflow and "contents: write" not in workflow
    assert "secrets." not in workflow
    assert "persist-credentials: false" in workflow
    assert "build_tools.verify_windows_bundle" in workflow
    assert "build_tools.run_test_matrix" in workflow
    assert "--files" not in workflow
    for line in workflow.splitlines():
        if "uses:" in line:
            pin = line.split("@", 1)[1].split()[0]
            assert len(pin) == 40 and all(c in "0123456789abcdef" for c in pin)


@pytest.mark.parametrize("fail", [False, True])
def test_self_test_scopes_profile_paths_and_restores_environment(tmp_path, monkeypatch, fail):
    keys = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME")
    previous = {}
    for index, key in enumerate(keys):
        if index % 2:
            monkeypatch.delenv(key, raising=False)
            previous[key] = None
        else:
            prior = tmp_path / f"original-{key}"
            prior.mkdir()
            (prior / "preserved.txt").write_text("original synthetic state")
            monkeypatch.setenv(key, str(prior))
            previous[key] = str(prior)
    observed = {}

    def synthetic_native_write(root, report):
        observed.update({key: Path(os.environ.get(key, "")) for key in keys})
        assert all(path.is_relative_to(root) for path in observed.values())
        cache = observed["LOCALAPPDATA"] / "Microsoft" / "Windows" / "Caches"
        cache.mkdir(parents=True)
        (cache / "synthetic-cache.bin").write_bytes(b"synthetic")
        if fail:
            raise OSError("ordinary synthetic check failure")

    monkeypatch.setattr(diagnostics, "_run_checks", synthetic_native_write)
    report = tmp_path / "profile-scope.json"
    assert diagnostics.run_self_test(report) == int(fail)
    payload = json.loads(report.read_text())
    assert payload["status"] == ("failed" if fail else "passed")
    if fail:
        assert payload["error"]["message"] == "ordinary synthetic check failure"
    assert {key: os.environ.get(key) for key in keys} == previous
    assert observed and all(not path.exists() for path in observed.values())
    for value in previous.values():
        if value is not None:
            assert sorted(p.name for p in Path(value).iterdir()) == ["preserved.txt"]
            assert (Path(value) / "preserved.txt").read_text() == "original synthetic state"


def test_profile_setup_failure_restores_environment_before_checks(tmp_path, monkeypatch):
    before = dict(os.environ)
    original_mkdir = Path.mkdir
    called = []

    def fail_profile_roaming(path, *args, **kwargs):
        if path.name == "roaming" and path.parent.name == "profile":
            raise OSError("synthetic profile setup failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_profile_roaming)
    monkeypatch.setattr(diagnostics, "_run_checks", lambda root, report: called.append(root))
    report = tmp_path / "setup-failure.json"
    assert diagnostics.run_self_test(report) == 1
    assert json.loads(report.read_text())["error"]["message"] == "synthetic profile setup failure"
    assert dict(os.environ) == before
    assert called == []
