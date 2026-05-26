# CURRENT_STATE

## 2026-05-11 Verified Current State

- [已確認] Slice 3 HTTP download 已完成補救修正：下載服務改為 `.part` 原子寫入、500 MB 上限、失敗清理 partial file。
- [已確認] 測試資源清理已補強：`tests/conftest.py` 將 `tempfile.mkdtemp()` 導入每個測試的 `tmp_path/_tempfile`，避免使用者 TEMP 累積。
- [已確認] 新增 Slice 3 成功路徑測試，直接觸發 `SettingsPage.on_download_registry()` 的真實 closure，驗證 import、audit、tmp cleanup。
- [已確認] 最新驗證：`python -m pytest -x --tb=short` => 183/183 passed in 198.26s。
- [已確認] 測後環境檢查：`python -m build_tools.check_resource_hygiene` 已執行；未列出 TaxOpsControlDesk / pytest / pyinstaller 殘留進程，僅列出巡檢命令本身；TIME_WAIT = 18；未發現 pytest 新增 server/browser/listen port。
- [待驗證] 真實 Windows 桌面操作仍需人工驗收：QFileDialog、QProgressDialog、QMessageBox、正式網路下載 BGMOPEN1.zip、EXE 內相同行為。
- [已確認] GCIS query 仍未完成；若 Slice 3 定義只限 HTTP download，Slice 3 可視為通過；若 Slice 3 包含 GCIS，則 GCIS 仍是 TODO。
- [已確認] 詳細資源清理稽核與修復閉環記錄在 `.ai/RESOURCE_CLEANUP_AUDIT.md`。

> [已確認] 2026-05-10 Slice 3 HTTP download 完成：下載財政部稅籍資料按鈕啟用，URL allowlist + 兩段確認 + audit trail + DownloadError。pytest 175/175 passed。

## Project Goal

- [已確認] 專案目標是建立 TaxOps Control Desk，一個 Windows-first、離線優先的台灣會計／稅務事務所營運桌面工具。
- [已確認] 產品定位包含事務所案件營運、客戶索件與缺件追蹤、稅務工作流管理、附件證據鏈、內部覆核、離線資料與待辦控制台。
- [已確認] MVP 不可宣稱完成，直到來源規格第 24 節全部完成並驗證。

## Current Status

- [已確認] Slice 1、Slice 2（稅籍快取）、客戶管理功能閉環（批量匯入 + 編輯/刪除 + 衝突審查）、Slice 2.6（搜尋/排序/分頁 + sidebar 收合）、Slice 3（HTTP download）、Slice 4（案件 + 索件）、Slice 4.5（案件編輯 + 索件項目狀態 UI）、Slice 5（待辦事項）、Slice 6（訊息模板）、Slice 7（產生催件訊息）、Slice 8（覆核意見 + 滯納金試算）、Slice 9（附件證據鏈 MVP + closeout correction）、Slice 10（Excel 匯出缺件清單 + CSV formula injection defense）、Slice 11（備份 / 還原）、Slice 12（FTS5 全文搜尋）、Slice 13（本地工商 / 稅籍查詢頁）、Slice 14（Dashboard 真實統計 + 篩選導向補完）均已完成實作。
- [已確認] `python -m pytest` 最後確認通過：942/942 passed（2026-05-26 Slice 21C v0.12.0；含 9 個新測試）。
- [已確認] G-1~G-15 UIUX 修復已完成：WA_DeleteOnClose、anti-double-click、toolbar_icon、error label、silent failure 修正等；dashboard high_risk_engagements 導向修正為 PAGE_REVIEW_NOTES + FilterKey.HIGH_RISK。
- [已確認] Slice 15-rental 新功能：Migration 0013（clients.lease_start/lease_end）、Migration 0014（workflow_tasks.engagement_id nullable）、欄位顯示控制（QMenu）、租約到期通知 dashboard 卡、任務不強制關聯案件。
- [已確認] ALLOWED_VARIABLES 現為 11 個（4 個未來欄位 payment_due_date / office_owner / reviewer / last_followed_up_at 已於 Slice 15 安全修正中移除）。
- [待確認] Supply Chain Locking = UNKNOWN / OPEN：pyproject.toml 中 PySide6、Jinja2、openpyxl、pytest、pyinstaller 均未 pin 版本。
- [已確認] 技術棧：Python 3.11+, PySide6, SQLite, SQLite FTS5, Jinja2, openpyxl, pytest, PyInstaller（Windows one-dir build + automated EXE smoke 已通過；人工 UI 驗收尚未完成）。

## Active Work

