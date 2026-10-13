"""Synthetic child-environment tests, not Windows build acceptance."""
from __future__ import annotations

import json
import os
import subprocess
import sys
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
    (tmp_path / "Git/mingw64/libexec/git-core").mkdir(parents=True)
    monkeypatch.setattr(environment, "sys", SimpleNamespace(
        prefix=str(prefix), base_prefix=str(base), executable=str(files[0]), _base_executable=str(files[1])))
    monkeypatch.setattr(environment, "windows_directories", lambda: (system, windows))
    monkeypatch.setattr(environment, "os", SimpleNamespace(environ=dict(os.environ)))
    monkeypatch.setattr(environment, "importlib", SimpleNamespace(util=SimpleNamespace(
        find_spec=lambda name: SimpleNamespace(origin=str(prefix / "Lib/site-packages" / name / "__init__.py")))))
    monkeypatch.setattr(environment, "shutil", SimpleNamespace(which=lambda name, path: str(git)))
    calls = []
    def run(command, **kwargs):
        calls.append(((command,), kwargs))
        return SimpleNamespace(stdout="git version 2.50.0.windows.1\n" if command[-1] == "--version"
                               else str(tmp_path / "Git/mingw64/libexec/git-core") + "\n")
    monkeypatch.setattr(environment, "subprocess", SimpleNamespace(run=run))
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


@pytest.mark.parametrize("change", ["path", "tool", "implementation", "package", "receipt", "anchor", "status"])
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
    elif change == "implementation":
        files[3].write_bytes(b"changed Git implementation")
    elif change == "package":
        files[-1].write_bytes(b"changed package")
    elif change == "receipt":
        child.pop("TAXOPS_PACKAGE_ENV_RECEIPT")
    elif change == "anchor":
        child.pop("TAXOPS_PACKAGE_ENV_RECEIPT_SHA256")
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
    monkeypatch.setattr(package, "subprocess", SimpleNamespace(run=lambda command, **kwargs:
        calls.append((command, kwargs)) or SimpleNamespace(returncode=0)))
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


@pytest.mark.parametrize("entry", ["cmd", "root_bin", "implementation", "case_root_bin"])
@pytest.mark.parametrize("layout", ["mingw64", "ucrt64", "both"])
def test_official_git_entry_shapes_normalize_to_cmd_only(tmp_path, monkeypatch, entry, layout):
    files, _ = inputs(tmp_path, monkeypatch)
    root = files[2].parent.parent
    implementation = "ucrt64" if layout in {"ucrt64", "both"} else "mingw64"
    if layout == "ucrt64":
        files[3].unlink()
    if layout in {"ucrt64", "both"}:
        path = root / "ucrt64/bin/git.exe"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic new UCRT64 implementation")
        (root / "ucrt64/libexec/git-core").mkdir(parents=True)
    if entry == "cmd":
        discovered = root / "cmd/git.exe"
    elif entry == "implementation":
        discovered = root / implementation / "bin/git.exe"
    else:
        discovered = root / ("BIN/GIT.EXE" if entry == "case_root_bin" else "bin/git.exe")
        discovered.parent.mkdir()
        discovered.write_bytes(b"synthetic official root/bin wrapper shape")
    monkeypatch.setattr(environment.shutil, "which", lambda *a, **k: str(discovered))
    monkeypatch.setattr(environment.os, "environ", {"Path": str(discovered.parent), "Git_Exec_Path": "cross-root override"})
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="git version 2.56.0.windows.1\n" if command[-1] == "--version"
                               else str(root / implementation / "libexec/git-core") + "\n")
    monkeypatch.setattr(environment.subprocess, "run", run)
    parent = dict(environment.os.environ)
    child, report = environment.prepare_environment(report_path=tmp_path / "package-environment.json")
    assert dict(environment.os.environ) == parent
    assert "Git_Exec_Path" not in child
    assert report["removed_git_override_variables"] == ["Git_Exec_Path"]
    git_paths = [Path(p) for p in child["PATH"].split(";") if Path(p).is_relative_to(root)]
    assert git_paths == [root / "cmd"]
    assert [command for command, _ in calls] == [[str(files[2]), "--version"], [str(files[2]), "--exec-path"]]
    assert all(kwargs["env"] is child for _, kwargs in calls)
    discovery = report["git_discovery"]
    assert discovery["discovered_path"] == str(discovered)
    assert discovery["selected_implementation"]["layout"] == implementation
    assert len(discovery["implementation_candidates"]) == (2 if layout == "both" else 1)
    for row in discovery["implementation_candidates"]:
        assert row["sha256"] == environment.sha256(Path(row["path"])) and row["bytes"] > 0
    assert report["tools"]["git_implementation"]["path"] == str(root / implementation / "bin/git.exe")
    monkeypatch.setattr(environment.os, "environ", child)
    assert environment.package_receipt()["sha256"] == environment.sha256(tmp_path / "package-environment.json")
    assert len(calls) == 2  # Receipt validation does not execute Git again.


