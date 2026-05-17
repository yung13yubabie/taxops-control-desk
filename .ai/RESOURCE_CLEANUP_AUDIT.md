# RESOURCE CLEANUP AUDIT

## 2026-05-17 - Development/Test Resource Hygiene Closeout

### Scope

- [已確認] 檢查範圍：pytest suite、HTTP download、SettingsPage QThread worker、PyInstaller EXE smoke subprocess、tempfile usage、本機 process / port / socket 狀態。
- [已確認] 本輪未發現測試啟動 server、browser、Chromium、Electron、Node 或每個 test 開新 port 的流程。
- [已確認] 本輪新增 `build_tools/check_resource_hygiene.py`，用於測後列出 TaxOps/PyTest/PyInstaller 相關進程、TCP state counts、Listen ports。

### Findings And Fixes

#### 1. Unexpected download stream failure could leave `.part`

- Root Cause: [已確認] `src/taxops/services/registry_download.py` 只清理 `DownloadError`、`URLError`、`OSError`；若 response.read() 或 mock stream 丟出非預期例外，`.part` 清理沒有 regression test 保證。
- Impact: [已確認] 測試或正式下載在非預期中斷時可能留下半成品檔案，造成後續誤判或磁碟累積。
- Fix Strategy: [已確認] 在 `download_registry_zip()` 補 `except Exception: _unlink_quietly(part_path); raise`，保留原例外語意但確保半成品清掉。
- Minimal Patch: [已確認] 修改 `src/taxops/services/registry_download.py`。
- Regression Risk: [已確認] 非預期例外仍會往外傳；只新增清理，不改既有 `DownloadError` mapping。
- Verification: [已確認] `tests/test_slice3_download.py::test_download_registry_zip_unexpected_read_error_cleans_part` 覆蓋 first chunk 後拋 RuntimeError，驗證 `out.zip` 與 `out.zip.part` 均不存在。
- Regression Test: [已確認] 同上，另補 `test_download_registry_zip_passes_finite_timeout` 確認 `urlopen(..., timeout=...)` 有明確 timeout。
- Rollback Plan: [已確認] 若發現外部 caller 依賴殘留 `.part` debug，回退該 except 區塊即可，但不建議。
- Evidence: [已確認] `python -m pytest tests/test_resource_cleanup.py tests/test_slice3_download.py tests/test_packaging_tools.py -q` => 29/29 passed；`python -m pytest -x --tb=short` => 643/643 passed。

#### 2. QThread worker QObject cleanup was implicit

- Root Cause: [已確認] `_RegistryWorker` 完成後會關閉 SQLite container/connection，但 `SettingsPage._run_async()` 沒有明確排程 `worker.deleteLater()`。
- Impact: [已確認] 連續執行下載/匯入/驗證等長任務時，Qt QObject 生命週期依賴 parent 清理，不利於長時間桌面操作與資源閉環證明。
- Fix Strategy: [已確認] 在 success/error slot 結束時呼叫 `worker.deleteLater()`。
- Minimal Patch: [已確認] 修改 `src/taxops/ui/pages/settings_page.py` 的 `_on_finished()` 與 `_on_errored()`。
- Regression Risk: [待驗證] 真實桌面 QThread signal delivery 仍需人工操作驗收；目前 offscreen 測試只能證明程式碼路徑與回歸測試不破。
- Verification: [已確認] `tests/test_resource_cleanup.py::test_settings_page_worker_is_deleted_after_async_completion` 檢查 cleanup hook 存在；全套 643/643 passed。
- Regression Test: [已確認] 同上。
- Rollback Plan: [已確認] 若真實 Qt 桌面操作發現 premature deletion，可改成連接 built-in thread finished 或用 `QTimer.singleShot(0, worker.deleteLater)`。
- Evidence: [已確認] `python -m pytest -x --tb=short` => 643/643 passed。

#### 3. No one-command post-test process/port/socket evidence

