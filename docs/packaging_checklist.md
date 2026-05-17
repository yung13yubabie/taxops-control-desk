# Packaging Checklist (Windows EXE)

PyInstaller packaging pre-closeout is implemented. The automated build and
smoke test pass, but the manual Windows UI checklist below must still be run
before release readiness is claimed.

## Build Commands

```powershell
python -m build_tools.clean_package
python -m build_tools.package_windows
python -m build_tools.smoke_test_exe
```

## Implemented Layout

- `TaxOpsControlDesk.spec`: PyInstaller one-dir build spec.
- `build_tools/pyinstaller_entry.py`: frozen-app entry point using absolute imports.
- `build_tools/clean_package.py`: removes `build/`, `dist/TaxOpsControlDesk/`, `__pycache__/`, `*.pyc`, `*.pyo`, and `*.spec.bak`.
- `build_tools/package_windows.py`: invokes `python -m PyInstaller TaxOpsControlDesk.spec --noconfirm --clean`.
- `build_tools/smoke_test_exe.py`: launches the built EXE with a temporary `LOCALAPPDATA` and verifies startup plus SQLite creation.

## Automated EXE Smoke Test

`python -m build_tools.smoke_test_exe` currently verifies and exits non-zero on failure:

- [x] EXE exists at `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
- [x] EXE starts and remains alive after startup wait.
- [x] SQLite initializes; `taxops.sqlite` is created under temp `LOCALAPPDATA\TaxOpsControlDeskDev\`.
- [x] EXE process is terminated after smoke; if terminate times out, it is killed and waited.

## Manual EXE Smoke Checklist

These items are printed by the smoke runner but still require human UI verification:

- [ ] Main window title is `TaxOps Control Desk`.
- [ ] All 11 nav labels display in Traditional Chinese.
- [ ] Sidebar collapse/expand toggle works.
- [ ] Settings page opens.
- [ ] Data paths are displayed with middle-elide, tooltip, open, and copy buttons.
- [ ] A new client can be created via dialog and persists after restarting the EXE.
- [ ] Audit log row exists for the create action.
- [ ] Disabled buttons show `此功能尚未開放` tooltip.
- [ ] No fake rows, fake counts, or fake success messages appear.
- [ ] Window renders correctly at 1366x768 with Windows scaling 100%, 125%, and 150%.

## Production vs Dev Data Roots

- Dev EXE: `%LOCALAPPDATA%\TaxOpsControlDeskDev\` when `TAXOPS_DEV=1`.
- Production EXE: `%LOCALAPPDATA%\TaxOpsControlDesk\` by default.
- Backups: `%USERPROFILE%\Documents\TaxOpsBackups\`.

## What Clean Must NOT Remove

- SQLite data
- Attachments
- Cache bundles
- Test data
- Source code
- Docs

## Verified State

- 2026-05-17: `python -m build_tools.package_windows` succeeded.
- 2026-05-17: `python -m build_tools.smoke_test_exe` succeeded.
- 2026-05-17: `python -m pytest -x --tb=short` passed at 639/639 during packaging closeout; later resource-hygiene closeout passed at 643/643.

## Known Boundary

Automated smoke currently proves EXE startup and SQLite creation only. It does not prove visual rendering, dialog behavior, client CRUD through the GUI, real registry download flow, or DPI/scaling compatibility. Those remain manual acceptance items.