- [已確認] 2026-05-26 完成 Slice 21C：新 `ColumnSettings` helper widget（右鍵 header 選單 + 自動 persist hidden/widths）；8 個新 app_settings keys；4 表全接入（engagements/doc_requests/doc_items/tasks）；核心欄保護不可隱藏。9 個新測試。
- [已確認] 2026-05-26 完成 Slice 21B：EngagementsPage 重寫為 master-detail vertical split（上半案件清單、下半嵌入式 DocumentRequestsPage(embedded=True)）；sidebar 移除「索件管理」入口（NAV_ORDER 12→11）；main_window 不再 instance DocumentRequestsPage；DocumentRequestsPage 加 embedded 參數隱藏 back/combo；EngagementsPage 移除 _doc_btn 與 open_doc_requests signal。8 個新測試。
- [已確認] 2026-05-26 完成 Slice 21A：CreateDocumentRequestInput breaking API（`item_names` 取代 `use_vat_template`）；新 DocumentItemTemplateDialog 含 checklist + 自訂項目 + 持久化（per-tax-type）；DocumentRequestsPage 加批量刪除文件項目；conftest autouse mock 修 modal-exec hang。18 個新測試。Slice 21 系列開始（A 完成，B/C/D 進行中）。
- [已確認] 2026-05-25 完成 Slice 20C：RecurringBillingService.create_plan_with_lines atomic transaction；module-level parse_bulk_lines helper；PlanDialog 兩段佈局（合約資訊 + 固定開立明細 table）+ 批量貼上對話；ConfirmOccurrenceDialog 保留 expected vs confirmed amount；audit 一次記 plan + line_count。16 個新測試。Slice 20 系列（A/B/C）全部完成。
- [已確認] 2026-05-24 完成 Slice 20B：workflow_tasks 加 client_id nullable（migration 0017，含 backfill）；TasksService.create_task 從 engagement 自動同步 client_id；TasksPage / NewTaskDialog 客戶 + 案件 cascade；新增 list_by_client、client_exists、get_engagement_client_id helpers；20 個新測試。下一輪 Slice 20C（固定開立 UX 重設）。詳見 .ai/HANDOFF.md。
- [已確認] 2026-05-24 完成 Slice 20A：DocumentRequestsPage 加案件 combo（全部案件 / 指定案件兩段）、全域模式新增索件批次彈出 engagement picker 不再 silent return、item 操作後同步刷新 request table 且保留選取；新增 15 個 UI 行為測試。Slice 20A 屬上下文自主化系列，B（代辦客戶選擇）與 C（固定開立 UX 重設）尚未開始。詳見 .ai/HANDOFF.md。
- [已確認] 2026-05-23 完成 Slice 19A/B/C/D + hotfix v0.6.1：Dashboard filter 污染修復、各頁全域視圖、索件項目批量操作、附件刪除、固定開立新增入口；hotfix 補修 delete_item 未重算父層狀態 + 空 item 集誤判為 accepted。詳見下方 Slice 19 記錄。
- [已確認] EXE packaging 檔案已建立：`TaxOpsControlDesk.spec`, `build_tools/pyinstaller_entry.py`, `build_tools/clean_package.py`, `build_tools/package_windows.py`, `build_tools/smoke_test_exe.py`, `tests/test_packaging_tools.py`。
- [已確認] PyInstaller 入口曾因 `src/taxops/__main__.py` relative import 造成 EXE 假啟動但不建 DB；已改用 `build_tools/pyinstaller_entry.py` absolute import，並以 regression test 固定。
- [已確認] `python -m build_tools.package_windows` 已產出 `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`；`python -m build_tools.smoke_test_exe` 已驗證 EXE 啟動且在 temp `LOCALAPPDATA\TaxOpsControlDeskDev\taxops.sqlite` 建立 SQLite。
- [已確認] Slice 14 補完內容包含：`DashboardPage.navigate_to_page = Signal(str, str)`、`FilterKey` 常數、`MainWindow.navigate_to(page_id, filter_key="")`、三個目標頁 `set_filter()`、以及 tasks / engagements / review_notes 的 repository/service 篩選查詢。
- [已確認] Slice 14 `/simplify` 修正包含：`today_iso()` 取代 inline date、`FilterKey.*` 取代 raw filter string、`NAV_ORDER.index()` 不再轉成 list 後查找。
- [待驗證] Slice 2/3/4/4.5 真實 UI 互動（QFileDialog、QProgressDialog、下載進度、中文 QMessageBox、案件編輯、項目狀態切換）尚未在真實 Windows 桌面驗收。
- [待驗證] 客戶管理新功能（批量匯入、編輯、刪除、衝突審查對話框）尚未在真實 Windows 桌面驗收。
- [待優化] Bundle 匯出/匯入使用 in-memory CSV（StringIO），170 萬筆在開發機可跑；一般事務所低規硬體記憶體穩定性尚未驗證。

