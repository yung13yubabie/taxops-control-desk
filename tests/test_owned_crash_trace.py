"""Bounded trace contracts; source child runs are not frozen Windows evidence."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_tools import trace_owned_crash as trace


@pytest.mark.parametrize("code", [77, 0, 1])
def test_actual_owned_source_child_code_and_raw_streams_are_saved(tmp_path, code):
    ready = tmp_path / "ready.json"
    script = (
        "import os,json; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text(json.dumps({{'loaded_modules':{{'process_id':os.getpid()}}}})); "
        "os.write(1,b'raw stdout\\xff'); os.write(2,b'raw stderr\\xfe'); "
        f"os._exit({code})"
    )
    result = trace.run_recorded(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=dict(trace.isolated_environment(tmp_path / "synthetic")),
        prefix=tmp_path / "owned",
        timeout=15,
        expected_exit=77,
        ready=ready,
    )
    assert result["bootloader_exit_code"] == code
    assert result["status"] == ("matched_expected_exit" if code == 77 else "failed")
    assert (tmp_path / "owned.stdout.bin").read_bytes() == b"raw stdout\xff"
    assert (tmp_path / "owned.stderr.bin").read_bytes() == b"raw stderr\xfe"
    assert (
        result["child_pid_reported"]
        == json.loads(ready.read_text())["loaded_modules"]["process_id"]
    )
    assert (
        result["child_exit_code"] is None
        and result["child_exit_code_observed"] is False
    )
    assert result["child_parent_pid_reported"] is None
    assert json.loads((tmp_path / "owned.process.json").read_text()) == result


def test_source_initialization_uses_owned_ready_release_then_waits(tmp_path):
    ready, release = tmp_path / "ready.json", tmp_path / "release"
    script = (
        "import os,json,time; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text(json.dumps({{'process_id':os.getpid()}}))\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
    )
    result = trace.run_recorded(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=dict(trace.isolated_environment(tmp_path / "synthetic")),
        prefix=tmp_path / "owned",
        timeout=15,
        expected_exit=0,
        ready=ready,
        release=release,
    )
    assert result["bootloader_exit_code"] == 0 and release.is_file()


def test_timeout_cleanup_is_failure_only_and_records_unobserved_inner_code(
    tmp_path, monkeypatch
):
    import subprocess

    class Process:
        pid = 1234
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("owned synthetic", timeout)

    process = Process()
    monkeypatch.setattr(
        trace, "subprocess", SimpleNamespace(Popen=lambda *a, **k: process)
    )
    cleaned = []

    def cleanup(target, path):
        assert target is process
        cleaned.append(path)
        process.returncode = 9
        return {"status": "synthetic forced cleanup"}

    monkeypatch.setattr(trace, "terminate_owned_tree", cleanup)
    result = trace.run_recorded(
        ["synthetic.exe"],
        cwd=tmp_path,
        env={},
        prefix=tmp_path / "owned",
        timeout=1,
        expected_exit=77,
    )
    assert result["status"] == "failed" and len(cleaned) == 1
    assert result["exit_code_before_forced_cleanup"] is None
    assert result["bootloader_exit_code"] == 9 and result["normal_cleanup"] is False
    assert result["child_exit_code_observed"] is False
    assert result["error"]["type"] == "TimeoutExpired"


def test_spawn_failure_is_recorded_without_guessing_any_exit_code(
    tmp_path, monkeypatch
):
    def failed(*args, **kwargs):
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(trace, "subprocess", SimpleNamespace(Popen=failed))
    result = trace.run_recorded(
        ["synthetic.exe"],
        cwd=tmp_path,
        env={},
        prefix=tmp_path / "owned",
        timeout=1,
        expected_exit=77,
    )
    assert result["status"] == "failed" and result["bootloader_exit_code"] is None
    assert (
        result["bootloader_pid"] is None and result["child_exit_code_observed"] is False
    )
    assert (
        json.loads((tmp_path / "owned.process.json").read_text())["error"]["type"]
        == "OSError"
    )


def test_trace_refuses_other_platform_or_wrong_exe_before_creating_output(
    tmp_path, monkeypatch
):
    exe = tmp_path / "synthetic.exe"
    exe.write_bytes(b"synthetic, not executable")
    output = tmp_path / "output"
    monkeypatch.setattr(trace, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(ValueError, match="Windows"):
        trace.trace(exe, trace.sha256(exe), output)
    monkeypatch.setattr(trace, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(ValueError, match="SHA-256"):
        trace.trace(exe, "0" * 64, output)
    assert not output.exists()
    output.mkdir()
    with pytest.raises(FileExistsError):
        trace.trace(exe, trace.sha256(exe), output)


def test_trace_isolation_and_exact_two_commands_without_process_scanning(
    tmp_path, monkeypatch
):
    exe = tmp_path / "synthetic.exe"
    exe.write_bytes(b"synthetic, not executable")
    monkeypatch.setattr(trace, "sys", SimpleNamespace(platform="win32"))
    calls = []

    def record(command, **kwargs):
        calls.append((command, kwargs))
        profile = Path(command[command.index("--profile-root") + 1])
        token = command[command.index("--profile-token") + 1]
        assert profile.parent == tmp_path / "new output"
        assert (profile / ".taxops-onefile-gate").read_text() == token
        for key, directory in {
            "LOCALAPPDATA": "local",
            "APPDATA": "roaming",
            "USERPROFILE": "user",
            "HOME": "user",
            "TEMP": "temp",
            "TMP": "temp",
        }.items():
            assert Path(kwargs["env"][key]) == profile / directory
        assert trace.sha256(Path(command[0])) == trace.sha256(exe)
        kwargs["ready"].write_text("{}")
        return {
            "status": "matched_expected_exit",
            "bootloader_exit_code": kwargs["expected_exit"],
        }

    monkeypatch.setattr(trace, "run_recorded", record)
    result = trace.trace(exe, trace.sha256(exe), tmp_path / "new output")
    assert len(calls) == 2 and result["status"] == "matched_expected_exit"
    assert (
        "--initialize-persistence" in calls[0][0]
        and "--crash-after-ready" not in calls[0][0]
    )
    assert (
        "--crash-after-ready" in calls[1][0]
        and "--initialize-persistence" not in calls[1][0]
    )
    assert calls[1][1]["expected_exit"] == 77 and calls[1][1]["release"] is None
    assert result["preserved_extraction_directories"] == []
