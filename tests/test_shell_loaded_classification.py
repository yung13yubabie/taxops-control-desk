"""Synthetic same-run classification guards, not native Windows acceptance."""

from __future__ import annotations

import copy
import ntpath
from types import SimpleNamespace

import pytest

from build_tools import shell_module_baseline as shell
from build_tools import windows_loaded_modules as modules
from test_loaded_modules import EXE, HASH, MEI, ROOTS, fixture


RUN_ID = "a" * 32
REPORT_HASH = "b" * 64
EXTERNAL = r"C:\Synthetic extensions 中文\observer-addon.dll"


def external_row(path=EXTERNAL):
    return {
        "path": path,
        "loader_path": path,
        "sha256": "c" * 64,
        "bytes": 321,
        "location": "external",
    }


def validate(report, inventory, phase, baseline=None, run_id=RUN_ID):
    return modules.validate_loaded_modules(
        report,
        expected_native=inventory,
        meipass=MEI,
        executable=EXE,
        executable_sha256=HASH,
        os_roots=ROOTS,
        phase=phase,
        shell_baseline=baseline,
        acceptance_run_id=run_id,
    )


@pytest.fixture(params=("gui_ready", "after_18_checks"))
def phase(request):
    return request.param


@pytest.fixture
def application(phase):
    report, inventory = fixture()
    report["phase"] = phase
    return report, inventory


@pytest.fixture
def live_baseline(monkeypatch, tmp_path):
    """Keep real current/match methods; fake only their synthetic host inputs.

    Using the private live key deliberately models a context already produced
    by the collector. No persisted receipt or duck-typed object gains authority.
    """
    def make(rows=None, *, protected_names=()):
        rows = [external_row()] if rows is None else copy.deepcopy(rows)
        interpreter = {
            "path": r"C:\Synthetic Python\python.exe",
            "sha256": "d" * 64,
            "bytes": 456,
        }
        report_path = tmp_path / "synthetic-shell-report.json"
        source = {"commit": "e" * 40, "tree": "f" * 40}
        helpers = [{"path": "synthetic-helper.py", "sha256": HASH, "bytes": 42}]
        host = {"computer": "synthetic-host", "os_roots": ROOTS.copy()}
        files = {
            str(report_path): {"path": str(report_path), "sha256": REPORT_HASH, "bytes": 99},
            interpreter["path"]: copy.deepcopy(interpreter),
            **{
                modules._path(row["path"]): {
                    key: row[key] for key in ("path", "sha256", "bytes")
                }
                for row in rows
            },
        }
        state = SimpleNamespace(
            source=copy.deepcopy(source),
            helpers=copy.deepcopy(helpers),
            host=copy.deepcopy(host),
            files=files,
            reads=[],
            report_path=report_path,
            interpreter_path=interpreter["path"],
        )

        def identity(path):
            key = str(path)
            if key != str(report_path) and key != interpreter["path"]:
                key = modules._path(key)
            state.reads.append(key)
            if key not in state.files:
                raise FileNotFoundError(str(path))
            return copy.deepcopy(state.files[key])

        monkeypatch.setattr(shell, "source_identity", lambda _root: copy.deepcopy(state.source))
        monkeypatch.setattr(shell, "helper_identities", lambda: copy.deepcopy(state.helpers))
        monkeypatch.setattr(shell.probe, "host_identity", lambda: copy.deepcopy(state.host))
        monkeypatch.setattr(shell.probe, "file_identity", identity)
        baseline = shell.LiveShellBaseline(
            shell._LIVE,
            run_id=RUN_ID,
            source=source,
            helpers=helpers,
            host=host,
            bootstrap=[interpreter],
            interpreter=interpreter,
            classification={"eligible": rows, "excluded": []},
            report_path=report_path,
            report_hash=REPORT_HASH,
            protected_names=set(protected_names),
        )
        return baseline, state

    return make