## MVP Scope

- [已確認] The MVP scope must include all items listed in section 24 of the source specification.
- [已確認] Implementation is phased internally, but MVP is not complete until every section 24 requirement is satisfied.

## Implemented

### Slice 1 — 基礎骨架
- [已確認] Schema: `schema_migrations`, `app_settings`, `clients`, `audit_logs`, `system_logs`.
- [已確認] Client minimal CRUD (create/list/get) + validation + audit trail + Chinese error labels.
- [已確認] Settings page: data-path, display-name, tax-cache settings skeleton.
- [已確認] 11 個導航項目。已實作頁面：dashboard、clients、engagements、doc_requests、tasks、templates、late_fee、review_notes、attachments、registry、settings（共 11 頁，無 placeholder）。registry 頁已完成（Slice 13）：本地快取查詢 + 套用至客戶主檔 diff dialog；GCIS 線上查詢保持 disabled。dashboard 頁已完成（Slice 14）：9 張真實統計卡片（含租約到期通知）。
- [已確認] UI action contract registry 為 visible button 唯一真相來源。
- [已確認] `.gitignore` 存在，排除 Python cache、build output、SQLite、attachments、cache bundles、`tmp/`。

### Slice 14 — Dashboard 控制台完整化（含篩選 + simplify，2026-05-17）
- [已確認] `src/taxops/repositories/dashboard.py`：`DashboardRepository`（8 個 COUNT 查詢方法，全部唯讀，參數化 SQL）。
- [已確認] `src/taxops/services/dashboard.py`：`DashboardCounts` frozen dataclass + `DashboardService.get_counts(today=None)`（today 可注入供測試）；`_UPCOMING_DAYS = 7`。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer` 新增 `dashboard: DashboardService`；`build_container()` 掛載。
- [已確認] `src/taxops/ui/pages/dashboard_page.py`：`DashboardPage`（8 張卡片 2 欄 QGridLayout）；`navigate_to_page = Signal(str, str)` —（page_id, filter_key）；`_CARD_DEFS` 5-tuple 含 `FilterKey.*` 常數；`_on_refresh()` 呼叫 `container.dashboard.get_counts()`；空 DB 顯示 0，不 hardcode。
- [已確認] `src/taxops/ui/main_window.py`：`navigate_to(page_id, filter_key="")` — 若 filter_key 非空則呼叫 `page.set_filter(filter_key)`；`NAV_ORDER.index()` 不再做多餘 list 轉型。
- [已確認] `src/taxops/ui/action_registry.py`：`FilterKey` class（DUE_TODAY / OVERDUE / UPCOMING / OPEN / HIGH_RISK）；4 個 PAGE_DASHBOARD enabled contracts（重新整理 / 前往待辦事項 / 前往覆核意見 / 前往案件管理）；無 disabled contracts。
- [已確認] `src/taxops/repositories/tasks.py`：新增 `list_due_today(today)` 唯讀查詢。
- [已確認] `src/taxops/repositories/engagements.py`：新增 `list_upcoming(today, until)` / `list_overdue(today)` 唯讀查詢。
- [已確認] `src/taxops/repositories/review_notes.py`：新增 `list_open_all()` / `list_high_risk_all()` 唯讀查詢。
- [已確認] `src/taxops/services/tasks.py`, `engagements.py`, `review_notes.py`：對應 wrapper 方法。
- [已確認] `src/taxops/ui/pages/tasks_page.py`：`set_filter(FilterKey)`；`_refresh()` 分支 due_today / overdue / 原 combo 邏輯；uses `today_iso()`。
- [已確認] `src/taxops/ui/pages/engagements_page.py`：`set_filter(FilterKey)`；`_refresh_engagements()` 分支 upcoming / overdue / 原 client 邏輯；uses `today_iso()`，`datetime.timedelta(days=7)` at module level。
- [已確認] `src/taxops/ui/pages/review_notes_page.py`：`set_filter(FilterKey)`；`_load()` 分支 open / high_risk / 原 engagement 邏輯。
- [confirmed] `tests/test_slice14_dashboard.py` (NEW): 31 tests - DashboardRepository (14), DashboardService (4), DashboardPage UI (8), action contracts (4); 636/636 passed.
- [已確認] 有明確 `FilterKey` 的 Dashboard 卡片會導向並套用篩選；`waiting_client` / `missing_item_requests` 目前 `filter_key=""`，僅誠實導向案件管理，不假裝已套用索件全局篩選；不可 hardcode 已由空 DB 回傳 0 測試驗證。

### Slice 2 — 稅籍快取離線匯入
- [已確認] 後端全閉環：registry parser, importer, bundle export/import, verify, matcher（`registry_match_results` schema）。
- [已確認] UI 5 個離線按鈕已啟用：`on_import_zip`, `on_import_bundle`, `on_export_bundle`, `on_verify_cache`, `on_regenerate_matches`。
- [已確認] ZIP guard：副檔名 `.zip` + 500 MB 大小上限。
- [已確認] 背景執行緒 fresh-connection pattern（QThread，threading.Thread smoke 驗證）。
- [已確認] `下載財政部稅籍資料` 仍 disabled（Slice 3）。
- [待驗證] QThread + QFileDialog + QProgressDialog 真實桌面互動。

### 客戶管理功能閉環（本 session 新增）
- [已確認] `src/taxops/services/clients_bulk.py`：批量匯入服務（Excel/CSV/貼上，欄位對應，驗證，寫入）。
- [已確認] `src/taxops/ui/dialogs/bulk_import_wizard.py`：6 步驟 QDialog 精靈，含 `_step_history` 正確 Back 導航。
- [已確認] `src/taxops/ui/dialogs/edit_client_dialog.py`：Edit client 對話框（先前實作；本 session 測試補齊）。
- [已確認] `src/taxops/ui/dialogs/mismatch_review_dialog.py`：衝突審查對話框（MismatchItem + 8 欄表格 + 採用/保留 checkbox）。
- [已確認] `src/taxops/ui/pages/clients_page.py`：新增編輯、刪除、批量匯入按鈕；雙擊列開啟 EditClientDialog。
- [已確認] `src/taxops/services/container.py`：ServiceContainer 新增 `clients_repo` 欄位。
- [已確認] `src/taxops/ui/action_registry.py`：新增 3 個 UIActionContract（儲存變更 / 刪除客戶 / 批量匯入）。
- [已確認] `src/taxops/ui/style.py`：全域 QSS + QPainter 產生 app icon（藍色圓角矩形 + 白色 "T"，64×64px）。
- [已確認] `src/taxops/ui/app.py`：啟動時呼叫 `apply_style(app)`。
- [已確認] `src/taxops/services/registry/matcher.py`：新增 `list_mismatches()` → 回傳所有 mismatch rows + client pairs。
- [已確認] `src/taxops/ui/pages/settings_page.py`：`on_regenerate_matches` 完成後詢問是否開衝突審查視窗，on Yes 開啟 MismatchReviewDialog。

### Slice 2.6 — 客戶管理與主框架可用性強化（2026-05-10）
- [已確認] `src/taxops/repositories/clients.py`：新增 `search_clients(query, order_by, order_dir, limit, offset)` + `count_clients(query)`；order_by 白名單保護防 SQL injection。
- [已確認] `src/taxops/services/clients.py`：新增 `search_clients()` + `count_clients()` pass-through；`list_clients()` 保留向後相容。
- [已確認] `src/taxops/ui/pages/clients_page.py`：加入搜尋列（QLineEdit + 搜尋/清除按鈕 + 總筆數 label）、欄位點擊排序（sectionClicked + setSortIndicator）、分頁導覽（◀上一頁 / 下一頁▶ + 第X–Y筆）；`_selected_client_id()` 永遠從 id 欄讀取，不用 row index。
- [已確認] `src/taxops/repositories/app_settings.py`：新增 `("ui.sidebar_collapsed", "0")` 到 DEFAULT_SETTINGS；ALLOWED_KEYS 自動包含。
- [已確認] `src/taxops/ui/main_window.py`：sidebar 包進 QWidget；上方加 QPushButton 收合/展開（◀/▶）；`_apply_collapsed()` + `_apply_expanded()` 讀寫 `ui.sidebar_collapsed` setting；重開後還原狀態。
- [已確認] `tests/test_slice26_clients_search.py`（NEW）：15 tests — count/search repo、sort/pagination、edit/delete client_id 安全、sidebar 設定種子與還原。

### 審計 — 已修復 HIGH 問題（本 session）
- [已確認] TOCTOU 競態：`import_validated` overwrite path 在 `find_by_code()` 回 None 時原本 fall-through 到 create；已補 `else: errors.append(...); skipped += 1; continue`。
- [已確認] MismatchReviewDialog `_on_apply()`：全部失敗時原本仍呼叫 `accept()`；已修正為 warning + `return`。
- [已確認] BulkImportWizard Back 導航：`_jump_to(4)` 後 Back 原本回 step 3（應跳過）；已改用 `_step_history` stack。

### 審計 — 已修復 MEDIUM 問題（後續 session）
- [已修復] `mismatch_review_dialog.py` `_parse_diffs()`：`_log.warning()` + 保守回 `{}`；補 `test_mismatch_dialog_malformed_diffs_json_returns_empty`。
- [已修復] `parse_excel()` / `parse_csv()` 無測試：補 `tests/test_clients_bulk_parse.py`（9 tests）。

### Slice 3 — HTTP 下載財政部稅籍資料（2026-05-10）
- [已確認] `src/taxops/services/registry_download.py`：`download_registry_zip(url, dest_path)` + `DownloadError`（含 network_error / io_error）。
- [已確認] `src/taxops/security/domains.py`：`is_allowed_official_url()` 驗證 HTTPS + allowlist 主機名。
- [已確認] `src/taxops/i18n/errors.py`：新增 3 個下載錯誤碼（not_allowed / network_error / io_error）。
- [已確認] `src/taxops/ui/pages/settings_page.py`：`on_download_registry()` 兩段確認（URL 確認 → 覆蓋確認）→ 背景下載+匯入 → audit；`_RegistryWorker.run()` 新增 DownloadError catch；`_set_slice2_buttons_enabled()` 同步禁用/啟用 `_download_btn`。
- [已確認] `src/taxops/ui/action_registry.py`：「下載財政部稅籍資料」改為 `enabled=True`，handler/service/audit_action 完整。
- [已確認] `tests/test_slice3_download.py`（NEW）：14 tests — allowlist 7 tests、DownloadError 2 tests、UI guard 3 tests、contract 2 tests。
- [已確認] 更新舊測試：`test_registry_cache_ui.py` + `test_settings_page_smoke.py` 改斷言按鈕已啟用。

### Slice 12 — FTS5 全文搜尋（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0012_fts5.py`：`fts_clients`（trigram, rowid=client.id, cols: client_code/client_name/tax_id/short_name/contact_name/note）+ `fts_engagements`（trigram, rowid=engagement.id, cols: engagement_name）；標準 FTS5 表（非 contentless）。
- [已確認] `src/taxops/repositories/search.py`：`SearchRepository`（add_client/update_client/delete_client/add_engagement/update_engagement/delete_engagement/search_client_ids/search_engagement_ids/rebuild_clients/rebuild_engagements）；`_fts_quote()` 防 SQL injection；刪除用 `DELETE FROM fts_... WHERE rowid=?`（而非 contentless 'delete' 命令）。
- [已確認] `src/taxops/services/search.py`：`SearchService`（search_clients/search_engagements/is_fts_eligible/rebuild_index）；`is_fts_eligible` → len(query.strip()) >= 3。
- [已確認] `src/taxops/services/clients.py`：新增 optional `search_repo: SearchRepository | None = None`；create_client→`_fts_add`；update_client→`_fts_update`；delete_client→`_fts_delete`；restore_client→`_fts_add`；所有 FTS 操作 try/except best-effort。
- [已確認] `src/taxops/services/engagements.py`：同上模式；create→`_fts_add`；update→`_fts_update`；delete→`_fts_delete`。
- [已確認] `src/taxops/services/container.py`：新增 `search: SearchService`；clients/engagements services 傳入 `search_repo`。
- [已確認] `src/taxops/ui/pages/clients_page.py`：`on_refresh()` query >= 3 chars 時使用 `container.search.search_clients()`；短查詢 fallback 原 LIKE 搜尋；FTS 結果仍使用 stable id（不用 row index）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_CLIENTS 新增「搜尋客戶」enabled contract。
- [已確認] `tests/test_fts5.py`（30 tests，含使用者補強）：FTS 表存在、新增可搜到、編輯舊詞消失/新詞可找、軟刪除不出現、中文子字串搜尋、6 種 injection 字串不爆、LIMIT 限制、engagement FTS、rebuild_index、is_fts_eligible、registry contract；並含 2 個使用者新增回歸測試（FTS update 的 INSERT 失敗時 rollback 舊索引仍保留、ClientsService FTS 失敗記 warning 不靜默）。
- [已確認] `tests/test_db_migrations.py`：EXPECTED_TABLES 加 fts_clients/fts_engagements；版本清單加 0012_fts5；count 11→12。
- [已確認] 使用者補強（2026-05-17）：`repositories/search.py` 所有 FTS 寫方法加 try/except → rollback → raise（防 DELETE 後 INSERT 失敗時半套狀態被後續 commit 提交）；`services/clients.py` 與 `services/engagements.py` FTS 失敗改為 `_log.warning(..., exc_info=True)`（不再靜默 pass）。
- [已確認] `python -m pytest` → **583/583 passed**（2026-05-17 Slice 12 + 使用者補強）。

