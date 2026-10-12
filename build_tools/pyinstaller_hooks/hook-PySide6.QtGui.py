"""Keep the upstream QtGui collection except the unused virtual keyboard.

TaxOps uses QWidget input and the Windows platform's native IME, not the
separate Qt Virtual Keyboard (GPL-only/commercial) plugin. Filter before
PyInstaller's dependency scan so its unused QtQuick/QML chain is not collected.
"""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries
            if Path(entry[0]).name.lower() != "qtvirtualkeyboardplugin.dll"]
