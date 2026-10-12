"""Synthetic Windows native-font evidence, never an offscreen fallback.

Run ``python -m build_tools.native_font_probe --output-dir artifacts/native-font``.
The supervising process preserves JSON even if Qt aborts loading its plugin.
Exit 0 means this limited native font probe passed, not the release gate.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback

SAMPLES = (
    ("latin", "TaxOps 0123456789", True),
    ("traditional", "所有案件／租約稅額臺灣", True),
    ("mixed", "王小明 A123 臺北市 金額 NT$1,234.50（含稅）", True),
    ("punctuation", "新增附件：搜尋檔名… 2026-10-12，確認／取消", True),
    ("rare_candidates", "𠮷𡃁", False),
)
CANDIDATES = ("Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans TC", "Noto Sans CJK TC", "PingFang TC", "Segoe UI")


def _write(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")



def _glyph_run_record(run, text: str) -> dict:
    """Record a glyph run only after capture's native-platform preflight.

    An explicitly invalid QRawFont has no metadata to query. Validity alone is
    not a safe capability check for offscreen box engines; capture rejects that
    backend before reaching this helper.
    """
    raw = run.rawFont()
    valid = raw.isValid()
    coverage = [
        {"codepoint": f"U+{ord(char):04X}",
         "supported": valid and raw.supportsCharacter(ord(char))}
        for char in sorted(set(text), key=ord)
    ]
    return {"family": raw.familyName() if valid else None,
            "style": raw.styleName() if valid else None,
            "valid": valid, "glyph_indexes": list(run.glyphIndexes()),
            "coverage": coverage}


def _capture_support_error(qt_platform: str, families: list[str]) -> str | None:
    if qt_platform != "windows":
        return "non_native_qt_platform"
    if not families:
        return "empty_font_database"
    return None


def _evaluate_glyph_records(runs: list[dict], text: str) -> tuple[bool, list[str]]:
    """Evaluate recorded evidence without querying Qt or requiring installed fonts."""
    supported = {int(c["codepoint"][2:], 16) for run in runs
                 for c in run["coverage"] if c["supported"]}
    missing = [f"U+{ord(c):04X}" for c in sorted(set(text), key=ord)
               if not c.isspace() and ord(c) not in supported]
    passed = (bool(runs) and all(r["valid"] and r["glyph_indexes"]
              and 0 not in r["glyph_indexes"] for r in runs) and not missing)
    return bool(passed), missing


def capture_probe(output_dir: Path) -> dict:
    """Inspect styled widgets using the already-selected Qt platform."""
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtGui import QFontDatabase, QFontInfo, QTextLayout
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QLabel, QLineEdit, QPushButton, QTableWidget,
        QTableWidgetItem, QVBoxLayout, QWidget,
    )
    from taxops.ui.style import apply

    app = QApplication.instance() or QApplication(["TaxOps native font probe"])
    families = QFontDatabase.families()
    preflight = {
        "passed": False, "stage": "qt_initialized", "qt_platform": app.platformName(),
        "platform": platform.platform(), "python": platform.python_version(),
        "pyside": PySide6.__version__, "qt": qVersion(),
        "font_families": families, "font_family_count": len(families),
        "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM"),
        "samples": [], "png_saved": False,
    }
    reason = _capture_support_error(app.platformName(), families)
    if reason:
        # This tool's raw-font inspection is native-only. In particular, Qt's
        # offscreen box engine can appear valid without a physical font family.
        preflight.update(stage="unsupported", reason=reason)
        _write(output_dir / "native-font-probe.json", preflight)
        return preflight
    _write(output_dir / "native-font-probe.json", preflight)
    apply(app)
    root = QWidget()
    root.setWindowTitle("TaxOps native font diagnostic")
    layout = QVBoxLayout(root)
    widgets = []
    for name, text, required in SAMPLES:
        widget = QLabel(text)
        widget.setObjectName("PageTitle" if name == "traditional" else name)
        layout.addWidget(widget)
        widgets.append((name, widget, text, required))
    for name, widget, text in (
        ("button", QPushButton("新增附件"), "新增附件"),
        ("edit", QLineEdit("王小明／臺北市 2026-10-12"), "王小明／臺北市 2026-10-12"),
        ("combo", QComboBox(), "所有案件"),
    ):
        if isinstance(widget, QComboBox):
            widget.addItem(text)
        layout.addWidget(widget)
        widgets.append((name, widget, text, True))
    table = QTableWidget(1, 2)
    table.setHorizontalHeaderLabels(["客戶名稱", "本期稅額"])
    table.setItem(0, 0, QTableWidgetItem("王小明"))
    table.setItem(0, 1, QTableWidgetItem("NT$1,234.50"))
    layout.addWidget(table)
    widgets.extend([
        ("table_header", table.horizontalHeader(), "客戶名稱 本期稅額", True),
        ("table_cell", table, "王小明 NT$1,234.50", True),
    ])
    root.resize(900, 540)
    root.show()
    app.processEvents()
    families = QFontDatabase.families()
    records = []
    for name, widget, text, required in widgets:
        font = widget.font()
        info = QFontInfo(font)
        shaped = QTextLayout(text, font)
        shaped.beginLayout()
        line = shaped.createLine()
        if line.isValid():
            line.setLineWidth(2000)
        shaped.endLayout()
        runs = [_glyph_run_record(run, text) for run in shaped.glyphRuns()]
        passed, missing = _evaluate_glyph_records(runs, text)
        records.append({"name": name, "widget_class": type(widget).__name__, "text": text,
                        "required": required, "passed": bool(passed),
                        "requested_families": font.families(),
                        "resolved_family": info.family(), "resolved_pixel_size": info.pixelSize(),
                        "exact_match": info.exactMatch(), "glyph_runs": runs,
                        "missing_codepoints": missing})
    png = output_dir / "native-font-probe.png"
    saved = root.grab().save(str(png))
    report = {"scope": "Synthetic styled Qt widgets; not a complete application or release gate",
              "platform": platform.platform(), "python": platform.python_version(),
              "pyside": PySide6.__version__, "qt": qVersion(),
              "qt_platform": app.platformName(), "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM"),
              "font_families": families, "font_family_count": len(families),
              "candidate_families": {f: f in families for f in CANDIDATES},
              "candidate_writing_systems": {
                  f: [w.name for w in QFontDatabase.writingSystems(f)]
                  for f in CANDIDATES if f in families
              },
              "samples": records, "png_saved": saved, "png_filename": png.name,
              "logical_dpi": [root.logicalDpiX(), root.logicalDpiY()],
              "device_pixel_ratio": root.devicePixelRatioF()}
    report["passed"] = (app.platformName() == "windows" and saved
                        and all(r["passed"] for r in records if r["required"]))
    root.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "native-font-probe.json"
    if args.worker:
        # Also enforce the backend when this internal entry is invoked directly.
        os.environ["QT_QPA_PLATFORM"] = "windows"
        try:
            report = capture_probe(args.output_dir)
        except Exception:
            report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            report.update(passed=False, error=traceback.format_exc(), stage="worker")
        _write(path, report)
        return 0 if report["passed"] else 1

    report = {"passed": False, "stage": "preflight", "requested_qt_platform": "windows",
              "platform": platform.platform(), "python": platform.python_version()}
    _write(path, report)
    if sys.platform != "win32":
        report["error"] = "Native Windows probe requires Windows; no offscreen fallback is permitted."
        _write(path, report)
        return 2
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    try:
        # No application bootstrap or user database is opened. Redirect Qt/user
        # writable locations to an ephemeral profile outside the evidence folder.
        with tempfile.TemporaryDirectory(prefix="taxops-native-font-") as temporary:
            for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                        "XDG_DATA_HOME", "HOME", "USERPROFILE", "TEMP", "TMP"):
                directory = Path(temporary) / key.lower()
                directory.mkdir()
                env[key] = str(directory)
            result = subprocess.run(
                [sys.executable, "-m", "build_tools.native_font_probe", "--worker",
                 "--output-dir", str(args.output_dir.resolve())],
                env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
        (args.output_dir / "native-font-probe.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (args.output_dir / "native-font-probe.stderr.txt").write_text(result.stderr, encoding="utf-8")
        report = json.loads(path.read_text(encoding="utf-8"))
        report["worker_returncode"] = result.returncode
        if result.returncode != 0:
            report["passed"] = False
        if report.get("qt_platform") != "windows":
            report["passed"] = False
            report["error"] = "Worker did not establish the native Windows Qt platform."
        if report.get("stage") == "preflight":
            report["error"] = "Qt worker exited before completing evidence; inspect stderr."
        _write(path, report)
        return 0 if result.returncode == 0 and report["passed"] else 1
    except Exception:
        # Retain any partial Qt evidence written before a timeout or crash.
        report = json.loads(path.read_text(encoding="utf-8"))
        report["passed"] = False
        report["stage"] = "supervisor"
        report["error"] = traceback.format_exc()
        _write(path, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
