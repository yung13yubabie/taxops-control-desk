"""Failure-only ownership checks; not actual Windows process termination evidence."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from build_tools import owned_process_cleanup as cleanup


def test_only_exact_owned_pid_is_targeted_without_shell_or_image_scan(tmp_path, monkeypatch):
    calls = []
    process = SimpleNamespace(pid=1234, _handle=object(), poll=lambda: None, wait=lambda timeout: 77)
    monkeypatch.setattr(cleanup, "system_taskkill", lambda: Path("C:/Windows/System32/taskkill.exe"))
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="synthetic", stderr="")
    monkeypatch.setattr(cleanup, "subprocess", SimpleNamespace(run=run, TimeoutExpired=TimeoutError))
    evidence = tmp_path / "cleanup.json"
    result = cleanup.terminate_owned_tree(process, evidence)
    assert calls[0][0] == ["C:/Windows/System32/taskkill.exe", "/PID", "1234", "/T", "/F"]
    assert "shell" not in calls[0][1]
    assert result["normal_cleanup"] is False and result["descendant_cleanup_verified"] is False
    assert json.loads(evidence.read_text())[0]["pid"] == 1234


@pytest.mark.parametrize("exited,handle", [(True, True), (False, False)])
def test_no_live_handle_means_no_pid_kill(tmp_path, monkeypatch, exited, handle):
    process = SimpleNamespace(pid=1234, poll=lambda: 0 if exited else None)
    if handle:
        process._handle = object()
    def forbidden():
        raise AssertionError("Must not resolve a kill command")
    monkeypatch.setattr(cleanup, "system_taskkill", forbidden)
    result = cleanup.terminate_owned_tree(process, tmp_path / "cleanup.json")
    assert result["status"] in {"failed", "parent_already_exited_children_unverified"}


def test_taskkill_failure_does_not_claim_descendants_gone(tmp_path, monkeypatch):
    process = SimpleNamespace(pid=1234, _handle=object(), poll=lambda: None, wait=lambda timeout: 77)
    monkeypatch.setattr(cleanup, "system_taskkill", lambda: Path("verified/taskkill.exe"))
    monkeypatch.setattr(cleanup, "subprocess", SimpleNamespace(run=lambda *a, **kw: SimpleNamespace(returncode=128, stdout="", stderr="parent exited"), TimeoutExpired=TimeoutError))
    result = cleanup.terminate_owned_tree(process, tmp_path / "cleanup.json")
    assert result["status"] == "tree_termination_failed_or_parent_exited_during_request"
    assert result["descendant_cleanup_verified"] is False
