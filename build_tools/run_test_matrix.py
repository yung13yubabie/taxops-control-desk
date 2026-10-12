"""Run every test file in its own process and gate combined raw branch coverage.

Qt process isolation is intentional. No test is dropped to obtain a green run.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path, PurePath

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_COVERAGE = 90.0


def coverage_meets_gate(payload: dict) -> bool:
    """Compare the unrounded numeric total, never the display percentage."""
    value = payload.get("totals", {}).get("percent_covered")
    return (payload.get("meta", {}).get("branch_coverage") is True
            and isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and MINIMUM_COVERAGE <= value <= 100)


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites:
        raise ValueError("No test suite recorded in JUnit report")
    return {name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
            for name in ("tests", "failures", "errors", "skipped")}


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _report_path(path: PurePath) -> str:
    """Use repository-relative POSIX paths in reports on every host OS."""
    return path.relative_to(ROOT).as_posix()


def run_matrix(output: Path, *, files: list[Path] | None = None, timeout: int = 900) -> dict:
    output = output.resolve()
    all_files = sorted((ROOT / "tests").glob("test_*.py"))
    selected = sorted(path.resolve() for path in (files if files is not None else all_files))
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one unique test file")
    for path in selected:
        if path not in all_files or not path.is_file():
            raise ValueError(f"Expected an existing repository test file: {path}")
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "matrix.json"
    if report_path.exists() or (output / "coverage-data").exists():
        raise ValueError("Use a fresh matrix output directory to avoid stale coverage")
    data_dir = output / "coverage-data"
    data_dir.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["COVERAGE_FILE"] = str(data_dir / ".coverage")
    summary = {"status": "running", "full_suite": selected == all_files,
               "coverage_gate": MINIMUM_COVERAGE, "source_commit": os.environ.get("GITHUB_SHA", "not_recorded"),
               "files": [], "coverage_commands": [],
               "unrun_files": [], "raw_percent_covered": None}

    def save():
        report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    save()
    for index, path in enumerate(selected):
        junit = output / f"{path.stem}.xml"
        command = [sys.executable, "-m", "coverage", "run", "--parallel-mode", "--branch",
                   "--source=taxops", "-m", "pytest", str(path), "-q", "--tb=short",
                   "-p", "no:cacheprovider", f"--junitxml={junit}"]
        started = time.monotonic()
        result = {"file": _report_path(path), "status": "failed", "exit_code": None}
        try:
            process = subprocess.run(command, cwd=ROOT, env=env, timeout=timeout,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace")
            result["exit_code"] = process.returncode
            log = process.stdout + "\n" + process.stderr
            if junit.is_file():
                try:
                    result.update(_junit_counts(junit))
                except (ET.ParseError, ValueError) as exc:
                    result["report_error"] = str(exc)
            else:
                result["report_error"] = "JUnit report is missing"
            if (process.returncode == 0 and "report_error" not in result
                    and result.get("failures") == 0 and result.get("errors") == 0):
                result["status"] = "passed"
            fatal = process.returncode < 0 or process.returncode > 255
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kills and waits for the exact owned child.
            # Halt the matrix rather than pretending unrun files passed.
            result["status"] = "timed_out"
            log = _text(exc.stdout) + "\n" + _text(exc.stderr)
            fatal = True
        result["seconds"] = round(time.monotonic() - started, 3)
        (output / f"{path.stem}.log").write_text(log, encoding="utf-8")
        summary["files"].append(result)
        print(f"{index + 1}/{len(selected)} {path.name}: {result['status']} (exit={result['exit_code']})", flush=True)
        if fatal:
            summary["unrun_files"] = [_report_path(p) for p in selected[index + 1:]]
            save()
            break
        save()

    coverage_json = output / "coverage.json"
    coverage_env = env.copy()
    coverage_env["COVERAGE_FILE"] = str(output / ".coverage")
    commands = (
        ("combine", ["combine", "--keep", str(data_dir)]),
        ("json", ["json", "-o", str(coverage_json)]),
        ("report", ["report", "--precision=4", f"--fail-under={MINIMUM_COVERAGE}"]),
    )
    for label, args in commands:
        try:
            process = subprocess.run([sys.executable, "-m", "coverage", *args], cwd=ROOT,
                                     env=coverage_env, timeout=120, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace")
            code = process.returncode
            log = process.stdout + "\n" + process.stderr
        except subprocess.TimeoutExpired as exc:
            code = -1
            log = "Coverage command timed out\n" + _text(exc.stdout) + _text(exc.stderr)
        (output / f"coverage-{label}.log").write_text(log, encoding="utf-8")
        summary["coverage_commands"].append({"command": label, "exit_code": code})
        if label == "combine" and code != 0:
            break
    if coverage_json.is_file():
        try:
            payload = json.loads(coverage_json.read_text(encoding="utf-8"))
            summary["raw_percent_covered"] = payload.get("totals", {}).get("percent_covered")
            summary["branch_coverage"] = payload.get("meta", {}).get("branch_coverage")
            coverage_ok = coverage_meets_gate(payload)
        except (ValueError, TypeError) as exc:
            summary["coverage_error"] = str(exc)
            coverage_ok = False
    else:
        coverage_ok = False
        summary["coverage_error"] = "Combined coverage JSON missing"
    all_commands_ok = (len(summary["coverage_commands"]) == 3
                       and all(item["exit_code"] == 0 for item in summary["coverage_commands"]))
    all_tests_ok = (not summary["unrun_files"] and len(summary["files"]) == len(selected)
                    and all(item["status"] == "passed" for item in summary["files"]))
    summary["status"] = "passed" if all_tests_ok and coverage_ok and all_commands_ok else "failed"
    summary["totals"] = {name: sum(row.get(name, 0) for row in summary["files"])
                         for name in ("tests", "failures", "errors", "skipped")}
    save()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-tests"))
    parser.add_argument("--files", nargs="+", type=Path, help="Diagnostic subset; full_suite will be false")
    parser.add_argument("--timeout", type=int, default=900, help="Timeout per test-file process")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        result = run_matrix(args.output, files=args.files, timeout=args.timeout)
    except Exception as exc:
        print(f"Test matrix failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({key: result[key] for key in ("status", "full_suite", "raw_percent_covered", "totals")}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
