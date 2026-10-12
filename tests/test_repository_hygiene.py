"""Synthetic positive/negative cases; never use real credentials or records."""
from __future__ import annotations

import hashlib
import subprocess

import pytest

from build_tools import check_repository_hygiene as hygiene


@pytest.mark.parametrize("path", [
    ".ai/HANDOFF.md", "docs/private-notes/session.md", ".env", ".env.production",
    "config/credentials-prod.json", "keys/server.key", "keys/server.pem",
    "keys/id_ed25519", "profile/customer.sqlite", "customer.sqlite3-wal",
    "private/export.csv", "exports/customers.csv", "backups/copy.zip",
    "snapshots/db.backup", "runtime/state.json", "screenshots/customer.png",
    "diagnostics/run.log", "tmp/unknown.zip", "HANDOFF.md", "CURRENT_STATE.md",
    "TASKS.md", "data/customer.db-shm", "data/tax.sql", ".netrc",
])
def test_private_paths_are_rejected(path):
    assert hygiene.inspect_blob(path, b"synthetic")


@pytest.mark.parametrize("path", [
    "assets/app.ico", "docs/architecture.md", "tests/fixtures/synthetic.json",
    "tests/fixtures/synthetic.png", "src/taxops/diagnostics.py", "SECURITY.md",
    "CONTRIBUTING.md", "docs/screenshot-guide.md",
])
def test_public_assets_and_source_are_allowed(path):
    assert hygiene.inspect_blob(path, b"synthetic") == []


@pytest.mark.parametrize("data,allowed", [
    (b"# Empty template\nAPI_TOKEN=\n", True), (b"\n", True),
    (b"API_TOKEN=synthetic\n", False), (b"API_TOKEN=''\n", False),
    (b"not an assignment", False), (b"\xff", False),
])
def test_environment_template_must_be_empty(data, allowed):
    assert bool(hygiene.inspect_blob(".env.example", data)) is not allowed


@pytest.mark.parametrize("synthetic", [
    b"gh" + b"p_" + b"A" * 36,
    b"github_" + b"pat_" + b"A" * 50,
    b"AK" + b"IA" + b"A" * 16,
    b"xox" + b"b-" + b"1" * 24,
    b"-----BEGIN " + b"PRIVATE KEY-----",
])
def test_content_markers_in_public_paths_are_rejected(synthetic):
    assert hygiene.inspect_blob("docs/example.md", synthetic)


def test_fixture_exception_is_exact_path_and_hash(monkeypatch):
    data = b"synthetic public fixture"
    monkeypatch.setattr(hygiene, "PUBLIC_FIXTURES", {"tmp/reviewed.zip": hashlib.sha256(data).hexdigest()})
    assert hygiene.inspect_blob("tmp/reviewed.zip", data) == []
    assert hygiene.inspect_blob("tmp/reviewed.zip", data + b"changed") == ["public-fixture-hash-changed"]
    assert hygiene.inspect_blob("tmp/other.zip", data)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_index_scan_reads_staged_blob_even_when_worktree_is_clean(tmp_path, capsys):
    git(tmp_path, "init")
    path = tmp_path / "public.md"
    marker = b"gh" + b"p_" + b"A" * 36
    path.write_bytes(marker)
    git(tmp_path, "add", "public.md")
    path.write_text("safe unstaged replacement")
    assert hygiene.check_index(tmp_path) == [("public.md", "github-token-marker")]
    assert hygiene.main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert marker.decode() not in output
    assert "github-token-marker" in output


def test_force_added_ignored_files_are_still_rejected(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text("SYNTHETIC=\n")
    git(tmp_path, "add", "-f", ".env")
    assert hygiene.check_index(tmp_path) == [(".env", "private-or-runtime-filename")]


def test_untracked_private_files_are_not_read(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".env").write_text("SYNTHETIC=value")
    assert hygiene.check_index(tmp_path) == []


def test_not_a_repository_fails_closed(tmp_path, capsys):
    assert hygiene.main(["--root", str(tmp_path)]) == 2
    assert "refusing to pass" in capsys.readouterr().out
