"""Rebuild and exercise modified Qt/PySide components inside a fresh single EXE."""
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from build_tools.dependency_licenses import ROOT, sha256
from build_tools.qgif_rebuild.prepare_source import prepare, QTBASE_SHA256
from build_tools.recombine_inputs import SUPPORT_MARKER
from build_tools.source_materials import source_identity


def run(command: list[str], *, env: dict | None = None, log: Path | None = None) -> None:
    if log:
        with log.open("w", encoding="utf-8") as handle:
            subprocess.run(command, cwd=ROOT, env=env, check=True, stdout=handle, stderr=subprocess.STDOUT)
    else:
        subprocess.run(command, cwd=ROOT, env=env, check=True)


def recombine(work: Path, qt_prefix: Path, qtbase_source: Path, vc_redist: Path,
              *, wheelhouse: Path | None = None, test_python: Path | None = None,
              release_python: Path | None = None, compiled_qgif: Path | None = None,
              compiled_qgif_sha256: str | None = None, prepared_qgif_source: Path | None = None) -> None:
    if sys.platform != "win32" or platform.python_version() != "3.11.9":
        raise ValueError("Run with Windows x64 Python 3.11.9 in an x64 Native Tools prompt")
    if not compiled_qgif and any(shutil.which(tool) is None for tool in ("cl", "cmake", "ninja")):
        raise ValueError("The x64 compiler, CMake and Ninja must already be available")
    if bool(test_python) != bool(release_python):
        raise ValueError("Supply both existing isolated test and release Python interpreters")
    if compiled_qgif and (not compiled_qgif_sha256 or prepared_qgif_source is None):
        raise ValueError("Reusing a compiled qgif requires its exact SHA-256 and prepared source directory")
    if sha256(qtbase_source) != QTBASE_SHA256:
        raise ValueError("Cached official Qt source SHA-256 mismatch")
    if not (qt_prefix / "bin/Qt6Core.dll").is_file():
        raise ValueError("Point --qt-prefix to the exact extracted Qt 6.10.2 SDK")
    work.mkdir(parents=True, exist_ok=False)
    (work / "input-source-identity.json").write_text(json.dumps(source_identity(ROOT), indent=2) + "\n", encoding="utf-8")
    install_options = ["--only-binary=:all:"]
    if wheelhouse:
        install_options += ["--no-index", "--find-links", str(wheelhouse.resolve())]
    interpreters = {}
    for kind in ("test", "release"):
        existing = test_python if kind == "test" else release_python
        if existing is not None:
            python = str(existing.resolve())
            interpreters[kind] = python
            run([python, "-c", "from build_tools.dependency_licenses import validate_build_environment; validate_build_environment()"])
            run([python, "-m", "pip", "check"])
            continue
        venv = work / f"venv-{kind}"
        run([sys.executable, "-m", "venv", str(venv)])
        python = str(venv / "Scripts/python.exe")
        interpreters[kind] = python
        requirements = ["--require-hashes", "-r", str(ROOT / "requirements-release-hashed.txt")]
        run([python, "-m", "pip", "install", *install_options, *requirements])
        if kind == "test":
            run([python, "-m", "pip", "install", *install_options, "-r", str(ROOT / "requirements-ci.txt")])
        run([python, "-m", "pip", "check"])
    run([interpreters["test"], "-m", "build_tools.run_test_matrix", "--output", str(work / "source-tests")])
    if compiled_qgif:
        plugin = compiled_qgif.resolve()
        if sha256(plugin) != compiled_qgif_sha256:
            raise ValueError("Previously compiled qgif SHA-256 mismatch")
        receipt = json.loads((prepared_qgif_source / "source-receipt.json").read_text(encoding="utf-8"))
        if receipt.get("source_archive_sha256") != QTBASE_SHA256 or receipt.get("qt_version") != "6.10.2":
            raise ValueError("Prepared qgif source is not bound to the fixed official archive")
        if {row["file"] for row in receipt.get("files", [])} != {"main.cpp", "qgifhandler.cpp", "qgifhandler_p.h", "gif.json"}:
            raise ValueError("Prepared qgif source receipt is incomplete")
        for row in receipt["files"]:
            if sha256(prepared_qgif_source / row["file"]) != row["prepared_sha256"]:
                raise ValueError("Prepared qgif source changed after its compile receipt")
        (work / "reused-qgif-identity.json").write_text(json.dumps({"sha256": sha256(plugin), "source_receipt": receipt}, indent=2) + "\n", encoding="utf-8")
    else:
        source = work / "modified-qgif-source"
        prepare(qtbase_source, source)
        build = work / "qgif-build"
        run(["cmake", "-S", str(ROOT / "build_tools/qgif_rebuild"), "-B", str(build), "-G", "Ninja",
             "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={qt_prefix}", f"-DQGIF_SOURCE_DIR={source}"], log=work / "qgif-configure.txt")
        run(["cmake", "--build", str(build), "--verbose"], log=work / "qgif-compile.txt")
        plugin = build / "plugins/imageformats/qgif.dll"
    run([interpreters["release"], "-m", "build_tools.recombine_probe", "--plugin", str(plugin), "--report", str(work / "compiled-qgif-probe.json")])
    original = subprocess.run([interpreters["release"], "-c", "import PySide6.support; print(PySide6.support.__file__)"],
                              check=True, capture_output=True, text=True).stdout.strip()
    support = work / "modified/PySide6/support/__init__.py"
    support.parent.mkdir(parents=True)
    support.write_bytes(Path(original).read_bytes() + f'\nTAXOPS_RECOMBINE_MARKER = "{SUPPORT_MARKER}"\n'.encode())
    specification = work / "recombine-input.json"
    specification.write_text(json.dumps({"schema": 1,
        "pyside_support": {"path": str(support), "sha256": sha256(support),
                           "origin": "Pinned PySide6_Essentials 6.10.2 PySide6/support/__init__.py",
                           "origin_sha256": sha256(Path(original))},
        "qgif": {"path": str(plugin), "sha256": sha256(plugin)}}, indent=2) + "\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(TAXOPS_RECOMBINE_INPUT=str(specification), TAXOPS_VC_REDIST_VSIX=str(vc_redist.resolve()))
    run([interpreters["release"], "-m", "build_tools.package_windows"], env=env)
    run([interpreters["release"], "-m", "build_tools.verify_onefile", "--recombined", "--output", str(work / "recombined-onefile"), "--source-matrix", str(work / "source-tests/matrix.json")], env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--qtbase-source", type=Path, required=True)
    parser.add_argument("--vc-redist-vsix", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--test-python", type=Path)
    parser.add_argument("--release-python", type=Path)
    parser.add_argument("--compiled-qgif", type=Path)
    parser.add_argument("--compiled-qgif-sha256")
    parser.add_argument("--prepared-qgif-source", type=Path)
    args = parser.parse_args()
    recombine(args.work.resolve(), args.qt_prefix.resolve(), args.qtbase_source.resolve(), args.vc_redist_vsix.resolve(), wheelhouse=args.wheelhouse, test_python=args.test_python, release_python=args.release_python,
              compiled_qgif=args.compiled_qgif, compiled_qgif_sha256=args.compiled_qgif_sha256,
              prepared_qgif_source=args.prepared_qgif_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
