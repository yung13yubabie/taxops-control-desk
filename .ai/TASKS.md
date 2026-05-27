# TASKS

## 2026-05-11 Task Update

### TODO

- [待驗證] 真實 Windows 桌面驗收：實際點擊「下載財政部稅籍資料」、確認兩段確認、進度視窗、成功/失敗中文訊息、tmp cleanup、audit log、正式 BGMOPEN1.zip 匯入結果。
  - 相關檔案或模組：`src/taxops/ui/pages/settings_page.py`, `src/taxops/services/registry_download.py`
  - 驗收方式：在 Windows UI/EXE 中操作；下載後 SQLite 可回讀 cache，audit_logs 有 `tax_cache.download`；測後無 python/pytest 殘留。
  - 是否可延後：不可延後到宣稱正式交付前；可在進 Slice 4 前後安排，但不能忘記。
- [待驗證] GCIS 線上查詢（工商查詢 API）仍未完成。本地稅籍快取查詢頁（Slice 13）已完成；Dashboard（Slice 14）已完成含篩選補完 + /simplify 修正：636/636 passed。GCIS 按鈕保持 disabled。
  - 相關檔案或模組：future `src/taxops/services/gcis.py`；`src/taxops/ui/pages/registry_page.py`（GCIS 按鈕目前 disabled）。
  - 驗收方式：需查官方 GCIS API 文件；需 URL allowlist、離線 fallback、測試與 action contract。
  - 是否可延後：可延後到 Dashboard 後；不得在未查官方文件情況下靠記憶實作（見 DECISIONS.md）。

### DONE

- [已確認] Slice 21E：待辦父子/批量 UI + 附件 PDF 預覽/檔案位置/`file:///` URL 顯示、複製、開啟，含空附件切換時清除 stale URL（2026-05-26）。
  - 相關檔案或模組：`src/taxops/ui/pages/tasks_page.py`, `src/taxops/ui/dialogs/task_bulk_dialogs.py`, `src/taxops/ui/pages/attachments_page.py`, `src/taxops/ui/action_registry.py`, `tests/test_slice21e_tasks_ui.py`, `tests/test_slice9_ui.py`
  - 驗收方式：`python -m pytest tests/test_slice21e_tasks_ui.py tests/test_slice21d_tasks_parent_bulk.py tests/test_slice5_ui.py -q --tb=short` => 36 passed；`python -m pytest tests/test_slice9_ui.py tests/test_attachments.py -q --tb=short` => 51 passed；cross suite => 105 passed；full suite `python -m pytest -q` => 972 passed；EXE build + smoke passed；resource hygiene 無殘留。
  - 待補驗證：人工在 EXE 內選取 PDF 附件確認視覺預覽。

- [已確認] Slice 21D backend：待辦 parent/child + bulk CRUD（2026-05-26）。
  - 相關檔案或模組：`src/taxops/db/migrations/_m0018_task_parent.py`, `src/taxops/services/tasks.py`, `src/taxops/repositories/tasks.py`, `tests/test_slice21d_tasks_parent_bulk.py`
  - 驗收方式：`python -m pytest tests/test_slice21d_tasks_parent_bulk.py tests/test_tasks.py tests/test_db_migrations.py -q --tb=short` => 60 passed；full pytest 輸出 958 passed。
  - 是否可延後：否，21E UI 已依此 backend 接線。

- [已確認] Resource hygiene closeout completed（2026-05-17）.
  - 相關檔案或模組：`src/taxops/services/registry_download.py`, `src/taxops/ui/pages/settings_page.py`, `build_tools/check_resource_hygiene.py`, `tests/test_slice3_download.py`, `tests/test_resource_cleanup.py`, `.ai/RESOURCE_CLEANUP_AUDIT.md`
  - 驗收方式：`python -m pytest tests/test_resource_cleanup.py tests/test_slice3_download.py tests/test_packaging_tools.py -q` => 29/29 passed；`python -m pytest -x --tb=short` => 643/643 passed；`python -m build_tools.check_resource_hygiene` 已輸出 process/TCP/listen port 證據。
  - 是否可延後：否，這是測試/開發環境穩定性補救。

- [已確認] Slice 3 HTTP download resource cleanup remediation completed.
  - 相關檔案或模組：`src/taxops/services/registry_download.py`, `src/taxops/i18n/errors.py`, `tests/conftest.py`, `tests/test_slice3_download.py`, `tests/test_resource_cleanup.py`, `.ai/RESOURCE_CLEANUP_AUDIT.md`
  - 驗收方式：`python -m pytest -x --tb=short` => 183/183 passed in 198.26s；測後無 `python` / `pytest` 殘留；TIME_WAIT = 8。
  - 是否可延後：否，已完成。

> [已確認] 2026-05-10 Slice 3 HTTP download 完成：下載按鈕啟用、URL allowlist + 兩段確認 + audit trail + DownloadError。pytest 175/175 passed。

## TODO

- [技術債] DB mutation + audit 非原子性：各 service 的 mutation 流程是「repository.commit() 後再 audit.record()」，兩步驟不在同一 SQLite transaction。若 audit 寫入失敗（如磁碟滿、connection 中斷），會留下「資料已改但 audit 缺失」的不一致狀態。橫跨所有 slice（clients / engagements / doc_requests / tasks）。
  - 修法方向：在 repository 層提供 transaction context manager，讓 service 把 repo 操作 + audit INSERT 包在同一個 `with conn:` 中。
  - 優先級：Medium — 正式交付前需修補，否則不符合 audit trail 完整性要求。
  - 可延後：可延後到所有功能 slice 完成後統一修。

- [待驗證] Slice 3 (GCIS 部分)：GCIS Swagger query implementation；enable 工商 / 稅籍查詢頁面。
  - 相關檔案：future `src/taxops/services/gcis.py`；`src/taxops/ui/pages/` 工商查詢頁。
  - 驗收方式：GCIS API 整合測試（可 mock）、查詢頁面顯示正確資料。
  - 可延後：MVP 範圍內，但可在其他模組後處理。

