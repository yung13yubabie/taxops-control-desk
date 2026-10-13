"""Read and export the bundled, offline third-party notice snapshot."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .resources import asset_path

_log = logging.getLogger(__name__)
# The original FreeType license uses a Latin-1 copyright sign. Keep its bytes
# unchanged for export instead of replacing that character during display.
_TEXT_ENCODINGS = {
    "qt-pdf-chromium/chromium/third_party/pdfium/third_party/freetype/FTL.TXT": "latin-1",
}


class NoticeError(RuntimeError):
    """The bundled notices are unavailable, or an export did not complete."""


def notice_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "third_party_licenses"
    return asset_path("third_party_licenses")


@dataclass(frozen=True)
class NoticeCatalog:
    """A verified in-memory snapshot: viewing and exporting use identical bytes."""

    files: Mapping[str, bytes]

    def text(self, name: str) -> str:
        try:
            return self.files[name].decode(_TEXT_ENCODINGS.get(name, "utf-8"))
        except (KeyError, UnicodeError) as exc:
            raise NoticeError("notice.read_failed") from exc

    def export(self, destination: Path) -> None:
        """Publish a complete ZIP atomically; preserve an old target on failure."""
        staging: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".taxops-notices-", suffix=".tmp", delete=False,
            ) as temporary:
                staging = Path(temporary.name)
            with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in sorted(self.files.items()):
                    archive.writestr(name, content)
            with zipfile.ZipFile(staging) as archive:
                if archive.testzip() is not None:
                    raise NoticeError("notice.export_failed")
            os.replace(staging, destination)
            staging = None
        except (OSError, zipfile.BadZipFile) as exc:
            raise NoticeError("notice.export_failed") from exc
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    _log.warning("Unable to remove failed notice export staging file", exc_info=True)


def load_notices(directory: Path | None = None) -> NoticeCatalog:
    """Validate the local manifest and all bytes before exposing any export."""
    root = notice_directory() if directory is None else directory
    try:
        if root.is_symlink() or (root / "manifest.json").is_symlink():
            raise ValueError("Notice symlink")
        manifest_bytes = (root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), list):
            raise ValueError("Invalid notice manifest")
        files = {"manifest.json": manifest_bytes}
        for item in manifest["files"]:
            name = item["path"]
            relative = PurePosixPath(name)
            if (not name or relative.is_absolute() or ".." in relative.parts
                    or "\\" in name or ":" in name or relative.as_posix() != name
                    or name in files):
                raise ValueError("Invalid notice path")
            path = root / relative
            if any(root.joinpath(*relative.parts[:index]).is_symlink()
                   for index in range(1, len(relative.parts) + 1)):
                raise ValueError("Notice symlink")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Changed notice")
            content.decode(_TEXT_ENCODINGS.get(name, "utf-8"))
            files[name] = content
        required = {"README.txt", "SOURCE_ACCESS.txt",
                    "qt-6.10.2/qtbase/LICENSES/LGPL-3.0-only.txt",
                    "qt-6.10.2/qtbase/LICENSES/GPL-3.0-only.txt"}
        if not required.issubset(files):
            raise ValueError("Required notice missing")
        return NoticeCatalog(MappingProxyType(files))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise NoticeError("notice.read_failed") from exc
