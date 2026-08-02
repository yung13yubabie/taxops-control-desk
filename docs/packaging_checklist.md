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
- `build_tools/smoke_test_exe.py`: launches the built EXE with a temporary `LOCALAPPDATA`, verifies startup and SQLite creation, and requires migration `0028_annual_compliance`.

## Automated EXE Smoke Test

`python -m build_tools.smoke_test_exe` currently verifies and exits non-zero on failure:

- [x] EXE exists at `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
- [x] EXE starts and remains alive after startup wait.
- [x] SQLite initializes; `taxops.sqlite` is created under temp `LOCALAPPDATA\TaxOpsControlDeskDev\`.
- [x] The database contains migration `0028_annual_compliance`.
- [x] EXE process is terminated after smoke; if terminate times out, it is killed and waited.

## Release ZIP Verification

This is a separate release step, not a capability of `smoke_test_exe.py`:

- [x] Extract the delivery ZIP to a fresh directory.
- [x] Launch the extracted EXE with a separate temporary `LOCALAPPDATA`.
- [x] Verify startup, SQLite creation, migration `0028_annual_compliance`, and process cleanup.

## Manual EXE Smoke Checklist

These items are printed by the smoke runner but still require human UI verification:

- [ ] Main window title is `TaxOps Control Desk`.
- [ ] All 12 nav labels display in Traditional Chinese, including `年度工作台`.
- [ ] Sidebar collapse/expand toggle works.
- [ ] Settings page opens.
- [ ] Data paths are displayed with middle-elide, tooltip, open, and copy buttons.
- [ ] A new client can be created via dialog and persists after restarting the EXE.
- [ ] Audit log row exists for the create action.
- [ ] Disabled buttons show `此功能尚未開放` tooltip.
- [ ] No fake rows, fake counts, or fake success messages appear.
- [ ] 年度工作台可建立 2026 母體、編輯年度明細日期，關閉再開後資料仍一致。
- [ ] 年度明細的 `索件／附件／任務` 可見；900x540 協作視窗各頁籤可捲到所有操作，不裁切、不偷偷放大。
- [ ] 固定開立可編輯起始日、無已確認歷史的方案可刪除；連點兩次 `新增列` 只留一個空白列。
- [ ] 待開立批量核對只處理所選資料，重複操作不產生重複紀錄或假成功。
- [ ] 客戶特殊要求／備註總覽可篩選；表格摘要不破壞資料，tooltip／編輯重開保留精確換行。
- [ ] 訊息模板的可用欄位說明清楚；產生訊息時能從客戶／案件／索件／固定開立資料帶入。
- [ ] 工商名稱同名查詢顯示多家公司可選；行業別可見；170 萬筆離線匯入時有明確進度且完成後可查。
- [ ] Window renders correctly at 1366x768 with Windows scaling 100%, 125%, 150%, and 200%.

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

- 2026-08-01: requested workflow refresh passes all 2,682 tests across 112
  sequential fresh processes at 90.11569881344029% combined coverage,
  including both real 65MB BGMOPEN1 imports.
- 2026-08-01: release pins pass `pip-audit` after moving setuptools to 83.0.0;
  the EXE was rebuilt in isolated Python 3.11.9 with PyInstaller 6.11.1 and
  PySide6 6.10.2.
- 2026-08-01: build-tree and fresh-ZIP-extraction smoke pass through migration
  `0028_annual_compliance`; 191 extracted files exactly match the build tree
  and the forbidden-path scan is empty.
- 2026-08-01: `TaxOpsControlDesk-v0.30.0-win64.zip` is 50,116,927 bytes with
  SHA-256 `39D09F530AE7FD42DA64103F814883D1AC4B0699454B4428CFA5C52D04204C7D`.

- 2026-07-31: clean branch coverage passes at 90.18%, 2663 tests.
- 2026-07-31: isolated v0.30.0 build and build-tree EXE smoke pass through migration 0028.
- 2026-07-31: Windows version metadata reports FileVersion/ProductVersion `0.30.0.0`, ProductName `TaxOps Control Desk`, and OriginalFilename `TaxOpsControlDesk.exe`.
- 2026-07-31: `TaxOpsControlDesk-v0.30.0-win64.zip` reads all 192 entries (191 files), exactly matches the build tree, and passes extracted-EXE smoke.
- 2026-07-31: ZIP size 50,095,302 bytes; SHA-256 `C42ADDC2761C6748252D91B9B35F73F7952229A94F9CF082CA4DA559AE0F4E9A`.

- 2026-05-17: `python -m build_tools.package_windows` succeeded.
- 2026-05-17: `python -m build_tools.smoke_test_exe` succeeded.
- 2026-05-17: `python -m pytest -x --tb=short` passed at 639/639 during packaging closeout; later resource-hygiene closeout passed at 643/643.

## Known Boundary

Automated smoke proves packaged startup, SQLite creation, latest schema, archive integrity, and process cleanup. It does not prove human-visible rendering, mouse/keyboard ergonomics, SmartScreen behavior, long-running real-office data, or DPI/scaling compatibility. Those remain manual acceptance items.
