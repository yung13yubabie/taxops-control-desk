"""Instrument the real GUI entry for isolated frozen lifecycle acceptance.

No production database is used: the external gate supplies an empty profile.
No alternative loader/bootstrap/instance implementation is provided here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
import uuid
import sys
from pathlib import Path


def write_report(path: Path, report: dict) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def require_isolated_profile(root: Path, token: str) -> None:
    root = root.resolve()
    token_path = root / ".taxops-onefile-gate"
    if not token or not token_path.is_file() or token_path.read_text(encoding="ascii") != token:
        raise ValueError("Lifecycle probe requires an external harness-owned synthetic profile")
    for key, name in {"LOCALAPPDATA": "local", "APPDATA": "roaming", "USERPROFILE": "user", "HOME": "user", "TEMP": "temp", "TMP": "temp"}.items():
        if not os.environ.get(key) or Path(os.environ[key]).resolve() != root / name:
            raise ValueError("Lifecycle probe refuses a non-isolated environment: " + key)
    if os.environ.get("TAXOPS_DEV"):
        raise ValueError("Lifecycle probe must exercise the production path policy in an isolated profile")


def _termination_api():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes, ctypes.WinDLL("kernel32", use_last_error=True)


def terminate_isolated_current_process(profile_root: Path, profile_token: str) -> None:
    """Inject an abrupt self-only exit, after checking the diagnostic boundary.

    This models unexpected termination without CRT/DLL-detach cleanup. It is
    not a fix for, or explanation of, any earlier os._exit native fault.
    """
    require_isolated_profile(profile_root, profile_token)
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        raise ValueError("Self-termination injection requires the Windows frozen probe")
    ctypes, wintypes, kernel = _termination_api()
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    own_handle = kernel.GetCurrentProcess()
    if not own_handle:
        raise RuntimeError("GetCurrentProcess did not provide its pseudo-handle")
    if not kernel.TerminateProcess(own_handle, 77):
        error = ctypes.get_last_error()
        raise ctypes.WinError(error)
    # Microsoft specifies that successful self-termination never returns.
    raise RuntimeError("Self TerminateProcess unexpectedly returned")


def persistent_client(container, record: Path, *, initialize: bool) -> dict:
    from taxops.services.clients import CreateClientInput
    if initialize:
        if record.exists():
            raise ValueError("Persistence fixture must not already exist")
        code = "ONEFILE-" + uuid.uuid4().hex[:12]
        client = container.clients.create_client(CreateClientInput(code, "單檔重開合成客戶 " + code))
        expected = {"id": client.id, "client_code": client.client_code, "client_name": client.client_name}
        with record.open("x", encoding="utf-8") as handle:
            json.dump(expected, handle, ensure_ascii=False)
    else:
        expected = json.loads(record.read_text(encoding="utf-8"))
    client = container.clients_repo.get(expected["id"])
    if client is None or any(getattr(client, key) != value for key, value in expected.items()):
        raise ValueError("The same synthetic business record did not survive a real restart")
    return expected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--instance-name", required=True)
    parser.add_argument("--start-barrier", type=Path)
    parser.add_argument("--arrived", type=Path)
    parser.add_argument("--crash-after-ready", action="store_true")
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--profile-token", required=True)
    parser.add_argument("--persistent-record", type=Path, required=True)
    parser.add_argument("--initialize-persistence", action="store_true")
    args = parser.parse_args(argv)
    report = {"status": "failed", "bootstrap_calls": 0, "window_shown": False,
              "activation_count": 0, "guard_acquired": None, "normal_exit": False, "shown_messages": []}
    try:
        require_isolated_profile(args.profile_root, args.profile_token)
        if not getattr(sys, "frozen", False) or sys.platform != "win32":
            raise ValueError("Lifecycle proof requires the actual Windows frozen executable")
        mei = Path(sys._MEIPASS).resolve()
        report.update({"frozen": True, "platform": sys.platform, "meipass": str(mei),
                       "instance_name": args.instance_name,
                       "native_files": {p.relative_to(mei).as_posix().casefold(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mei.rglob("*") if p.is_file() and p.suffix.casefold() in {".dll", ".pyd", ".exe"}}})
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox
        from taxops.ui import app
        from taxops.ui.main_window import MainWindow
        from taxops.ui.single_instance import SingleInstanceGuard
        app._SINGLE_INSTANCE_NAME = args.instance_name
        original_bootstrap, original_show = app.bootstrap, MainWindow.show
        original_acquire, original_activate = SingleInstanceGuard.acquire, app._activate_window
        original_information, original_critical = QMessageBox.information, QMessageBox.critical
        def bootstrap(*a, **kw):
            report["bootstrap_calls"] += 1
            return original_bootstrap(*a, **kw)
        barrier_passed = False
        def acquire(guard):
            nonlocal barrier_passed
            if args.start_barrier and not barrier_passed:
                if args.arrived is None:
                    raise ValueError("Synchronized startup requires an arrived file")
                args.arrived.write_text("Ready before real atomic acquire\n", encoding="utf-8")
                deadline = time.monotonic() + 60
                while not args.start_barrier.is_file():
                    if time.monotonic() >= deadline:
                        raise ValueError("Startup barrier was not released")
                    time.sleep(0.01)
                barrier_passed = True
            result = original_acquire(guard)
            report["guard_acquired"] = result
            return result
        def activate(window):
            report["activation_count"] += 1
            return original_activate(window)
        def message(original, kind, *a, **kw):
            # Exercise the actual modal startup message, then click OK.
            report["shown_messages"].append({"kind": kind, "title": a[1], "text": a[2]})
            def accept():
                from PySide6.QtWidgets import QApplication
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget, QMessageBox):
                        widget.accept()
            QTimer.singleShot(100, accept)
            return original(*a, **kw)
        def information(*a, **kw):
            return message(original_information, "information", *a, **kw)
        def critical(*a, **kw):
            return message(original_critical, "critical", *a, **kw)
        def show(window):
            original_show(window)
            if report["window_shown"]:
                return
            report["window_shown"] = True
            report["db_path"] = str(window._container.paths.db_path.resolve())
            report["migration_count"] = window._container.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            report["persistent_client"] = persistent_client(window._container, args.persistent_record, initialize=args.initialize_persistence)
            from build_tools.windows_loaded_modules import capture_loaded_modules
            report["loaded_modules"] = capture_loaded_modules("gui_ready")
            if args.crash_after_ready:
                report["crash_injection"] = {"api": "TerminateProcess", "target": "current_process_pseudo_handle", "requested_exit_code": 77}
            write_report(args.ready, report)
            if args.crash_after_ready:
                terminate_isolated_current_process(args.profile_root, args.profile_token)
            timer = QTimer(window)
            timer.setInterval(100)
            timer.timeout.connect(lambda: window.close() if args.release.is_file() else None)
            timer.start()
            window._lifecycle_probe_timer = timer
        app.bootstrap, MainWindow.show = bootstrap, show
        SingleInstanceGuard.acquire, app._activate_window = acquire, activate
        QMessageBox.information, QMessageBox.critical = information, critical
        try:
            result = app.run()
        finally:
            app.bootstrap, MainWindow.show = original_bootstrap, original_show
            SingleInstanceGuard.acquire, app._activate_window = original_acquire, original_activate
            QMessageBox.information, QMessageBox.critical = original_information, original_critical
        report.update({"exit_code": result, "normal_exit": True,
                       "status": "passed" if result == 0 else "failed"})
        return result
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return 1
    finally:
        write_report(args.report, report)


if __name__ == "__main__":
    raise SystemExit(main())
