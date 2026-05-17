"""Automated smoke test for the packaged EXE.

Usage:
    python -m build_tools.smoke_test_exe

Automatable checks (exits non-zero on any failure):
  1. EXE file exists at expected path
  2. EXE starts without immediately crashing (process alive after 8s)
  3. SQLite database file is created in the temp data dir

Manual checklist items are printed at the end for human verification.

Data isolation: uses a fresh temp directory as LOCALAPPDATA so no
production or dev data is touched. Temp dir is removed on exit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_EXE = _PROJECT_ROOT / "dist" / "TaxOpsControlDesk" / "TaxOpsControlDesk.exe"

_STARTUP_WAIT = 8      # seconds to wait before checking liveness
_DB_WAIT = 15          # seconds total to wait for SQLite creation

_MANUAL_CHECKLIST = """\
Manual verification checklist
==============================
After automated checks pass, open the EXE (TAXOPS_DEV=1) and confirm:

  [ ] Main window title: "TaxOps Control Desk"
  [ ] All 11 nav labels display in Traditional Chinese
  [ ] Sidebar collapse/expand toggle works
  [ ] Settings page opens; data paths shown with copy + open buttons
  [ ] Can create a new client via dialog; client persists after restart
  [ ] Audit log row exists for the create action
  [ ] Disabled tax-cache buttons show correct tooltip
  [ ] No fake rows, fake counts, or fake success messages
  [ ] Window renders correctly at 1366x768 / 125% DPI / 150% DPI
"""


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _check_exe_exists() -> None:
    if not _EXE.exists():
        _fail(
            f"EXE not found: {_EXE}\n"
            "Run  python -m build_tools.package_windows  first."
        )
    print(f"OK   EXE found: {_EXE}")


def _run_smoke(tmp_localappdata: Path) -> None:
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_localappdata)
    env["TAXOPS_DEV"] = "1"

    expected_db = tmp_localappdata / "TaxOpsControlDeskDev" / "taxops.sqlite"

    print(f"     Launching EXE with temp LOCALAPPDATA: {tmp_localappdata}")
    proc = subprocess.Popen([str(_EXE)], env=env)

    try:
        time.sleep(_STARTUP_WAIT)
        if proc.poll() is not None:
            _fail(f"EXE exited with code {proc.returncode} within {_STARTUP_WAIT}s (crash or error).")
        print(f"OK   EXE still running after {_STARTUP_WAIT}s (pid {proc.pid})")

        deadline = time.monotonic() + (_DB_WAIT - _STARTUP_WAIT)
        while not expected_db.exists():
            if time.monotonic() > deadline:
                _fail(f"SQLite not created within {_DB_WAIT}s: {expected_db}")
            time.sleep(0.5)
        print(f"OK   SQLite created: {expected_db}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def run_smoke_tests() -> None:
    _check_exe_exists()

    tmp = Path(tempfile.mkdtemp(prefix="taxops_smoke_"))
    try:
        _run_smoke(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nAll automated checks passed.")
    print()
    print(_MANUAL_CHECKLIST)


if __name__ == "__main__":
    run_smoke_tests()
    sys.exit(0)