def test_exact_same_run_external_identity_is_classified(application, phase, live_baseline):
    report, inventory = application
    report["modules"].append(external_row())
    baseline, state = live_baseline()

    result = validate(report, inventory, phase, baseline)

    assert result["phase"] == phase
    assert result["independently_shell_observed_external"] == [{
        "classification": "independently_shell_observed_external",
        "path": EXTERNAL,
        "sha256": "c" * 64,
        "bytes": 321,
        "baseline_report_sha256": REPORT_HASH,
        "acceptance_run_id": RUN_ID,
    }]
    assert result["shell_eligible_not_observed"] == []
    assert result["not_observed_embedded"] == ["pyside6/plugins/imageformats/qgif.dll"]
    assert modules.CORE_PATHS.issubset(result["loaded_embedded"])
    assert result["os_location_module_count"] == 1
    assert result["clean_os_verified"] is False
    assert result["scope"] == modules.LIMITATION
    assert modules._path(EXTERNAL) in state.reads


def test_unobserved_shell_addition_is_not_claimed_loaded(application, phase, live_baseline):
    report, inventory = application
    baseline, _state = live_baseline()
    result = validate(report, inventory, phase, baseline)
    assert result["independently_shell_observed_external"] == []
    assert result["shell_eligible_not_observed"] == [modules._path(EXTERNAL)]


@pytest.mark.parametrize("context", ("absent", "saved_receipt", "duck_typed"))
def test_external_requires_actual_live_context(application, phase, context):
    report, inventory = application
    report["modules"].append(external_row())
    baseline = None
    if context == "saved_receipt":
        baseline = {"status": "observed", "classification": {"eligible": [external_row()]}}
    elif context == "duck_typed":
        baseline = SimpleNamespace(
            current=lambda _run_id: None,
            match=lambda row: row,
            protected_names=frozenset(),
            _eligible={modules._path(EXTERNAL): external_row()},
        )
    with pytest.raises(modules.LoadedModuleError):
        validate(report, inventory, phase, baseline)


@pytest.mark.parametrize("run_id", (None, "f" * 32, ""))
def test_wrong_or_missing_run_fails(application, phase, live_baseline, run_id):
    report, inventory = application
    report["modules"].append(external_row())
    baseline, _state = live_baseline()
    with pytest.raises(modules.LoadedModuleError, match="context changed"):
        validate(report, inventory, phase, baseline, run_id)


@pytest.mark.parametrize("fault", ("source", "helpers", "host", "report", "bootstrap", "pid"))
def test_live_context_must_still_match(application, phase, live_baseline, fault):
    report, inventory = application
    report["modules"].append(external_row())
    baseline, state = live_baseline()
    if fault == "source":
        state.source["tree"] = "0" * 40
    elif fault == "helpers":
        state.helpers[0]["sha256"] = "0" * 64
    elif fault == "host":
        state.host["computer"] = "another-synthetic-host"
    elif fault == "report":
        state.files[str(state.report_path)]["sha256"] = "0" * 64
    elif fault == "bootstrap":
        state.files[state.interpreter_path]["sha256"] = "0" * 64
    elif fault == "pid":
        baseline.pid += 1
    with pytest.raises(modules.LoadedModuleError, match="context changed"):
        validate(report, inventory, phase, baseline)


@pytest.mark.parametrize("fault", ("path", "hash", "bytes", "unknown"))
def test_application_external_must_match_baseline_exactly(application, phase, live_baseline, fault):
    report, inventory = application
    row = external_row()
    baseline, _state = live_baseline()
    if fault == "path":
        row["path"] = r"C:\Another location\observer-addon.dll"
        row["loader_path"] = row["path"]
    elif fault == "hash":
        row["sha256"] = "0" * 64
    elif fault == "bytes":
        row["bytes"] += 1
    elif fault == "unknown":
        row["path"] = r"C:\Synthetic extensions 中文\unknown-addon.dll"
        row["loader_path"] = row["path"]
    report["modules"].append(row)
    with pytest.raises(modules.LoadedModuleError, match="exact same-run"):
        validate(report, inventory, phase, baseline)


