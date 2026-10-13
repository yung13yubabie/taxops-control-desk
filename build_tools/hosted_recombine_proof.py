"""Bounded hosted proof of the fixed, already-delivered recombination kit.

This orchestration is outside the exported Application Code. It never changes
that code, accepts terms, installs an SDK, publishes a release or weakens a gate.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = "yung13yubabie/taxops-control-desk"
RUN = 38352573945
ARTIFACT = 11792730247
OUTER_BYTES = 371481709
OUTER_FILES = 848
OUTER_EXPANDED = 371278191
KIT_BYTES = 68030291
KIT_EXPANDED = 73346732
EXE_BYTES = 44922684
SOURCE_FILES = 720
HEAD = "667a661dd523bbfdfe0c4511a51b41555313920f"
COMMIT = "4b135c42a25bc64ade191095e7bce722cd2b8a08"
TREE = "e3760516797677dbf5d4a41dcdb24bf6460f11a9"
OUTER_SHA = "ba8be70289408c0d23eb1c5a4e0e650f08ef9b2f45811b760bc4fe0f0449e49b"
KIT_SHA = "7de9f51b8ed182cc65190e6c7b1146d789a0987b2855cde95926ee426a705152"
EXE_SHA = "cd6af50d8acca38e05f7a433062cf9bf000236a92630ed8400d0585032b191e4"
PROVENANCE_SHA = "cab0952b3d9ae851261cc64ec800eb7b394557a9201823a67c13b9d99e97448b"
MATERIAL_SHA = "adce51b5e5708016a1ff3f2f926c82d6be0029ca658f1ab398eca3548f7bb332"
STOCK_QGIF_SHA = "d86d2e5a17c3af5569a930c5ed204860d0f583549e66db60991dce8b07298ac0"
SUPPORT_SHA = "0ec13f5a5f7e381a31c2d1994d5baaea4d88f3a0524ba7ab9416bb1e9b3635ff"
QGIF_MARKER = "taxops-qgif-recombine-6.10.2-v1"
SUPPORT_MARKER = "taxops-pyside-support-recombine-6.10.2-v1"
KIT_NAME = "TaxOpsControlDesk-recombine-kit.zip"
STAGING = ("package-environment.json", "official-vc.json", "windows-system-runtime.json",
           "windows-staging-input.json", "windows-staging-dependencies.json")
INPUTS = {
    "qtbase-sdk.7z": {
        "url": "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6102/qt6_6102/qt.qt6.6102.win64_msvc2022_64/6.10.2-0-202601261212qtbase-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z",
        "bytes": 42287623,
        "sha256": "c4cedcc54d2036ab20b193db113cf324d90f390647f831a522952cc9b158f38b"},
    "qtbase-source.tar.xz": {
        "url": "https://download.qt.io/archive/qt/6.10/6.10.2/submodules/qtbase-everywhere-src-6.10.2.tar.xz",
        "bytes": 50374380,
        "sha256": "aeb78d29291a2b5fd53cb55950f8f5065b4978c25fb1d77f627d695ab9adf21e"},
    "Microsoft.VC.fixed.vsix": {
        "url": "https://download.visualstudio.microsoft.com/download/pr/45d3b8dd-bced-4b37-9974-142f748d710c/4aaf54db0bfc9435f7c3660e1a00237a4b556042bfeea64bde44c2e0194e6ee5/Microsoft.VC.14.44.17.14.CRT.Redist.X64.base.vsix",
        "bytes": 3224191,
        "sha256": "4aaf54db0bfc9435f7c3660e1a00237a4b556042bfeea64bde44c2e0194e6ee5"},
}


class ProofError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_once(url: str, *, token: str | None = None):
    """No redirect ever carries this request's Authorization header elsewhere."""
    headers = {"User-Agent": "TaxOps-fixed-kit-proof"}
    if token is not None:
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == "https" and parsed.netloc == "api.github.com"
                and parsed.path.startswith(f"/repos/{REPO}/actions/"), "Invalid authenticated endpoint")
        headers.update(Authorization=f"Bearer {token}", Accept="application/vnd.github+json",
                       **{"X-GitHub-Api-Version": "2022-11-28"})
    request = urllib.request.Request(url, headers=headers)
    try:
        return urllib.request.build_opener(NoRedirect()).open(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc
        # Never print HTTPError/URLError: they can contain signed URLs or tokens.
        raise ProofError("Download HTTP failure") from None
    except (urllib.error.URLError, OSError):
        raise ProofError("Download transport failure") from None


def secure_url(url: str, *, storage: bool = False) -> str:
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname and parsed.username is None
            and parsed.password is None and parsed.port in (None, 443) and not parsed.fragment,
            "Unexpected download URL")
    if storage:
        require(any(parsed.hostname.endswith(suffix) for suffix in
                    (".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com")),
                "Unexpected artifact storage host")
    return url


