"""Synthetic notice/inventory contracts; these never qualify a Windows artifact."""
from __future__ import annotations

import ast
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from build_tools import dependency_licenses as licenses
from build_tools import verify_windows_bundle as gate

ROOT = Path(__file__).resolve().parents[1]


def _notice_copy(tmp_path):
    target = tmp_path / "notices"
    shutil.copytree(licenses.NOTICE_SOURCE, target)
    return target


def test_notice_corpus_has_original_complete_texts_and_exact_sources():
    manifest = licenses.validate_notice_tree(licenses.NOTICE_SOURCE)
    assert manifest["python_version"] == "3.11.9"
    assert manifest["qt_version"] == "6.10.2"
    assert manifest["qt_pdf_source_revision"] == "c971c6841dd6beab9f54aeaf9a53be413273039e"
    paths = {item["path"] for item in manifest["files"]}
    for needed in (
        "CPython-3.11.9/LICENSE.txt", "native/OpenSSL-3.0.13-LICENSE.txt",
        "native/OpenSSL-3.5.5-LICENSE.txt", "native/LLVM-3.6.2-LICENSE.txt",
        "qt-pdf-chromium/chromium/third_party/pdfium/LICENSE",
        "qt-pdf-chromium/chromium/third_party/freetype/src/docs/FTL.TXT",
        "qt-pdf-chromium/chromium/third_party/libjpeg_turbo/README.ijg",
        "qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt",
        "qt-6.10.2/qtbase/LICENSES/GPL-3.0-only.txt",
        "python-packages/openpyxl/openpyxl-3.1.5.dist-info/LICENCE.rst",
        "python-packages/et_xmlfile/et_xmlfile-2.0.0.dist-info/LICENCE.python",
        "python-packages/PyInstaller/pyinstaller-6.11.1.dist-info/COPYING.txt",
    ):
        assert needed in paths
    assert "This software is based in part on the work of the Independent JPEG Group." in (
        licenses.NOTICE_SOURCE / "README.txt").read_text(encoding="utf-8")
    assert all(item.get("source_url", "").startswith("https://") or item.get("origin")
               for item in manifest["files"])
    assert not any("LicenseRef-Qt-Commercial" in name for name in paths)
    assert manifest["unresolved_release_review"]


