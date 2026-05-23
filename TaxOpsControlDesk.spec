# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TaxOps Control Desk (Windows one-dir build).

Output: dist/TaxOpsControlDesk/TaxOpsControlDesk.exe
Run with:  pyinstaller TaxOpsControlDesk.spec --noconfirm --clean
"""

a = Analysis(
    ["build_tools/pyinstaller_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets/app_icon.ico", "assets")],
    hiddenimports=[
        # PySide6 modules not always auto-detected but loaded at runtime
        "PySide6.QtSvg",
        "PySide6.QtXml",
        "PySide6.QtPrintSupport",
        "PySide6.QtNetwork",
        # openpyxl internal modules referenced by string at runtime
        "openpyxl.cell._writer",
        "openpyxl.styles.stylesheet",
        "openpyxl.styles.differential",
        # Jinja2 extensions used internally
        "jinja2.ext",
        "jinja2.compiler",
        "jinja2.runtime",
        "jinja2.filters",
        # All taxops migration modules (imported by __init__ by name)
        "taxops.db.migrations._m0001_initial",
        "taxops.db.migrations._m0002_tax_cache",
        "taxops.db.migrations._m0003_soft_delete",
        "taxops.db.migrations._m0004_engagements",
        "taxops.db.migrations._m0005_workflow_tasks",
        "taxops.db.migrations._m0006_message_templates",
        "taxops.db.migrations._m0007_generated_messages",
        "taxops.db.migrations._m0008_review_notes",
        "taxops.db.migrations._m0009_late_fee",
        "taxops.db.migrations._m0010_attachments",
        "taxops.db.migrations._m0011_backup",
        "taxops.db.migrations._m0012_fts5",
        "taxops.db.migrations._m0013_client_lease",
        "taxops.db.migrations._m0014_nullable_engagement",
        "taxops.db.migrations._m0015_recurring_billing",
        "taxops.db.migrations._m0016_rename_amount_cents",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test tooling — not needed at runtime
        "pytest",
        "_pytest",
        "pyinstaller",
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
    upx=True,
    console=False,          # No console window in production
    icon="assets/app_icon.ico",
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
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    name="TaxOpsControlDesk",
)
