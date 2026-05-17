"""Regression tests for local resource hygiene in the test suite."""

from __future__ import annotations

import tempfile
from pathlib import Path


def test_tempfile_mkdtemp_is_isolated_under_pytest_tmp_path(tmp_path: Path) -> None:
    """Direct tempfile.mkdtemp() calls must not leak into the user's TEMP root."""
    created = Path(tempfile.mkdtemp())

    assert created.is_dir()
    assert created.is_relative_to(tmp_path)


def test_settings_page_worker_is_deleted_after_async_completion() -> None:
    source = Path("src/taxops/ui/pages/settings_page.py").read_text(encoding="utf-8")

    assert "worker.deleteLater()" in source


def test_resource_hygiene_script_checks_processes_ports_and_tcp_states() -> None:
    source = Path("build_tools/check_resource_hygiene.py").read_text(encoding="utf-8")

    assert "Get-CimInstance Win32_Process" in source
    assert "Get-NetTCPConnection" in source
    assert "State" in source
    assert "Listen" in source