@pytest.mark.parametrize("mutation", ["missing", "changed", "extra", "manifest"])
def test_notice_gate_rejects_incomplete_or_changed_assets(tmp_path, mutation):
    target = _notice_copy(tmp_path)
    path = target / "native/OpenSSL-3.0.13-LICENSE.txt"
    if mutation == "missing":
        path.unlink()
    elif mutation == "changed":
        path.write_text("a placeholder is not a license", encoding="utf-8")
    elif mutation == "extra":
        (target / "unreviewed.txt").write_text("extra", encoding="utf-8")
    else:
        (target / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(licenses.LicenseAssetError):
        licenses.validate_notice_tree(target)


@pytest.mark.parametrize("name", ["../outside.txt", "/absolute.txt", "a\\b.txt", "manifest.json"])
def test_notice_manifest_rejects_unsafe_and_duplicate_paths(tmp_path, name):
    expected = tmp_path / "expected"
    expected.mkdir()
    payload = {"schema": 1, "files": [{"path": name, "sha256": "0" * 64}]}
    (expected / "manifest.json").write_text(json.dumps(payload))
    with pytest.raises(licenses.LicenseAssetError, match="Unsafe or duplicate"):
        licenses.validate_notice_tree(expected, expected=expected)


def test_version_gate_accepts_only_the_reviewed_release_environment(monkeypatch):
    manifest = json.loads((licenses.NOTICE_SOURCE / "manifest.json").read_text())
    monkeypatch.setattr(licenses.platform, "python_version", lambda: "3.11.9")
    monkeypatch.setattr(licenses.importlib.metadata, "version", manifest["release_packages"].__getitem__)
    licenses.validate_build_environment()
    monkeypatch.setattr(licenses.platform, "python_version", lambda: "3.11.10")
    with pytest.raises(licenses.LicenseAssetError, match="Python version"):
        licenses.validate_build_environment()


def test_version_gate_rejects_changed_installed_package(monkeypatch):
    manifest = json.loads((licenses.NOTICE_SOURCE / "manifest.json").read_text())
    monkeypatch.setattr(licenses.platform, "python_version", lambda: "3.11.9")
    monkeypatch.setattr(licenses.importlib.metadata, "version", lambda name:
                        "6.10.3" if name == "PySide6" else manifest["release_packages"][name])
    with pytest.raises(licenses.LicenseAssetError, match="Installed PySide6"):
        licenses.validate_build_environment()


def test_version_gate_rejects_changed_requirements(tmp_path, monkeypatch):
    monkeypatch.setattr(licenses, "ROOT", tmp_path)
    (tmp_path / "requirements-release.txt").write_text("PySide6==6.10.3\n")
    with pytest.raises(licenses.LicenseAssetError, match="Release pins changed"):
        licenses.validate_build_environment()


@pytest.mark.parametrize("relative", [
    "_internal/PySide6/Qt6VirtualKeyboard.dll",
    "_internal/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "_internal/PySide6/Qt6Charts.dll", "_internal/PySide6/QtDataVisualization.pyd",
    "_internal/PySide6/Qt6Quick.dll", "_internal/PySide6/Qt6Qml.dll",
    "_internal/PySide6/plugins/imageformats/unreviewed.dll",
    "_internal/PySide6/unreviewed.dll", "Elsewhere/QT6VIRTUALKEYBOARD.DLL",
])
def test_actual_bundle_inventory_rejects_unreviewed_qt_native_files(tmp_path, relative):
    file = tmp_path / relative
    with pytest.raises(licenses.LicenseAssetError, match="Unapproved"):
        licenses.validate_qt_inventory([file], tmp_path)


def test_inventory_preserves_pdf_print_images_and_native_windows_input(tmp_path):
    relatives = [
        "_internal/PySide6/Qt6Core.dll", "_internal/PySide6/Qt6Gui.dll",
        "_internal/PySide6/Qt6Pdf.dll", "_internal/PySide6/Qt6PdfWidgets.dll",
        "_internal/PySide6/Qt6PrintSupport.dll", "_internal/PySide6/QtPdf.pyd",
        "_internal/PySide6/QtPrintSupport.pyd", "_internal/PySide6/opengl32sw.dll",
        "_internal/PySide6/VCRUNTIME140.dll", "_internal/PySide6/VCRUNTIME140_1.dll",
        "_internal/PySide6/plugins/platforms/qwindows.dll",
        "_internal/PySide6/plugins/imageformats/qpdf.dll",
        "_internal/PySide6/plugins/imageformats/qjpeg.dll",
    ]
    licenses.validate_qt_inventory([tmp_path / p for p in relatives], tmp_path)


def test_qtgui_hook_only_filters_virtual_keyboard_plugin(monkeypatch):
    qt = ModuleType("PyInstaller.utils.hooks.qt")
    collected = [
        (str(Path("wheel/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll")), "input"),
        (str(Path("wheel/plugins/platforms/qwindows.dll")), "platforms"),
        (str(Path("wheel/plugins/platforminputcontexts/nativeime.dll")), "input"),
        (str(Path("wheel/plugins/imageformats/qpdf.dll")), "images"),
    ]
    qt.add_qt6_dependencies = lambda _: (["PySide6.QtCore"], collected, [("source", "target")])
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks.qt", qt)
    result = runpy.run_path(str(ROOT / "build_tools/pyinstaller_hooks/hook-PySide6.QtGui.py"))
    assert result["hiddenimports"] == ["PySide6.QtCore"]
    assert result["datas"] == [("source", "target")]
    assert result["binaries"] == collected[1:]


def test_spec_and_package_entrypoint_require_notices():
    spec = (ROOT / "TaxOpsControlDesk.spec").read_text()
    package = (ROOT / "build_tools/package_windows.py").read_text()
    assert "validate_build_environment()" in spec and "validate_build_environment()" in package
    assert '(str(NOTICE_SOURCE), "third_party_licenses")' in spec
    assert 'hookspath=["build_tools/pyinstaller_hooks"]' in spec
    assert '"THIRD_PARTY_NOTICES.txt"' in spec
    assert "assets/third_party_licenses/** -text" in (ROOT / ".gitattributes").read_text()


def _fake_bundle(root):
    root.mkdir()
    for name in gate._REQUIRED_FILES:
        (root / ("TaxOpsControlDesk.exe" if name == "taxopscontroldesk.exe" else name)).write_bytes(b"synthetic")
    shutil.copytree(licenses.NOTICE_SOURCE, root / licenses.NOTICE_DESTINATION)
    shutil.copyfile(licenses.NOTICE_SOURCE / "README.txt", root / "THIRD_PARTY_NOTICES.txt")
    return root


def test_zip_gate_records_notice_hash_without_legal_clearance(tmp_path):
    bundle = _fake_bundle(tmp_path / "bundle")
    result = gate.archive_bundle(bundle, tmp_path / "candidate.zip")
    assert result["notice_manifest_sha256"] == hashlib.sha256(
        (licenses.NOTICE_SOURCE / "manifest.json").read_bytes()).hexdigest()
    assert result["license_review_complete"] is False
    assert result["unresolved_license_items"]


@pytest.mark.parametrize("missing", ["THIRD_PARTY_NOTICES.txt", "_internal/third_party_licenses/manifest.json"])
def test_zip_gate_refuses_missing_notices_before_archive_creation(tmp_path, missing):
    bundle = _fake_bundle(tmp_path / "bundle")
    (bundle / missing).unlink()
    archive = tmp_path / "candidate.zip"
    with pytest.raises(gate.BundleVerificationError, match="Third-party license gate"):
        gate.archive_bundle(bundle, archive)
    assert not archive.exists()


def test_zip_gate_refuses_virtual_keyboard_before_archive_creation(tmp_path):
    bundle = _fake_bundle(tmp_path / "bundle")
    (bundle / "Qt6VirtualKeyboard.dll").write_bytes(b"synthetic")
    archive = tmp_path / "candidate.zip"
    with pytest.raises(gate.BundleVerificationError, match="Unapproved Qt module"):
        gate.archive_bundle(bundle, archive)
    assert not archive.exists()


def test_direct_spec_gate_imports_from_spec_directory_outside_repo(tmp_path):
    spec = ast.parse((ROOT / "TaxOpsControlDesk.spec").read_text())
    prefix = []
    for node in spec.body:
        prefix.append(node)
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "validate_build_environment"):
            break
    prefix_source = ast.unparse(ast.Module(body=prefix, type_ignores=[]))
    package = tmp_path / "build_tools"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "dependency_licenses.py").write_text(
        "NOTICE_SOURCE = None\ndef validate_build_environment():\n    print('spec-gate-ran')\n")
    harness = """
import sys, types
sys.path = [p for p in sys.path if p and 'taxops' not in p.lower()]
for name in ['PyInstaller', 'PyInstaller.utils', 'PyInstaller.utils.hooks', 'PySide6', 'PySide6.QtCore']:
    sys.modules[name] = types.ModuleType(name)
sys.modules['PyInstaller.utils.hooks'].collect_submodules = lambda _: []
sys.modules['PySide6.QtCore'].QLibraryInfo = object
"""
    harness += f"exec({prefix_source!r}, {{'SPECPATH': {str(tmp_path)!r}}})\n"
    process = subprocess.run([sys.executable, "-c", harness], cwd=tmp_path,
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert "spec-gate-ran" in process.stdout


@pytest.mark.parametrize("change", ["none", "bytes", "path"])
def test_microsoft_runtime_provenance_is_bound_to_reviewed_bytes(tmp_path, change):
    file = tmp_path / "_internal/VCRUNTIME140.dll"
    file.parent.mkdir()
    file.write_bytes(b"reviewed synthetic runtime")
    manifest = {"reviewed_microsoft_binaries": [{
        "bundle_path": "_internal/vcruntime140.dll",
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
    }]}
    if change == "bytes":
        file.write_bytes(b"different synthetic runtime")
    elif change == "path":
        manifest["reviewed_microsoft_binaries"][0]["bundle_path"] = "other.dll"
    if change == "none":
        licenses.validate_microsoft_inventory([file], tmp_path, manifest)
    else:
        with pytest.raises(licenses.LicenseAssetError, match="Microsoft runtime"):
            licenses.validate_microsoft_inventory([file], tmp_path, manifest)