- [待改善] Dialog 錯誤目前用 Python `logging`，不寫入 SQLite `system_logs`。
  - 影響：audit trail 不完整；嚴格符合 system log 規格需把 `SystemLogService` 傳進 dialog 或由 page 包裝記錄。
  - 可延後：不影響「不露 raw exception 給 UI」的修正結果；可延後到 Slice 3 前處理。

- [已完成] engagement, document request, task, template, attachment, late-fee, and review-note modules — Slices 4–9 全部實作完成（Slice 9 closeout 後 512/512 passed, 2026-05-17）。

- [已完成] Excel 匯出缺件清單（Section 19 + 23）：`csv_guard.py` + `DocumentRequestsRepository.list_missing_items_for_export()` + `ExportService` + UI 按鈕 + action contract + 24 tests；536/536 passed（2026-05-17）。

- [已完成] Slice 11：備份 / 還原（Section 20）：`_m0011_backup.py` + `BackupRepository` + `BackupService`（SQLite backup API + before_restore 安全快照）+ 設定頁「備份與還原」group + 2 action contracts + 17 tests；553/553 passed（2026-05-17）。

- [已完成] Slice 14：Dashboard 控制台完整化 + 篩選補完 + /simplify 修正（2026-05-17）：
  - `src/taxops/repositories/dashboard.py`（NEW）：`DashboardRepository`（8 個 COUNT 查詢）。
  - `src/taxops/services/dashboard.py`（NEW）：`DashboardCounts` + `DashboardService`（`get_counts(today=None)`）。
  - `src/taxops/services/container.py`：新增 `dashboard: DashboardService`。
  - `src/taxops/ui/pages/dashboard_page.py`（NEW）：`DashboardPage`（8 張卡片）；`navigate_to_page = Signal(str, str)`；`_CARD_DEFS` 5-tuple 含 `FilterKey.*`。
  - `src/taxops/ui/main_window.py`：`DashboardPage` routing；`navigate_to(page_id, filter_key="")` 呼叫 `set_filter`；`NAV_ORDER.index()` 不再轉 list。
  - `src/taxops/ui/action_registry.py`：`FilterKey` class；4 個 PAGE_DASHBOARD enabled contracts；篩選比對使用 `FilterKey.*` 常數，不使用 raw string。
  - `tasks_page.py` / `engagements_page.py` / `review_notes_page.py`：各加 `set_filter(FilterKey)` 接口；repos + services 新增對應篩選查詢。
  - `/simplify` 修正：Dashboard filter 使用 `FilterKey` 常數；日期使用 `today_iso()`；`EngagementsPage` 的 upcoming 日期計算保留 `datetime` module-level import。
  - `tests/test_slice14_dashboard.py`（NEW）：31 tests（含篩選 signal 驗證）。
  - **636/636 passed**（2026-05-17）。

- [已完成] Slice 13：工商/稅籍查詢頁完整化（2026-05-17）：
  - `src/taxops/ui/pages/registry_page.py`（NEW）：`RegistryPage`；本地快取查詢 + 結果顯示 + 套用至客戶主檔；GCIS 按鈕保持 disabled。
  - `src/taxops/ui/dialogs/registry_apply_dialog.py`（NEW）：`RegistryApplyDialog`；欄位差異比較 + checkbox 選擇 + `UpdateClientInput` 套用；無差異時 OK 停用。
  - `src/taxops/ui/main_window.py`：新增 `PAGE_REGISTRY` routing。
  - `src/taxops/ui/action_registry.py`：2 個 enabled contracts（查詢本地快取 / 套用至客戶主檔）；GCIS 保持 disabled。
  - `src/taxops/i18n/errors.py`：4 個 `registry.apply.*` 錯誤碼。
  - `tests/test_slice13_registry.py`（NEW）：22 tests（search / UI / dialog / contracts）。
  - **605/605 passed**（2026-05-17）。
  - ⚠️ GCIS 線上查詢仍為 disabled，不在本 slice 完成範圍。

- [已完成] Slice 12：FTS5 全文搜尋（Section 21）：migration 0012（fts_clients + fts_engagements trigram）+ SearchRepository（add/update/delete/search_*_ids/rebuild_*，全寫方法 try/except→rollback→raise）+ SearchService（search_clients/search_engagements/is_fts_eligible/rebuild_index）+ ClientsService/EngagementsService FTS 同步（create→add, update→update, delete→delete，失敗 _log.warning 不靜默）+ container 掛載 + ClientsPage FTS 增強搜尋（query>=3 chars 走 FTS，shorter fallback LIKE）+ action registry contract + 30 tests（含使用者補強 2 個回歸測試）；583/583 passed（2026-05-17）。

- [待驗證] Implement security tests: XSS/HTML injection, resource limits.
  - 相關檔案：`src/taxops/core/text.py`, `tests/test_*security*`.
  - 驗收方式：來源規格第 23.1 節列出的 payload 必須有 pytest 覆蓋（CSV formula injection 已由 test_export_security.py 覆蓋）。
  - 可延後：否；屬 MVP 完成定義。

- [已完成] Windows EXE packaging pre-closeout（PyInstaller one-dir build + automated smoke）。
  - 相關檔案：`TaxOpsControlDesk.spec`, `build_tools/pyinstaller_entry.py`, `build_tools/clean_package.py`, `build_tools/package_windows.py`, `build_tools/smoke_test_exe.py`, `tests/test_packaging_tools.py`, `docs/packaging_checklist.md`。
  - 驗收方式：`python -m build_tools.package_windows` 產出 `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`；`python -m build_tools.smoke_test_exe` 驗證 EXE 啟動且 SQLite 建立於 temp `LOCALAPPDATA\TaxOpsControlDeskDev`；packaging 當輪 `python -m pytest -x --tb=short` => 639/639 passed；resource hygiene closeout 後全套更新為 643/643 passed。
  - 已修正問題：PyInstaller 直接使用 `src/taxops/__main__.py` 時 relative import 會導致 windowed EXE 假啟動但不建 DB；已改用 absolute-import entry point。
  - 尚未完成：人工 Windows UI checklist（主視窗、11 導覽、設定頁、客戶新增持久化、audit、縮放 125/150%）。
  - 可延後：人工驗收不可延後到正式交付之外。

