"""Synthetic preparation and real CMake parsing, not Windows compiler evidence."""
import hashlib
import io
import json
import os
from pathlib import PurePosixPath, PureWindowsPath
import shutil
import subprocess
import tarfile

import pytest

from build_tools.qgif_rebuild import prepare_source as qgif
from build_tools import recombine


def archive(tmp_path, monkeypatch, extra=None):
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as target:
        for name in qgif.INPUTS:
            data = b'{"Keys":["gif"],"MimeTypes":["image/gif"]}' if name == "gif.json" else b"synthetic source"
            entry = tarfile.TarInfo(f"{qgif.SOURCE_ROOT}/src/plugins/imageformats/gif/{name}")
            entry.size = len(data)
            target.addfile(entry, io.BytesIO(data))
        entry = tarfile.TarInfo(extra or f"{qgif.SOURCE_ROOT}/LICENSES/LGPL-3.0-only.txt")
        if extra and extra.endswith("link"):
            entry.type = tarfile.SYMTYPE
            entry.linkname = "../../escape"
            target.addfile(entry)
        else:
            entry.size = 7
            target.addfile(entry, io.BytesIO(b"license"))
    monkeypatch.setattr(qgif, "QTBASE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_prepare_retains_sources_licenses_and_changes_real_metadata(tmp_path, monkeypatch):
    path = archive(tmp_path, monkeypatch)
    out = tmp_path / "prepared"
    result = qgif.prepare(path, out)
    assert json.loads((out / "gif.json").read_text())["TaxOpsRecombineMarker"] == qgif.MARKER
    assert len(result["files"]) == 4
    assert (out / "LICENSES/LGPL-3.0-only.txt").read_bytes() == b"license"
    assert result["files"][-1]["upstream_sha256"] != result["files"][-1]["prepared_sha256"]
    with pytest.raises(ValueError, match="new source directory"):
        qgif.prepare(path, out)


def test_hash_failure_does_not_create_output(tmp_path):
    path = tmp_path / "invalid.tar.xz"
    path.write_bytes(b"not the Qt archive")
    with pytest.raises(ValueError, match="SHA-256"):
        qgif.prepare(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("tail", ["../../escape", "link", "C:/absolute", "back\\slash"])
def test_unsafe_license_member_is_rejected_and_partial_output_retained(tmp_path, monkeypatch, tail):
    path = archive(tmp_path, monkeypatch, f"{qgif.SOURCE_ROOT}/LICENSES/{tail}")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="Unsafe"):
        qgif.prepare(path, out)
    assert out.is_dir() and not (out / "source-receipt.json").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("path, expected", [
    (PureWindowsPath(r"D:\a\_temp\空 白's\qgif"), "D:/a/_temp/空 白's/qgif"),
    (PureWindowsPath(r"\\server\share\空 白\qgif"), "//server/share/空 白/qgif"),
    (PurePosixPath("/tmp/空 白's/qgif"), "/tmp/空 白's/qgif"),
])
def test_cmake_paths_preserve_absolute_roots_spaces_and_unicode(path, expected):
    assert recombine.cmake_path(path) == expected
    args = recombine.cmake_path_arguments(path, path, path, path)
    assert args == ["-S", expected, "-B", expected,
                    f"-DCMAKE_PREFIX_PATH:PATH={expected}", f"-DQGIF_SOURCE_DIR:PATH={expected}"]


@pytest.mark.parametrize("suffix", ['semi;colon', 'double"quote', "back\\slash",
                                     "gen$<CONFIG>", *[f"control{chr(i)}" for i in [*range(32), 127]]])
def test_cmake_rejects_unsupported_single_path_syntax(suffix):
    with pytest.raises(ValueError, match="use a build/source/SDK directory"):
        recombine.cmake_path(PurePosixPath("/tmp") / suffix)


@pytest.mark.parametrize("path", [PurePosixPath("relative"), PureWindowsPath("D:relative"),
                                  PureWindowsPath(r"\rooted-without-drive")])
def test_cmake_requires_an_absolute_path(path):
    with pytest.raises(ValueError, match="absolute"):
        recombine.cmake_path(path)


@pytest.mark.parametrize("position", range(4))
def test_every_cmake_path_argument_is_validated(position):
    paths = [PureWindowsPath(r"D:\a\safe")] * 4
    paths[position] = PureWindowsPath(r"D:\a\unsafe;list")
    with pytest.raises(ValueError, match="semicolon"):
        recombine.cmake_path_arguments(*paths)


@pytest.mark.parametrize("invalid", ["work", "sdk", "harness"])
def test_invalid_cmake_path_fails_before_writes_or_source_tests(tmp_path, monkeypatch, invalid):
    before = list(tmp_path.iterdir())
    monkeypatch.setattr(recombine.sys, "platform", "win32")
    monkeypatch.setattr(recombine.platform, "python_version", lambda: "3.11.9")
    monkeypatch.setattr(recombine.shutil, "which", lambda name: name)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid CMake paths reached an input read or external command")
    monkeypatch.setattr(recombine, "sha256", forbidden)
    monkeypatch.setattr(recombine, "run", forbidden)
    root = tmp_path / ("bad;root" if invalid == "harness" else "source")
    monkeypatch.setattr(recombine, "ROOT", root)
    work = tmp_path / ("bad;work" if invalid == "work" else "work")
    sdk = tmp_path / ("bad;sdk" if invalid == "sdk" else "sdk")
    with pytest.raises(ValueError, match="semicolon"):
        recombine.recombine(work, sdk, tmp_path / "qt.tar.xz", tmp_path / "vc.vsix")
    assert list(tmp_path.iterdir()) == before


def configure_fixture(tmp_path, *, generated):
    """No Qt/compiler/network access: exercise the original add_library form."""
    cmake = shutil.which("cmake")
    assert cmake, "CMake >=3.22 is required for source tests; see BUILD_RECOMBINE.txt"
    harness = tmp_path / "harness 空 白's"
    harness.mkdir()
    sources = ["main.cpp", "qgifhandler.cpp", "qgifhandler_p.h", "gif.json"]
    inputs = "\n".join(f'    "${{QGIF_SOURCE_DIR}}/{name}"' for name in sources)
    generated_block = f"set_source_files_properties(\n{inputs}\n    PROPERTIES GENERATED TRUE)\n" if generated else ""
    (harness / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\nproject(PathBoundary LANGUAGES NONE)\n"
        + generated_block + f"add_library(qgif INTERFACE\n{inputs})\n"
        'target_include_directories(qgif INTERFACE "${QGIF_SOURCE_DIR}")\n'
        'get_target_property(inputs qgif SOURCES)\n'
        'file(WRITE "${CMAKE_BINARY_DIR}/inputs.txt" "${inputs}")\n'
        'get_target_property(includes qgif INTERFACE_INCLUDE_DIRECTORIES)\n'
        'file(WRITE "${CMAKE_BINARY_DIR}/includes.txt" "${includes}")\n', encoding="utf-8")
    return cmake, harness, sources


def assert_configure_values(build, prefix, source, sources, *, expected_include=None):
    cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
    assert f"CMAKE_PREFIX_PATH:PATH={prefix}\n" in cache
    assert f"QGIF_SOURCE_DIR:PATH={source}\n" in cache
    assert (build / "inputs.txt").read_text(encoding="utf-8").split(";") == [f"{source}/{n}" for n in sources]
    assert (build / "includes.txt").read_text(encoding="utf-8") == (expected_include or source)


def run_configure(command, request, label):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    # Persist actual commands and red/green output in the existing JUnit artifact.
    request.node.user_properties.append((label, json.dumps({
        "argv": command, "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=True)))
    return result


def test_real_cmake_configures_existing_space_unicode_paths(tmp_path, request):
    cmake, harness, sources = configure_fixture(tmp_path, generated=False)
    source = tmp_path / "source 空 白's"
    source.mkdir()
    for name in sources:
        (source / name).write_text("synthetic", encoding="utf-8")
    prefix = tmp_path / "Qt SDK 空 白's"
    prefix.mkdir()
    build = tmp_path / "build 空 白's"
    command = [cmake, *recombine.cmake_path_arguments(harness, build, prefix, source)]
    result = run_configure(command, request, "existing-path-configure")
    assert result.returncode == 0, result.stdout + result.stderr
    assert_configure_values(build, prefix.as_posix(), source.as_posix(), sources)


@pytest.mark.parametrize("source", [PureWindowsPath(r"D:\a\_temp\空 白's"),
                                    PureWindowsPath(r"\\server\share\空 白's")])
def test_real_cmake_windows_drive_and_unc_values_are_not_escape_sequences(tmp_path, source, request):
    # GENERATED stubs test syntax only, not drive/share existence or Windows compilation.
    cmake, harness, sources = configure_fixture(tmp_path, generated=True)
    build = tmp_path / "new 空 白"
    args = recombine.cmake_path_arguments(harness, build, source, source)
    result = run_configure([cmake, *args], request, "normalized-path-configure")
    assert result.returncode == 0, result.stdout + result.stderr
    # Linux does not interpret a Windows drive as a filesystem root. This is
    # deliberately a syntax/cache fixture, not a cross-platform drive mount.
    expected_include = (harness.as_posix() + "/" + source.as_posix()
                        if os.name != "nt" and source.drive == "D:" else source.as_posix())
    assert_configure_values(build, source.as_posix(), source.as_posix(), sources,
                            expected_include=expected_include)
    if source.drive == "D:":
        # Exact old boundary: untyped str(WindowsPath), identical add_library fixture.
        old = [cmake, "-S", str(harness), "-B", str(tmp_path / "old"),
               f"-DCMAKE_PREFIX_PATH={source}", f"-DQGIF_SOURCE_DIR={source}"]
        failed = run_configure(old, request, "original-path-negative-control")
        assert failed.returncode != 0
        assert "Invalid character escape '\\a'" in failed.stderr
