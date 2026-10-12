"""Export exact public Application Code matched to an accepted single EXE."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

from build_tools.dependency_licenses import ROOT, sha256
from build_tools.source_materials import source_identity


def build_kit(exe: Path, provenance: Path, destination: Path) -> dict:
    evidence = json.loads(provenance.read_text(encoding="utf-8"))
    identity = source_identity(ROOT)
    if (evidence.get("status") != "passed" or evidence.get("single_file") is not True
            or evidence.get("source_exe_sha256") != sha256(exe)
            or evidence.get("build_source_commit") != identity["source_commit"]
            or evidence.get("build_source_tree") != identity["source_tree"]):
        raise ValueError("EXE acceptance/source identity does not match this source tree")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT, check=True, capture_output=True)
    archive = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=ROOT,
                             check=True, capture_output=True).stdout
    files = []
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        names = [i.filename for i in source.infolist() if not i.is_dir()]
        required = {"TaxOpsControlDesk.spec", "BUILD_RECOMBINE.txt", "requirements-release.txt", "requirements-ci.txt",
                    "requirements-release-hashed.txt", "build_tools/pyinstaller_hooks/hook-PySide6.QtGui.py",
                    "build_tools/qgif_rebuild/CMakeLists.txt", "assets/app_icon.ico", "assets/third_party_licenses/manifest.json",
                    "assets/third_party_licenses/RECOMBINE_PERMISSION.txt", "build_tools/recombine.py"}
        if not required.issubset(names) or len([n for n in names if re.fullmatch(r"src/taxops/db/migrations/_m[0-9]{4}_[^/]+\.py", n)]) != 28:
            raise ValueError("Incomplete Application Code/spec/permission/migration kit")
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as target:
            for name in names:
                data = source.read(name)
                files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
                target.writestr("source/" + name, data)
            manifest = {"schema": 1, **identity, "files": files, "accepted_exe_sha256": sha256(exe)}
            target.writestr("source/SOURCE_IDENTITY.json", json.dumps(manifest, indent=2) + "\n")
            target.writestr("BUILD_RECOMBINE.txt", source.read("BUILD_RECOMBINE.txt"))
            target.writestr("RECOMBINE_PERMISSION.txt", source.read("assets/third_party_licenses/RECOMBINE_PERMISSION.txt"))
    with zipfile.ZipFile(destination) as verify:
        if verify.testzip() is not None:
            raise ValueError("Recombination kit ZIP readback failed")
        for row in files:
            if hashlib.sha256(verify.read("source/" + row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Recombination kit source readback mismatch")
    return {"kit_sha256": sha256(destination), "source_file_count": len(files), **identity,
            "accepted_exe_sha256": sha256(exe)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_kit(args.exe, args.provenance, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
