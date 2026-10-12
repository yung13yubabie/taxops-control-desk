"""Synthetic contract tests; these are not native Windows font acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

from build_tools import native_font_probe as probe


def test_non_windows_is_explicit_failure_with_json(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux", executable=sys.executable))
    assert probe.main(["--output-dir", str(tmp_path)]) == 2
    report = json.loads((tmp_path / "native-font-probe.json").read_text())
    assert not report["passed"]
    assert "no offscreen fallback" in report["error"]


def test_native_worker_abort_preserves_preflight_and_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    def aborted(command, **kwargs):
        assert kwargs["env"]["QT_QPA_PLATFORM"] == "windows"
        assert "--worker" in command
        for key in ("APPDATA", "LOCALAPPDATA", "XDG_CACHE_HOME", "HOME", "USERPROFILE", "TEMP", "TMP"):
            assert "taxops-native-font-" in kwargs["env"][key]
            assert str(tmp_path) != kwargs["env"][key]
        return SimpleNamespace(returncode=3, stdout="", stderr="plugin failed")
    monkeypatch.setattr(probe, "subprocess", SimpleNamespace(run=aborted))
    assert subprocess.check_output([sys.executable, "-c", "print(123)"], text=True).strip() == "123"
    assert sys.platform != probe.sys.platform or sys is not probe.sys
    assert probe.main(["--output-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "native-font-probe.json").read_text())
    assert report["worker_returncode"] == 3
    assert not report["passed"]
    assert "before completing" in report["error"]
    assert (tmp_path / "native-font-probe.stderr.txt").read_text() == "plugin failed"


def test_native_worker_timeout_is_nonzero_with_json(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 90)
    monkeypatch.setattr(probe, "subprocess", SimpleNamespace(run=timeout))
    assert probe.main(["--output-dir", str(tmp_path)]) == 1
    assert json.loads((tmp_path / "native-font-probe.json").read_text())["stage"] == "supervisor"


def test_capture_records_actual_glyphs_and_backend(qapp, tmp_path):
    original_stylesheet = qapp.styleSheet()
    original_icon = qapp.windowIcon()
    try:
        report = probe.capture_probe(tmp_path)
        assert report["qt_platform"] == qapp.platformName()
        assert report["font_family_count"] == len(report["font_families"])
        assert report["png_saved"]
        assert (tmp_path / report["png_filename"]).is_file()
        assert {r["widget_class"] for r in report["samples"]} >= {"QLabel", "QLineEdit", "QPushButton", "QComboBox", "QTableWidget"}
        assert all("glyph_runs" in r and "missing_codepoints" in r for r in report["samples"])
        latin = next(r for r in report["samples"] if r["name"] == "latin")
        assert latin["glyph_runs"]
        assert all("coverage" in r and "glyph_indexes" in r for r in latin["glyph_runs"])
        if qapp.platformName() != "windows":
            assert not report["passed"]
    finally:
        qapp.setStyleSheet(original_stylesheet)
        qapp.setWindowIcon(original_icon)


def test_worker_exception_preserves_qt_checkpoint(tmp_path, monkeypatch):
    def fail(output):
        probe._write(output / "native-font-probe.json", {
            "passed": False, "qt_platform": "windows", "font_families": ["example"],
        })
        raise RuntimeError("synthetic capture failure")
    monkeypatch.setattr(probe, "capture_probe", fail)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert probe.main(["--worker", "--output-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "native-font-probe.json").read_text())
    assert report["qt_platform"] == "windows"
    assert report["font_families"] == ["example"]
    assert "synthetic capture failure" in report["error"]
    assert probe.os.environ["QT_QPA_PLATFORM"] == "windows"


def test_success_and_glyph_failure_propagate(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    for passed in (True, False):
        def finished(command, **kwargs):
            probe._write(tmp_path / "native-font-probe.json", {
                "passed": passed, "qt_platform": "windows", "samples": [],
            })
            return SimpleNamespace(returncode=0 if passed else 1, stdout="", stderr="")
        monkeypatch.setattr(probe, "subprocess", SimpleNamespace(run=finished))
        assert probe.main(["--output-dir", str(tmp_path)]) == (0 if passed else 1)
        assert json.loads((tmp_path / "native-font-probe.json").read_text())["passed"] == passed


def test_supervisor_rejects_report_claiming_offscreen_success(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    def finished(command, **kwargs):
        probe._write(tmp_path / "native-font-probe.json", {
            "passed": True, "qt_platform": "offscreen",
        })
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(probe, "subprocess", SimpleNamespace(run=finished))
    assert probe.main(["--output-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "native-font-probe.json").read_text())
    assert not report["passed"]
    assert "native Windows" in report["error"]