### Slice 10 — Excel 匯出缺件清單（2026-05-17）

- [已確認] `src/taxops/security/csv_guard.py`：`safe_spreadsheet_cell(value)` — `value.lstrip()[0:1]` 偵測前導空白後公式頭（=, +, -, @），命中時原值前綴 `'`，不裁切空白。
- [已確認] `src/taxops/repositories/document_requests.py`：新增 `list_missing_items_for_export(engagement_id=None)` — 4 表 JOIN；item_status IN (missing, incomplete, invalid, pending_confirm)；LIMIT 100,000；支援按案件篩選；回傳 list[dict]。
- [已確認] `src/taxops/services/export.py`：`ExportService`（`ExportValidationError` + `export_missing_items_xlsx(output_path, engagement_id=None)`）；openpyxl 寫入 XLSX（header 粗體，工作表名「缺件清單」）；每格套 `safe_spreadsheet_cell`；audit `export.missing_items`；回傳 row count。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer` 新增 `export: ExportService`；`build_container()` 掛載。
- [已確認] `src/taxops/i18n/errors.py`：新增 `export.query_failed` / `export.save_failed` / `export.no_rows`。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「匯出缺件清單」按鈕 + `_on_export()` handler（QFileDialog.getSaveFileName + 完成筆數提示）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增 1 個 enabled contract（匯出缺件清單，audit_action=export.missing_items）。
- [已確認] `tests/test_export_security.py`（24 tests）：safe_spreadsheet_cell 前導空白/tab 注入、query filter、欄位完整性、engagement 篩選、XLSX 產出、formula injection 逃逸、audit、空結果 XLSX、UI handler 整合、action registry 合約。
- [已確認] `python -m pytest` → **536/536 passed**（2026-05-17）。

### Slice 9 — 附件證據鏈 MVP（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0010_attachments.py`：attachments（16 欄位含 FK→engagements/document_requests、SHA-256、stored_filename、status DEFAULT 'uploaded'、accepted_by/at）+ attachment_versions（attachment_id/supersedes_id）；3+1 索引。
- [已確認] `src/taxops/security/file_guard.py`：`MAX_FILE_SIZE=50MB`、`ALLOWED_EXTENSIONS`（10 種）、`BLOCKED_EXTENSIONS`（13 種）、`FileGuardError(code)`、`check_extension`/`check_file_size`/`resolve_safe_path`（path traversal 防護）/`sha256_file`（串流）。
- [已確認] `src/taxops/repositories/attachments.py`：`AttachmentRow`/`AttachmentVersionRow` frozen dataclass + `AttachmentsRepository`（7 方法含 engagement_exists）。
- [已確認] `src/taxops/services/attachments.py`：`AttachmentsService`；upload 流程：副檔名→大小→FK→sha256→uuid 路徑→copy2→insert→insert_version(supersedes_id=None)→audit；每個 mutation 均 audit（target_type="attachment"）。
- [已確認] `src/taxops/ui/pages/attachments_page.py`：`AttachmentsPage`（案件 combo/6 欄位表格/上傳/驗收/退回/資訊 dialog/開啟 disabled+tooltip）；`_AttachmentInfoDialog`（完整 metadata QFormLayout）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_ATTACHMENTS 新增 3 個 enabled contracts（新增附件/標記已驗收/標記退回）。
- [已確認] `tests/test_file_guard.py`（27 tests）+ `tests/test_attachments.py`（23 tests）+ `tests/test_slice9_ui.py`（12 tests）+ `tests/test_db_migrations.py` 更新至 0010。
- [已確認] `python -m pytest` → **512/512 passed**（2026-05-17 Slice 9 closeout correction）。