- [待驗證] Draft Traditional Chinese user manual.
  - 相關檔案：future `docs/user_manual_zh_tw.md`.
  - 驗收方式：手冊需描述已實作功能，不得描述未完成功能為可用。
  - 可延後：可延後到主要功能完成後，但不可延後到 MVP 之外。

- [待驗證] Keep `.ai/DESIGN.md` aligned with UI implementation decisions.
  - 相關檔案：`.ai/DESIGN.md`, UI pages.
  - 可延後：否；UI slice 開始前需讀取。

- [待驗證] Implement remaining MVP modules required by section 24 of the source specification.
  - 相關檔案：`docs/implementation_spec.md`, source specification compact file.
  - 驗收方式：第 24 節 checklist 全部有測試或手動驗收證據。
  - 可延後：否；MVP 不完成前不可宣稱交付。

- [部分驗收] Perform real Windows desktop manual acceptance: 1366x768, 1920x1080, scaling 100%/125%/150%.
  - 相關檔案：PySide6 UI, `src/taxops/ui/pages/settings_page.py`, future EXE.
  - 驗收方式：實機截圖或明確手動驗收紀錄。
  - 可延後：可延後到可互動 UI/EXE 後，但不可延後到 MVP 之外。
  - [已驗收 offscreen] SettingsPage 建構、5 按鈕啟用、下載按鈕停用、verify_cache、真實 BGMOPEN1.zip（1,705,060 筆）：7/7 passed。
  - [仍待人工驗收] QFileDialog 選檔、QProgressDialog 進度視窗、QMessageBox 中文字型、QThread 整合、客戶管理新功能（批量匯入、編輯、刪除、衝突審查）桌面操作。

## DOING

- 無進行中項目。

## RECENTLY COMPLETED

- [已確認] v0.14.2（2026-05-27）— 固定開立 toolbar RWD：
  - `RecurringBillingPage` 頂部 filter row 從 QHBoxLayout 改 FlowLayout（reuse v0.14.1 widgets/flow_layout.py）
  - 「+ 新增方案」+「產生待開立紀錄」+ 客戶 combo + 包含已封存 checkbox 全部會在窄窗口換行
  - 移除原 stretch + insertWidget 雜湊處理
  - 26/26 tests passed
  - pyproject.toml + __init__.py 0.14.1 → 0.14.2

- [中繼點] v0.14.3 – v0.15.2 留下次 session（roadmap 已透過 /grill-me 對齊細節）：
  - v0.14.3 案件→索件→文件 drill-down 三層
  - v0.15.0 Dashboard → QDockWidget 浮動 helper
  - v0.15.1 全刪 ReviewNotes + 新增 folder_bookmarks 資料夾管理
  - v0.15.2 筆記模板 markdown + obsidian-cli 整合
  - 完成後 Codex 全 codebase review + final ship
  - 完整 spec 見 .ai/HANDOFF.md 「中繼點」段

- [已確認] SLOP patch round v0.14.1（2026-05-27）— 4 點介面修正：
  - **EXE 多開鎖**：新檔 `src/taxops/ui/single_instance.py` 提供 `SingleInstanceGuard`，使用 `QLocalServer`/`QLocalSocket` 命名通訊；第二個 process 啟動時送 `activate` payload → 顯示中文提示 → exit；第一個實例 raise/activate 主視窗。
  - **索件批次 context banner + 所屬案件 column**：`DocumentRequestsPage` 加高對比 banner（藍底 #DBEAFE / 深藍字 #1E3A8A），global 模式顯示「現在顯示：全部案件（N 筆索件批次）」、engagement 模式顯示「現在顯示：[客戶名] — [案件名]」。`_REQ_COLUMNS` 新增 `engagement_label`（標題「所屬案件」），global 預設顯示、engagement 隱藏。
  - **RWD toolbar wrap**：新檔 `src/taxops/ui/widgets/flow_layout.py`；DocumentRequestsPage（12 個按鈕）+ EngagementsPage（5 個按鈕）toolbar 改用 FlowLayout，窗口窄化自動換行。
  - **附件 URL 整併**：刪預覽區「檔案URL：」row + 複製/開啟按鈕；「檔案位置」按鈕加 `CustomContextMenu`，右鍵彈選單「複製 file:// URL」一鍵複製。
  - **中央按鈕設計 token**：`style.py` 加 `BTN_PRIMARY_SM` / `BTN_SECONDARY_SM` / `BTN_DANGER_SM`（含完整 bg/color/hover/disabled）；`recurring_billing_page.py` 將 `_SMALL_BTN`/`_SKIP_BTN`/`_DANGER_BTN` aliased 到中央 tokens，解決「編輯方案 / 新增明細」按鈕背景透明 + 文字對比 SLOP。
  - `tests/test_single_instance.py`（NEW，5 passed + 1 skipped）+ `tests/test_slice9_ui.py` 移除 4 個 URL-row 測試新增 2 個 context-menu 測試。
  - pyproject.toml + __init__.py 0.14.0 → 0.14.1。

