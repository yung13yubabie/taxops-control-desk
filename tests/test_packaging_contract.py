"""Packaging must include every registered database migration."""

from __future__ import annotations

from pathlib import Path


def test_pyinstaller_spec_collects_all_migration_submodules() -> None:
    spec = Path("TaxOpsControlDesk.spec").read_text(encoding="utf-8")

    assert 'collect_submodules("taxops.db.migrations")' in spec


def test_release_requirements_pin_runtime_and_packaging_dependencies() -> None:
    lines = {
        line.strip()
        for line in Path("requirements-release.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    for package in ("PySide6", "Jinja2", "openpyxl", "PyInstaller", "setuptools"):
        assert any(line.startswith(f"{package}==") for line in lines), package
    assert all("==" in line for line in lines)


def test_quick_packaging_preflight_calls_shared_cli_and_preserves_nonzero() -> None:
    workflow = Path(".github/workflows/windows-candidate.yml").read_text(encoding="utf-8")
    main, quick = workflow.split("  windows-ui-diagnostics:", 1)
    step = quick.split("      - name: Preflight packaging inputs in the diagnostic environment", 1)[1]
    step = step.split("      - name:", 1)[0]
    assert "python.exe -m build_tools.windows_package_environment --output" in step
    assert "pinned test venv; not a release build or artifact acceptance" in step
    assert 'package-environment.json' in step and 'package-input-boundary.json' in step
    assert 'package-input-process.log' in step
    assert '--probe-qt-translation' in step
    assert "$code = $LASTEXITCODE" in step and "if ($code -ne 0) { exit $code }" in step
    assert "continue-on-error" not in step
    assert "build_tools.package_windows" in main and "build_tools.verify_onefile" in main
    assert "build_tools.run_test_matrix" in main
    assert "build_tools.windows_package_environment --output" not in main


def test_quick_startup_diagnostics_preserve_complete_files_and_failure_exit() -> None:
    workflow = Path(".github/workflows/windows-candidate.yml").read_text(encoding="utf-8")
    main, quick = workflow.split("  windows-ui-diagnostics:", 1)
    expected = (
        "test_qgif_rebuild", "test_shell_icon_probe", "test_shell_module_baseline",
        "test_shell_loaded_classification", "test_windows_inbox_runtime",
        "test_notification_readiness", "test_activation_delivery",
        "test_atomic_instance_lock", "test_single_instance", "test_onefile_gate",
        "test_native_font_probe", "test_qt_geometry_diagnostics",
        "test_deep_chinese_ui", "test_frozen_self_test", "test_novice_client_forms",
        "test_ui_stage_5_date_field", "test_v032_receipt_workbench",
    )
    declared = quick.split("$files = @(", 1)[1].split(")", 1)[0]
    assert tuple(item.strip().strip("'") for item in declared.split(",")) == expected
    assert "Seventeen complete synthetic packaging/startup/UI/diagnostic test files" in quick
    assert '\"tests/$file.py\"' in quick
    assert "if ($code -ne 0) { $failed = $true }" in quick
    assert "if ($failed) { exit 1 }" in quick
    assert "continue-on-error" not in quick
    assert "build_tools.run_test_matrix" in main
    assert "build_tools.verify_onefile" in main