def download(url: str, destination: Path, *, expected_size: int, expected_hash: str,
             token: str | None = None) -> None:
    require(not destination.exists(), "Download destination already exists")
    response = request_once(secure_url(url), token=token)
    with response:
        if token is not None:
            require(response.status == 302, "Artifact API did not return its storage redirect")
            # Discard auth permanently before making even the first storage request.
            next_url = secure_url(response.headers.get("Location", ""), storage=True)
        elif response.status in (301, 302, 303, 307, 308):
            next_url = secure_url(urllib.parse.urljoin(url, response.headers.get("Location", "")))
        else:
            require(response.status == 200, "Unexpected download response")
            _save_download(response, destination, expected_size, expected_hash)
            return
    for _ in range(5):
        response = request_once(next_url)  # deliberately no auth, including subsequent redirects
        with response:
            if response.status == 200:
                _save_download(response, destination, expected_size, expected_hash)
                return
            require(response.status in (301, 302, 303, 307, 308), "Unexpected download response")
            next_url = secure_url(urllib.parse.urljoin(next_url, response.headers.get("Location", "")),
                                  storage=token is not None)
    raise ProofError("Too many download redirects")


def _save_download(response, destination: Path, size: int, sha: str) -> None:
    count = 0
    hasher = hashlib.sha256()
    with destination.open("xb") as handle:
        while block := response.read(1024 * 1024):
            count += len(block)
            require(count <= size, "Download exceeds fixed byte count")
            hasher.update(block)
            handle.write(block)
    require(count == size and hasher.hexdigest() == sha, "Downloaded bytes differ from the fixed input")


def artifact_metadata(data: dict) -> None:
    run = data.get("workflow_run", {})
    require(data.get("id") == ARTIFACT and data.get("name") == f"windows-candidate-{COMMIT}"
            and data.get("size_in_bytes") == OUTER_BYTES and data.get("expired") is False
            and data.get("digest") == "sha256:" + OUTER_SHA
            and run.get("id") == RUN and run.get("head_sha") == HEAD
            and run.get("repository_id") == 1241835486 and run.get("head_repository_id") == 1241835486,
            "Artifact metadata differs from the fixed public run")


def safe_name(name: str) -> str:
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            "Unsafe archive path")
    require(not name.startswith("/") and not name.endswith("/"), "Expected a regular archive file")
    parts = name.split("/")
    for part in parts:
        require(part not in ("", ".", "..") and not part.endswith((".", " "))
                and not any(ord(c) < 32 for c in part)
                and not any(c in '<>"|?*' for c in part)
                and not re.fullmatch(r"(?i)(con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", part),
                "Unsafe archive path")
    return PurePosixPath(name).as_posix()


def zip_files(archive: zipfile.ZipFile, *, max_files: int, max_bytes: int) -> dict:
    files, folded, total = {}, set(), 0
    for item in archive.infolist():
        # These particular immutable artifacts contain only regular-file entries.
        name = safe_name(item.filename)
        mode = item.external_attr >> 16
        require(not item.is_dir() and (not stat.S_IFMT(mode) or stat.S_ISREG(mode))
                and not (item.external_attr & 0x400) and not (item.flag_bits & 1),
                "Non-regular, reparse or encrypted ZIP entry")
        require(name.casefold() not in folded, "Duplicate or case-colliding ZIP path")
        folded.add(name.casefold())
        files[name] = item
        total += item.file_size
        require(len(files) <= max_files and total <= max_bytes, "Archive exceeds fixed bounds")
    # A file may not also be the parent of another file on Windows.
    require(all('/'.join(n.split('/')[:i]).casefold() not in folded
                for n in files for i in range(1, len(n.split('/')))), "Archive file-directory collision")
    return files


