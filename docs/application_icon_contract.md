# Application icon contract

The EXE, application windows, and taskbar use the same visual identity through
different Windows/Qt entry points. A shortcut is a launcher, not a second brand.
The app's existing blue tile with a white T is a custom ICO, not the PyInstaller
default icon. Application identity is separate from Windows Shell extensions
that obtain icons for documents or folders inside the app.

## Source and candidate assets

The original vector candidates are in `assets/application_icon_candidates/`:

- `ledger`: an accounting ledger with a blue binding and summary line.
- `workbench`: a navigation rail and compact working area.
- `monogram`: a TO mark continuing the current primary blue tile.

The selected shipping design is **ledger**. Its master SVGs are copied to
`assets/app_icon.svg` and `assets/app_icon-small.svg`, and the generated ICO is
`assets/app_icon.ico`. The candidate folders are retained for design provenance
and are not bundled by the spec. The candidates
use existing palette values (`#1E293B`, `#2563EB`, white), geometry only, and no
fonts, third-party artwork, gradients, external resources, or network requests.
`mark-small.svg` optically adjusts 16/24/32 pixel frames rather than shrinking
all details from the 256 pixel master.

Generate candidates with the pinned release dependencies:

```text
python -m build_tools.generate_app_icons
python -m build_tools.generate_app_icons --output-directory <review-directory> --preview <preview.png>
python -m build_tools.generate_app_icons --shipping
```

For headless Linux generation, set `QT_QPA_PLATFORM=offscreen`. This is a build
tool using already-required PySide6; users of the standalone EXE need no converter
or additional software. Each ICO contains 32-bit RGBA frames at 16, 24, 32, 48,
64, 128, and 256 pixels. Small frames are DIB plus transparency masks; the
256 pixel frame is PNG. Both forms are supported by the target Windows versions.
Checked-in ICOs can be reproduced using pinned Qt 6.10.2.

Candidate-only generation leaves the shipping icon unchanged. `--shipping`
explicitly regenerates it from the selected master SVGs. The existing spec
already embeds that ICO path as the EXE icon and as runtime data;
no installer, registry changes, or target-machine dependencies are needed.

## Window, executable, and shortcut responsibilities

1. **Explorer / an EXE placed on the desktop:**
   `TaxOpsControlDesk.spec` uses `EXE(icon="assets/app_icon.ico")`. The icon is a
   PE resource in the standalone executable and remains available while closed.
2. **Running window and application dialogs:**
   `src/taxops/ui/app.py` sets the QApplication icon before constructing the UI.
   `style.apply()` also applies that same asset. Widgets with no explicit
   override inherit the application icon. Individual dialog overrides are not
   necessary for a single app identity. `asset_path()` uses the bootloader's
   bundle location while frozen and ignores the working directory.
3. **Taskbar grouping and pinning:**
   `run()` sets the stable `TaxOps.ControlDesk.Desktop` AppUserModelID before Qt
   creates any UI. It must remain unchanged across ordinary app upgrades.
   If a shortcut is created, its `System.AppUserModel.ID` must match that ID.
   Its target is the user's stable copy of `TaxOpsControlDesk.exe`, and its icon
   location is that executable with icon index 0. Do not use `python.exe`, a
   development launcher, or a temporary `_MEI` path as a persistent launcher.

The runtime data ICO inside `_MEI` is suitable for immediate Qt loading. A
pinned shortcut must use the stable executable's icon resource, because the
temporary extraction is removed after normal exit. Merely setting a Qt icon
does not prove a desktop shortcut or taskbar pin has the correct persistent
target, metadata, or cached icon.

The app does not currently create shortcuts or modify user pinning settings.
Any future shortcut feature should use Shell Link properties and the same ID;
do not introduce an installer solely for the icon. If explicit window-level
relaunch properties become necessary, their launch command and icon must also
refer to the stable EXE, and must be set before the window-level AppUserModelID.
Microsoft recommends the matching shortcut when one exists.

## Verification gates

- Parse all seven ICO directory entries, dimensions, bit depth, offsets, and
  transparent mask orientation. Render original SVGs and verify byte-for-byte
  regeneration with pinned Qt. Decode each exact size with Qt's ICO reader.
- Run `test_application_icon_candidates.py`, `test_frozen_resources.py`, and
  `test_packaging_tools.py`. Preserve shipping assets before selection. Run
  the required full test matrix and repository hygiene gate for an integrated
  candidate; focused checks alone are not the release gate.
- On the actual Windows-built candidate, compare embedded `RT_GROUP_ICON` and
  `RT_ICON` payloads with the selected ICO; confirm the runtime asset matches.
  Launch from a directory containing spaces and Traditional Chinese with an
  unrelated working directory. Check the application and main window icon.
- On Windows 10/11, check Explorer/desktop EXE, desktop shortcut, running taskbar,
  Alt+Tab, and the taskbar pin both running and closed at 100%, 125%, and 150%
  scaling. Confirm pinning launches the stable EXE, groups with the same app
  rather than creating a duplicate button, and still works after normal exit,
  reboot, and replacement by a new candidate at the same location.
- If an EXE is moved, existing shortcuts still target its old location; recreate
  the affected shortcut/pin with user permission. Do not silently rewrite pins
  or delete Windows icon caches. An unchanged cached icon is not evidence that
  the PE resource or Qt icon failed.

A Linux/offscreen Qt pass verifies rendering and decoding only. Hosted Windows
automated tests do not establish the user's actual desktop, shortcut, taskbar
pin, theme, or DPI acceptance. Record these stages separately.

## Official references for the pinned release

- [Qt 6.10 application icon overview](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-appicon.html)
- [Qt 6.10 QWidget icon inheritance](https://doc.qt.io/qtforpython-6.10/PySide6/QtWidgets/QWidget.html)
- [PyInstaller 6.11.1 icon option](https://pyinstaller.org/en/v6.11.1/usage.html#cmdoption-i)
- [PyInstaller 6.11.1 runtime paths](https://pyinstaller.org/en/v6.11.1/runtime-information.html)
- [Microsoft AppUserModelID placement and shortcut matching](https://learn.microsoft.com/en-us/windows/win32/shell/appids)
- [Microsoft process AppUserModelID startup ordering](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-setcurrentprocessexplicitappusermodelid)
- [Microsoft Shell Link icon path and index](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ishelllinkw-seticonlocation)
- [Microsoft pinned relaunch icon resource](https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-relaunchiconresource)
- [Microsoft app icon design guidance](https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-design)
- [Microsoft icon resource formats and PNG support](https://devblogs.microsoft.com/oldnewthing/20231025-00/?p=108925)
