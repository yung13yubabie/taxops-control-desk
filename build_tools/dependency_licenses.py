"""Offline, fail-closed checks for the reviewed Windows notice assets.

This is a packaging integrity check, not a legal compliance determination.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
NOTICE_SOURCE = ROOT / "assets" / "third_party_licenses"
NOTICE_DESTINATION = Path("_internal/third_party_licenses")
# Only modules used by the Widgets application or its PDF/image paths are approved.
# An added module requires review of its exact license and transitive dependencies.
QT_MODULES = frozenset({"Core", "Gui", "Widgets", "Network", "OpenGL", "Pdf",
                        "PdfWidgets", "PrintSupport", "Svg", "Xml"})
QT_PLUGINS = frozenset({
    "generic/qtuiotouchplugin.dll", "iconengines/qsvgicon.dll",
    "imageformats/qgif.dll", "imageformats/qicns.dll", "imageformats/qico.dll",
    "imageformats/qjpeg.dll", "imageformats/qpdf.dll", "imageformats/qsvg.dll",
    "imageformats/qtga.dll", "imageformats/qtiff.dll", "imageformats/qwbmp.dll",
    "imageformats/qwebp.dll", "networkinformation/qnetworklistmanager.dll",
    "platforms/qdirect2d.dll", "platforms/qminimal.dll", "platforms/qoffscreen.dll",
    "platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll",
    "tls/qcertonlybackend.dll", "tls/qopensslbackend.dll", "tls/qschannelbackend.dll",
})
QT_SUPPORT = frozenset({"pyside6.abi3.dll", "opengl32sw.dll", "msvcp140.dll",
                         "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll",
                         "vcruntime140_1.dll"})


class LicenseAssetError(RuntimeError):
    """The bundle differs from the reviewed notice/version/module boundary."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_notice_tree(directory: Path, *, expected: Path = NOTICE_SOURCE) -> dict:
    """Check every notice byte against the source manifest, never a bundled claim."""
    manifest_path = expected / "manifest.json"
    payload = manifest_path.read_bytes()
    manifest = json.loads(payload)
    if manifest.get("schema") != 1 or not manifest.get("files"):
        raise LicenseAssetError("Invalid or empty third-party notice manifest")
    if (directory / "manifest.json").is_symlink() or (directory / "manifest.json").read_bytes() != payload:
        raise LicenseAssetError("Bundled third-party notice manifest differs from reviewed source")
    wanted = {"manifest.json"}
    for item in manifest["files"]:
        relative = PurePosixPath(item["path"])
        if (relative.is_absolute() or ".." in relative.parts or "\\" in item["path"]
                or item["path"] in wanted):
            raise LicenseAssetError("Unsafe or duplicate notice path")
        wanted.add(item["path"])
        path = directory / relative
        if not path.is_file() or path.is_symlink() or sha256(path) != item["sha256"]:
            raise LicenseAssetError(f"Missing or changed third-party notice: {relative}")
    entries = list(directory.rglob("*"))
    if any(p.is_symlink() for p in entries):
        raise LicenseAssetError("Notice symlinks are forbidden")
    actual = {p.relative_to(directory).as_posix() for p in entries if p.is_file()}
    if actual != wanted:
        raise LicenseAssetError("Unexpected third-party notice files")
    return manifest


def validate_build_environment() -> None:
    """Refuse stale notices when release pins or the installed environment change."""
    manifest = validate_notice_tree(NOTICE_SOURCE)
    pins = {}
    for line in (ROOT / "requirements-release.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.strip().split("==")
            pins[name] = version
    if pins != manifest["release_packages"]:
        raise LicenseAssetError("Release pins changed; review and regenerate notice assets")
    if platform.python_version() != manifest["python_version"]:
        raise LicenseAssetError("Python version differs from the reviewed notice baseline")
    for name, version in pins.items():
        if importlib.metadata.version(name) != version:
            raise LicenseAssetError(f"Installed {name} differs from the reviewed notice baseline")


def validate_qt_inventory(files: list[Path], bundle: Path) -> None:
    """Reject unreviewed Qt modules/plugins, including GPL-only accidental imports."""
    libraries = {f"qt6{name}.dll".lower() for name in QT_MODULES}
    bindings = {f"qt{name}.pyd".lower() for name in QT_MODULES}
    for path in files:
        relative = path.relative_to(bundle).as_posix().lower()
        name = path.name.lower()
        if name == "qtvirtualkeyboardplugin.dll":
            raise LicenseAssetError("Unapproved Qt Virtual Keyboard plugin in bundle")
        if name.startswith("qt6") and name.endswith(".dll") and name not in libraries:
            raise LicenseAssetError(f"Unapproved Qt module: {relative}")
        if name.startswith("qt") and name.endswith(".pyd") and name not in bindings:
            raise LicenseAssetError(f"Unapproved Qt binding: {relative}")
        if "/pyside6/" not in "/" + relative or path.suffix.lower() not in {".dll", ".pyd"}:
            continue
        tail = ("/" + relative).split("/pyside6/", 1)[1]
        if tail.startswith("plugins/"):
            approved = tail[len("plugins/"):] in QT_PLUGINS
        else:
            approved = tail in libraries | bindings | QT_SUPPORT
        if not approved:
            raise LicenseAssetError(f"Unapproved Qt native file: {relative}")


def validate_microsoft_inventory(files: list[Path], bundle: Path, manifest: dict) -> None:
    """Keep file-level source/terms questions bound to the actual reviewed bytes."""
    approved = {row["bundle_path"].casefold(): row["sha256"]
                for row in manifest["reviewed_microsoft_binaries"]}
    for path in files:
        if not re.fullmatch(r"(?:api-ms-win-.*|ucrtbase|vcruntime.*|msvcp.*)\.dll",
                            path.name, flags=re.IGNORECASE):
            continue
        relative = path.relative_to(bundle).as_posix().casefold()
        if approved.get(relative) != sha256(path):
            raise LicenseAssetError(f"Unreviewed or changed Microsoft runtime: {relative}")


def validate_bundle_licenses(bundle: Path, files: list[Path]) -> dict:
    manifest = validate_notice_tree(bundle / NOTICE_DESTINATION)
    if (bundle / "THIRD_PARTY_NOTICES.txt").read_bytes() != (NOTICE_SOURCE / "README.txt").read_bytes():
        raise LicenseAssetError("Root third-party notice index missing or changed")
    validate_qt_inventory(files, bundle)
    validate_microsoft_inventory(files, bundle, manifest)
    return {
        "notice_manifest_sha256": sha256(NOTICE_SOURCE / "manifest.json"),
        "notice_file_count": len(manifest["files"]) + 1,
        "license_review_complete": False,
        "unresolved_license_items": manifest["unresolved_release_review"],
    }