@pytest.mark.parametrize("fault", ("hash", "bytes", "deleted"))
def test_external_file_is_rechecked_at_classification(application, phase, live_baseline, fault):
    report, inventory = application
    report["modules"].append(external_row())
    baseline, state = live_baseline()
    path = modules._path(EXTERNAL)
    if fault == "hash":
        state.files[path]["sha256"] = "0" * 64
    elif fault == "bytes":
        state.files[path]["bytes"] += 1
    else:
        del state.files[path]
    with pytest.raises((modules.LoadedModuleError, FileNotFoundError)):
        validate(report, inventory, phase, baseline)
    assert path in state.reads


def test_external_canonical_and_loader_path_must_agree(application, phase, live_baseline):
    report, inventory = application
    row = external_row()
    row["loader_path"] = r"C:\Synthetic redirect\observer-addon.dll"
    report["modules"].append(row)
    baseline, _state = live_baseline()
    with pytest.raises(modules.LoadedModuleError, match="loader path"):
        validate(report, inventory, phase, baseline)


def test_equivalent_case_and_extended_loader_paths_remain_valid(application, phase, live_baseline):
    report, inventory = application
    row = external_row()
    row["path"] = EXTERNAL.upper()
    row["loader_path"] = "\\\\?\\" + EXTERNAL
    report["modules"].append(row)
    baseline, _state = live_baseline()
    result = validate(report, inventory, phase, baseline)
    assert len(result["independently_shell_observed_external"]) == 1
    assert result["shell_eligible_not_observed"] == []


@pytest.mark.parametrize("name", (
    "qgif.dll",  # Payload entry that is legitimately unobserved in the core fixture.
    "python311.dll", "python999.dll", "Qt6Core.dll", "Qt7Future.dll",
    "PySide6.abi3.dll", "Shiboken6.abi3.dll", "VCRUNTIME140.dll",
    "MSVCP140.dll", "concrt140.dll", "vcamp140.dll", "vcomp140.dll",
    "TaxOpsAddon.dll", "innocent-name.pyd",
))
def test_protected_names_never_gain_shell_permission(application, phase, live_baseline, name):
    report, inventory = application
    row = external_row(ntpath.join(ntpath.dirname(EXTERNAL), name))
    report["modules"].append(row)
    # Deliberately over-generous synthetic eligibility tests the downstream guard.
    baseline, _state = live_baseline([row])
    with pytest.raises(modules.LoadedModuleError, match="outside"):
        validate(report, inventory, phase, baseline)


def dependency_names():
    return shell.required_dependency_names({
        "status": "passed",
        "inventory": [{
            "path": "plugins/inventory-only.dll",
            "imports": [
                {"kind": "normal", "dll": "NORMAL-DEPENDENCY.DLL", "symbols": []},
                {"kind": "delay", "dll": "DELAY-DEPENDENCY.DLL", "symbols": []},
                {"kind": "normal", "dll": "KERNEL32.DLL", "symbols": []},
            ],
            "exports": [{"name": "Forwarded", "ordinal": 1,
                         "forwarder": "FORWARDER-DEPENDENCY.Target"}],
        }],
        "dependencies": [{"kind": "normal", "dll": "NORMAL-DEPENDENCY.DLL",
            "resolution": {"kind": "windows_system", "module_path": ROOTS["system32"] + r"\normal-dependency.dll", "symbols": []}}],
    })


