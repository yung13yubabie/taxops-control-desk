"""Exercise a recompiled plugin and modified Python module in a fresh process."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

SUPPORT_MARKER = "taxops-pyside-support-recombine-6.10.2-v1"
QGIF_MARKER = "taxops-qgif-recombine-6.10.2-v1"
# One red pixel, palette index zero. No network or user image is involved.
GIF = bytes.fromhex("47494638396101000100800000ff00000000002c00000000010001000002024401003b")


def probe(plugin: Path, *, require_support: bool) -> dict:
    from PySide6.QtCore import QCoreApplication, QPluginLoader, QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader
    app = QCoreApplication.instance() or QCoreApplication([])
    if plugin.parent.name != "imageformats":
        raise ValueError("Use an imageformats/qgif.dll plugin path")
    # Exclude wheel/default plugins from the factory lookup; only this plugin
    # directory may provide GIF support in this fresh diagnostic process.
    QCoreApplication.setLibraryPaths([str(plugin.parent.parent.resolve())])
    loader = QPluginLoader(str(plugin.resolve()))
    metadata = loader.metaData()
    if metadata.get("MetaData", {}).get("TaxOpsRecombineMarker") != QGIF_MARKER:
        raise ValueError("Actual qgif plugin metadata lacks the compiled modification")
    if loader.instance() is None:
        raise ValueError("Recompiled qgif could not load: " + loader.errorString())
    buffer = QBuffer()
    buffer.setData(QByteArray(GIF))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError("Synthetic GIF buffer could not open")
    reader = QImageReader(buffer, QByteArray(b"gif"))
    image = reader.read()
    if image.isNull() or image.width() != 1 or image.height() != 1 or image.pixelColor(0, 0).getRgb() != (255, 0, 0, 255):
        raise ValueError("Recompiled qgif failed real synthetic GIF decoding")
    support_marker = None
    if require_support:
        import PySide6.support
        import PySide6.support.deprecated
        if not hasattr(PySide6.support, "__path__") or PySide6.support.deprecated.__package__ != "PySide6.support":
            raise ValueError("Modified PySide6.support lost its package/submodule semantics")
        support_marker = getattr(PySide6.support, "TAXOPS_RECOMBINE_MARKER", None)
        if support_marker != SUPPORT_MARKER:
            raise ValueError("Executed PySide6.support lacks its source modification")
    return {"status": "passed", "frozen": bool(getattr(sys, "frozen", False)),
            "plugin": str(plugin.resolve()), "plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
            "plugin_metadata": metadata, "gif_pixel_rgba": [255, 0, 0, 255],
            "support_marker": support_marker, "support_package_and_submodule_verified": require_support,
            "qt_library_paths": app.libraryPaths()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--require-frozen", action="store_true")
    parser.add_argument("--require-support", action="store_true")
    args = parser.parse_args(argv)
    report = {"status": "failed"}
    try:
        frozen = bool(getattr(sys, "frozen", False))
        if args.require_frozen and not frozen:
            raise ValueError("This gate requires the recombined frozen EXE")
        if frozen:
            if args.plugin is not None:
                raise ValueError("Frozen proof must use its embedded plugin, not an external path")
            plugin = Path(sys._MEIPASS) / "PySide6/plugins/imageformats/qgif.dll"
        elif args.plugin is not None:
            plugin = args.plugin
        else:
            raise ValueError("Source probe requires --plugin")
        report = probe(plugin, require_support=args.require_support)
        return 0
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return 1
    finally:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
