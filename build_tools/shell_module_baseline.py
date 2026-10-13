"""Live, same-verifier Shell observation context, never an imported allowlist.

The CPython bootstrap inventory below applies only to the independent observer.
It grants no application runtime permission and is not a publisher attestation.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import subprocess
import sys
from pathlib import Path

from build_tools import shell_icon_probe as probe
from build_tools.owned_process_cleanup import terminate_owned_tree
from build_tools.source_materials import source_identity
from build_tools.windows_loaded_modules import (
    LoadedModuleError,
    _LiveShellEvidence,
    _path,
    protected_module_name,
)

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_PATHS = (
    "python.exe",
    "python311.dll",
    "python3.dll",
    "vcruntime140.dll",
    "DLLs/_ctypes.pyd",
    "DLLs/libffi-8.dll",
    "DLLs/_hashlib.pyd",
    "DLLs/libcrypto-3.dll",
    "DLLs/_bz2.pyd",
    "DLLs/_lzma.pyd",
)
HELPERS = (
    "shell_icon_probe.py",
    "shell_module_baseline.py",
    "windows_loaded_modules.py",
    "owned_process_cleanup.py",
    "source_materials.py",
    "verify_onefile.py",
    "windows_pe_dependencies.py",
    "windows_inbox_runtime.py",
    "official_vc_runtime.py",
    "verify_microsoft_signature.ps1",
)
_LIVE = object()


def helper_identities() -> list[dict]:
    return [probe.file_identity(ROOT / "build_tools" / name) for name in HELPERS]


def row_identity(row: dict) -> tuple[str, str, int]:
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        or type(row.get("bytes")) is not int
        or row["bytes"] <= 0
    ):
        raise LoadedModuleError("Missing Shell module path/hash/bytes")
    return _path(row.get("path")), row["sha256"], row["bytes"]


def index_snapshot(snapshot: dict) -> dict:
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("status") != "observed"
        or type(snapshot.get("attempt")) is not int
        or not 1 <= snapshot["attempt"] <= 3
        or not isinstance(snapshot.get("modules"), list)
        or not snapshot["modules"]
    ):
        raise LoadedModuleError("Incomplete Shell snapshot")
    indexed, handles = {}, set()
    for row in snapshot["modules"]:
        path, _digest, _size = row_identity(row)
        if (
            row.get("status") != "observed"
            or _path(row.get("loader_path")) != path
            or path in indexed
            or type(row.get("handle")) is not int
            or row["handle"] <= 0
            or row["handle"] in handles
        ):
            raise LoadedModuleError("Duplicate or invalid Shell module identity")
        indexed[path] = row
        handles.add(row["handle"])
    return indexed


def os_location(path: str, roots: dict) -> bool:
    return ntpath.dirname(path) == _path(roots["system32"]) or path.startswith(
        _path(roots["winsxs"]) + "\\"
    )


def qt_contamination(path: str) -> bool:
    return (
        re.match(r"(?:qt\d|pyside|shiboken|taxops)", ntpath.basename(path)) is not None
    )


def checked_additions(before: dict, after: dict) -> list[dict]:
    old, new = index_snapshot(before), index_snapshot(after)
    if set(old) - set(new) or any(
        row_identity(old[p]) != row_identity(new[p]) for p in old.keys() & new.keys()
    ):
        raise LoadedModuleError("Shell snapshots removed or changed modules")
    return [new[p] for p in sorted(set(new) - set(old))]


def validate_observation(
    receipt: dict,
    *,
    challenge: dict,
    pid: int,
    parent_pid: int,
    interpreter: dict,
    sources: list,
    host: dict,
    bootstrap: list,
    input_identity: dict,
    roots: dict,
    protected_names: set,
) -> dict:
    """Pure validation; its return alone cannot create live acceptance authority."""
    if (
        receipt.get("schema") != 2
        or receipt.get("status") != "observed"
        or receipt.get("scope") != probe.SCOPE
        or receipt.get("challenge") != challenge
        or receipt.get("process_id") != pid
        or receipt.get("parent_process_id") != parent_pid
        or receipt.get("executable") != interpreter
        or receipt.get("source") != sources
        or receipt.get("source_after") != sources
        or receipt.get("host") != host
        or receipt.get("input") != input_identity
        or receipt.get("python") != [3, 11, 9]
        or receipt.get("isolated") != 1
        or receipt.get("no_site") != 1
        or receipt.get("qt_or_taxops_imported") is not False
    ):
        raise LoadedModuleError(
            "Shell observation run/process/source/host identity mismatch"
        )
    com = receipt.get("com", {})
    if (
        com.get("accepted") is not True
        or type(com.get("hresult")) is not int
        or com["hresult"] not in (0, 1)
        or com.get("uninitialized") is not True
    ):
        raise LoadedModuleError("Shell COM initialization or cleanup failed")
    old = index_snapshot(receipt.get("before"))
    approved_bootstrap = {row_identity(row) for row in bootstrap}
    if row_identity(interpreter) not in {row_identity(row) for row in old.values()}:
        raise LoadedModuleError("Shell observer EXE missing from baseline")
    for path, row in old.items():
        if qt_contamination(path) or (
            not os_location(path, roots) and row_identity(row) not in approved_bootstrap
        ):
            raise LoadedModuleError("Contaminated Shell before snapshot")
    calls = receipt.get("calls")
    if not isinstance(calls, list) or len(calls) != 2:
        raise LoadedModuleError("Incomplete Shell query sequence")
    previous = receipt["before"]
    target_root = ntpath.dirname(input_identity["path"])
    for call, target in zip(
        calls,
        (input_identity["path"], ntpath.join(target_root, "synthetic folder")),
        strict=True,
    ):
        if (
            not isinstance(call, dict)
            or _path(call.get("path")) != _path(target)
            or call.get("flags") != probe.FLAGS
            or call.get("file_attributes_argument") != 0
            or call.get("status") != "observed"
            or type(call.get("return_value")) is not int
            or call["return_value"] <= 0
            or type(call.get("hicon")) is not int
            or call["hicon"] <= 0
            or call.get("destroy_icon", {}).get("return_value") != 1
        ):
            raise LoadedModuleError("Shell query or owned icon cleanup failed")
        checked_additions(previous, call.get("after"))
        # Delta is recorded for review, but cannot grant permission by itself.
        if call.get("delta") != probe.delta(previous, call["after"]):
            raise LoadedModuleError("Shell per-query delta was altered")
        previous = call["after"]
    if receipt.get("after") != previous:
        raise LoadedModuleError("Shell final snapshot differs from last query")
    added = checked_additions(receipt["before"], previous)
    if receipt.get("delta") != probe.delta(receipt["before"], previous):
        raise LoadedModuleError("Shell aggregate delta was altered")
    if any(qt_contamination(path) for path in index_snapshot(previous)):
        raise LoadedModuleError(
            "Qt or TaxOps native module contaminated Shell observer"
        )
    eligible, excluded = [], []
    for row in added:
        path, _digest, _size = row_identity(row)
        if protected_module_name(ntpath.basename(path), protected_names):
            excluded.append(
                {"module": row, "reason": "protected_application_dependency_name"}
            )
        elif os_location(path, roots):
            excluded.append(
                {"module": row, "reason": "existing_narrow_os_location_rule"}
            )
        else:
            eligible.append(row)
    return {
        "eligible": eligible,
        "excluded": excluded,
        "before_count": len(old),
        "after_count": len(index_snapshot(previous)),
        "added_count": len(added),
    }


def required_dependency_names(report: dict) -> set[str]:
    """Names from the already-passed complete PE inventory, including forwarders."""
    if (
        report.get("status") != "passed"
        or not report.get("inventory")
        or not report.get("dependencies")
    ):
        raise LoadedModuleError("Missing passed PE dependency evidence")
    names = set()
    from build_tools.windows_pe_dependencies import dll_name

    for row in report["inventory"]:
        names.add(ntpath.basename(row["path"]).casefold())
        for entry in row["imports"]:
            names.add(dll_name(entry["dll"]).casefold())
        for entry in row["exports"]:
            if entry.get("forwarder"):
                names.add(
                    dll_name(entry["forwarder"].rsplit(".", 1)[0] + ".dll").casefold()
                )

    def relative_name(path):
        if (
            not isinstance(path, str)
            or not path
            or ntpath.isabs(path)
            or ":" in path
            or ".." in path.replace("\\", "/").split("/")
        ):
            raise LoadedModuleError("Invalid bundled PE resolution path")
        return ntpath.basename(path).casefold()

    def resolution_names(resolution, depth=0):
        if not isinstance(resolution, dict) or depth > 64:
            raise LoadedModuleError("Invalid or excessively nested PE resolution")
        kind = resolution.get("kind")
        if kind == "windows_system":
            names.add(ntpath.basename(_path(resolution.get("module_path"))))
            symbols = resolution.get("symbols")
            if not isinstance(symbols, list):
                raise LoadedModuleError("Missing resolved PE provider symbols")
            for symbol in symbols:
                if not isinstance(symbol, dict):
                    raise LoadedModuleError("Invalid resolved PE provider symbol")
                names.add(ntpath.basename(_path(symbol.get("provider"))))
        elif kind == "bundle":
            candidates, forwarders = (
                resolution.get("candidates"),
                resolution.get("forwarders"),
            )
            if (
                not isinstance(candidates, list)
                or not candidates
                or not isinstance(forwarders, list)
            ):
                raise LoadedModuleError("Incomplete bundled PE resolution")
            names.update(relative_name(path) for path in candidates)
            for forwarder in forwarders:
                if not isinstance(forwarder, dict):
                    raise LoadedModuleError("Invalid bundled PE forwarder resolution")
                resolution_names(forwarder.get("resolution"), depth + 1)
        else:
            raise LoadedModuleError("Unknown PE resolution kind")

    for dependency in report["dependencies"]:
        if not isinstance(dependency, dict) or dependency.get("kind") not in {
            "normal",
            "delay",
        }:
            raise LoadedModuleError("Invalid PE dependency edge")
        resolution_names(dependency.get("resolution"))
    return names


class LiveShellBaseline(_LiveShellEvidence):
    def __init__(
        self,
        key,
        *,
        run_id,
        source,
        helpers,
        host,
        bootstrap,
        interpreter,
        classification,
        report_path,
        report_hash,
        protected_names,
    ):
        if key is not _LIVE:
            raise LoadedModuleError(
                "A saved Shell receipt cannot authorize classification"
            )
        self.pid, self.run_id = os.getpid(), run_id
        self.source, self.helpers, self.host = source, helpers, host
        self.bootstrap, self.interpreter = bootstrap, interpreter
        self.classification, self.report_path, self.report_hash = (
            classification,
            report_path,
            report_hash,
        )
        self.protected_names = frozenset(protected_names)
        self._eligible = {
            row_identity(row)[0]: row for row in classification["eligible"]
        }

    def current(self, run_id: str) -> None:
        if (
            self.pid != os.getpid()
            or self.run_id != run_id
            or self.source != source_identity(ROOT)
            or self.helpers != helper_identities()
            or self.host != probe.host_identity()
            or probe.file_identity(self.report_path)["sha256"] != self.report_hash
            or any(
                probe.file_identity(Path(row["path"])) != row for row in self.bootstrap
            )
        ):
            raise LoadedModuleError(
                "Shell classification context changed after live observation"
            )

    def match(self, row: dict) -> dict:
        identity = row_identity(row)
        baseline = self._eligible.get(identity[0])
        if baseline is None or row_identity(baseline) != identity:
            raise LoadedModuleError(
                "External module lacks exact same-run Shell addition evidence"
            )
        current = probe.file_identity(Path(row["path"]))
        if row_identity(current) != identity:
            raise LoadedModuleError(
                "Shell-observed file bytes changed before application classification"
            )
        return {
            "classification": "independently_shell_observed_external",
            **current,
            "baseline_report_sha256": self.report_hash,
            "acceptance_run_id": self.run_id,
        }


def collect(
    output: Path, *, run_id: str, protected_names: set, timeout: int = 90
) -> LiveShellBaseline:
    if sys.platform != "win32" or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise LoadedModuleError(
            "Live Shell baseline requires Windows and a fresh verifier run ID"
        )
    root = output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for relative in (
        "profile/local",
        "profile/roaming",
        "temp",
        "inputs/synthetic folder",
    ):
        (root / relative).mkdir(parents=True)
    (root / "inputs/synthetic.txt").write_bytes(probe.CONTENT)
    process = None
    report_path = root / "report.json"
    evidence = {
        "schema": 1,
        "status": "failed",
        "scope": probe.SCOPE,
        "acceptance_run_id": run_id,
    }
    try:
        base = Path(sys._base_executable).resolve(strict=True)
        interpreter = probe.file_identity(base)
        if base.name.casefold() != "python.exe" or tuple(sys.version_info[:3]) != (
            3,
            11,
            9,
        ):
            raise LoadedModuleError(
                "Shell observer requires the pinned base CPython 3.11.9"
            )
        bootstrap = [
            probe.file_identity(base.parent / name) for name in BOOTSTRAP_PATHS
        ]
        source, helpers, host = (
            source_identity(ROOT),
            helper_identities(),
            probe.host_identity(),
        )
        sources, input_identity = (
            probe.source_identity(),
            probe.file_identity(root / "inputs/synthetic.txt"),
        )
        import secrets

        challenge = {
            "acceptance_run_id": run_id,
            "nonce": secrets.token_hex(32),
            "source": source,
        }
        env = os.environ.copy()
        for key in list(env):
            if key.upper().startswith(
                ("PYTHON", "QT_", "PYSIDE", "SHIBOKEN", "TAXOPS")
            ):
                env.pop(key)
        for key, relative in (
            ("USERPROFILE", "profile"),
            ("HOME", "profile"),
            ("LOCALAPPDATA", "profile/local"),
            ("APPDATA", "profile/roaming"),
            ("TEMP", "temp"),
            ("TMP", "temp"),
        ):
            env[key] = str(root / relative)
        env["PATH"] = host["os_roots"]["system32"]
        env["HOMEDRIVE"], env["HOMEPATH"] = ntpath.splitdrive(env["USERPROFILE"])
        evidence.update(
            {
                "schema": 1,
                "status": "failed",
                "scope": probe.SCOPE,
                "challenge": challenge,
                "source": source,
                "helpers": helpers,
                "host": host,
                "interpreter": interpreter,
                "bootstrap": bootstrap,
                "input": input_identity,
            }
        )
        command = [
            str(base),
            "-I",
            "-S",
            str(ROOT / "build_tools/shell_icon_probe.py"),
            "--output",
            str(root),
        ]
        with (
            (root / "stdout.bin").open("wb") as stdout,
            (root / "stderr.bin").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
            )
            evidence["retained_popen_pid"] = process.pid
            process.communicate(
                (json.dumps(challenge) + "\n").encode("utf-8"), timeout=timeout
            )
            evidence["outer_returncode"] = process.returncode
        if process.returncode != 0:
            raise LoadedModuleError("Direct Shell observer exited unsuccessfully")
        receipt = json.loads((root / "child.json").read_text(encoding="utf-8"))
        evidence["child"] = receipt
        classification = validate_observation(
            receipt,
            challenge=challenge,
            pid=process.pid,
            parent_pid=os.getpid(),
            interpreter=interpreter,
            sources=sources,
            host=host,
            bootstrap=bootstrap,
            input_identity=input_identity,
            roots=host["os_roots"],
            protected_names=protected_names,
        )
        if (
            source_identity(ROOT) != source
            or helper_identities() != helpers
            or probe.source_identity() != sources
            or probe.host_identity() != host
            or probe.file_identity(root / "inputs/synthetic.txt") != input_identity
            or any(probe.file_identity(Path(row["path"])) != row for row in bootstrap)
        ):
            raise LoadedModuleError("Shell observer source/input/runtime changed")
        evidence.update(
            status="observed",
            classification=classification,
            child_exit_directly_observed=True,
        )
    except Exception as exc:
        evidence["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if process is not None and process.poll() is None:
            evidence["forced_cleanup"] = terminate_owned_tree(
                process, root / "owned-cleanup.json"
            )
        probe.save(report_path, evidence)
    return LiveShellBaseline(
        _LIVE,
        run_id=run_id,
        source=source,
        helpers=helpers,
        host=host,
        bootstrap=bootstrap,
        interpreter=interpreter,
        classification=classification,
        report_path=report_path,
        report_hash=probe.file_identity(report_path)["sha256"],
        protected_names=protected_names,
    )