@pytest.mark.parametrize("change", ["missing_cmd", "missing_implementation", "missing_exec_dir", "cmd_dll", "wrong_name", "usr_bin", "cross_root", "arbitrary_exec_dir", "unavailable_selected", "relative_exec", "fake_version", "missing_version", "query_failure"])
def test_git_layout_and_metadata_fail_closed_without_parent_change(tmp_path, monkeypatch, change):
    files, _ = inputs(tmp_path, monkeypatch)
    root = files[2].parent.parent
    discovered = root / "bin/git.exe"
    discovered.parent.mkdir()
    discovered.write_bytes(b"synthetic root/bin wrapper")
    version = "git version 2.56.0.windows.1\n"
    exec_path = str(root / "mingw64/libexec/git-core") + "\n"
    if change == "missing_cmd":
        files[2].unlink()
    elif change == "missing_implementation":
        files[3].unlink()
    elif change == "missing_exec_dir":
        (root / "mingw64/libexec/git-core").rmdir()
    elif change == "cmd_dll":
        (files[2].parent / "shadow.DLL").write_bytes(b"shadow")
    elif change == "wrong_name":
        discovered = root / "bin/fake-git.exe"
        discovered.write_bytes(b"fake name")
    elif change == "usr_bin":
        discovered = root / "usr/bin/git.exe"
        discovered.parent.mkdir(parents=True)
        discovered.write_bytes(b"unrecognized usr/bin")
    elif change == "cross_root":
        exec_path = str(tmp_path / "OtherGit/mingw64/libexec/git-core")
    elif change == "arbitrary_exec_dir":
        exec_path = str(root / "arbitrary/libexec/git-core")
    elif change == "unavailable_selected":
        exec_path = str(root / "ucrt64/libexec/git-core")
    elif change == "relative_exec":
        exec_path = "mingw64/libexec/git-core"
    elif change == "fake_version":
        version = "git version syntheticwindowsmetadata"
    elif change == "missing_version":
        version = "git version 2.56.0"
    monkeypatch.setattr(environment.shutil, "which", lambda *a, **k: str(discovered))
    monkeypatch.setattr(environment.os, "environ", {"Path": str(discovered.parent), "INCLUDE": "original compiler"})
    calls = []
    report_path = tmp_path / "package-environment.json"
    def run(command, **kwargs):
        calls.append(command)
        assert json.loads(report_path.read_text(encoding="utf-8"))["git_discovery"]["discovered_path"] == str(discovered)
        if change == "query_failure":
            raise RuntimeError("synthetic metadata query failure")
        return SimpleNamespace(stdout=version if command[-1] == "--version" else exec_path)
    monkeypatch.setattr(environment.subprocess, "run", run)
    parent = dict(environment.os.environ)
    with pytest.raises(RuntimeError):
        environment.prepare_environment(report_path=report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["error"]
    assert report["git_discovery"]["discovered_path"] == str(discovered)
    assert dict(environment.os.environ) == parent
    assert all(command[0] == str(files[2]) for command in calls)


def test_git_exec_metadata_case_and_separators_do_not_expand_path(tmp_path, monkeypatch):
    files, _ = inputs(tmp_path, monkeypatch)
    root = files[2].parent.parent
    monkeypatch.setattr(environment.os, "environ", {"Path": str(root / "cmd")})
    # Case-insensitive path comparison is a Windows contract; no extra source is added.
    monkeypatch.setattr(environment.subprocess, "run", lambda command, **kwargs: SimpleNamespace(
        stdout="git version 2.56.0.windows.1" if command[-1] == "--version"
        else str(root / "mingw64/libexec/git-core").upper()))
    child, report = environment.prepare_environment(report_path=tmp_path / "package-environment.json")
    assert report["git_discovery"]["selected_implementation"]["layout"] == "mingw64"
    assert str(root / "mingw64/bin") not in child["PATH"]


def test_git_metadata_decoding_is_strict_utf8_for_non_ascii_installation(tmp_path, monkeypatch):
    files, calls = inputs(tmp_path / "工具 é", monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    child, report = environment.prepare_environment(report_path=tmp_path / "package-environment.json")
    assert "工具 é" in report["git_exec_path"]
    assert all(kwargs["encoding"] == "utf-8" and kwargs["errors"] == "strict" for _, kwargs in calls)
    monkeypatch.setattr(environment.os, "environ", child)
    assert environment.package_receipt()["filename"] == "package-environment.json"


def test_preflight_cli_uses_the_same_prepare_function(tmp_path, monkeypatch, capsys):
    output = tmp_path / "preflight.json"
    seen = []
    monkeypatch.setattr(environment, "prepare_environment", lambda **kwargs: seen.append(kwargs) or ({}, {}))
    environment.main(["--output", str(output)])
    assert seen == [{"report_path": output}]
    assert "no PyInstaller build or EXE acceptance" in capsys.readouterr().out


def test_preflight_cli_propagates_prepare_failure(tmp_path, monkeypatch):
    output = tmp_path / "preflight.json"
    def fail(**kwargs):
        kwargs["report_path"].write_text('{"status":"failed"}', encoding="utf-8")
        raise RuntimeError("synthetic unavailable Git layout")
    monkeypatch.setattr(environment, "prepare_environment", fail)
    with pytest.raises(RuntimeError):
        environment.main(["--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"


def test_fake_inputs_do_not_replace_shared_stdlib_or_parent_environment(tmp_path, monkeypatch):
    import importlib.util
    import shutil
    original = dict(os.environ)
    real_run, real_which, real_find_spec = subprocess.run, shutil.which, importlib.util.find_spec
    files, _ = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent), "synthetic_secret": "not copied to parent"})
    environment.prepare_environment(report_path=tmp_path / "package-environment.json")
    assert subprocess.run is real_run and shutil.which is real_which and importlib.util.find_spec is real_find_spec
    assert dict(os.environ) == original
    assert subprocess.check_output([sys.executable, "-c", "print('real stdlib still works')"], text=True).strip() == "real stdlib still works"


@pytest.mark.parametrize("change", ["git_override", "missing_tools", "missing_implementation_tool", "extra_tool", "selected_path", "selected_layout", "candidate_path", "missing_candidate", "duplicate_candidate", "extra_candidate", "root", "cmd_launcher", "implementation_tool", "exec_path", "relative_exec_path", "nul_exec_path", "version"])
def test_git_receipt_consumption_rejects_inconsistent_selection(tmp_path, monkeypatch, change):
    files, calls = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    report_path = tmp_path / "package-environment.json"
    child, report = environment.prepare_environment(report_path=report_path)
    monkeypatch.setattr(environment.os, "environ", child)
    discovery = report["git_discovery"]
    if change == "git_override":
        child["gIt_ExEc_PaTh"] = str(tmp_path / "outside")
    elif change == "missing_tools":
        report.pop("tools")
    elif change == "missing_implementation_tool":
        report["tools"].pop("git_implementation")
    elif change == "extra_tool":
        report["tools"]["extra"] = environment._file(files[4])
    elif change == "selected_path":
        discovery["selected_implementation"] = {**discovery["selected_implementation"], "path": str(tmp_path / "outside/git.exe")}
    elif change == "selected_layout":
        discovery["selected_implementation"] = {**discovery["selected_implementation"], "layout": "arbitrary"}
    elif change == "candidate_path":
        discovery["implementation_candidates"][0]["path"] = str(tmp_path / "outside/git.exe")
    elif change == "missing_candidate":
        discovery["implementation_candidates"] = []
    elif change == "duplicate_candidate":
        discovery["implementation_candidates"].append(dict(discovery["implementation_candidates"][0]))
    elif change == "extra_candidate":
        discovery["implementation_candidates"].append({"layout": "arbitrary", **environment._file(files[4])})
    elif change == "root":
        discovery["root"] = str(tmp_path / "outside")
    elif change == "cmd_launcher":
        discovery["cmd_launcher"] = environment._file(files[4])
    elif change == "implementation_tool":
        report["tools"]["git_implementation"] = environment._file(files[4])
    elif change == "exec_path":
        report["git_exec_path"] = str(tmp_path / "outside/mingw64/libexec/git-core")
    elif change == "relative_exec_path":
        report["git_exec_path"] = "mingw64/libexec/git-core"
    elif change == "nul_exec_path":
        report["git_exec_path"] += "\x00"
    else:
        report["git_version"] = "git version fake"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    # Relink this synthetic anchor to challenge structural validation independently.
    child["TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"] = environment.sha256(report_path)
    with pytest.raises(RuntimeError):
        environment.package_receipt()
    assert len(calls) == 2  # No native query or outside-root execution during receipt validation.


def test_completed_receipt_anchor_rejects_coherent_other_implementation_selection(tmp_path, monkeypatch):
    files, calls = inputs(tmp_path, monkeypatch)
    root = files[2].parent.parent
    other = root / "ucrt64/bin/git.exe"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"synthetic second implementation")
    (root / "ucrt64/libexec/git-core").mkdir(parents=True)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent),
        "taxops_package_env_receipt": "old receipt", "Taxops_Package_Env_Receipt_SHA256": "old anchor"})
    parent = dict(environment.os.environ)
    report_path = tmp_path / "package-environment.json"
    child, report = environment.prepare_environment(report_path=report_path)
    assert dict(environment.os.environ) == parent
    assert len([key for key in child if key.upper() == "TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"]) == 1
    assert child["TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"] == environment.sha256(report_path)
    assert report == json.loads(report_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(environment.os, "environ", child)
    environment.package_receipt()
    selected = next(row for row in report["git_discovery"]["implementation_candidates"] if row["layout"] == "ucrt64")
    report["git_discovery"]["selected_implementation"] = selected
    report["tools"]["git_implementation"] = {key: selected[key] for key in ("path", "sha256", "bytes")}
    report["git_exec_path"] = str(root / "ucrt64/libexec/git-core")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(RuntimeError, match="prepared child anchor"):
        environment.package_receipt()
    assert len(calls) == 2


def test_receipt_anchor_is_created_only_after_successful_final_write(tmp_path, monkeypatch):
    files, calls = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    class FailedFinalWritePath(type(tmp_path)):
        def write_bytes(self, data):
            raise OSError("synthetic failed final receipt write")
    report_path = FailedFinalWritePath(tmp_path / "package-environment.json")
    with pytest.raises(OSError, match="failed final receipt write"):
        environment.prepare_environment(report_path=report_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "failed"
    assert all("TAXOPS_PACKAGE_ENV_RECEIPT_SHA256" not in kwargs["env"] for _, kwargs in calls)


@pytest.mark.parametrize("change", ["schema", "status", "PATH", "import_overrides", "release_python"])
def test_child_comparison_diagnostics_identify_operand_without_private_values(tmp_path, monkeypatch, change):
    files, _ = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent), "ARBITRARY_SECRET": "sentinel-private-value"})
    path = tmp_path / "package-environment.json"
    child, report = environment.prepare_environment(report_path=path)
    monkeypatch.setattr(environment.os, "environ", child)
    if change == "schema":
        report["schema"] = 999
    elif change == "status":
        report["status"] = "failed"
    elif change == "PATH":
        child["PATH"] = "sentinel-private-path;" + child["PATH"]
    elif change == "import_overrides":
        child["PyThOnPaTh"] = "sentinel-private-override"
    else:
        report["release_python"]["sha256"] = "sentinel-private-hash"
    path.write_text(json.dumps(report), encoding="utf-8")
    child["TAXOPS_PACKAGE_ENV_RECEIPT_SHA256"] = environment.sha256(path)
    with pytest.raises(RuntimeError, match="Package child environment differs") as exc:
        environment.package_receipt()
    text = str(exc.value)
    comparison = json.loads(text.split(": ", 1)[1])
    assert comparison["matches"] == {name: name != change for name in
                                    ("schema", "status", "PATH", "import_overrides", "release_python")}
    assert "sentinel-private" not in text and "ARBITRARY_SECRET" not in text