### Slice 7 — 產生催件訊息（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0007_generated_messages.py`：generated_messages 表（id/request_id/template_id/body/generated_at）+ idx_generated_messages_request 索引。
- [已確認] `src/taxops/repositories/generated_messages.py`：`GeneratedMessageRow` frozen dataclass + `GeneratedMessagesRepository`（insert/get/list_by_request）。
- [已確認] `src/taxops/services/generated_messages.py`：`GeneratedMessagesService`；`build_variables(request_id)` 從 doc_request + engagement + client + items 組裝 11 個 ALLOWED_VARIABLES（payment_due_date, office_owner, reviewer, last_followed_up_at 已於 Slice 15 安全修正中移除）；`generate()` render + insert + audit；TemplateValidationError → GeneratedMessageValidationError code 轉傳。
- [已確認] `src/taxops/ui/dialogs/generate_message_dialog.py`：`GenerateMessageDialog`（模板 QComboBox + 即時預覽 QTextEdit + 複製/儲存按鈕）；選模板時即時 render；save 後關閉 dialog。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「產生訊息」QPushButton；選取索件批次後 enabled；`_on_generate_message()` 開啟 GenerateMessageDialog。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增 1 個 enabled contract（產生訊息）。
- [已確認] `src/taxops/services/container.py`：新增 `gen_messages: GeneratedMessagesService` + build 連線。
- [已確認] `src/taxops/i18n/errors.py`：5 個 gen_message 錯誤碼（request_not_found / engagement_not_found / client_not_found / render_failed / save_failed）。
- [已確認] `tests/test_generated_messages.py`（15 tests，含 FK schema 驗證）+ `tests/test_slice7_ui.py`（10 tests，含 select→save→DB→audit 整合路徑）+ migration 更新至 7 版本 + generated_messages 表加入 EXPECTED_TABLES。
- [已確認] `python -m pytest` → **381/381 passed**（2026-05-17 closeout correction）。