def materialize(outer: Path, root: Path) -> dict:
    require(outer.stat().st_size == OUTER_BYTES and file_hash(outer) == OUTER_SHA,
            "Outer artifact ZIP identity mismatch")
    destination = root / "kit"
    require(not destination.exists(), "Materialization destination already exists")
    with zipfile.ZipFile(outer) as archive:
        names = zip_files(archive, max_files=OUTER_FILES, max_bytes=OUTER_EXPANDED)
        require(len(names) == OUTER_FILES, "Outer artifact file count mismatch")
        kit = archive.read(KIT_NAME)
        exe = archive.read("windows-onefile/TaxOpsControlDesk.exe")
        provenance_bytes = archive.read("windows-onefile/onefile-provenance.json")
        require(len(kit) == KIT_BYTES and digest(kit) == KIT_SHA, "Fixed kit identity mismatch")
        require(len(exe) == EXE_BYTES and digest(exe) == EXE_SHA, "Fixed normal EXE identity mismatch")
        require(digest(provenance_bytes) == PROVENANCE_SHA, "Fixed normal provenance identity mismatch")
        normal = json.loads(provenance_bytes)
        require(normal.get("status") == "passed" and normal.get("single_file") is True
                and normal.get("recombined") is False and normal.get("source_exe_sha256") == EXE_SHA
                and normal.get("build_source_commit") == COMMIT and normal.get("build_source_tree") == TREE,
                "Normal EXE provenance is not the fixed accepted source")
    with zipfile.ZipFile(io.BytesIO(kit)) as archive:
        files = zip_files(archive, max_files=SOURCE_FILES + 3, max_bytes=KIT_EXPANDED)
        manifest = json.loads(archive.read("source/SOURCE_IDENTITY.json"))
        require(manifest.get("schema") == 1 and manifest.get("source_commit") == COMMIT
                and manifest.get("source_tree") == TREE and manifest.get("accepted_exe_sha256") == EXE_SHA,
                "Source manifest identity mismatch")
        rows = manifest.get("files", [])
        require(len(rows) == SOURCE_FILES, "Source manifest file count mismatch")
        expected, material, folded = {}, {}, set()
        for row in rows:
            name = safe_name(row["path"])
            require(name.casefold() not in folded, "Duplicate source manifest path")
            folded.add(name.casefold())
            expected[name] = row
            content = archive.read("source/" + name)
            require(len(content) == row["bytes"] and digest(content) == row["sha256"],
                    "Source file differs from manifest")
            material[name] = digest(content)
        require(set(files) == {"source/" + name for name in expected} | {
            "source/SOURCE_IDENTITY.json", "BUILD_RECOMBINE.txt", "RECOMBINE_PERMISSION.txt"},
                "Unexpected or missing kit member")
        require(digest(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()) == MATERIAL_SHA,
                "Source material does not match independently fixed file hashes")
        require(archive.read("BUILD_RECOMBINE.txt") == archive.read("source/BUILD_RECOMBINE.txt")
                and archive.read("RECOMBINE_PERMISSION.txt") == archive.read(
                    "source/assets/third_party_licenses/RECOMBINE_PERMISSION.txt"), "Top-level kit instructions differ")
        # No imported kit code has run, and every archive entry has been checked.
        destination.mkdir()
        for name in files:
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
    original = root / "original"
    original.mkdir()
    (original / "TaxOpsControlDesk.exe").write_bytes(exe)
    (original / "onefile-provenance.json").write_bytes(provenance_bytes)
    receipt = {"status": "passed", "repository": REPO, "input_run_id": RUN,
               "input_artifact_id": ARTIFACT, "artifact_sha256": OUTER_SHA,
               "kit_sha256": KIT_SHA, "accepted_normal_exe_sha256": EXE_SHA,
               "normal_provenance_sha256": PROVENANCE_SHA, "source_commit": COMMIT,
               "source_tree": TREE, "source_material_sha256": MATERIAL_SHA, "source_file_count": SOURCE_FILES}
    write_json(root / "evidence/materialization.json", receipt)
    return receipt