@pytest.mark.parametrize("change", [None, "query_failure", "shutdown_failure", "extra_secret", "private_path", "long_private_path", "loop_runtime_error", "nul_path", "read_failure", "wrong_package", "missing", "basename", "hash", "bytes", "target", "symlink", "path_drift", "override_drift"])
def test_isolated_qt_input_rechecks_parent_and_exact_asset_without_imports(tmp_path, monkeypatch, change):
    files, _ = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(environment.os, "environ", {"Path": str(files[2].parent)})
    child, _ = environment.prepare_environment(report_path=tmp_path / "package-environment.json")
    monkeypatch.setattr(environment.os, "environ", child)
    package_dir = Path(environment.release_inputs()[1]["packages"]["PySide6"]["path"]).parent
    source = package_dir / "translations/qtbase_zh_TW.qm"
    source.parent.mkdir()
    source.write_bytes(b"synthetic catalogue bytes")
    result = {**environment._file(source), "target": str(Path("PySide6/translations"))}
    if change == "extra_secret":
        result["secret"] = "sentinel-private-child-value"
    elif change == "private_path":
        result["path"] = str(package_dir / "sentinel-private-child-value/qtbase_zh_TW.qm")
    elif change == "long_private_path":
        result["path"] = str(package_dir / ("sentinel-private-" + "x" * 300) / "qtbase_zh_TW.qm")
    elif change == "loop_runtime_error":
        result["path"] = str(package_dir / "sentinel-private-loop/qtbase_zh_TW.qm")
        class CyclicPath(type(source)):
            def resolve(self, *args, **kwargs):
                raise RuntimeError("Symlink loop from sentinel-private-loop")
        real_path = environment.Path
        monkeypatch.setattr(environment, "Path", lambda value: CyclicPath(value)
                            if str(value) == result["path"] else real_path(value))
    elif change == "nul_path":
        result["path"] = str(package_dir / "sentinel-private-\x00/qtbase_zh_TW.qm")
    elif change == "read_failure":
        real_file = environment._file
        def failed_read(path):
            if path == source:
                raise OSError("sentinel-private-file-read")
            return real_file(path)
        monkeypatch.setattr(environment, "_file", failed_read)
    elif change == "wrong_package":
        external = tmp_path / "outside/qtbase_zh_TW.qm"
        external.parent.mkdir()
        external.write_bytes(b"foreign catalogue")
        result.update(environment._file(external))
    elif change == "missing":
        source.unlink()
    elif change == "basename":
        result["path"] = str(source.parent / "different.qm")
    elif change == "hash":
        result["sha256"] = "0" * 64
    elif change == "bytes":
        result["bytes"] += 1
    elif change == "target":
        result["target"] = "arbitrary/target"
    elif change == "symlink":
        target = source.with_suffix(".real")
        source.rename(target)
        source.symlink_to(target)
    events = []
    class IsolatedChild:
        def __enter__(self):
            events.append("enter")
            return self
        def call(self, function, expected_package):
            assert function is environment._query_qt_translation and expected_package == str(package_dir)
            events.append("query")
            if change == "query_failure":
                raise RuntimeError("synthetic isolated Qt import failure")
            if change == "path_drift":
                environment.os.environ["PATH"] = "unexpected;" + environment.os.environ["PATH"]
            if change == "override_drift":
                environment.os.environ["Qt_Plugin_Path"] = "sentinel-private-override"
            return result
        def __exit__(self, *args):
            events.append("exit")
            if change == "shutdown_failure":
                raise RuntimeError("synthetic strict child shutdown failure")
    monkeypatch.setattr(environment, "_qt_isolation", IsolatedChild)
    checks = []
    real_receipt = environment.package_receipt
    def receipt():
        checks.append("checked")
        return real_receipt()
    monkeypatch.setattr(environment, "package_receipt", receipt)
    modules = {key: value for key, value in sys.modules.items() if key == "PySide6" or key.startswith("PySide6.")}
    parent = dict(environment.os.environ)
    if change:
        with pytest.raises(RuntimeError) as exc:
            environment.qt_translation_input()
        assert "sentinel-private" not in str(exc.value)
    else:
        assert environment.qt_translation_input() == result
    assert events == ["enter", "query", "exit"] and checks == ["checked", "checked"]
    assert modules == {key: value for key, value in sys.modules.items() if key == "PySide6" or key.startswith("PySide6.")}
    if change not in {"path_drift", "override_drift"}:
        assert dict(environment.os.environ) == parent