- [已確認] Slice 21C v0.12.0（2026-05-26）— 欄位顯示控制 + 欄寬持久化：
  - 新 `src/taxops/ui/widgets/column_settings.py` helper：對任意 QTableWidget 安裝右鍵 header 選單（per-col checkbox + 自動調整 + 重設預設）；auto-persist `columns_hidden` (CSV) + `column_widths` (JSON) 到 app_settings；核心欄不可隱藏（即使設定誤寫也會被強制顯示）。
  - 8 個新 app_settings keys：`ui.{engagements,doc_requests,doc_items,tasks}.{columns_hidden,column_widths}` 加入 DEFAULT_SETTINGS（自動納入 ALLOWED_KEYS）。
  - 4 表全接入：EngagementsPage / DocumentRequestsPage 兩個 tables / TasksPage；各定義 `_CORE_COLS` 依 Grill #2.5 規格（案件={engagement_name, status}、索件批次={period_name, status}、文件項目={item_name, item_status}、待辦={title, status}）。
  - 欄寬 JSON 容量 480 字元安全上限（settings 500 字元 cap）。
  - `tests/test_slice21c_column_settings.py`（NEW，9 tests）：helper unit (6) + page integration (3)。
  - pyproject.toml + __init__.py 版本升至 0.12.0；git tag v0.12.0；dist zip + GitHub Release。
  - **942/942 passed**（2026-05-26，含 9 新測試）。

- [已確認] Slice 21B v0.11.0（2026-05-26）— 索件管理併入案件管理：
  - **DocumentRequestsPage 加 `embedded` 參數**：True 時隱藏 back_btn / context_label / engagement combo + label，外緣 margin 0；standalone 模式完全保留。
  - **EngagementsPage master-detail 重寫**：QSplitter(Vertical) 上半案件清單 + 下半嵌入式 `DocumentRequestsPage(embedded=True)`；row 選取 → `load_engagement(id)`；無選取 → `clear_filter` + 全部案件視圖。
  - **sidebar 移除 PAGE_DOC_REQUESTS**：`NAV_ORDER` 從 12 → 11 items；常數保留供 action_registry contracts 使用。
  - **main_window 移除 DocumentRequestsPage routing**：移除 import / build branch / `_on_open_doc_requests` / `open_doc_requests.connect` 連線。
  - **EngagementsPage 移除 `_doc_btn` 與 `open_doc_requests` Signal**（polish — 內嵌不需跨頁按鈕）。
  - **tests/test_slice4_ui_smoke 兩個 test 移除「管理索件批次」斷言**。
  - **tests/test_ui_action_contracts 加 `_EMBEDDED_ONLY_PAGES` whitelist**：PAGE_DOC_REQUESTS contracts 可不在 NAV_ORDER 仍合法。
  - `tests/test_slice21b_merged_engagements.py`（NEW，8 tests）。
  - pyproject.toml + __init__.py 版本升至 0.11.0；git tag v0.11.0；dist zip + GitHub Release。
  - **933/933 passed**（2026-05-26，含 8 新測試）。

- [已確認] Slice 21A v0.10.0（2026-05-26）— 索件批次模板選擇 + 批量刪除：
  - **Breaking API**：`CreateDocumentRequestInput.use_vat_template: bool` 移除，改為 `item_names: tuple[str, ...] = ()`；caller 直接傳項目清單，service 不再 hardcode VAT_ITEMS 查表；`VAT_ITEMS` 保留為 module-level 常數供 UI consume。
  - **新 `DocumentItemTemplateDialog`**：checklist（VAT_ITEMS 9 項預設全勾）+ 全選/全不選按鈕 + 自訂項目 input/list + 持久化到 `app_settings.ui.doc_request_template.vat`（per-tax-type JSON `{"checked": [...], "custom": [...]}`）。
  - **DocumentRequestsPage `_on_new_request` 流程改寫**：picker engagement → template dialog → create_request(item_names=)；取消對話即中止整流程，不寫入空 doc_request。
  - **批量刪除文件項目**：item_table ExtendedSelection；新 toolbar 按鈕「批量刪除項目」；新 service `delete_items_bulk(ids) -> int`（per-request 重算狀態一次，audit 一次 `doc_request_item.bulk_delete`）。
  - **conftest autouse fixture**：`DocumentItemTemplateDialog.exec` mock 修舊 tests 因 modal-exec hang。
  - `tests/test_slice21a_doc_request_template_and_bulk_delete.py`（NEW，18 tests）；`tests/test_document_requests.py` 12 個 caller 改用 `item_names=VAT_ITEMS`。
  - pyproject.toml + __init__.py 版本升至 0.10.0；git tag v0.10.0；dist zip `TaxOpsControlDesk-v0.10.0-windows.zip`；GitHub Release v0.10.0 含 EXE artifact。
  - **925/925 passed**（2026-05-26，含 18 新測試）。

- [已確認] Slice 20C v0.9.0（2026-05-25）— 固定開立 UX 重設：
  - `services/recurring_billing.py`：新增 module-level `parse_bulk_lines(text) -> (lines, errors)` tab 分隔解析、空行跳過、行號錯誤回報；新增 `RecurringBillingService.create_plan_with_lines(plan_inp, lines_inp)` atomic 方法（驗證所有 inputs → 透過 repo 單一 transaction 寫入 → audit 一次紀錄 line_count）。
  - `repositories/recurring_billing.py`：新增 `insert_plan_with_lines(plan_dict, lines_list)` 原子方法，try/commit/except/rollback 保證 plan + lines 一致。
  - `ui/dialogs/recurring_billing_dialogs.py`：PlanDialog create-mode 重寫為兩段 QGroupBox（合約資訊 + 固定開立明細 table）；新增 `_BulkPasteDialog` 二級彈窗接 tab 分隔貼上；新增 `_on_add_line_row` / `_on_remove_line_row` / `_set_line_cell` / `_read_lines_from_table` 方法。Edit-mode 保留 update_plan 流程。
  - `i18n/errors.py`：新增 `recurring_billing.lines.empty` + `recurring_billing.amount.invalid` 兩錯誤碼。
  - `tests/test_slice20c_recurring_billing.py`（NEW，16 tests）：atomic create (5) + parse_bulk_lines (6) + confirm audit (1) + PlanDialog (4)。
  - pyproject.toml + __init__.py 版本升至 0.9.0；git tag v0.9.0；dist zip `TaxOpsControlDesk-v0.9.0-windows.zip`；GitHub Release v0.9.0 含 EXE artifact。
  - **907/907 passed**（2026-05-25，含 16 新測試）。

