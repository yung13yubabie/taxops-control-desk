"""Synthetic child-environment tests, not Windows build acceptance."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from build_tools import windows_package_environment as environment
from build_tools import package_windows as package


def inputs(tmp_path, monkeypatch):
    prefix = tmp_path / "release"
    base = tmp_path / "python"
    system, windows = tmp_path / "Windows/System32", tmp_path / "Windows"
    git = tmp_path / "Git/cmd/git.exe"
    files = [prefix / "Scripts/python.exe", base / "python.exe", git,
             tmp_path / "Git/mingw64/bin/git.exe", system / "WindowsPowerShell/v1.0/powershell.exe"]
    for name in ("PySide6", "shiboken6", "PyInstaller"):
        files.append(prefix / "Lib/site-packages" / name / "__init__.py")
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic existing tool, never executed")
    monkeypatch.setattr(environment, "sys", SimpleNamespace(
        prefix=str(prefix), base_prefix=str(base), executable=str(files[0]), _base_executable=str(files[1])))
    monkeypatch.setattr(environment, "windows_directories", lambda: (system, windows))
    monkeypatch.setattr(environment.importlib.util, "find_spec",
        lambda name: SimpleNamespace(origin=str(prefix / "Lib/site-packages" / name / "__init__.py")))
    monkeypatch.setattr(environment.shutil, "which", lambda name, path: str(git))
    calls = []
    monkeypatch.setattr(environment.subprocess, "run", lambda *args, **kwargs:
        calls.append((args, kwargs)) or SimpleNamespace(stdout="git version 2.50.0.windows.1\n"))
    return files, calls


def test_child_path_is_explicit_parent_compiler_untouched_and_reachable(tmp_path, monkeypatch):
    files, calls = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {
        "Path": str(files[2].parent) + ";C:/Codex/libheif;C:/QtSDK/bin;C:/JDK/bin",
        "PATH": str(files[2].parent) + ";C:/Codex/libheif;C:/QtSDK/bin;C:/JDK/bin",
        "INCLUDE": "compiler headers", "LIB": "compiler libraries", "LIBPATH": "compiler metadata",
        "PYTHONPATH": "unrelated SDK", "PythonHome": "unrelated Python", "QT_PLUGIN_PATH": "SDK plugins",
        "TAXOPS_RECOMBINE_INPUT": "exact original input", "TAXOPS_VC_REDIST_VSIX": "exact original VSIX",
        "PSModulePath": "existing signature child removes this separately"})
    parent = dict(environment.os.environ)
    path = tmp_path / "package-environment.json"
    child, report = environment.prepare_environment(report_path=path)
    assert dict(environment.os.environ) == parent
    assert len([k for k in child if k.upper() == "PATH"]) == 1
    assert "Codex" not in child["PATH"] and "SDK" not in child["PATH"] and "JDK" not in child["PATH"]
    assert child["PATH"].split(";") == [str(files[0].parent), str(files[1].parent),
        str(files[4].parents[2]), str(files[4].parents[3]), str(files[4].parent), str(files[2].parent)]
    assert all(child[k] == parent[k] for k in ("INCLUDE", "LIB", "LIBPATH", "PSModulePath",
        "TAXOPS_RECOMBINE_INPUT", "TAXOPS_VC_REDIST_VSIX"))
    assert not any(k.upper() in environment._IMPORT_VARIABLES for k in child)
    assert report["status"] == "passed" and len(report["removed_path_entries"]) == 3
    assert calls[0][0][0] == [str(files[2]), "--version"] and calls[0][1]["env"] == child
    monkeypatch.setattr(environment.os, "environ", child)
    link = environment.package_receipt()
    assert link["sha256"] == environment.sha256(path)
    assert link["filename"] == path.name


@pytest.mark.parametrize("change", ["conflict", "no_git", "no_powershell", "foreign_git", "git_dll", "foreign_package", "global_python", "wrong_python"])
def test_missing_or_shadowed_build_inputs_fail_with_receipt(tmp_path, monkeypatch, change):
    files, _ = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    if change == "conflict":
        environment.os.environ["PATH"] = "different"
    elif change == "no_git":
        monkeypatch.setattr(environment.shutil, "which", lambda *a, **k: None)
    elif change == "no_powershell":
        files[4].unlink()
    elif change == "foreign_git":
        monkeypatch.setattr(environment.shutil, "which", lambda *a, **k: str(tmp_path / "foreign/git.exe"))
    elif change == "git_dll":
        (files[2].parent / "shadow.DLL").write_bytes(b"shadow")
    elif change == "foreign_package":
        monkeypatch.setattr(environment.importlib.util, "find_spec", lambda name: SimpleNamespace(origin="/SDK/foreign/__init__.py"))
    elif change == "global_python":
        environment.sys.base_prefix = environment.sys.prefix
    else:
        environment.sys.executable = str(files[1])
    parent = dict(environment.os.environ)
    report = tmp_path / "package-environment.json"
    with pytest.raises(RuntimeError):
        environment.prepare_environment(report_path=report)
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "failed"
    assert dict(environment.os.environ) == parent


@pytest.mark.parametrize("change", ["path", "tool", "package", "receipt", "status"])
def test_child_receipt_integrity(tmp_path, monkeypatch, change):
    files, _ = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    path = tmp_path / "package-environment.json"
    child, _ = environment.prepare_environment(report_path=path)
    monkeypatch.setattr(environment.os, "environ", child)
    if change == "path":
        child["Path"] = "shadow directory"
    elif change == "tool":
        files[4].write_bytes(b"changed powershell")
    elif change == "package":
        files[-1].write_bytes(b"changed package")
    elif change == "receipt":
        child.pop("TAXOPS_PACKAGE_ENV_RECEIPT")
    else:
        row = json.loads(path.read_text(encoding="utf-8"))
        row["status"] = "failed"
        path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(RuntimeError):
        environment.package_receipt()


def test_package_passes_same_child_env_to_both_absolute_python_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(package, "_SPEC", tmp_path / "project.spec")
    monkeypatch.setattr(package, "_EXE", tmp_path / "application.exe")
    package._SPEC.write_text("synthetic", encoding="utf-8")
    package._EXE.write_bytes(b"synthetic")
    monkeypatch.setattr(package, "validate_build_environment", lambda: None)
    child = {"PATH": "explicit controlled child"}
    monkeypatch.setattr(package, "prepare_environment", lambda: (child, {}))
    calls = []
    monkeypatch.setattr(package.subprocess, "run", lambda command, **kwargs:
        calls.append((command, kwargs)) or SimpleNamespace(returncode=0))
    package.build()
    assert len(calls) == 2
    assert all(Path(command[0]).is_absolute() and kwargs["env"] is child for command, kwargs in calls)


def test_spec_controls_source_path_before_collecting_and_requires_all_migrations():
    import ast
    spec = (environment.ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")
    assert spec.index('sys.path.insert(0, str(Path(SPECPATH).resolve() / "src"))') < spec.index('_migration_modules = collect_submodules') < spec.index('a = Analysis(')
    tree = ast.parse(spec)
    selected = [node for node in tree.body if
        (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
         and node.targets[0].id in {"_migration_modules", "_expected_migrations"})
        or (isinstance(node, ast.If) and "_expected_migrations" in ast.unparse(node.test))]
    code = compile(ast.Module(body=selected, type_ignores=[]), "synthetic-spec-gate", "exec")
    modules = ["taxops.db.migrations." + path.stem for path in
               (environment.ROOT / "src/taxops/db/migrations").glob("_m*.py")]
    assert len(modules) == 28
    for selected_modules in (modules, modules[:-1], []):
        namespace = {"Path": Path, "SPECPATH": str(environment.ROOT),
                     "collect_submodules": lambda name: selected_modules}
        if len(selected_modules) == 28:
            exec(code, namespace)
        else:
            with pytest.raises(RuntimeError, match="hidden imports"):
                exec(code, namespace)