def test_spec_and_quick_probe_share_strict_isolated_qt_helper(tmp_path, monkeypatch):
    import ast
    source = (environment.ROOT / "TaxOpsControlDesk.spec").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imports += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name == "PySide6" or name.startswith("PySide6.") for name in imports)
    assert source.index("_qt_translation_input = qt_translation_input()") < source.index("a = Analysis(")
    assert 'datas=[("assets/app_icon.ico", "assets"), (str(_qt_translation), _qt_translation_target)' in source
    assert source.index("a = Analysis(") < source.index("filter_system_runtime(a.binaries, a.datas)")
    calls = []
    fake = SimpleNamespace(Python=lambda **kwargs: calls.append(kwargs) or "isolated context")
    monkeypatch.setitem(sys.modules, "PyInstaller", SimpleNamespace(isolated=fake))
    assert environment._qt_isolation() == "isolated context" and calls == [{"strict_mode": True}]
    child = {"PATH": "prepared child", "TAXOPS_PACKAGE_ENV_RECEIPT_SHA256": "anchored"}
    monkeypatch.setattr(environment, "prepare_environment", lambda **kwargs: (child, {}))
    runs = []
    waits = []
    process = SimpleNamespace(wait=lambda **kwargs: waits.append(kwargs) or 0)
    monkeypatch.setattr(environment, "subprocess", SimpleNamespace(Popen=lambda command, **kwargs:
        runs.append((command, kwargs)) or process))
    parent = dict(os.environ)
    environment.main(["--output", str(tmp_path / "preflight.json"), "--probe-qt-translation"])
    assert len(runs) == 1 and runs[0][0][0] == str(Path(sys.executable).resolve())
    assert "qt_translation_input()" in runs[0][0][-1]
    assert runs[0][1] == {"env": child} and waits == [{"timeout": 120}]
    assert dict(os.environ) == parent


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "cleanup_failed"])
def test_qt_probe_preserves_failure_and_cleans_only_retained_live_tree(tmp_path, monkeypatch, failure):
    from build_tools import owned_process_cleanup
    child = {"PATH": "prepared child"}
    monkeypatch.setattr(environment, "prepare_environment", lambda **kwargs: (child, {}))
    events = []
    class Process:
        pid = 1234
        _handle = "retained synthetic Windows handle"
        def wait(self, timeout):
            events.append(("wait", timeout))
            if failure != "nonzero":
                raise subprocess.TimeoutExpired("synthetic owned probe", timeout)
            return 17
    process = Process()
    def launch(command, **kwargs):
        assert Path(command[0]).is_absolute() and kwargs == {"env": child}
        events.append("launch")
        return process
    monkeypatch.setattr(environment, "subprocess", SimpleNamespace(
        Popen=launch, TimeoutExpired=subprocess.TimeoutExpired, CalledProcessError=subprocess.CalledProcessError))
    evidence = tmp_path / "package-qt-probe-cleanup.json"
    def cleanup(owned, output):
        assert owned is process and owned._handle == "retained synthetic Windows handle" and output == evidence
        events.append("cleanup")
        record = {"status": "failed" if failure == "cleanup_failed" else "owned_tree_termination_requested",
                  "descendant_cleanup_verified": False, "normal_cleanup": False}
        output.write_text(json.dumps([record]), encoding="utf-8")
        return record
    monkeypatch.setattr(owned_process_cleanup, "terminate_owned_tree", cleanup)
    error = subprocess.CalledProcessError if failure == "nonzero" else subprocess.TimeoutExpired
    with pytest.raises(error):
        environment.main(["--output", str(tmp_path / "preflight.json"), "--probe-qt-translation"])
    assert events == ["launch", ("wait", 120)] + ([] if failure == "nonzero" else ["cleanup"])
    if failure != "nonzero":
        record = json.loads(evidence.read_text(encoding="utf-8"))[0]
        assert record["descendant_cleanup_verified"] is False and record["normal_cleanup"] is False