- [已確認] Slice 20B v0.8.0（2026-05-24）— 代辦事項客戶選擇：
  - Migration 0017_workflow_tasks_client_id：`ALTER TABLE workflow_tasks ADD COLUMN client_id INTEGER REFERENCES clients(id)` + UPDATE backfill 從 engagements join + `idx_workflow_tasks_client` 索引。
  - `repositories/tasks.py`：`TaskRow.client_id`、`_row_to_task` mapping、`insert(... client_id=None)`；新增 `get_engagement_client_id(engagement_id)`、`client_exists(client_id)`、`list_by_client(client_id, ...)` 三個 helper。
  - `services/tasks.py`：`CreateTaskInput.client_id` 欄；`create_task` 自動從 engagement 同步 client_id（engagement 為單一真相來源，覆寫任何 caller 提供值）；只綁 client 時驗證 `client_exists` 否則 raise `task.client_not_found`；新增 `list_by_client(client_id)` wrapper。
  - `ui/pages/tasks_page.py` 重寫：`_client_combo` + `_eng_combo` cascade；三段 filter（指定案件 → list_by_engagement；指定客戶 → list_by_client；全部 → list_all）；`refresh_context()` reload client + engagement combos。
  - `ui/dialogs/new_task_dialog.py` 重寫：fixed engagement mode 保留；cascade mode 客戶 combo（含「不指定客戶」`_NO_CLIENT=-1`）+ 依 client 過濾的案件 combo（含「不綁案件」`_NO_ENGAGEMENT=-1`）；`on_save` 組裝 `CreateTaskInput` 由 service 負責 client_id 同步。
  - `i18n/errors.py`：新增 `task.client_not_found = "找不到指定客戶，待辦無法建立"`。
  - `tests/test_slice20b_tasks_client.py`（NEW，20 tests）：schema 3 + backfill 1 + service create_task 5 + list_by_client 2 + page cascade 6 + dialog 4。
  - `tests/test_db_migrations.py`：versions list 追加 0017，count 16→17。
  - `tests/test_slice5_ui.py`：`_FakeContainer` 補 `system_log` + `clients` services 以支援新 TasksPage。
  - pyproject.toml + __init__.py 版本升至 0.8.0；git tag v0.8.0；dist zip `TaxOpsControlDesk-v0.8.0-windows.zip`。
  - **891/891 passed**（2026-05-24，含 20 新測試）。

- [已確認] Slice 20A v0.7.0（2026-05-24）— 索件管理上下文自主化：
  - `src/taxops/ui/pages/document_requests_page.py` 重寫：新增 `_engagement_combo`（全部案件 + 全部 active engagements），label「客戶名 — 案件名 — 期別」；切換 combo 直接刷新索件列表，不需回案件管理頁。
  - `_on_new_request()` 在全域模式（`_engagement_id is None`）改為彈出 `QInputDialog.getItem` engagement picker 而非 silent return；無案件時顯示 info dialog 引導建案件。
  - `_on_edit_item` / `_on_set_item_status` / `_on_delete_item` 改為呼叫 `_refresh_requests()`（含 `_fill_request_table` 的選取保留 + 強制 `_load_items_for_selected()`），item 操作後 request 表立即同步且選取不跳掉。
  - 全部 mutation catch-all 改為 `system_log.error(...)` + QMessageBox，不再 silent return。
  - `tests/test_slice20a_doc_requests_context.py`（NEW，15 tests）：combo presence / label format / switch / global picker / item refresh sync / preserve selection / clear_filter 回 global。
  - `tests/test_slice4_ui_smoke.py` 移除過時「新增按鈕 load 前 disabled」斷言。
  - pyproject.toml + __init__.py 版本升至 0.7.0；git tag v0.7.0；dist zip `TaxOpsControlDesk-v0.7.0-windows.zip`。
  - **871/871 passed**（2026-05-24，含 15 新測試）。

- [已確認] Slice 19 hotfix v0.6.1（2026-05-23）：
  - `_derive_request_status()` 加入空 frozenset 防衛（empty set → "requested"，避免被誤判 accepted）。
  - `delete_item()` service 刪除後呼叫 `_recompute_request_status()` 更新父層 document request 狀態。
  - `test_document_requests.py` 補 2 個測試：`test_delete_item_recomputes_request_status`、`test_delete_all_items_returns_request_to_requested_not_accepted`。
  - `test_slice19d_recurring_billing.py` 補 2 個行為測試：全部客戶 → info dialog；指定客戶 → PlanDialog.exec()。
  - pyproject.toml + __init__.py 版本升至 0.6.1；git tag v0.6.1；dist zip 重新打包為 v0.6.1。
  - **856/856 passed**（2026-05-23）。

## BLOCKED

- [已確認] No blocker is currently recorded in this file.
- [待驗證] Real Windows visual/interaction verification remains unperformed, but it is not currently marked as a blocker.

## DONE