@pytest.mark.parametrize("name", (
    "inventory-only.dll", "normal-dependency.dll", "delay-dependency.dll",
    "forwarder-dependency.dll",
))
def test_complete_pe_dependency_names_are_protected(application, phase, live_baseline, name):
    report, inventory = application
    names = dependency_names()
    assert name in names
    row = external_row(ntpath.join(ntpath.dirname(EXTERNAL), name))
    report["modules"].append(row)
    baseline, _state = live_baseline([row], protected_names=names)
    with pytest.raises(modules.LoadedModuleError, match="outside"):
        validate(report, inventory, phase, baseline)


def test_required_kernel32_retains_existing_narrow_os_rule(application, phase, live_baseline):
    report, inventory = application
    names = dependency_names()
    assert "kernel32.dll" in names
    report["modules"].append(external_row())
    baseline, _state = live_baseline(protected_names=names)
    result = validate(report, inventory, phase, baseline)
    assert result["os_location_module_count"] == 1
    assert len(result["independently_shell_observed_external"]) == 1


@pytest.mark.parametrize("name", ("python311.dll", "Qt6Core.dll", "MSVCP140.dll", "innocent.pyd"))
@pytest.mark.parametrize("location", ("windows_system32", "windows_winsxs"))
def test_shell_context_does_not_relax_protected_os_modules(application, phase, live_baseline, name, location):
    report, inventory = application
    root = ROOTS["system32"] if location == "windows_system32" else ROOTS["winsxs"] + r"\synthetic"
    row = external_row(ntpath.join(root, name))
    row["location"] = location
    report["modules"].append(row)
    baseline, _state = live_baseline([row])
    with pytest.raises(modules.LoadedModuleError, match="outside"):
        validate(report, inventory, phase, baseline)


@pytest.mark.parametrize("fault", (
    "missing_python", "missing_qt", "missing_binding", "missing_vc", "missing_exe",
    "missing_os", "extraction_hash", "unknown_extraction", "exe_hash", "duplicate",
))
def test_shell_context_preserves_complete_core_gate(application, phase, live_baseline, fault):
    report, inventory = application
    rows = report["modules"]
    baseline, _state = live_baseline()
    missing_names = {
        "missing_python": "python311.dll",
        "missing_qt": "qt6core.dll",
        "missing_binding": "pyside6.abi3.dll",
        "missing_vc": "msvcp140.dll",
        "missing_exe": "taxopscontroldesk.exe",
        "missing_os": "kernel32.dll",
    }
    if fault in missing_names:
        rows[:] = [row for row in rows if ntpath.basename(row["path"]).casefold() != missing_names[fault]]
    elif fault == "extraction_hash":
        next(row for row in rows if row["location"] == "extraction")["sha256"] = "0" * 64
    elif fault == "unknown_extraction":
        row = external_row(MEI + r"\unknown.dll")
        row["location"] = "extraction"
        rows.append(row)
    elif fault == "exe_hash":
        rows[0]["sha256"] = "0" * 64
    elif fault == "duplicate":
        rows.append(copy.deepcopy(rows[-1]))
    rows.append(external_row())
    with pytest.raises(modules.LoadedModuleError):
        validate(report, inventory, phase, baseline)


def test_frozen_collector_does_not_statically_import_host_acceptance_tools():
    import ast
    from pathlib import Path
    root = Path(modules.__file__).resolve().parent.parent
    pending, visited = ["build_tools.windows_loaded_modules"], set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        source = root.joinpath(*name.split(".")).with_suffix(".py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith("build_tools."))
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("build_tools."):
                pending.append(node.module)
    assert visited == {"build_tools.windows_loaded_modules"}
    assert issubclass(shell.LiveShellBaseline, modules._LiveShellEvidence)


def test_bare_interface_cannot_authorize_classification(application, phase):
    report, inventory = application
    report["modules"].append(external_row())
    bare = modules._LiveShellEvidence()
    with pytest.raises(modules.LoadedModuleError, match="not live"):
        validate(report, inventory, phase, bare)
    with pytest.raises(modules.LoadedModuleError, match="not live"):
        bare.match(external_row())