- Root Cause: [已確認] 先前靠手動 PowerShell 指令檢查進程與 TCP 狀態，容易漏跑或每個 agent 輸出不一致。
- Impact: [已確認] 若 pytest、PyInstaller smoke 或 EXE 測試殘留進程，下一輪可能遇到 port 被佔用、socket 狀態異常或測試互搶資源，但 handoff 證據不一致。
- Fix Strategy: [已確認] 新增 `python -m build_tools.check_resource_hygiene` 作為固定測後巡檢命令；只列證據，不自動 kill。
- Minimal Patch: [已確認] 新增 `build_tools/check_resource_hygiene.py`。
- Regression Risk: [已確認] 此工具是診斷用途；不影響產品程式與 pytest 正常流程。
- Verification: [已確認] 執行 `python -m build_tools.check_resource_hygiene`，輸出 suspicious process、TCP state counts、Listen ports。
- Regression Test: [已確認] `tests/test_resource_cleanup.py::test_resource_hygiene_script_checks_processes_ports_and_tcp_states` 檢查腳本包含 Win32 process 與 TCP/Listen 查詢。
- Rollback Plan: [已確認] 若 PowerShell 查詢在特定 Windows 環境不支援，可保留工具但在文件標註手動 fallback，或改為平台偵測。
- Evidence: [已確認] 測後輸出：僅看到當下執行中的 `python -m build_tools.check_resource_hygiene`；最新 TCP states: Bound=35, CloseWait=2, Established=30, Listen=33, TimeWait=18。

### Environment Verification

- [已確認] Targeted suite: `python -m pytest tests/test_resource_cleanup.py tests/test_slice3_download.py tests/test_packaging_tools.py -q` => 29 passed in 11.16s.
- [已確認] Full suite: `python -m pytest -x --tb=short` => 643 passed in 585.37s.
- [已確認] Post-test resource check: `python -m build_tools.check_resource_hygiene` completed; no TaxOpsControlDesk / pytest / pyinstaller residual process was listed, except the diagnostic command's own Python process.
- [已確認] Post-test TCP state did not show abnormal TIME_WAIT explosion: TimeWait=18.
- [已確認] Listen ports were reported for existing system/app processes; this pytest run did not start a test server/browser.

### Current Verdict

- [已確認] 目前測試流程沒有發現 server/browser/port collision 型殘留。
- [已確認] HTTP download 與 EXE smoke 的可控資源清理已補 regression test。
- [待驗證] 真實 Windows 桌面連續操作 QThread / QFileDialog / QProgressDialog 仍需人工長時間測試。

## 2026-05-11 - Slice 3 Network / Process / Port / Socket Review

### Scope

- [已確認] 檢查範圍：Slice 3 HTTP download、SettingsPage QThread workflow、pytest resource cleanup、SQLite container cleanup、本機 port/socket/process 狀態。
- [已確認] Context Hub 已查詢 `pytest-timeout` 2.4.0 文件；本專案目前未新增 `pytest-timeout` 依賴，因專案規則要求新增依賴需先確認。
- [已確認] 本輪未啟動 server、browser、Electron、Chromium 或 Node 測試流程。

### Findings And Fixes

#### 1. Download partial file and oversized stream guard

- Root Cause: [已確認] `src/taxops/services/registry_download.py` 原本直接寫入目標檔，且只依賴 timeout，沒有 Content-Length / streaming byte 上限，也沒有 `.part` 原子寫入。
- Impact: [已確認] 下載過大或中途中斷時，可能留下半成品 zip；官方網域若回傳異常大檔，可能耗盡磁碟或長時間佔用連線。
- Fix Strategy: [已確認] 加入 500 MB `MAX_DOWNLOAD_BYTES`，先寫入 `*.part`，成功後 `replace()`，失敗時清除 `.part`。
- Minimal Patch: [已確認] 修改 `download_registry_zip(url, dest_path, timeout=300, max_bytes=MAX_DOWNLOAD_BYTES)`。
- Regression Risk: [待驗證] 若官方 BGMOPEN1.zip 未來超過 500 MB，HTTP 下載會拒絕；離線匯入規格同樣是 500 MB 上限，因此目前行為與規格一致。
- Verification: [已確認] `tests/test_slice3_download.py` 新增 atomic write、Content-Length too large、stream too large cleanup 測試。
- Regression Test: [已確認] `test_download_registry_zip_writes_atomically_on_success`, `test_download_registry_zip_rejects_large_content_length`, `test_download_registry_zip_rejects_stream_over_limit_and_cleans_part`。
- Rollback Plan: [已確認] 若修補造成合法下載失敗，可回退 `registry_download.py` 的 `.part`/max_bytes 變更，但必須保留 tmp cleanup 測試或改採等效保護。
- Evidence: [已確認] `python -m pytest -x --tb=short` 通過 183/183。

#### 2. Test temp directories leaked outside pytest tmp_path