### Slice 4 — 案件 + 索件後端（backend partial，2026-05-14）

- [已確認] Migration `0004_engagements`：3 表 7 索引（engagements, document_requests, document_request_items）；帶 `deleted_at` 軟刪除。
- [已確認] `src/taxops/repositories/engagements.py`：`EngagementRow` + `EngagementsRepository`（insert/get/list_by_client/count_by_client/update/update_status/delete/client_exists）。
- [已確認] `src/taxops/repositories/document_requests.py`：`DocumentRequestRow` + `DocumentRequestItemRow` + `DocumentRequestsRepository`（含原子批次 `insert_request_with_items` + `engagement_exists`）。
- [已確認] `src/taxops/services/engagements.py`：`EngagementsService` 含狀態轉換守衛（`_ALLOWED_TRANSITIONS`）+ FK 驗證（`engagement.client_not_found`）。
- [已確認] `src/taxops/services/document_requests.py`：`DocumentRequestsService` 含 item→request 狀態自動重算（`_derive_request_status`）+ FK 驗證（`doc_request.engagement_not_found`）。
- [已確認] `src/taxops/services/container.py`：新增 `engagements` + `doc_requests` 欄位與 build 連線。
- [已確認] `src/taxops/i18n/errors.py`：新增 engagement / doc_request / doc_request_item 系列錯誤碼。
- [已確認] `tests/test_engagements.py`（22 tests）、`tests/test_document_requests.py`（25 tests）：含 FK 驗證、transition guard、atomicity、5 種 recompute 情境。
- [已確認] `python -m pytest` → **230/230 passed**（2026-05-14 backend）。

