"""Explicit build-time LGPL replacement inputs; never a runtime DLL loader."""
from __future__ import annotations
import json
import os
from pathlib import Path

from build_tools.dependency_licenses import sha256

SUPPORT_MARKER = "taxops-pyside-support-recombine-6.10.2-v1"
QGIF_MARKER = "taxops-qgif-recombine-6.10.2-v1"


def apply_recombination(pure: list[tuple], binaries: list[tuple]) -> tuple[list, list]:
    value = os.environ.get("TAXOPS_RECOMBINE_INPUT")
    if not value:
        return pure, binaries
    specification = Path(value).resolve()
    settings = json.loads(specification.read_text(encoding="utf-8"))
    if settings.get("schema") != 1:
        raise ValueError("Unsupported recombination input schema")
    replacements = {}
    for key in ("pyside_support", "qgif"):
        row = settings[key]
        original = Path(row["path"])
        source = original.resolve()
        if not source.is_file() or original.is_symlink() or sha256(source) != row["sha256"]:
            raise ValueError(f"Missing or changed recombination input: {key}")
        if key == "pyside_support" and source.name != "__init__.py":
            raise ValueError("PySide6.support replacement must retain __init__.py package semantics")
        replacements[key] = str(source)
    rewritten_pure, rewritten_binaries = [], []
    counts = {"pyside_support": 0, "qgif": 0}
    for name, source, kind in pure:
        if name == "PySide6.support":
            source = replacements["pyside_support"]
            counts["pyside_support"] += 1
        rewritten_pure.append((name, source, kind))
    for name, source, kind in binaries:
        if name.replace("\\", "/").casefold() == "pyside6/plugins/imageformats/qgif.dll":
            source = replacements["qgif"]
            counts["qgif"] += 1
        rewritten_binaries.append((name, source, kind))
    if counts != {"pyside_support": 1, "qgif": 1}:
        raise ValueError("Each recombination input must replace exactly one analyzed module")
    # A new pure list deliberately has no PyInstaller modulegraph code cache.
    # PYZ compiles the replaced source rather than reusing the old code object.
    return rewritten_pure, rewritten_binaries
