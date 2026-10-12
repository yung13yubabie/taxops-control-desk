"""Check staged Git blobs without printing content or contacting external services.

This deterministic safety net is not a complete secret/PII/history scanner.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import subprocess
from pathlib import Path, PurePosixPath

# Reviewed existing official fixture: see docs/fixture_provenance.md.
PUBLIC_FIXTURES = {
    "tmp/BGMOPEN1.zip": "eea1c8be633f9ce13bb38096b96f547e02333da980f97fde9eac97012004cfa1",
}
PRIVATE_DIRS = {
    ".ai", ".agent", ".codex", ".claude", "private", "private-notes",
    "local-notes", "notes-private", "backups", "taxopsbackups", "exports",
    "logs", "screenshots", "screen-recordings", "runtime", "local-data",
    "attachments", "artifacts", "dist", "build", ".venv", ".venv-test",
    ".venv-release", ".pytest_cache", ".ruff_cache", "__pycache__",
}
PRIVATE_NAMES = {"handoff.md", "current_state.md", "tasks.md", ".env", ".npmrc",
                 ".pypirc", ".netrc", "credentials", "secrets"}
PRIVATE_GLOBS = (
    ".env.*", "*.env", "credentials*.json", "secrets*.json", "*.key", "*.pem",
    "*.p12", "*.pfx", "*.jks", "id_rsa*", "id_ed25519*", "*.db", "*.db-*",
    "*.sqlite", "*.sqlite-*", "*.sqlite3", "*.sqlite3-*", "*.sql", "*.taxops.zip",
    "*.bak", "*.backup", "*.dump", "*.log", "*.pid",
)
CONTENT_RULES = {
    "private-key-marker": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token-marker": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})\b"),
    "aws-access-key-marker": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "slack-token-marker": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b"),
}


def inspect_blob(path: str, data: bytes) -> list[str]:
    """Return rule identifiers, never matching content."""
    normalized = PurePosixPath(path)
    parts = tuple(part.lower() for part in normalized.parts)
    name = parts[-1] if parts else ""
    issues: list[str] = []
    fixture_hash = PUBLIC_FIXTURES.get(path)
    if fixture_hash is not None:
        if hashlib.sha256(data).hexdigest() != fixture_hash:
            issues.append("public-fixture-hash-changed")
        return issues
    if any(part in PRIVATE_DIRS for part in parts[:-1]):
        issues.append("private-or-generated-directory")
    if parts and parts[0] == "tmp":
        issues.append("unreviewed-temporary-file")
    if name == ".env.example":
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            issues.append("invalid-environment-template")
        else:
            if any(line.strip() and not line.lstrip().startswith("#")
                   and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=", line.strip())
                   for line in lines):
                issues.append("nonempty-environment-template")
    elif name in PRIVATE_NAMES or any(fnmatch.fnmatchcase(name, pattern) for pattern in PRIVATE_GLOBS):
        issues.append("private-or-runtime-filename")
    issues.extend(rule for rule, pattern in CONTENT_RULES.items() if pattern.search(data))
    return issues


def check_index(root: Path) -> list[tuple[str, str]]:
    """Inspect exact index content, not ignored/untracked/worktree replacements."""
    listing = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root,
                             check=True, capture_output=True).stdout
    failures = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if stage != b"0" or mode not in {b"100644", b"100755"}:
            failures.append((path, "unsupported-index-entry"))
            continue
        blob = subprocess.run(["git", "cat-file", "blob", oid.decode("ascii")],
                              cwd=root, check=True, capture_output=True).stdout
        failures.extend((path, rule) for rule in inspect_blob(path, blob))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        failures = check_index(args.root)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Repository hygiene could not inspect the Git index; refusing to pass.")
        return 2
    for path, rule in failures:
        # repr escapes control characters to prevent forged diagnostic lines.
        print(f"{path!r}: {rule}")
    print(f"Repository hygiene: {len(failures)} violation(s); staged content only.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