### Slice 4.5 — 案件編輯 + 索件項目狀態 UI（2026-05-15）

- [已確認] `src/taxops/ui/dialogs/edit_engagement_dialog.py`（新建）：預填表單（名稱/稅種/期間/負責人/備註），`on_save()` 呼叫 `update_engagement()`，status 保持原值，audit `engagement.update`。
- [已確認] `src/taxops/ui/pages/engagements_page.py`：補「編輯案件」按鈕，無列選取時 disabled；`_on_edit_engagement()` 開啟 EditEngagementDialog，Accept 後 refresh。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：補「切換項目狀態」按鈕，無項目選取時 disabled；`_on_set_item_status()` 透過 `QInputDialog` 選擇新狀態，呼叫 `set_item_status()`，audit `doc_request_item.status_change`；`_on_item_selection_changed()` 管理按鈕 enabled 狀態。
- [已確認] `src/taxops/ui/action_registry.py`：新增 3 個 enabled contract（編輯案件、儲存編輯、切換項目狀態）。
- [已確認] `tests/test_slice45_ui.py`（9 tests）：預填驗證、DB+audit 閉環、按鈕 enabled/disabled；全通過。
- [已確認] `python -m pytest` → **257/257 passed**（2026-05-15）。

### Slice 4 — 案件 + 索件 UI（2026-05-14）