def acquire(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    require(shutil.disk_usage(root).free >= 6 * 1024**3, "Need at least 6 GiB free for this bounded proof")
    token = os.environ.get("GITHUB_TOKEN")
    require(bool(token), "Ephemeral job token is required for the fixed artifact")
    with request_once(f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}", token=token) as response:
        require(response.status == 200, "Artifact metadata request failed")
        data = json.loads(response.read(1024 * 1024))
    artifact_metadata(data)
    write_json(root / "evidence/artifact-identity.json", {k: data[k] for k in (
        "id", "name", "size_in_bytes", "expired", "digest", "workflow_run")})
    archive = root / "original-artifact.zip"
    download(f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}/zip", archive,
             expected_size=OUTER_BYTES, expected_hash=OUTER_SHA, token=token)
    materialize(archive, root)
    inputs = root / "downloads"
    inputs.mkdir()
    for name, row in INPUTS.items():
        download(row["url"], inputs / name, expected_size=row["bytes"], expected_hash=row["sha256"])
    write_json(root / "evidence/official-inputs.json", INPUTS)


def reject_reparse(path: Path, boundary: Path) -> None:
    require(path.is_relative_to(boundary), "Evidence path escapes its owned root")
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            require(not stat.S_ISLNK(info.st_mode)
                    and not (getattr(info, "st_file_attributes", 0) & 0x400), "Refusing a symlink or reparse path")
        if candidate == boundary:
            return
    raise ProofError("Evidence root is not an ancestor")


def verify_materialized_source(source: Path, *, allow_build_outputs: bool = False) -> dict:
    """Independent check before importing any potentially changed exported code."""
    reject_reparse(source, source)
    manifest_path = source / "SOURCE_IDENTITY.json"
    reject_reparse(manifest_path, source)
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == 1 and manifest.get("source_commit") == COMMIT
            and manifest.get("source_tree") == TREE and manifest.get("accepted_exe_sha256") == EXE_SHA
            and len(manifest.get("files", [])) == SOURCE_FILES, "Materialized source manifest identity mismatch")
    actual, folded = {}, set()
    for row in manifest["files"]:
        name = safe_name(row["path"])
        require(name.casefold() not in folded, "Duplicate materialized source path")
        folded.add(name.casefold())
        path = source / name
        reject_reparse(path, source)
        require(path.is_file() and path.stat().st_size == row["bytes"] and file_hash(path) == row["sha256"],
                "Materialized source bytes changed")
        actual[name] = row["sha256"]
    require(digest(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()) == MATERIAL_SHA,
            "Materialized source independent hash mismatch")
    for path in source.rglob("*"):
        reject_reparse(path, source)
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        generated = (relative.parts[0] in {"artifacts", "build", "dist", ".pytest_cache", ".ruff_cache"}
                     or "__pycache__" in relative.parts)
        require(relative.as_posix() in actual or relative.as_posix() == "SOURCE_IDENTITY.json"
                or (allow_build_outputs and generated), "Unexpected file in materialized source")
    return {"source_commit": COMMIT, "source_tree": TREE, "source_material_sha256": MATERIAL_SHA,
            "source_file_count": SOURCE_FILES}


def clean_environment() -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "QT", "QML", "TAXOPS_", "CMAKE_", "PYINSTALLER_", "VCPKG_", "PIP_"))
           and key.upper() not in {"GITHUB_TOKEN", "GH_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                                   "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "CC", "CXX", "CFLAGS", "CXXFLAGS",
                                   "LDFLAGS", "CL", "_CL_", "LINK", "_LINK_"}}
    env.update(PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def execute(command: list[str], cwd: Path, env: dict, log: Path, *, expected: int = 0) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, check=False)
    require(result.returncode == expected, f"Proof subprocess failed; see {log.name}")


