"""Security tests for file_guard: extension allowlist, size limits, path traversal."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from taxops.security.file_guard import (
    ALLOWED_EXTENSIONS,
    BLOCKED_EXTENSIONS,
    MAX_FILE_SIZE,
    FileGuardError,
    check_extension,
    check_file_size,
    resolve_safe_path,
    sha256_file,
)


# ── check_extension ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename", [
    "document.pdf", "photo.jpg", "photo.jpeg", "image.png",
    "sheet.xlsx", "sheet.xls", "word.docx", "word.doc",
    "notes.txt", "data.csv",
])
def test_allowed_extension_passes(filename):
    check_extension(filename)  # must not raise


@pytest.mark.parametrize("filename", [
    "malware.exe", "script.bat", "script.cmd", "script.ps1",
    "vbs.vbs", "code.js", "page.html", "page.htm",
    "screen.scr", "lib.dll", "installer.msi",
])
def test_blocked_extension_raises(filename):
    with pytest.raises(FileGuardError) as exc_info:
        check_extension(filename)
    assert exc_info.value.code == "attachment.extension_not_allowed"


def test_path_traversal_extension_still_checked():
    # ../evil.pdf passes extension check (pdf is allowed) -- path safety handled separately
    check_extension("../evil.pdf")


def test_no_extension_is_rejected():
    with pytest.raises(FileGuardError) as exc_info:
        check_extension("README")
    assert exc_info.value.code == "attachment.extension_not_allowed"


def test_extension_case_insensitive():
    check_extension("FILE.PDF")
    check_extension("IMAGE.JPG")


# ── check_file_size ────────────────────────────────────────────────────────────

def test_file_size_within_limit_passes():
    check_file_size(MAX_FILE_SIZE)  # exactly at limit -- must not raise


def test_file_size_one_byte_over_limit_raises():
    with pytest.raises(FileGuardError) as exc_info:
        check_file_size(MAX_FILE_SIZE + 1)
    assert exc_info.value.code == "attachment.file_too_large"


def test_file_size_zero_passes():
    check_file_size(0)


def test_file_size_100mb_raises():
    with pytest.raises(FileGuardError) as exc_info:
        check_file_size(100 * 1024 * 1024)
    assert exc_info.value.code == "attachment.file_too_large"


# ── resolve_safe_path ──────────────────────────────────────────────────────────

def test_resolve_safe_path_returns_inside_base(tmp_path):
    result = resolve_safe_path(tmp_path, "2026/05/abc.pdf")
    assert str(result).startswith(str(tmp_path.resolve()))


def test_resolve_safe_path_single_dotdot_rejected(tmp_path):
    with pytest.raises(FileGuardError) as exc_info:
        resolve_safe_path(tmp_path, "../evil.pdf")
    assert exc_info.value.code == "attachment.path_traversal"


def test_resolve_safe_path_nested_traversal_rejected(tmp_path):
    with pytest.raises(FileGuardError) as exc_info:
        resolve_safe_path(tmp_path, "2026/../../windows/system32/cmd.exe")
    assert exc_info.value.code == "attachment.path_traversal"


def test_resolve_safe_path_absolute_rejected(tmp_path):
    with pytest.raises(FileGuardError) as exc_info:
        resolve_safe_path(tmp_path, "/etc/passwd")
    assert exc_info.value.code == "attachment.path_traversal"


def test_resolve_safe_path_nested_subdir_ok(tmp_path):
    result = resolve_safe_path(tmp_path, "2026/05/abc123.pdf")
    assert result == (tmp_path / "2026" / "05" / "abc123.pdf").resolve()


# ── sha256_file ────────────────────────────────────────────────────────────────

def test_sha256_matches_hashlib(tmp_path):
    content = b"hello taxops"
    f = tmp_path / "test.txt"
    f.write_bytes(content)
    assert sha256_file(f) == hashlib.sha256(content).hexdigest()


def test_sha256_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    assert sha256_file(f) == hashlib.sha256(b"").hexdigest()


def test_sha256_different_content_differs(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_bytes(b"abc")
    f2.write_bytes(b"xyz")
    assert sha256_file(f1) != sha256_file(f2)