- [已確認] `src/taxops/ui/pages/engagements_page.py`：`EngagementsPage`，client combo filter + 案件列表 + 新增/切換狀態/刪除/管理索件批次；Signal `open_doc_requests(int)` 供 MainWindow 路由。
- [已確認] `src/taxops/ui/dialogs/new_engagement_dialog.py`：`NewEngagementDialog`，表單含案件名稱、稅種、期間、狀態、負責人、備註。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：`DocumentRequestsPage`，上半索件批次列表 + 下半文件項目表格（QSplitter），Signal `back_to_engagements()` 返回。
- [已確認] `src/taxops/ui/main_window.py`：新增 EngagementsPage / DocumentRequestsPage，`navigate_to()` + `_on_open_doc_requests()` 完成跨頁導航。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_ENGAGEMENTS 新增 5 個已啟用合約（新增案件/切換狀態/刪除案件/管理索件批次/建立案件），PAGE_DOC_REQUESTS 新增 4 個已啟用合約（新增索件批次/標記已發出/催件+1/刪除批次）。
- [已確認] `src/taxops/services/engagements.py`：新增 `valid_next_statuses(engagement_id)` 方法供 UI 取得有效狀態列表。
- [已確認] `tests/test_slice4_ui_smoke.py`：11 個 smoke test，覆蓋頁面實例化、按鈕存在、啟用/禁用預設。
- [已確認] `python -m pytest` → **241/241 passed**（2026-05-14 UI 閉環）。

## Not Implemented Yet

- [已確認] GCIS query（`data.gcis.nat.gov.tw` Swagger）仍 disabled（`此功能尚未開放`）。
- [已確認] backup/restore 已實作（Slice 11）。
- [已確認] FTS5 search 已實作（Slice 12）。
- [已確認] 安全測試（XSS/HTML injection, resource limits）仍部分未覆蓋（CSV formula injection 已由 test_export_security.py 覆蓋）。
- [已確認] PyInstaller EXE packaging pre-closeout 已完成: one-dir build + automated smoke 通過; 人工 UI checklist 仍待驗證.
- [待驗證] 真實 Windows 桌面驗收（1366×768, 1920×1080, 縮放 100%/125%/150%）尚未執行。

## Frozen / Do Not Change Casually

- [已確認] MVP 範圍必須包含來源規格第 24 節全部項目。
- [已確認] 不做 WSTP 備份讀取、不做自動申報、不做自動 LINE/Email。
- [已確認] 稅籍/工商來源使用官方開放資料；MVP 不爬財政部稅籍登記資料公示查詢頁。
- [已確認] 稅籍快取包不加密且不得包含客戶對照結果。
- [已確認] 單人本機模式，不做登入、角色或權限系統。
- [已確認] UI 方向以 `.ai/DESIGN.md` 為準；不複製品牌識別。

## UI Direction

- [已確認] UI 方向：高奢、簡潔、清楚明瞭；`.ai/DESIGN.md` 為實作權威。
- [已確認] 全域 QSS 已透過 `src/taxops/ui/style.py` + `app.py` 套用（深色 sidebar #1E293B，主色 #2563EB，底色 #F8FAFC）。
- [已確認] `/frontend-design` 和 `/huashu-design` skills 不存在（`~/.claude/skills/` 無此目錄）；UI 改善直接透過 `style.py` 實作。

## Known Bugs / Risks

- [已確認] 目前沒有已確認的測試失敗（583/583 passed）。
- [已修復] `bulk_import_wizard.py` raw exception 露出：已改 `error_message(exc.code)` + `_log.error()`。
- [已修復] `mismatch_review_dialog.py` raw exception 露出：已拆 `ClientValidationError` / generic，UI 顯示中文。
- [已修復] `_parse_diffs()` 靜默吞 JSON 錯誤：已改 `_log.warning()` + 保守回 `{}`。
- [已修復] `parse_excel()` / `parse_csv()` 無測試：已補 `tests/test_clients_bulk_parse.py`（9 tests）。
- [待改善] 兩個 dialog 的錯誤使用 Python `logging`，不是寫入 SQLite `system_logs`。嚴格符合 system log 規格需把 `SystemLogService` 傳進 dialog 或由 page 包裝記錄；不影響「不露 raw exception 給 UI」的目標。
- [待驗證] 真實 Windows 桌面渲染、縮放、hover tooltip、剪貼簿、開啟資料夾。
- [待驗證] PyInstaller EXE 人工 UI 驗收仍需確認字型、版面、對話框、QFileDialog、QProgressDialog、QMessageBox、真實下載流程與客戶 CRUD 持久化。

## Recommended Next Step

1. [建議] 真實 Windows 桌面驗收（Slice 2 五個按鈕 + 客戶管理：編輯、刪除、批量匯入、衝突審查）。
2. [待驗證] Slice 3（HTTP download + URL allowlist + 兩段確認 + GCIS query）。
3. [待改善] Dialog 錯誤改寫入 SQLite `system_logs`（目前用 Python `logging`）。
