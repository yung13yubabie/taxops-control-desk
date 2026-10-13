"""Windows-only, synthetic cross-process diagnosis of the real notification path.

A completed diagnostic is not application, frozen-EXE or window acceptance.
No timeout, frame, retry rule or notification verdict is changed by this probe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from build_tools.owned_process_cleanup import terminate_owned_tree
from build_tools.verify_windows_bundle import isolated_environment

CASES = ("immediate", "delayed_accept", "accepted_no_dispatch", "never_accept", "peer_close")
HOLD_SECONDS = 0.8
CONTROL_TIMEOUT = 15
TRACE_LIMIT = 64

def write_json(path: Path, value: dict) -> None:
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)

def wait_marker(path: Path, *, process=None) -> None:
    deadline = time.monotonic() + CONTROL_TIMEOUT
    while not path.is_file():
        if (process is not None and process.poll() is not None) or time.monotonic() >= deadline:
            raise RuntimeError("Synthetic control handshake did not complete")
        time.sleep(0.005)


class SocketTrace:
    """Observe scalars only; never retain a socket or prolong pending writes."""

    def __init__(self, socket_type, directory: Path, case: str):
        self.socket_type, self.directory, self.case = socket_type, directory, case
        self.events: list[dict] = []
        self.originals: dict = {}
        self.started = time.monotonic_ns()
        self.observed_error = False
        self.bytes_written = 0
        self.terminal = None
        self.truncated = False

    def record(self, phase: str, socket=None, **extra):
        now = time.monotonic_ns()
        row = {"phase": phase, "monotonic_ns": now,
               "observer_elapsed_ms": (now - self.started) / 1_000_000,
               "observed_error": self.observed_error,
               "bytes_written_signal_total": self.bytes_written, **extra}
        if socket is not None:
            row.update(pending_bytes=socket.bytesToWrite(), state=socket.state().value,
                       valid=socket.isValid(), socket_error_code=socket.error().value)
        if phase == "before_disconnectFromServer":
            self.terminal = row  # Before cleanup can manufacture a disconnected state.
        if len(self.events) < TRACE_LIMIT:
            self.events.append(row)
        else:
            self.truncated = True

    def written(self, count):
        self.bytes_written += count
        self.record("bytes_written", count=count)

    def error(self, error):
        self.observed_error = True
        self.record("socket_error", code=error.value)

    def __enter__(self):
        for method in ("connectToServer", "write", "flush", "waitForBytesWritten", "disconnectFromServer"):
            original = getattr(self.socket_type, method)
            self.originals[method] = original
            def observed(socket, *args, _method=method, _original=original):
                if _method == "connectToServer":
                    # These callbacks close over this trace, never the socket.
                    socket.bytesWritten.connect(self.written)
                    socket.errorOccurred.connect(self.error)
                extra = {"requested_wait_ms": args[0]} if _method == "waitForBytesWritten" else {}
                self.record("before_" + _method, socket, **extra)
                result = _original(socket, *args)
                self.record("after_" + _method, socket, result=result)
                if _method == "connectToServer" and self.case in {"accepted_no_dispatch", "peer_close"}:
                    if (socket.state() == self.socket_type.LocalSocketState.ConnectedState
                            and socket.isValid()):
                        self.record("begin_connected_marker")
                        (self.directory / "connected").write_text("connected and valid", encoding="ascii")
                        self.record("end_connected_marker")
                        self.record("begin_write_permission_handshake")
                        wait_marker(self.directory / "allow-write")
                        self.record("end_write_permission_handshake")
                elif _method == "write" and self.case in {"delayed_accept", "accepted_no_dispatch"}:
                    self.record("begin_write_marker")
                    write_json(self.directory / "write-returned", {"accepted_bytes": result})
                    self.record("end_write_marker")
                return result
            setattr(self.socket_type, method, observed)
        return self

    def __exit__(self, *exc):
        for method, original in self.originals.items():
            setattr(self.socket_type, method, original)

def actor(role: str, directory: Path, case: str, token: str) -> int:
    if sys.platform != "win32":
        raise RuntimeError("Native pipe diagnosis requires Windows")
    if not token or (directory.parent / ".probe-owned").read_text(encoding="ascii") != token:
        raise RuntimeError("A harness-owned synthetic directory is required")
    from PySide6.QtCore import QCoreApplication, QTimer, qVersion
    from PySide6.QtNetwork import QLocalSocket
    from taxops.ui.single_instance import SingleInstanceGuard
    app = QCoreApplication([])
    guard = SingleInstanceGuard("TaxOpsNotifyProbe." + token + "." + case,
                                lock_directory=directory / "locks")
    import PySide6
    report = {"role": role, "case": case, "qt_version": qVersion(),
              "pyside_version": PySide6.__version__, "python_version": list(sys.version_info[:3]),
              "application_type": "QCoreApplication",
              "single_instance_source_sha256": hashlib.sha256(
                  Path(sys.modules[SingleInstanceGuard.__module__].__file__).read_bytes()).hexdigest(),
              "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "status": "failed"}
    trace = None
    try:
        if report["qt_version"] != "6.10.2" or report["pyside_version"] != "6.10.2":
            raise RuntimeError("The diagnostic requires the pinned Qt/PySide version")
        if role == "sender":
            with SocketTrace(QLocalSocket, directory, case) as trace:
                result = guard.notify_existing()  # The unchanged production implementation.
            report.update(notify_result=result, notification=dict(guard._notification_diagnostics),
                          trace=trace.events, terminal_before_disconnect=trace.terminal,
                          trace_truncated=trace.truncated, status="diagnostic_complete")
            (directory / "sender-done").write_text("notify returned", encoding="ascii")
        else:
            events = report["events"] = []
            def observe(phase):
                events.append({"phase": phase, "monotonic_ns": time.monotonic_ns()})
            guard.activation_requested.connect(lambda: observe("activation_received"))
            assert guard.acquire()
            observe("listening")
            guard._server.newConnection.connect(lambda: observe("accepted_connection"))
            (directory / "listening").write_text("real Qt server listening", encoding="ascii")
            if case == "delayed_accept":
                wait_full_write_marker(directory)
                observe("begin_accept_hold")
                time.sleep(HOLD_SECONDS)  # Controlled experiment, not a product timeout.
            elif case == "accepted_no_dispatch":
                wait_marker(directory / "connected")
                guard._server.waitForNewConnection(1000)
                if len(guard._activation_buffers) != 1:
                    raise RuntimeError("The real peer was not accepted before the dispatch hold")
                observe("accepted_before_write")
                (directory / "allow-write").write_text("real peer accepted", encoding="ascii")
                wait_full_write_marker(directory)
                observe("begin_dispatch_hold")
                time.sleep(HOLD_SECONDS)
            elif case == "never_accept":
                wait_marker(directory / "sender-done")
            elif case == "peer_close":
                wait_marker(directory / "connected")
                guard.release()
                observe("peer_closed_before_write")
                (directory / "allow-write").write_text("peer closed", encoding="ascii")
                wait_marker(directory / "sender-done")
            if case not in {"never_accept", "peer_close"}:
                observe("begin_dispatch")
                resume = time.monotonic()
                timer = QTimer()
                def check_finished():
                    if ((directory / "sender-done").is_file() and time.monotonic() - resume >= 0.3):
                        app.quit()
                timer.timeout.connect(check_finished)
                timer.start(20)
                QTimer.singleShot(CONTROL_TIMEOUT * 1000, app.quit)
                app.exec()
                if not (directory / "sender-done").is_file():
                    raise RuntimeError("The sender did not finish during receiver observation")
            report.update(events=events,
                          activation_count=sum(event["phase"] == "activation_received" for event in events),
                          status="diagnostic_complete")
    except Exception as exc:
        report["error_type"] = type(exc).__name__  # No raw exception/path/environment.
        return 1
    finally:
        if trace is not None:
            report.update(trace=trace.events, terminal_before_disconnect=trace.terminal,
                          trace_truncated=trace.truncated,
                          notification=dict(guard._notification_diagnostics))
        guard.release()
        write_json(directory / (role + ".json"), report)
    return 0

def summarize_process_output(handle) -> dict:
    """Raw actor output is private transient input, never an upload artifact."""
    handle.seek(0)
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: handle.read(65536), b""):
        digest.update(block)
        size += len(block)
    return {"output_bytes": size, "output_sha256": digest.hexdigest(),
            "raw_text_omitted": True}


def cleanup_owned_processes(processes: list, directory: Path) -> None:
    safe_records = []
    for role, process in zip(("receiver", "sender"), processes):
        if process.poll() is None:
            try:
                cleanup = terminate_owned_tree(process, directory / "profile/raw-cleanup.json")
                safe = {key: cleanup[key] for key in (
                    "pid", "normal_cleanup", "status", "descendant_cleanup_verified",
                    "taskkill_exit_code", "parent_exit_code", "parent_still_running") if key in cleanup}
                if "error" in cleanup:
                    safe["error_type"] = cleanup["error"]["type"]
            except Exception as exc:
                # Raw-receipt I/O can fail after an attempted termination. Its
                # outcome stays unverified; still attempt the other owned actor.
                safe = {"pid": process.pid, "normal_cleanup": False,
                        "status": "cleanup_call_failed", "descendant_cleanup_verified": False,
                        "error_type": type(exc).__name__}
            safe["role"] = role
            safe_records.append(safe)
    if safe_records:
        # A public receipt failure must not prevent either cleanup attempt.
        write_json(directory / "owned-process-cleanup.json", {"processes": safe_records})


def wait_full_write_marker(directory: Path) -> None:
    marker = directory / "write-returned"
    wait_marker(marker)
    if json.loads(marker.read_text(encoding="utf-8")) != {"accepted_bytes": 9}:
        raise RuntimeError("The controlled hold requires full frame acceptance by Qt")

def validate_actor_receipt(receipt: dict, role: str, case: str, expected: dict) -> None:
    identity = {"role": role, "case": case, "qt_version": expected["qt_version"],
                "pyside_version": expected["pyside_version"], "python_version": expected["python_version"],
                "application_type": "QCoreApplication",
                "single_instance_source_sha256": expected["single_instance_source_sha256"],
                "probe_source_sha256": expected["probe_source_sha256"]}
    if any(receipt.get(key) != value for key, value in identity.items()):
        raise ValueError("Actor receipt does not match the requested source and control identity")

def run(output: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Native pipe diagnosis requires Windows")
    import PySide6
    from PySide6.QtCore import qVersion
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    token = uuid.uuid4().hex
    (output / ".probe-owned").write_text(token, encoding="ascii")
    root = Path(__file__).resolve().parents[1]
    source = root / "src/taxops/ui/single_instance.py"
    report = {"status": "running", "scope": "source Qt/PySide notification transport diagnosis; not the frozen EXE or replaced VC runtime; not application/window acceptance",
              "single_instance_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "qt_version": qVersion(), "pyside_version": PySide6.__version__,
              "python_version": list(sys.version_info[:3]),
              "hold_ms": round(HOLD_SECONDS * 1000), "cases": []}
    try:
        for case in CASES:
            directory = output / case
            directory.mkdir()
            env = isolated_environment(directory / "profile")
            env["PYTHONPATH"] = str(root / "src")
            processes, logs = [], []
            row = {"case": case, "status": "failed"}
            try:
                for role in ("receiver", "sender"):
                    command = [sys.executable, "-m", "build_tools.notification_transport_probe", "--role", role,
                               "--output", str(directory), "--case", case, "--token", token]
                    # Never publish raw Qt/runtime stderr: even a synthetic
                    # traceback can include the runner's absolute user path.
                    log = tempfile.TemporaryFile(dir=directory / "profile/temp")
                    logs.append((role, log))
                    process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log)
                    processes.append(process)
                    if role == "receiver":
                        wait_marker(directory / "listening", process=process)
                for role, process in zip(("receiver", "sender"), processes):
                    row[role + "_process_exit_code"] = process.wait(timeout=CONTROL_TIMEOUT + 5)
                    row[role] = json.loads((directory / (role + ".json")).read_text(encoding="utf-8"))
                    validate_actor_receipt(row[role], role, case, report)
                if any(row[role + "_process_exit_code"] != 0 or row[role]["status"] != "diagnostic_complete"
                       for role in ("receiver", "sender")):
                    raise RuntimeError("One transport actor did not complete its diagnostic")
                row["status"] = "diagnostic_complete"
            except Exception as exc:
                row["error_type"] = type(exc).__name__
            finally:
                cleanup_owned_processes(processes, directory)
                for role, log in logs:
                    write_json(directory / (role + "-process.log"), summarize_process_output(log))
                    log.close()
                report["cases"].append(row)
                write_json(output / "notification-transport.json", report)
        report["status"] = "diagnostic_complete" if all(row["status"] == "diagnostic_complete" for row in report["cases"]) else "failed"
    finally:
        write_json(output / "notification-transport.json", report)
    return report

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("receiver", "sender"))
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--token")
    args = parser.parse_args(argv)
    try:
        if args.role:
            return actor(args.role, args.output, args.case, args.token)
        return 0 if run(args.output)["status"] == "diagnostic_complete" else 1
    except Exception as exc:
        print("Notification transport probe failed: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