def run(root: Path) -> None:
    require(sys.platform == "win32" and sys.version_info[:3] == (3, 11, 9), "Windows CPython 3.11.9 required")
    require(sys.maxsize > 2**32, "x64 Python required")
    source = root / "kit/source"
    env = clean_environment()
    for name, row in INPUTS.items():
        path = root / "downloads" / name
        require(path.stat().st_size == row["bytes"] and file_hash(path) == row["sha256"], "Official input changed")
    # Recheck outside the exported code immediately before its first import.
    write_json(root / "evidence/independent-source-before.json", verify_materialized_source(source))
    execute([sys.executable, "-c", "import json; from build_tools.source_materials import source_identity; "
             "print(json.dumps(source_identity(__import__('pathlib').Path.cwd()), sort_keys=True))"],
            source, env, root / "evidence/source-identity-before.json")
    identity = read_json(root / "evidence/source-identity-before.json")
    require(identity == {"source_commit": COMMIT, "source_tree": TREE, "base_source_tree": TREE,
                        "source_material_sha256": MATERIAL_SHA, "modified_source_paths": []}, "Exported source identity changed")
    tools = {name: shutil.which(name) for name in ("cl", "cmake", "ninja", "7z", "git", "python")}
    require(all(tools.values()), "Runner is missing an existing required tool")
    write_json(root / "evidence/tool-paths.json", {"tools": tools,
        "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
        "windows_sdk": os.environ.get("WindowsSDKVersion"), "vc_tools": os.environ.get("VCToolsVersion"),
        "python": sys.version, "orchestrator_sha256": file_hash(Path(__file__))})
    for name in ("cmake", "ninja", "git"):
        execute([tools[name], "--version"], source, env, root / f"evidence/{name}-version.txt")
    # cl /Bv without a source returns a diagnostic nonzero; retain, do not call it a compile.
    with (root / "evidence/cl-version.txt").open("w", encoding="utf-8") as handle:
        subprocess.run([tools["cl"], "/Bv"], cwd=source, env=env, stdout=handle, stderr=subprocess.STDOUT, check=False)
    sdk = root / "qt-sdk"
    require(not sdk.exists(), "SDK extraction directory already exists")
    execute([tools["7z"], "x", str(root / "downloads/qtbase-sdk.7z"), "-o" + str(sdk), "-y"],
            source, env, root / "evidence/sdk-extraction.txt")
    require(all((sdk / name).is_file() for name in (
        "bin/moc.exe", "bin/Qt6Core.dll", "lib/Qt6Gui.lib", "include/QtGui/6.10.2/QtGui/private/qimage_p.h")),
        "Exact Qt SDK layout missing")
    command = [sys.executable, "-m", "build_tools.recombine", "--work", str(root / "work"),
               "--qt-prefix", str(sdk), "--qtbase-source", str(root / "downloads/qtbase-source.tar.xz"),
               "--vc-redist-vsix", str(root / "downloads/Microsoft.VC.fixed.vsix")]
    execute(command, source, env, root / "evidence/recombine-process.log")
    for kind in ("test", "release"):
        interpreter = str(root / f"work/venv-{kind}/Scripts/python.exe")
        execute([interpreter, "-m", "pip", "freeze", "--all"], source, env, root / f"evidence/{kind}-environment.txt")
        execute([interpreter, "-m", "pip", "check"], source, env, root / f"evidence/{kind}-pip-check.txt")
    # Verification needs PyInstaller from the new isolated release venv.
    execute([str(root / "work/venv-release/Scripts/python.exe"), str(Path(__file__).resolve()),
             "verify", "--root", str(root)], source, env, root / "evidence/linkage-process.log")


