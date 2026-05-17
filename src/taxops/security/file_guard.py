"""File security guards: extension allowlist, size limits, and path traversal protection."""

from __future__ import annotations

import hashlib
from pathlib import Path

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png",
    ".xlsx", ".xls", ".docx", ".doc",
    ".txt", ".csv",
})

BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs",
    ".js", ".html", ".htm", ".scr", ".dll",
    ".msi", ".jar", ".lnk",
})


class FileGuardError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_extension(filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext in BLOCKED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
        raise FileGuardError("attachment.extension_not_allowed")


def check_file_size(size_bytes: int) -> None:
    if size_bytes > MAX_FILE_SIZE:
        raise FileGuardError("attachment.file_too_large")


def resolve_safe_path(base_dir: Path, relative: str) -> Path:
    resolved = (base_dir / relative).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise FileGuardError("attachment.path_traversal")
    return resolved


def sha256_file(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()
