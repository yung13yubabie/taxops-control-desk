"""Portable backup files and additive asset restore support.

The SQLite snapshot is the authoritative reference set. Restored assets are
published into a new namespace before committing that database, so an interrupted
restore never overwrites files referenced by the previous live database.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import zipfile
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from ..core.paths import AppPaths

FULL_BACKUP_SUFFIX = ".taxops.zip"
ASSET_NAMES = ("attachments", "workflow_assets", "note_assets")
DATABASE_NAME = "database.sqlite"
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_FILES = 200_000
MAX_BUNDLE_BYTES = 20 * 1024 * 1024 * 1024
_CHUNK = 1024 * 1024


class BackupBundleError(Exception):
    pass


def asset_roots(paths: AppPaths) -> dict[str, Path]:
    return {
        "attachments": paths.attachments_dir,
        "workflow_assets": paths.data_root / "workflow_assets",
        "note_assets": paths.data_root / "note_assets",
    }


def relative_name(raw: str) -> str:
    """Accept portable relative paths, including legacy Windows separators."""
    normalized = raw.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or PureWindowsPath(normalized).drive
        or any(part in ("", ".", "..") for part in normalized.split("/"))
        or any(":" in part or part.endswith((" ", ".")) for part in path.parts)
        or "\x00" in normalized
    ):
        raise BackupBundleError("backup.invalid_file")
    return path.as_posix()


def _transform_json(
    raw: str | None, key: str, visit: Callable[[str], str]
) -> str | None:
    if raw is None:
        return None
    changed = False

    def transform(value):
        nonlocal changed
        if isinstance(value, dict):
            for name, child in value.items():
                if name == key and isinstance(child, str) and child:
                    replacement = visit(child)
                    changed = changed or replacement != child
                    value[name] = replacement
                else:
                    transform(child)
        elif isinstance(value, list):
            for child in value:
                transform(child)

    try:
        value = json.loads(raw)
        transform(value)
        return json.dumps(value, ensure_ascii=False) if changed else raw
    except (ValueError, TypeError, RecursionError) as exc:
        raise BackupBundleError("backup.assets.incomplete") from exc


_JSON_FIELDS = (
    ("workflow_templates_v2", "context_snapshot", "workflow_assets", "image_path"),
    ("workflow_templates_v2", "stages_json", "workflow_assets", "image_path"),
    ("workflow_runs", "context_snapshot", "workflow_assets", "image_path"),
    ("workflow_runs", "stages_json", "workflow_assets", "image_path"),
    ("canvas_notes", "scene_json", "note_assets", "asset_path"),
)


def references(conn: sqlite3.Connection) -> list[tuple[str, str, bool]]:
    found: list[tuple[str, str, bool]] = []
    for raw, status in conn.execute("SELECT stored_filename, status FROM attachments"):
        found.append(("attachments", relative_name(raw), status != "archived"))
    for table, field, root, key in _JSON_FIELDS:
        for raw, deleted_at in conn.execute(f"SELECT {field}, deleted_at FROM {table}"):

            def collect(value: str) -> str:
                found.append((root, relative_name(value), deleted_at is None))
                return value

            _transform_json(raw, key, collect)
    return found


def validate_references(conn: sqlite3.Connection, files: dict[str, dict]) -> None:
    for root, relative, required in references(conn):
        if required and f"{root}/{relative}" not in files:
            raise BackupBundleError("backup.assets.incomplete")
    # A full backup must not silently certify altered attachment bytes.
    for relative, expected_hash, status in conn.execute(
        "SELECT stored_filename, file_hash_sha256, status FROM attachments"
    ):
        entry = files.get(f"attachments/{relative_name(relative)}")
        if status != "archived" and (entry is None or entry["sha256"] != expected_hash):
            raise BackupBundleError("backup.assets.incomplete")


def write_bundle(database: Path, paths: AppPaths, destination: Path) -> dict:
    sources = [(DATABASE_NAME, database)]
    for name, root in asset_roots(paths).items():
        if root.is_symlink():
            raise BackupBundleError("backup.assets.incomplete")
        if not root.exists():
            continue
        for source in sorted(root.rglob("*")):
            if source.is_symlink():
                raise BackupBundleError("backup.assets.incomplete")
            if source.is_file():
                if not source.resolve().is_relative_to(root.resolve()):
                    raise BackupBundleError("backup.assets.incomplete")
                relative = relative_name(source.relative_to(root).as_posix())
                sources.append((f"{name}/{relative}", source))
    if len(sources) > MAX_BUNDLE_FILES:
        raise BackupBundleError("backup.too_large")
    if len({name.casefold() for name, _ in sources}) != len(sources):
        raise BackupBundleError("backup.assets.incomplete")
    entries: list[dict] = []
    total = 0
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, source in sources:
            digest = hashlib.sha256()
            size = 0
            with (
                source.open("rb") as stream,
                archive.open(name, "w", force_zip64=True) as out,
            ):
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    total += len(chunk)
                    if total > MAX_BUNDLE_BYTES:
                        raise BackupBundleError("backup.too_large")
                    digest.update(chunk)
                    out.write(chunk)
            entries.append({"path": name, "size": size, "sha256": digest.hexdigest()})
        with closing(sqlite3.connect(database)) as connection:
            validate_references(connection, {entry["path"]: entry for entry in entries})
        manifest = {
            "format": "taxops.full-backup",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": entries,
        }
        payload = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_MANIFEST_BYTES:
            raise BackupBundleError("backup.too_large")
        archive.writestr(MANIFEST_NAME, payload)
    return manifest


def read_bundle(source: Path, destination: Path) -> dict:
    """Validate every manifest entry and byte before exposing staged assets."""
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BUNDLE_FILES + 1:
                raise BackupBundleError("backup.too_large")
            names = [info.filename for info in infos]
            if len({name.casefold() for name in names}) != len(names):
                raise BackupBundleError("backup.invalid_file")
            info = archive.getinfo(MANIFEST_NAME)
            if info.file_size > MAX_MANIFEST_BYTES:
                raise BackupBundleError("backup.too_large")
            payload = archive.read(info)
            manifest = json.loads(payload)
            if not isinstance(manifest, dict) or (
                manifest.get("format") != "taxops.full-backup"
                or manifest.get("version") != 1
            ):
                raise BackupBundleError("backup.invalid_file")
            entries = manifest.get("files")
            if not isinstance(entries, list) or len(entries) > MAX_BUNDLE_FILES:
                raise BackupBundleError("backup.invalid_file")
            files: dict[str, dict] = {}
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("path"), str
                ):
                    raise BackupBundleError("backup.invalid_file")
                name = relative_name(entry["path"])
                parts = PurePosixPath(name).parts
                if (
                    name != entry["path"]
                    or name in files
                    or not (
                        name == DATABASE_NAME
                        or len(parts) > 1
                        and parts[0] in ASSET_NAMES
                    )
                ):
                    raise BackupBundleError("backup.invalid_file")
                size, digest = entry.get("size"), entry.get("sha256")
                if (
                    type(size) is not int
                    or size < 0
                    or not isinstance(digest, str)
                    or (
                        len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)
                    )
                ):
                    raise BackupBundleError("backup.invalid_file")
                files[name] = entry
            if DATABASE_NAME not in files or set(names) != set(files) | {MANIFEST_NAME}:
                raise BackupBundleError("backup.assets.incomplete")
            if sum(entry["size"] for entry in entries) > MAX_BUNDLE_BYTES:
                raise BackupBundleError("backup.too_large")
            for name, entry in files.items():
                info = archive.getinfo(name)
                if (
                    info.is_dir()
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.file_size != entry["size"]
                ):
                    raise BackupBundleError("backup.invalid_file")
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as stream, target.open("xb") as out:
                    while chunk := stream.read(_CHUNK):
                        size += len(chunk)
                        if size > entry["size"]:
                            raise BackupBundleError("backup.invalid_file")
                        digest.update(chunk)
                        out.write(chunk)
                if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupBundleError("backup.invalid_file")
            manifest["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
            return manifest
    except BackupBundleError:
        raise
    except (KeyError, ValueError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise BackupBundleError("backup.invalid_file") from exc


def install_assets(
    staged_root: Path,
    manifest: dict,
    paths: AppPaths,
    restore_id: str,
) -> dict[tuple[str, str], str]:
    """Only add files in owned fresh directories; retain partials for recovery."""
    mapping: dict[tuple[str, str], str] = {}
    roots = asset_roots(paths)
    prepared: set[str] = set()
    for index, entry in enumerate(manifest["files"]):
        name = entry["path"]
        if name == DATABASE_NAME:
            continue
        root_name, relative = name.split("/", 1)
        root = roots[root_name]
        if root.is_symlink():
            raise BackupBundleError("backup.assets.incomplete")
        namespace = root / f"restored_{restore_id}"
        if root_name not in prepared:
            namespace.mkdir(parents=True, exist_ok=False)
            prepared.add(root_name)
        # Flatten restores so repeated round-trips do not grow Windows paths.
        new_relative = f"restored_{restore_id}/{index}{PurePosixPath(relative).suffix}"
        destination = root / new_relative
        shutil.copyfile(staged_root / name, destination)
        with destination.open("rb+") as stream:
            copied_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
        if (
            destination.stat().st_size != entry["size"]
            or copied_hash != entry["sha256"]
        ):
            raise BackupBundleError("backup.assets.incomplete")
        mapping[(root_name, relative)] = new_relative
    return mapping


def rewrite_references(
    conn: sqlite3.Connection,
    mapping: dict[tuple[str, str], str],
    restore_id: str,
) -> None:
    def mapped(root: str, raw: str, required: bool) -> str:
        relative = relative_name(raw)
        result = mapping.get((root, relative))
        if result is None:
            if required:
                raise BackupBundleError("backup.assets.incomplete")
            # Preserve a missing historical reference without accidentally
            # attaching it to a different file in the target data directory.
            digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
            return f"restored_{restore_id}/missing_{digest}"
        return result

    with conn:
        for row_id, raw, status in conn.execute(
            "SELECT id, stored_filename, status FROM attachments"
        ).fetchall():
            conn.execute(
                "UPDATE attachments SET stored_filename = ? WHERE id = ?",
                (mapped("attachments", raw, status != "archived"), row_id),
            )
        for table, field, root, key in _JSON_FIELDS:
            rows = conn.execute(
                f"SELECT id, {field}, deleted_at FROM {table}"
            ).fetchall()
            for row_id, raw, deleted_at in rows:
                rewritten = _transform_json(
                    raw, key, lambda value: mapped(root, value, deleted_at is None)
                )
                if rewritten != raw:
                    conn.execute(
                        f"UPDATE {table} SET {field} = ? WHERE id = ?",
                        (rewritten, row_id),
                    )


def write_restore_history(paths: AppPaths, restore_id: str, record: dict) -> None:
    directory = paths.data_root / "restore_history"
    if directory.is_symlink():
        raise BackupBundleError("backup.assets.incomplete")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{restore_id}.json"
    temporary = destination.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
