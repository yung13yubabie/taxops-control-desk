"""Prepare exact upstream qgif sources with a visible, reproducible modification."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath

QTBASE_SHA256 = "aeb78d29291a2b5fd53cb55950f8f5065b4978c25fb1d77f627d695ab9adf21e"
SOURCE_ROOT = "qtbase-everywhere-src-6.10.2"
MARKER = "taxops-qgif-recombine-6.10.2-v1"
INPUTS = ("main.cpp", "qgifhandler.cpp", "qgifhandler_p.h", "gif.json")


def prepare(archive: Path, destination: Path) -> dict:
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != QTBASE_SHA256:
        raise ValueError("Qt source archive SHA-256 mismatch")
    if destination.exists():
        raise ValueError("Choose a new source directory; existing paths are not overwritten")
    destination.mkdir(parents=True)
    records = []
    try:
        with tarfile.open(archive, "r:xz") as source:
            for name in INPUTS:
                member = source.getmember(f"{SOURCE_ROOT}/src/plugins/imageformats/gif/{name}")
                if not member.isfile():
                    raise ValueError("qgif input is not a regular file")
                content = source.extractfile(member).read()
                original = hashlib.sha256(content).hexdigest()
                if name == "gif.json":
                    metadata = json.loads(content)
                    metadata["TaxOpsRecombineMarker"] = MARKER
                    content = (json.dumps(metadata, indent=4) + "\n").encode()
                (destination / name).write_bytes(content)
                records.append({"file": name, "upstream_sha256": original,
                                "prepared_sha256": hashlib.sha256(content).hexdigest()})
            for member in source.getmembers():
                if member.name.startswith(f"{SOURCE_ROOT}/LICENSES/"):
                    relative = PurePosixPath(member.name).relative_to(SOURCE_ROOT)
                    if (".." in relative.parts or "\\" in member.name or ":" in member.name
                            or relative.is_absolute() or not (member.isfile() or member.isdir())):
                        raise ValueError("Unsafe Qt license archive member")
                    if member.isfile():
                        target = destination / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(source.extractfile(member).read())
        receipt = {"schema": 1, "qt_version": "6.10.2", "source_archive_sha256": digest,
                   "marker": MARKER, "modification": "Added TaxOpsRecombineMarker to gif.json",
                   "files": records}
        (destination / "source-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt
    except BaseException:
        # Keep the dedicated output for diagnosis/recoverable user cleanup.
        # No receipt is emitted on failure, so incomplete inputs cannot pass.
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.output), indent=2))