- [已確認] Slice 8：覆核意見 + 滯納金試算（2026-05-17）：
  - `src/taxops/db/migrations/_m0008_review_notes.py`：review_notes 表（FK→engagements + workflow_tasks）+ 2 索引。
  - `src/taxops/db/migrations/_m0009_late_fee.py`：late_fee_records 表（FK→document_requests）+ 1 索引。
  - `src/taxops/repositories/review_notes.py`：`ReviewNoteRow` + `ReviewNotesRepository`（insert/get/list_by_engagement/update_status）。
  - `src/taxops/repositories/late_fee.py`：`LateFeeRow` + `LateFeeRepository`（insert/get/list_by_request）。
  - `src/taxops/services/review_notes.py`：`ReviewNotesService`（create/update_status/list_by_engagement/get）；狀態機 open→responded/waived→resolved/reopened；critical 不可 waive；waive 需 reason；audit trail。
  - `src/taxops/services/late_fee.py`：`LateFeeService`（calculate_and_save/list_by_request）+ `calculate_penalty_percent()` 純函數；labor_health → needs_manual_review=True, penalty=0；10% 上限；audit trail。
  - `src/taxops/ui/pages/review_notes_page.py`：`ReviewNotesPage`（案件 filter + 覆核意見表格 + 新增/回覆/解決/豁免/重新開啟按鈕）。
  - `src/taxops/ui/pages/late_fee_page.py`：`LateFeePage`（案件+索件 filter + 試算表單 + 試算記錄表格 + 人工確認警示）。
  - `src/taxops/ui/action_registry.py`：新增 5 個 enabled contracts（開始試算 / 新增覆核意見 / 回覆 / 豁免）；移除 2 個 disabled stubs。
  - `src/taxops/ui/main_window.py`：路由 PAGE_LATE_FEE + PAGE_REVIEW_NOTES。
  - `src/taxops/services/container.py`：新增 review_notes + late_fee service fields + build 連線。
  - `src/taxops/i18n/errors.py`：新增 9 個 review_note.* + 4 個 late_fee.* 錯誤碼。
  - `src/taxops/i18n/status_labels.py`：新增 labor_health / severity / review note status 標籤 + SEVERITY_LABELS / REVIEW_NOTE_STATUS_LABELS dicts。
  - `tests/test_review_notes.py`（21 tests）+ `tests/test_late_fee.py`（17 tests，含 11 parametrize 公式驗證）+ `tests/test_slice8_ui.py`（12 tests）+ migration 更新 7→9 versions/tables。
  - **437/437 passed**（2026-05-17）。

- [已確認] Slice 7：產生催件訊息（generated_messages）（2026-05-17）：
  - `src/taxops/db/migrations/_m0007_generated_messages.py`：generated_messages 表 + idx_generated_messages_request 索引。
  - `src/taxops/repositories/generated_messages.py`：`GeneratedMessageRow` + `GeneratedMessagesRepository`（insert/get/list_by_request）。
  - `src/taxops/services/generated_messages.py`：`GeneratedMessagesService`（build_variables/generate/list_by_request/get_message）；`build_variables()` 組裝全部 11 個 ALLOWED_VARIABLES（4 個未來欄位已於 Slice 15 移除）；`generate()` 呼叫 render + insert + audit，TemplateValidationError 轉成 GeneratedMessageValidationError。
  - `src/taxops/ui/dialogs/generate_message_dialog.py`：`GenerateMessageDialog`（模板 combo + 即時預覽 + 複製 + 儲存並關閉）。
  - `src/taxops/ui/pages/document_requests_page.py`：新增「產生訊息」按鈕；`_on_generate_message()` 開啟 dialog。
  - `src/taxops/ui/action_registry.py`：新增 1 個 enabled contract（產生訊息）。
  - `src/taxops/services/container.py`：新增 `gen_messages: GeneratedMessagesService` + build 連線。
  - `src/taxops/i18n/errors.py`：新增 5 個 gen_message 錯誤碼。
  - `tests/test_generated_messages.py`（15 tests，含 FK schema 驗證）+ `tests/test_slice7_ui.py`（10 tests，含 select→save→DB→audit 整合路徑）+ migration version/table 更新至 7。
  - **Closeout correction（2026-05-17）**：補 FK、補 2 個 UI 整合測試、build_variables 未來欄位注釋。
  - **381/381 passed**（2026-05-17 closeout）。

- [已確認] Slice 6：訊息模板管理（message_templates）（2026-05-16）：
  - `src/taxops/db/migrations/_m0006_message_templates.py`：message_templates 表 + is_builtin 旗標 + seed 兩筆內建模板（首次索件 / 催件通知）。
  - `src/taxops/repositories/templates.py`：`TemplateRow` + `TemplatesRepository`（insert/get/list_all/update/delete）；軟刪除 + is_builtin=0 保護。
  - `src/taxops/services/templates.py`：`TemplatesService`（create_template/update_template/delete_template/get_template/list_all/render_template）；Jinja2 `ALLOWED_VARIABLES` 白名單驗證；`_validate_body()` 重用 `self._env` + 已解析 AST 避免重複建立 Environment。
  - `src/taxops/i18n/status_labels.py`：新增 `TEMPLATE_TYPE_LABELS`（首次索件 / 催件通知 / 自訂）。
  - `src/taxops/ui/dialogs/template_form_dialog.py`：`TemplateFormDialog` 合併新增/編輯；內建模板唯讀（所有欄位 + save 按鈕停用）；`_BODY_FOCUS_ERRORS` frozenset。
  - `src/taxops/ui/pages/templates_page.py`：`TemplatesPage`（表格 + 右側預覽 QSplitter + `_body_cache` dict 避免 per-selection DB 查詢）。
  - `src/taxops/ui/main_window.py`：連接 `TemplatesPage`。
  - `src/taxops/ui/action_registry.py`：PAGE_TEMPLATES 4 個 enabled contract（新增/編輯/刪除模板/儲存編輯）。
  - `src/taxops/services/container.py`：補 `templates_repo` + `templates_service` build 連線。
  - `tests/test_templates.py`（35 tests）+ `tests/test_slice6_ui.py`（12 tests）：schema/CRUD/render/audit/UI smoke 全覆蓋。
  - `tests/test_db_migrations.py`：更新至 6 個 migration 版本。
  - **Closeout correction**（2026-05-16）：TemplatesService 改 `StrictUndefined`（缺值拋 `template.variable.missing`）；`ALLOWED_VARIABLES` 從 7 擴充至 15；tests/test_templates.py 新增 6 個 render 缺值 + 擴充白名單測試；errors.py 補 `template.variable.missing` 錯誤碼；CURRENT_STATE.md 頁面計數修正。
  - **357/357 passed**（2026-05-16 closeout 後）。