def code_fingerprint(code: types.CodeType) -> dict:
    """Compare executable code, ignoring build-machine filenames/debug positions."""
    def constant(value):
        if isinstance(value, types.CodeType):
            return {"code": code_fingerprint(value)}
        if isinstance(value, tuple):
            return {"tuple": [constant(item) for item in value]}
        if isinstance(value, frozenset):
            return {"frozenset": sorted((constant(item) for item in value), key=repr)}
        return {"type": type(value).__name__, "repr": repr(value)}
    return {**{name: getattr(code, name) for name in (
        "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
        "co_names", "co_varnames", "co_freevars", "co_cellvars", "co_name", "co_qualname")},
        "co_code": code.co_code.hex(), "co_exceptiontable": code.co_exceptiontable.hex(),
        "co_consts": [constant(value) for value in code.co_consts]}


def negative_report(report: dict, exit_code: int) -> None:
    require(exit_code == 1 and report == {"status": "failed", "error": {
        "type": "ValueError", "message": "Actual qgif plugin metadata lacks the compiled modification"}},
        "Normal EXE negative control did not fail for the expected missing compiled marker")


def verify_receipt_contracts(records: dict) -> None:
    # These are separate existing contracts, not one shared schema version.
    expected = {"package-environment.json": (1, "passed"), "official-vc.json": (1, "passed"),
                "windows-system-runtime.json": (2, "passed"), "windows-staging-input.json": (1, None),
                "windows-staging-dependencies.json": (1, "passed")}
    require(set(records) == set(expected), "All five fresh build receipts are required")
    for name, (schema, status) in expected.items():
        row = records[name]
        require(type(row.get("schema")) is int and row["schema"] == schema
                and (status is None or row.get("status") == status), "Fresh build receipt contract mismatch: " + name)


