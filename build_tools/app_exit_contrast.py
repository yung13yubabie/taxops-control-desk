"""Two isolated real-TaxOps source controls; not frozen EXE acceptance."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
def _load_tools():
    # The -I child imports this fixed checkout, never its arbitrary cwd.
    if __package__ in (None, ""):
        sys.path.insert(0, str(ROOT))
    from build_tools import qt_exit_contrast
    from build_tools.source_materials import source_identity
    return qt_exit_contrast, source_identity


common, source_identity = _load_tools()

CASES = (("taxops-close", 0), ("taxops-exit", 77))


def require_source(expected_tree: str) -> dict:
    identity = source_identity(ROOT)
    if identity["source_tree"] != expected_tree:
        raise ValueError("Source tree does not match the explicitly selected checkout")
    return identity


def validate_app_report(child: dict, directory: Path) -> None:
    expected_db = directory / "profile/local/TaxOpsControlDesk/taxops.sqlite"
    if (child.get("bootstrap_calls") != 1 or child.get("guard_acquired") is not True
            or child.get("window_shown") is not True or child.get("ready") is not True
            or child.get("migration_count") != 28
            or Path(child.get("db_path", "")) != expected_db
            or not child.get("persistent_client") or child.get("shown_messages")):
        raise ValueError("Real application did not reach the owned ready checkpoint")


def run_child(case: str, directory: Path, token: str, tree: str, instance: str) -> int:
    report = {"schema": 1, "case": case, "status": "failed", "process_id": os.getpid(),
              "parent_process_id": os.getppid(), "source_tree_requested": tree,
              "scope": "real TaxOps source in a new synthetic profile; not frozen evidence",
              "bootstrap_calls": 0, "guard_acquired": None, "window_shown": False,
              "ready": False, "shown_messages": []}
    try:
        common.require_profile(directory / "profile", token)
        if not instance or not instance.startswith("TaxOps.SourceExitControl."):
            raise ValueError("A synthetic diagnostic instance name is required")
        if getattr(sys, "frozen", False):
            raise ValueError("This control requires source execution")
        report["runtime"] = common.runtime_identity()
        common.validate_runtime(report["runtime"])
        from build_tools.onefile_runtime_probe import require_isolated_profile, persistent_client
        require_isolated_profile(directory / "profile", token)
        sys.path.insert(0, str(ROOT / "src"))
        import PySide6
        from PySide6 import QtCore, QtWidgets
        from taxops.ui import app, main_window
        from taxops.ui.single_instance import SingleInstanceGuard
        if Path(app.__file__).resolve() != ROOT / "src/taxops/ui/app.py":
            raise ValueError("Application import escaped the fixed source checkout")
        report["runtime"].update(qt_loaded=True, qt_version=QtCore.qVersion(),
            pyside_version=PySide6.__version__, pyside_package=common.file_identity(Path(PySide6.__file__)),
            qtcore_extension=common.file_identity(Path(QtCore.__file__)),
            qtwidgets_extension=common.file_identity(Path(QtWidgets.__file__)))
        if QtCore.qVersion() != "6.10.2" or PySide6.__version__ != "6.10.2":
            raise ValueError("Actual Qt and PySide6 must both be 6.10.2")
        report["source_files"] = {name: common.file_identity(Path(module.__file__))
                                  for name, module in (("app", app), ("main_window", main_window))}
        return run_application(case, directory, instance, report, app, main_window,
                               SingleInstanceGuard, QtCore, QtWidgets, persistent_client)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        common.save(directory / "child.json", report)
        return 1



def run_application(case, directory, instance, report, app, main_window,
                    SingleInstanceGuard, QtCore, QtWidgets, persistent_client):
    window_type = main_window.MainWindow
    original_bootstrap, original_show = app.bootstrap, window_type.show
    original_acquire, original_instance = SingleInstanceGuard.acquire, app._SINGLE_INSTANCE_NAME
    original_critical, original_information = QtWidgets.QMessageBox.critical, QtWidgets.QMessageBox.information

    def bootstrap():
        paths = app.resolve_paths()
        if paths.db_path.resolve() != directory / "profile/local/TaxOpsControlDesk/taxops.sqlite":
            raise ValueError("Refusing bootstrap outside the synthetic data root")
        report["bootstrap_calls"] += 1
        return original_bootstrap()

    def acquire(guard):
        result = original_acquire(guard)
        report["guard_acquired"] = result
        return result

    def message(original, kind, *args, **kwargs):
        report["shown_messages"].append({"kind": kind, "title": args[1], "text": args[2]})
        def accept():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMessageBox):
                    widget.accept()
        QtCore.QTimer.singleShot(100, accept)
        return original(*args, **kwargs)

    def show(window):
        original_show(window)
        if report["window_shown"]:
            return
        report.update(window_shown=True, qt_platform=QtWidgets.QApplication.instance().platformName())
        if report["qt_platform"] != "windows":
            raise ValueError("Real app source control requires native Windows Qt")
        report["db_path"] = str(window._container.paths.db_path.resolve())
        report["migration_count"] = window._container.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        report["persistent_client"] = persistent_client(window._container, directory / "synthetic-client.json", initialize=True)
        report.update(ready=True, checkpoint="real_mainwindow_show_returned_before_exec",
                      requested_exit_code=77 if case == "taxops-exit" else 0)
        validate_app_report(report, directory)
        report["status"] = "requesting_exit" if case == "taxops-exit" else "ready"
        common.save(directory / "child.json", report)
        if case == "taxops-exit":
            os._exit(77)  # Preserve the original CRT-exit hypothesis unchanged.
        if case != "taxops-close":
            raise ValueError("Unknown real application source control")
        QtCore.QTimer.singleShot(100, window.close)

    app.bootstrap, window_type.show = bootstrap, show
    SingleInstanceGuard.acquire, app._SINGLE_INSTANCE_NAME = acquire, instance
    QtWidgets.QMessageBox.critical = lambda *a, **kw: message(original_critical, "critical", *a, **kw)
    QtWidgets.QMessageBox.information = lambda *a, **kw: message(original_information, "information", *a, **kw)
    try:
        code = app.run()
    finally:
        app.bootstrap, window_type.show = original_bootstrap, original_show
        SingleInstanceGuard.acquire, app._SINGLE_INSTANCE_NAME = original_acquire, original_instance
        QtWidgets.QMessageBox.critical, QtWidgets.QMessageBox.information = original_critical, original_information
    validate_app_report(report, directory)
    report.update(status="normal_return", requested_exit_code=0, application_exit_code=code)
    common.save(directory / "child.json", report)
    return code

def contrast(python: Path, output: Path, tree: str, timeout: int = 180) -> dict:
    if sys.platform != "win32":
        raise ValueError("Real application source contrast requires Windows")
    if output.is_relative_to(ROOT):
        raise ValueError("Diagnostics must be outside the fixed source checkout")
    source = require_source(tree)
    runtime = common.configured_runtime(python)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": 1, "status": "failed", "source_identity": source,
              "expected_runtime": runtime, "harness": common.file_identity(Path(__file__)), "cases": [],
              "scope": "two real TaxOps source controls; not frozen EXE acceptance",
              "limits": "Source wheel VC bytes and frozen official VC replacements may differ; no frozen loader or native-module inventory validation is performed."}
    try:
        for case, expected in CASES:
            directory = output / case
            directory.mkdir()
            token, instance = uuid.uuid4().hex, "TaxOps.SourceExitControl." + uuid.uuid4().hex
            env = common.profile_environment(directory / "profile", token)
            (directory / "profile/.taxops-onefile-gate").write_text(token, encoding="ascii")
            command = [str(python), "-I", "-B", str(Path(__file__).resolve()), "--child-case", case,
                       "--output", str(directory), "--profile-token", token, "--source-tree", tree,
                       "--instance-name", instance]
            record = common.run_case(command, directory, env, expected, timeout,
                                     expected_runtime=runtime, expected_case=case)
            try:
                validate_app_report(record.get("child", {}), directory)
            except ValueError as exc:
                record.update(status="failed", application_validation_error=str(exc))
            common.save(directory / "process.json", record)
            result["cases"].append(record)
            if record.get("child", {}).get("error") or "receipt_error" in record or "error" in record:
                break
        result["source_after"] = require_source(tree)
        if len(result["cases"]) == 2 and all(r["status"] == "matched_control" for r in result["cases"]):
            result["status"] = "matched_controls"
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        common.save(output / "app-contrast.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--child-case", choices=[name for name, _ in CASES], help=argparse.SUPPRESS)
    parser.add_argument("--profile-token", help=argparse.SUPPRESS)
    parser.add_argument("--instance-name", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if args.child_case:
        if not args.instance_name or not args.instance_name.startswith("TaxOps.SourceExitControl."):
            parser.error("A synthetic diagnostic instance name is required")
        return run_child(args.child_case, args.output.resolve(), args.profile_token,
                         args.source_tree, args.instance_name)
    if args.python is None:
        parser.error("--python must identify an existing pinned environment")
    result = contrast(args.python.resolve(), args.output.resolve(), args.source_tree, args.timeout)
    return 0 if result["status"] == "matched_controls" else 1


if __name__ == "__main__":
    raise SystemExit(main())