- [已確認] Slice 5：待辦事項（workflow_tasks）（2026-05-15）：
  - `src/taxops/db/migrations/_m0005_workflow_tasks.py`：workflow_tasks 表 + 4 索引。
  - `src/taxops/repositories/tasks.py`：`TaskRow` + `TasksRepository`（insert/get/list_by_engagement/list_all/list_overdue/update/update_status/complete/delete/engagement_exists）。
  - `src/taxops/services/tasks.py`：`TasksService`（create_task/complete_task/set_status/delete_task/list_by_engagement/list_all/list_overdue）、whitelist 驗證、`_ALLOWED_TASK_TRANSITIONS`、audit log on every mutation。
  - `src/taxops/repositories/engagements.py` + `src/taxops/services/engagements.py`：補 `list_all()` 供 TasksPage engagement 篩選 combo 使用。
  - `src/taxops/ui/pages/tasks_page.py`：`TasksPage`（engagement 篩選、任務表格、新增/完成/切換狀態/刪除/重新整理、空狀態）。
  - `src/taxops/ui/dialogs/new_task_dialog.py`：`NewTaskDialog`（標題必填、負責人、到期日、優先級、下一步）。
  - `src/taxops/ui/main_window.py`：連接 `TasksPage`。
  - `src/taxops/ui/action_registry.py`：4 個 enabled contracts（新增/完成/切換狀態/刪除待辦）。
  - `src/taxops/i18n/errors.py`：11 個 task error codes。
  - `src/taxops/i18n/status_labels.py`：`PRIORITY_LABELS` 中文對照。
  - `tests/test_tasks.py`（33 tests）+ `tests/test_slice5_ui.py`（13 tests）。
  - 不含 document request cross-link（Not in scope this slice）。
  - 不含 Dashboard overdue card（Not in scope this slice）。
  - **303/303 passed**（2026-05-15）。

- [已確認] Slice 4.5 案件編輯 + 索件項目狀態 UI（2026-05-15）：
  - `src/taxops/ui/dialogs/edit_engagement_dialog.py`（新建）：預填表單，`update_engagement()` + audit。
  - `src/taxops/ui/pages/engagements_page.py`：補「編輯案件」按鈕，wire `_on_edit_engagement()`。
  - `src/taxops/ui/pages/document_requests_page.py`：補「切換項目狀態」按鈕，wire `_on_set_item_status()` + `_on_item_selection_changed()`。
  - `src/taxops/ui/action_registry.py`：新增 3 個 enabled contract（編輯案件/儲存編輯/切換項目狀態）。
  - `tests/test_slice45_ui.py`（NEW）：9 tests，含預填驗證、DB+audit 閉環。
  - **257/257 passed**（2026-05-15）。

- [已確認] Slice 4 UI（2026-05-15）：
  - `src/taxops/ui/pages/engagements_page.py`：案件列表（依客戶過濾）+ 新增/切換狀態/刪除/開啟索件批次。
  - `src/taxops/ui/pages/document_requests_page.py`：索件批次列表 + item 列表 + 新增/標記已發出/催件/刪除。
  - `src/taxops/ui/dialogs/new_engagement_dialog.py`：新增案件表單（draft-only，無初始狀態選擇器）。
  - `src/taxops/ui/action_registry.py`：啟用 5 個案件 actions + 4 個索件 actions；移除殘留 disabled placeholder。
  - `src/taxops/ui/main_window.py`：cross-page navigation（Signal/Slot）。
  - `tests/test_slice4_ui_smoke.py`：11 smoke tests + 3 handler integration tests；全通過。
  - 修正：`create_engagement()` 強制 draft-only；`test_engagements.py` 更新對應測試。
  - **241/241 passed**（2026-05-15）。

- [已確認] Slice 4 後端（backend partial，2026-05-14）：
  - Migration 0004：engagements + document_requests + document_request_items（3 表 7 索引）。
  - `EngagementsRepository` + `DocumentRequestsRepository`（含 `insert_request_with_items` 原子批次）。
  - `EngagementsService`（狀態轉換守衛 `_ALLOWED_TRANSITIONS` + FK 驗證）。
  - `DocumentRequestsService`（item→request 狀態自動重算 `_derive_request_status` + FK 驗證）。
  - `ServiceContainer` 新增 `engagements` + `doc_requests`。
  - `tests/test_engagements.py`（22 tests）+ `tests/test_document_requests.py`（25 tests）：全通過，含 FK/transition/atomicity/recompute。
  - **230/230 passed**（2026-05-14）。
  - **⚠️ UI 尚未完成** — engagements/document_requests 頁面仍為 placeholder。

- [已確認] Slice 3 HTTP download 完成（2026-05-10）：
  - `src/taxops/services/registry_download.py`：`download_registry_zip()` + `DownloadError`（network/io）。
  - `src/taxops/ui/pages/settings_page.py`：`on_download_registry()` 兩段確認 + 背景下載+匯入 + audit；`_RegistryWorker` 新增 `DownloadError` catch。
  - `src/taxops/ui/action_registry.py`：「下載財政部稅籍資料」改 `enabled=True`，完整合約。
  - `src/taxops/i18n/errors.py`：3 個下載錯誤碼。
  - `tests/test_slice3_download.py`（NEW）：14 tests，全 passed。
  - 更新舊斷言：`test_registry_cache_ui.py` + `test_settings_page_smoke.py`。
  - 已實際驗證：`python -m pytest` → **175/175 passed**。

