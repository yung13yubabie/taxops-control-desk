# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TaxOps Control Desk (Windows one-dir build).

Output: dist/TaxOpsControlDesk/TaxOpsControlDesk.exe
Run with:  pyinstaller TaxOpsControlDesk.spec --noconfirm --clean
"""

from PyInstaller.utils.hooks import collect_submodules
import PySide6
from PySide6.QtCore import QLibraryInfo
from pathlib import Path
from shutil import copyfile
import sys

# The pyinstaller console script does not guarantee the spec directory is on
# sys.path. Analysis.pathex is applied later than this build-time gate.
sys.path.insert(0, str(Path(SPECPATH).resolve()))

from build_tools.dependency_licenses import NOTICE_SOURCE, validate_build_environment

validate_build_environment()

_qt_translation = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / "qtbase_zh_TW.qm"
_qt_translation_target = str(Path("PySide6") / _qt_translation.parent.relative_to(Path(PySide6.__file__).parent))
if not _qt_translation.is_file():
    raise RuntimeError("Required Traditional Chinese Qt catalogue is missing")


a = Analysis(
    ["build_tools/pyinstaller_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets/app_icon.ico", "assets"), (str(_qt_translation), _qt_translation_target),
           (str(NOTICE_SOURCE), "third_party_licenses")],
    hiddenimports=[
        # PySide6 modules not always auto-detected but loaded at runtime
        "PySide6.QtSvg",
        "PySide6.QtXml",
        "PySide6.QtPrintSupport",
        "PySide6.QtNetwork",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        # openpyxl internal modules referenced by string at runtime
        "openpyxl.cell._writer",
        "openpyxl.styles.stylesheet",
        "openpyxl.styles.differential",
        # Jinja2 extensions used internally
        "jinja2.ext",
        "jinja2.compiler",
        "jinja2.runtime",
        "jinja2.filters",
    ] + collect_submodules("taxops.db.migrations"),
    hookspath=["build_tools/pyinstaller_hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # No application use; prevent accidental GPL-only/commercial binding.
        "PySide6.QtVirtualKeyboard",
        # Test tooling — not needed at runtime
        "pytest",
        "_pytest",
        "pyinstaller",
        # Runtime networking uses urllib; do not bundle unrelated environment
        # packages whose versions may be mutually incompatible.
        "requests",
        "urllib3",
        "chardet",
        "charset_normalizer",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TaxOpsControlDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # No console window in production
    icon="assets/app_icon.ico",
    version="build_tools/windows_version_info.txt",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    name="TaxOpsControlDesk",
)

# Keep the notice index discoverable beside the executable; all original texts
# remain under the default PyInstaller _internal directory.
copyfile(NOTICE_SOURCE / "README.txt", Path(coll.name) / "THIRD_PARTY_NOTICES.txt")