def verify(root: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader
    import PySide6.support

    source, work = root / "kit/source", root / "work"
    verify_materialized_source(source, allow_build_outputs=True)
    sys.path.insert(0, str(source))
    from build_tools.source_materials import source_identity
    from build_tools.verify_windows_bundle import isolated_environment, validate_report
    require(source_identity(source) == read_json(root / "evidence/source-identity-before.json"), "Source changed during build")
    result_dir = work / "recombined-onefile"
    provenance = read_json(result_dir / "onefile-provenance.json")
    matrix = read_json(work / "source-tests/matrix.json")
    require(provenance.get("status") == "passed" and provenance.get("recombined") is True
            and provenance.get("single_file") is True and provenance.get("build_source_commit") == COMMIT
            and provenance.get("build_source_tree") == TREE, "Recombined gate did not pass the fixed source")
    require(matrix.get("status") == "passed" and matrix.get("full_suite") is True
            and len(matrix.get("files", [])) == 164 and matrix.get("totals") == {
                "tests": 4474, "failures": 0, "errors": 0, "skipped": 0}
            and matrix.get("raw_percent_covered", 0) >= 90, "Fresh complete source matrix missing")
    validate_report(read_json(result_dir / "frozen-self-test.json"))
    for name in STAGING:
        require((source / "artifacts/build-staging" / name).is_file(), "Fresh build receipt missing")
    verify_receipt_contracts({name: read_json(source / "artifacts/build-staging" / name) for name in STAGING})
    original = root / "original/TaxOpsControlDesk.exe"
    require(file_hash(original) == EXE_SHA, "Normal EXE changed")
    negative = root / "evidence/normal-exe-negative.json"
    env = isolated_environment(root / "negative-profile")
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        env.pop(name, None)
    with (root / "evidence/normal-exe-negative.log").open("w", encoding="utf-8") as handle:
        process = subprocess.run([str(original), "--recombine-probe", "--require-frozen", "--require-support",
                                  "--report", str(negative)], cwd=original.parent, env=env,
                                 stdout=handle, stderr=subprocess.STDOUT, timeout=180, check=False)
    negative_report(read_json(negative), process.returncode)
    require(not list((root / "negative-profile/temp").glob("_MEI*")), "Negative control extraction survived normal exit")
    exe = result_dir / "TaxOpsControlDesk.exe"
    exe_sha = file_hash(exe)
    require(exe_sha != EXE_SHA and exe_sha == provenance["source_exe_sha256"]
            and exe_sha == file_hash(source / "dist/TaxOpsControlDesk.exe"), "New EXE identity is not closed")
    inputs = read_json(work / "recombine-input.json")
    plugin = work / "qgif-build/plugins/imageformats/qgif.dll"
    plugin_sha = file_hash(plugin)
    require(plugin_sha != STOCK_QGIF_SHA and inputs["qgif"]["sha256"] == plugin_sha, "Compiled plugin identity missing")
    prepared = read_json(work / "modified-qgif-source/source-receipt.json")
    require(prepared.get("source_archive_sha256") == INPUTS["qtbase-source.tar.xz"]["sha256"]
            and prepared.get("marker") == QGIF_MARKER and len(prepared.get("files", [])) == 4,
            "Modified qgif source receipt missing")
    changed = []
    for row in prepared["files"]:
        require(row["file"] in {"main.cpp", "qgifhandler.cpp", "qgifhandler_p.h", "gif.json"}
                and file_hash(work / "modified-qgif-source" / row["file"]) == row["prepared_sha256"], "Prepared source changed")
        if row["prepared_sha256"] != row["upstream_sha256"]:
            changed.append(row["file"])
    require(changed == ["gif.json"], "Unexpected qgif modification")
    for path in (work / "compiled-qgif-probe.json", result_dir / "frozen-recombine.json"):
        report = read_json(path)
        require(report.get("status") == "passed" and report.get("plugin_sha256") == plugin_sha
                and report.get("pyside_runtime_version") == "6.10.2" and report.get("qt_runtime_version") == "6.10.2"
                and report.get("gif_pixel_rgba") == [255, 0, 0, 255]
                and report.get("plugin_metadata", {}).get("MetaData", {}).get("TaxOpsRecombineMarker") == QGIF_MARKER,
                "Real modified-plugin execution is not linked to the compiled bytes")
    frozen = read_json(result_dir / "frozen-recombine.json")
    require(frozen.get("frozen") is True and frozen.get("support_marker") == SUPPORT_MARKER
            and frozen.get("support_package_and_submodule_verified") is True, "Modified PySide source did not execute")
    frozen_plugin = Path(frozen["plugin"])
    require(frozen_plugin.is_relative_to(result_dir / "selftest-profile/temp")
            and frozen_plugin.parent.parent.parent.parent.name.startswith("_MEI")
            and frozen.get("qt_library_paths") == [str(frozen_plugin.parent.parent)], "Frozen plugin came from outside its extraction")
    support = work / "modified/PySide6/support/__init__.py"
    original_support = Path(PySide6.support.__file__)
    require(file_hash(original_support) == SUPPORT_SHA and inputs["pyside_support"]["origin_sha256"] == SUPPORT_SHA
            and file_hash(support) == inputs["pyside_support"]["sha256"]
            and support.read_bytes() == original_support.read_bytes() + f'\nTAXOPS_RECOMBINE_MARKER = "{SUPPORT_MARKER}"\n'.encode(),
            "Modified support source is not the exact isolated pinned source change")
    archive = CArchiveReader(str(exe))
    embedded_plugins = [name for name in archive.toc
                        if name.replace("\\", "/").casefold() == "pyside6/plugins/imageformats/qgif.dll"]
    require(len(embedded_plugins) == 1 and digest(archive.extract(embedded_plugins[0])) == plugin_sha,
            "Embedded qgif differs from the actual compiled DLL")
    pyz_names = [name for name, row in archive.toc.items() if row[-1] == "z"]
    require(len(pyz_names) == 1, "Expected exactly one Python module archive")
    pyz = archive.open_embedded_archive(pyz_names[0])
    require(pyz.toc.get("PySide6.support", (None,))[0] == 1
            and "PySide6.support.deprecated" in pyz.toc, "Support package/submodule semantics lost")
    observed_code = code_fingerprint(pyz.extract("PySide6.support"))
    expected_code = code_fingerprint(compile(support.read_bytes(), "<support>", "exec", dont_inherit=True, optimize=0))
    require(observed_code == expected_code, "Embedded support code differs from modified source")
    require((work / "qgif-build/CMakeCache.txt").is_file()
            and (work / "qgif-compile.txt").stat().st_size > 0, "Fresh compiler evidence missing")
    write_json(root / "evidence/proof-result.json", {"status": "passed", "input_run_id": RUN,
        "input_artifact_id": ARTIFACT, "kit_sha256": KIT_SHA, "normal_exe_sha256": EXE_SHA,
        "source_commit": COMMIT, "source_tree": TREE, "source_material_sha256": MATERIAL_SHA,
        "recombined_exe_sha256": exe_sha, "compiled_and_embedded_qgif_sha256": plugin_sha,
        "modified_support_sha256": file_hash(support), "embedded_support_code_verified": True,
        "normal_exe_negative_control": "expected missing compiled marker", "fresh_source_tests": matrix["totals"],
        "raw_branch_coverage": matrix["raw_percent_covered"], "clean_os_verified": False,
        "manual_gui_verified": False, "release_published": False})


def collect(root: Path, output: Path) -> None:
    """Explicit evidence allowlist; never copy downloads, SDK, venvs or profiles."""
    output.mkdir(parents=True, exist_ok=False)
    def copy_tree(src: Path, dst: Path, *, suffixes: set[str] | None = None, recursive: bool = True):
        reject_reparse(src, root)
        if not src.is_dir():
            return
        for path in (src.rglob("*") if recursive else src.iterdir()):
            reject_reparse(path, root)
            if path.is_file() and (suffixes is None or path.suffix.lower() in suffixes):
                target = dst / path.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    textual = {".json", ".txt", ".log", ".xml"}
    copy_tree(root / "evidence", output / "evidence", suffixes=textual)
    copy_tree(root / "work/source-tests", output / "source-tests", suffixes=textual)
    # Keep root reports and the two explicit proof directories, never any profile,
    # TEMP/_MEI tree, logical payload extraction, or relocated EXE directory.
    onefile = root / "work/recombined-onefile"
    copy_tree(onefile, output / "recombined-onefile", suffixes=textual, recursive=False)
    for name in ("current-host-native-proof", "shell-baseline"):
        copy_tree(onefile / name, output / "recombined-onefile" / name,
                  suffixes=textual | {".bin"}, recursive=False)
    copy_tree(root / "work/modified-qgif-source", output / "modified-qgif-source")
    copy_tree(root / "work/modified", output / "modified")
    selected = {
        "work/recombined-onefile/TaxOpsControlDesk.exe": "TaxOpsControlDesk-recombined.exe",
        "work/qgif-build/plugins/imageformats/qgif.dll": "modified-qgif/qgif.dll",
        "work/qgif-build/CMakeCache.txt": "qgif-build/CMakeCache.txt",
        "work/qgif-configure.txt": "qgif-configure.txt", "work/qgif-compile.txt": "qgif-compile.txt",
        "work/recombine-input.json": "recombine-input.json", "work/input-source-identity.json": "input-source-identity.json",
        "work/compiled-qgif-probe.json": "compiled-qgif-probe.json",
        "kit/source/SOURCE_IDENTITY.json": "SOURCE_IDENTITY.json",
        "original/onefile-provenance.json": "normal-onefile-provenance.json",
    }
    selected.update({"kit/source/artifacts/build-staging/" + name: "build-staging/" + name for name in STAGING})
    for name, target_name in selected.items():
        path = root / name
        reject_reparse(path, root)
        if path.is_file():
            target = output / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    status = read_json(root / "evidence/proof-result.json").get("status") if (root / "evidence/proof-result.json").is_file() else "incomplete"
    write_json(output / "EVIDENCE-INVENTORY.json", {"status": status, "files": [
        {"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size, "sha256": file_hash(p)}
        for p in sorted(output.rglob("*")) if p.is_file()]})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("acquire", "run", "verify", "collect"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.phase == "collect":
            require(args.output is not None, "Output directory required")
            collect(root, args.output.resolve())
        else:
            globals()[args.phase](root)
        print(f"Hosted proof {args.phase}: passed")
        return 0
    except Exception as exc:
        # Only our fixed, non-sensitive error messages are safe to show.
        message = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
        print(f"Hosted proof {args.phase}: failed ({message})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