- [已確認] Slice 2.6 客戶管理與主框架可用性強化（2026-05-10）：
  - `ClientsRepository.search_clients()` + `count_clients()`：LIKE 搜尋 client_code/client_name/tax_id，order_by 白名單防注入，分頁 limit/offset。
  - `ClientsService.search_clients()` + `count_clients()`：pass-through；`list_clients()` 保留。
  - `clients_page.py`：搜尋列（QLineEdit + 搜尋/清除 + 總筆數）、排序（點擊欄位標題 + setSortIndicator）、分頁（◀上一頁/下一頁▶ + 第X–Y筆）；所有操作用 client_id，不用 row index。
  - `app_settings.py`：`("ui.sidebar_collapsed", "0")` 加入 DEFAULT_SETTINGS。
  - `main_window.py`：nav 包進 sidebar QWidget；toggle 按鈕 ◀/▶；collapse/expand 讀寫 app_settings；重開後還原。
  - `tests/test_slice26_clients_search.py`（NEW）：15 tests — 全 passed。
  - 已實際驗證：`python -m pytest -x --tb=short` → **159/159 passed**。

- [已確認] 稅籍查詢帶入 + 錯誤保護 + prefill audit + 批量匯入可捲動（2026-05-10）：
  - `TaxRegistryRepository.search()`：統編精確 / 名稱 LIKE，limit=20。
  - `NewClientDialog`：稅籍查詢面板（有快取時顯示），結果 tooltip 顯示地址，帶入填欄位，搜尋錯誤中文提示不崩潰。
  - `ClientsService.create_client()`：audit detail 增加 `registry_prefill_used`, `source_tax_id`, `cache_version`。
  - `bulk_import_wizard.py` Step 1：改 QScrollArea，底部按鈕固定可見。
  - `clients_page.py` `on_new_client()`：try/except 包 count()，失敗時 system_log.warn + 隱藏稅籍面板。
  - 軟刪除 UI 文案改為「請聯絡系統維護人員」（移除假裝使用者可自行復原）。
  - 已新增：`tests/test_registry_lookup_in_new_client.py`（7 tests）、`tests/test_registry_error_guard.py`（4 tests）。
  - 已實際驗證：`python -m pytest -x --tb=short` → **143/143 passed**。

- [已確認] Slice 2.5-A 批量匯入說明強化 + B 回退（2026-05-10）：
  - 已完成：`bulk_import_wizard.py` Step 1 新增多列格式說明、3 列 placeholder、複製貼上範本按鈕（`_PASTE_TEMPLATE`）、下載 Excel 範本按鈕（disabled）。
  - 已放棄：B（客戶列表補 address/match_status/matched_name/matched_address）— 全部回退。
  - 已新增：`tests/test_clients_page_smoke.py`（3 個 Slice 2.5-A smoke tests）。
  - 已實際驗證：`python -m pytest -x --tb=short` → **132/132 passed**（含軟刪除 6 tests）。

- [已確認] 錯誤訊息修正 + parser 測試補齊（2026-05-10）：
  - 已修復：`bulk_import_wizard.py` raw exception 露出 → `error_message(exc.code)` + `_log.error()`。
  - 已修復：`mismatch_review_dialog.py` raw exception 露出 → 拆 `ClientValidationError` / generic + 中文訊息。
  - 已修復：`_parse_diffs()` 靜默吞錯 → `_log.warning()` + 保守 `{}`。
  - 已修復：`parse_excel()` / `parse_csv()` 無測試 → `tests/test_clients_bulk_parse.py`（9 tests）。
  - 已補測試：`test_dialog_acceptance.py` 新增 `test_mismatch_dialog_malformed_diffs_json_returns_empty`。

- [已確認] 客戶管理功能閉環（2026-05-10）：
  - 新增檔案：`clients_bulk.py`, `bulk_import_wizard.py`, `mismatch_review_dialog.py`, `style.py`, `test_dialog_acceptance.py`.
  - 修改檔案：`clients_page.py`, `container.py`, `action_registry.py`, `matcher.py`, `settings_page.py`, `app.py`, `test_clients.py`, `ui_action_contract.md`.
  - 已實際驗證：3 個 HIGH 審計問題修復（TOCTOU fix, accept-on-failure fix, wizard Back fix）。
  - [待驗證] 真實 Windows 桌面互動（批量匯入、編輯/刪除、衝突審查視窗）。

- [已確認] Slice 2 完成 + closeout correction（2026-05-10）：
  - 已實際驗證：83 tests passed；12 個 test_registry_cache_ui.py（10 原始 + 2 thread smoke）。
  - 已實際驗證：ZIP importer extension guard + 500MB 大小上限。
  - 已實際驗證：5 個離線按鈕 enabled，含 service/repository/audit_action/handler。
  - 已實際驗證：`tmp/` 加入 .gitignore。
  - 已實際驗證：背景執行緒 fresh-connection pattern（threading.Thread smoke）。
  - [已驗收 offscreen] 7/7 SettingsPage smoke tests（含真實 BGMOPEN1.zip 1,705,060 筆）。
  - [未驗收] settings_page.py UI handlers 在真實 Windows 桌面互動。

- [已確認] Slice 1 corrections (2026-05-09): `client_code NOT NULL UNIQUE`, rename `name` → `client_name`, validation paths, 移除 silent except, .gitignore. 39/39 tests.

- [已確認] Slice 1 base implementation (2026-05-09): skeleton, clients minimal CRUD, settings, 11-item nav, audit/system log, i18n, UI action contract registry. 37/37 tests.

- [已確認] Established project skeleton, `.ai/` collaboration layer, initial docs, `docs/implementation_spec.md`, `docs/registry_cache_workflow.md`.

- [已確認] Confirmed all long-term decisions: MVP scope = full section 24, no WSTP, official open data sources, no-encrypt bundles, single local-user mode, EXE packaging required, premium simple UI direction.

## Notes

- [已確認] 2026-05-10 更新：稅籍查詢帶入、錯誤保護、prefill audit、批量匯入 QScrollArea、軟刪除文案修正 → **143/143 passed**。下一步建議：真實 Windows 桌面驗收（稅籍查詢帶入流程、批量匯入視窗捲動、停用確認文案）。
