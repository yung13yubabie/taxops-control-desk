"""Synthetic contracts for the per-file process/coverage gate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest
from build_tools import run_test_matrix as matrix


@pytest.mark.parametrize(("value", "expected"), [(89.999999, False), (90.0, True), (90.000001, True), (True, False), ("90", False), (float("inf"), False), (float("nan"), False)])
def test_raw_coverage_gate_does_not_round_up(value, expected):
    assert matrix.coverage_meets_gate({"meta": {"branch_coverage": True}, "totals": {"percent_covered": value}}) is expected
    assert not matrix.coverage_meets_gate({"meta": {"branch_coverage": False}, "totals": {"percent_covered": value}})


def _fixture(tmp_path, monkeypatch, *, percentage=91.0, first_exit=0, timeout=False):
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    for name in ("test_alpha.py", "test_beta.py"):
        (tests / name).write_text("# synthetic fixture only\n")
    monkeypatch.setattr(matrix, "ROOT", root)
    monkeypatch.setattr(matrix, "source_identity", lambda _root: {"source_commit": "synthetic", "source_tree": "synthetic-tree"})
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        if "pytest" in command:
            if timeout:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            junit = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
            code = first_exit if "test_alpha.py" in command[command.index("pytest") + 1] else 0
            if code >= 0:
                junit.write_text(f'<testsuites><testsuite tests="1" failures="{int(code != 0)}" errors="0" skipped="0"/></testsuites>')
            return subprocess.CompletedProcess(command, code, "synthetic output", "")
        if "json" in command:
            Path(command[-1]).write_text(json.dumps({"meta": {"branch_coverage": True}, "totals": {"percent_covered": percentage}}))
        return subprocess.CompletedProcess(command, 0, "synthetic coverage output", "")
    monkeypatch.setattr(matrix, "subprocess", SimpleNamespace(
        run=fake_run, TimeoutExpired=subprocess.TimeoutExpired,
    ))
    return root, calls


def test_each_file_gets_own_process_then_coverage_is_combined(tmp_path, monkeypatch):
    stdlib_run = subprocess.run
    root, calls = _fixture(tmp_path, monkeypatch)
    assert subprocess.run is stdlib_run
    result = matrix.run_matrix(tmp_path / "output")
    assert result["status"] == "passed" and result["full_suite"] is True
    children = [command for command in calls if "pytest" in command]
    assert len(children) == 2
    assert all("--parallel-mode" in command and "--branch" in command for command in children)
    assert result["totals"]["tests"] == 2
    assert [row["exit_code"] for row in result["files"]] == [0, 0]
    assert [row["file"] for row in result["files"]] == ["tests/test_alpha.py", "tests/test_beta.py"]
    assert (tmp_path / "output" / "matrix.json").is_file()


@pytest.mark.parametrize(("percentage", "first_exit"), [(89.999999, 0), (99.0, 1)])
def test_coverage_or_test_failure_blocks_matrix(tmp_path, monkeypatch, percentage, first_exit):
    _fixture(tmp_path, monkeypatch, percentage=percentage, first_exit=first_exit)
    result = matrix.run_matrix(tmp_path / "output")
    assert result["status"] == "failed"
    assert len(result["files"]) == 2


@pytest.mark.parametrize("kind", ["crash", "timeout"])
def test_crash_or_timeout_records_unrun_files(tmp_path, monkeypatch, kind):
    _fixture(tmp_path, monkeypatch, first_exit=-11 if kind == "crash" else 0, timeout=kind == "timeout")
    result = matrix.run_matrix(tmp_path / "output")
    assert result["status"] == "failed"
    assert len(result["files"]) == 1
    assert result["unrun_files"] == ["tests/test_beta.py"]


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_report_paths_use_posix_separators_for_both_host_flavors(monkeypatch, path_type):
    root = path_type("repo")
    monkeypatch.setattr(matrix, "ROOT", root)
    assert matrix._report_path(root / "tests" / "test_beta.py") == "tests/test_beta.py"


def test_existing_results_are_not_reused(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    matrix.run_matrix(tmp_path / "output")
    with pytest.raises(ValueError, match="fresh matrix"):
        matrix.run_matrix(tmp_path / "output")


def test_subset_is_not_reported_as_full_suite(tmp_path, monkeypatch):
    root, _ = _fixture(tmp_path, monkeypatch)
    result = matrix.run_matrix(tmp_path / "output", files=[root / "tests/test_alpha.py"])
    assert result["full_suite"] is False
    with pytest.raises(ValueError, match="repository test"):
        matrix.run_matrix(tmp_path / "other", files=[tmp_path / "unrelated.py"])
