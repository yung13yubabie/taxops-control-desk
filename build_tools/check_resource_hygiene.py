"""Check for common local resource leaks after development/test runs.

Usage:
    python -m build_tools.check_resource_hygiene

This is a Windows-first diagnostic helper. It does not kill anything; it only
prints process and TCP state evidence that can be pasted into a handoff.
"""

from __future__ import annotations

import subprocess
import sys


_PROCESS_QUERY = r"""
$patterns = 'TaxOpsControlDesk|pytest|pyinstaller|PyInstaller|build_tools|taxops'
Get-CimInstance Win32_Process |
  Where-Object {
    ($_.Name -match 'TaxOpsControlDesk|pytest|pyinstaller') -or
    (($_.Name -match 'python') -and ($_.CommandLine -match $patterns))
  } |
  Select-Object Name, ProcessId, CommandLine |
  Format-Table -AutoSize -Wrap
"""


_TCP_STATE_QUERY = r"""
Get-NetTCPConnection |
  Group-Object State |
  Sort-Object Name |
  Select-Object Name, Count |
  Format-Table -AutoSize
"""


_LISTEN_QUERY = r"""
Get-NetTCPConnection -State Listen |
  Sort-Object LocalPort |
  Select-Object LocalAddress, LocalPort, OwningProcess |
  Format-Table -AutoSize
"""


def _run_powershell(title: str, script: str) -> int:
    print(f"\n== {title} ==")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    else:
        print("(no rows)")
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def main() -> int:
    rc = 0
    for title, script in (
        ("Suspicious TaxOps/PyTest/PyInstaller processes", _PROCESS_QUERY),
        ("TCP state counts", _TCP_STATE_QUERY),
        ("Listening ports", _LISTEN_QUERY),
    ):
        rc = max(rc, _run_powershell(title, script))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
