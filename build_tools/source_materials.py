"""Identify Git trees and exported, hash-manifested Application Code kits."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


def source_identity(root: Path) -> dict:
    exported = root / "SOURCE_IDENTITY.json"
    if not exported.exists():
        result = subprocess.run(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=root,
                                capture_output=True, text=True, check=True)
        commit, tree = result.stdout.split()
        state = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, check=True)
        if state.stdout.strip():
            raise ValueError("Commit tracked source changes before producing release provenance")
        return {"source_commit": commit, "source_tree": tree}
    manifest = json.loads(exported.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not manifest.get("files"):
        raise ValueError("Invalid recombination-kit source manifest")
    actual, expected, changed = {}, {}, []
    for item in manifest["files"]:
        name = item["path"]
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
                or name in expected or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Unsafe or duplicate source manifest path")
        expected[name] = item["sha256"]
        path = root / relative
        if path.is_symlink():
            raise ValueError("Source-kit symlinks are not permitted")
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        if actual[name] != expected[name]:
            changed.append(name)
    for directory in ("src", "build_tools", "assets", "tests"):
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            if name not in expected:
                actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                changed.append(name)
    material_hash = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"source_commit": manifest["source_commit"],
            "source_tree": manifest["source_tree"] if not changed else "recombined-sha256:" + material_hash,
            "base_source_tree": manifest["source_tree"], "source_material_sha256": material_hash,
            "modified_source_paths": sorted(changed)}