- Root Cause: [已確認] 多個測試 helper 使用 `tempfile.mkdtemp()`，未指定目錄；大量重跑或失敗時會在使用者 TEMP 累積測試資料夾。
- Impact: [已確認] 不會造成 port collision，但會造成本機暫存檔無限制增加，長期會污染開發環境。
- Fix Strategy: [已確認] 在 `tests/conftest.py` 增加 autouse fixture，把 `tempfile.tempdir` 導到每個 test 的 `tmp_path/_tempfile`。
- Minimal Patch: [已確認] 新增 `isolated_tempfile_dir(tmp_path, monkeypatch)` fixture。
- Regression Risk: [待驗證] 若未來某測試必須使用系統 TEMP 根目錄，此 fixture 會改變行為；目前未發現此需求。
- Verification: [已確認] 新增 `tests/test_resource_cleanup.py::test_tempfile_mkdtemp_is_isolated_under_pytest_tmp_path`。
- Regression Test: [已確認] 該測試會直接呼叫 `tempfile.mkdtemp()`，並斷言路徑位於 pytest `tmp_path`。
- Rollback Plan: [已確認] 可移除 autouse fixture，改逐一改寫 helper 接收 `tmp_path`；但工作量較大。
- Evidence: [已確認] `python -m pytest tests/test_slice3_download.py tests/test_resource_cleanup.py -x --tb=short -vv` 通過 22/22。

#### 3. Test hang caused by infinite mocked read()

- Root Cause: [已確認] 修改下載為 `.part` 寫入後，既有 `test_download_registry_zip_raises_on_io_error` 不再在 open 目標目錄時失敗；mock response 的 `read.return_value = b"data"` 造成無限讀取。
- Impact: [已確認] 先前完整 pytest 曾被工具層 10 分鐘 timeout；縮小範圍測試也曾被 5 分鐘 timeout，殘留一個 `python -m pytest ...` 進程。
- Fix Strategy: [已確認] 將 mock read 改成有限 side_effect，並用不存在 parent path 觸發 `.part` open 的 OSError。
- Minimal Patch: [已確認] 修改 `tests/test_slice3_download.py::test_download_registry_zip_raises_on_io_error`。
- Regression Risk: [已確認] 測試意圖仍是驗證 IO error mapping，不影響正式程式碼。
- Verification: [已確認] 卡住的 pytest 進程已確認 command line 後終止；修補後窄範圍 22/22 通過，完整 183/183 通過。
- Regression Test: [已確認] 同一測試保留，且不再使用永遠回傳資料的 mock。
- Rollback Plan: [已確認] 若需要其他 IO error 模擬，可 patch `builtins.open` raise `OSError`，但不可回到 infinite `read.return_value`。
- Evidence: [已確認] 測後 `Get-Process` 無 `python/pytest` 殘留。

#### 4. SettingsPage download success path was under-tested

- Root Cause: [已確認] 既有 success-path 測試手刻類似 `_do()` 的 service-level 流程，沒有直接執行 `SettingsPage.on_download_registry()` 建立的 closure。
- Impact: [已確認] 若 UI closure 的 audit 參數、tmp cleanup 或 import sequence 壞掉，測試可能漏掉。
- Fix Strategy: [已確認] 用 inline `_run_async` 替代 QThread，直接觸發 `on_download_registry()` 的真實 closure；download function 用 mock 寫入有效 zip，不做真實 HTTP。
- Minimal Patch: [已確認] 新增 `test_download_button_success_runs_import_audit_and_cleans_tmp`。
- Regression Risk: [已確認] 只影響測試，不改 UI 執行模型。
- Verification: [已確認] 測試確認 import row count、audit action/detail、tmp cleanup、success message。
- Regression Test: [已確認] `tests/test_slice3_download.py::test_download_button_success_runs_import_audit_and_cleans_tmp`。
- Rollback Plan: [已確認] 若 UI refactor 改變 `_run_async` 介面，需同步更新此測試以保持 closure 級驗證。
- Evidence: [已確認] `python -m pytest -x --tb=short` 通過 183/183。

### Environment Verification

- [已確認] Full suite: `python -m pytest -x --tb=short` => 183/183 passed in 198.26s.
- [已確認] Post-test process check: no `python` / `pytest` process remains.
- [已確認] Post-test TCP state: `TIME_WAIT = 8`; no abnormal explosion observed.
- [已確認] Post-test listen ports are existing system/app ports; pytest did not start a server or browser.
- [已確認] Existing `chrome` / `node` processes were observed before and after tests; they were not killed because they were not proven to be created by this pytest run.

### Current Verdict

- [已確認] Slice 3 HTTP download path is acceptable after this remediation.
- [待驗證] Real Windows UI interaction for QFileDialog / QProgressDialog / QMessageBox and actual online download with official BGMOPEN1.zip still requires manual desktop acceptance.
- [已確認] GCIS query remains separate TODO and is not completed by Slice 3 HTTP download.
