# HANDOFF

## Latest Handoff Update (2026-05-26 — Slice 21C 欄位顯示控制 + 欄寬持久化, v0.12.0)

### 本輪完成事項

- [已確認] **新 `ColumnSettings` helper widget**（`src/taxops/ui/widgets/column_settings.py`）：對任意 QTableWidget 安裝右鍵 header 選單（per-col 顯示/隱藏 checkbox + 「自動調整所有欄寬」+ 「重設預設」），自動 persist 隱藏欄位 (CSV) 與欄寬 (JSON) 到 `app_settings`。核心欄（core_cols）checkbox 灰掉不可隱藏。
- [已確認] **8 個新 app_settings keys**：`ui.{engagements,doc_requests,doc_items,tasks}.{columns_hidden,column_widths}` 全部加入 DEFAULT_SETTINGS 並自動進入 ALLOWED_KEYS whitelist。
- [已確認] **4 個表格全部接入**：
  - EngagementsPage._table（table_id=engagements，core={engagement_name, status}）
  - DocumentRequestsPage._req_table（table_id=doc_requests，core={period_name, status}）
  - DocumentRequestsPage._item_table（table_id=doc_items，core={item_name, item_status}）
  - TasksPage._table（table_id=tasks，core={title, status}）
- [已確認] **欄寬 persist 機制**：QHeaderView.sectionResized signal → `_save_widths`；JSON 容量 480 字元安全上限（settings 500 字元上限），超過記 warning 不寫入。
- [已確認] **核心欄隱藏保護**：即使 `columns_hidden` 設定誤寫入核心欄 key，restore 階段會強制顯示（防止使用者意外把識別欄位藏掉）。

### 新增/修改檔案

- `src/taxops/ui/widgets/column_settings.py`（NEW）：`ColumnSettings` 類別含 install/restore/save_hidden/save_widths/menu handler。
- `src/taxops/repositories/app_settings.py`：DEFAULT_SETTINGS 加 8 個 keys。
- `src/taxops/ui/pages/engagements_page.py`：import + `_CORE_COLS` + `_col_settings`。
- `src/taxops/ui/pages/document_requests_page.py`：import + `_REQ_CORE_COLS` + `_ITEM_CORE_COLS` + `_req_col_settings` + `_item_col_settings`。
- `src/taxops/ui/pages/tasks_page.py`：import + `_CORE_COLS` + `_col_settings`。
- `tests/test_slice21c_column_settings.py`（NEW，9 tests）：helper unit (6) + page integration (3)。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.11.0 → 0.12.0。

### 下一輪注意事項

- Slice 21C 完整閉環，v0.12.0 穩定。
- **下一輪 Slice 21D（v0.13.0）— 待辦事項 parent/child + bulk CRUD**：
  - migration 0018 `workflow_tasks.parent_task_id INTEGER NULL REFERENCES workflow_tasks(id)` + 2-level depth check。
  - TasksService 新增 `convert_to_child(task_id, parent_id)`、`create_tasks_bulk(template, client_ids)`、`update_tasks_bulk(ids, fields)`、`delete_tasks_bulk(ids)`。
  - 3 個新對話：`BulkCreateTasksDialog`（client checkbox grid + template form）、`BulkEditTasksDialog`（4 個 per-field checkbox 套用 same change）、bulk delete two-step confirm。
  - TasksPage 加 multi-select (ExtendedSelection) + 一欄 checkbox + 全選 header + 單筆/多筆 按鈕互鎖。
  - Title 縮排前綴 `　└ ` 顯示子任務階層。
  - 子任務 client_id/engagement_id 繼承自父，禁止刪父若仍有子，允許「轉子任務」。

---

## Latest Handoff Update (2026-05-26 — Slice 21B 索件管理併入案件管理, v0.11.0)

### 本輪完成事項

- [已確認] **DocumentRequestsPage 新增 `embedded: bool = False` 構造參數**：當 True 時隱藏 `_back_btn`、`_context_label`、`_eng_combo_label`、`_engagement_combo`，外緣 margin 改 0。Standalone 模式（既有 Slice 4/4.5/19A/20A tests 直接構造）UI 完全保留。
- [已確認] **EngagementsPage 重寫為 master-detail vertical split**：
  - 上半：原本的客戶 combo + 案件 CRUD 工具列 + 案件列表（保留 Slice 14/19A/20A 已有的 client combo、filter_key 接口、refresh_context 邏輯）。
  - 下半：嵌入式 `DocumentRequestsPage(container, embedded=True)`，承接索件批次 + 文件項目 + 全部既有 Slice 21A 功能（VAT checklist、批量刪除等）。
  - 中間 QSplitter(Vertical)，stretch 因子 1:2，使用者可自行拖曳。
- [已確認] **選取案件即載入嵌入 widget**：`_on_selection_changed` → `_sync_embedded_to_selection`；row 選中 → `load_engagement(id)`；無選取 → `clear_filter()` + `refresh_context()`（全部案件視圖）。
- [已確認] **移除 sidebar 「索件管理」入口**：`NAV_ORDER` tuple 從 12 → 11 items；`PAGE_DOC_REQUESTS` 常數保留供 `action_registry.actions_for_page` contracts 使用。
- [已確認] **main_window 不再 instantiate DocumentRequestsPage**：移除 `elif page_id == PAGE_DOC_REQUESTS` 分支、`_on_open_doc_requests` 方法、`DocumentRequestsPage` import、`PAGE_DOC_REQUESTS` import；EngagementsPage 不再有 `open_doc_requests` Signal 與 `_doc_btn` 按鈕（polish — 不需要跨頁導航就不需要按鈕）。
- [已確認] **既有 test_slice4_ui_smoke 兩個 test 移除「管理索件批次」按鈕斷言**（按鈕已拿掉）。
- [已確認] **Standalone DocumentRequestsPage 行為完全保留**：Slice 4/4.5/19A/20A/21A 所有測試直接 `DocumentRequestsPage(container)` 構造仍然 work，且 combo / back button 可見。

### 新增/修改檔案

- `src/taxops/ui/pages/document_requests_page.py`：constructor 加 `embedded` flag；hide back_btn / context_label / engagement combo + label when True；margin 改 0。
- `src/taxops/ui/pages/engagements_page.py`（重寫）：QSplitter(Vertical) master-detail；移除 `open_doc_requests` Signal、`_doc_btn`、`_on_open_doc_requests`；新增 `_doc_requests_widget`、`_sync_embedded_to_selection`、`refresh_context` 同步嵌入 widget。
- `src/taxops/ui/action_registry.py`：`NAV_ORDER` 移除 `PAGE_DOC_REQUESTS`。
- `src/taxops/ui/main_window.py`：移除 `DocumentRequestsPage` import + `PAGE_DOC_REQUESTS` import + 對應 build branch + `_on_open_doc_requests` 方法 + `open_doc_requests.connect` 連線。
- `tests/test_slice21b_merged_engagements.py`（NEW，8 tests）：embedded widget 存在、隱藏 combo/back、selection sync、no-selection global view、nav_order 不含 doc_requests、action_registry contracts 保留、main_window 不路由 PAGE_DOC_REQUESTS。
- `tests/test_slice4_ui_smoke.py`：移除「管理索件批次」按鈕斷言（按鈕拿掉）。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.10.0 → 0.11.0。

### 下一輪注意事項

- Slice 21B 完整閉環，v0.11.0 穩定。Sidebar 從 12 → 11 items。
- **下一輪 Slice 21C（v0.12.0）— 欄位顯示控制 + 欄寬持久化**：4 表（案件、索件批次、文件項目、待辦）；right-click header 選單 + persist via app_settings（8 個新 settings key）；核心欄/可選欄 split per Grill #2.5。
- **再之後 Slice 21D（v0.13.0）— 待辦 parent/child + bulk CRUD 三件套**。

---

## Latest Handoff Update (2026-05-26 — Slice 21A 索件批次模板選擇 + 批量刪除, v0.10.0)

### 本輪完成事項

- [已確認] **Breaking API change**: `CreateDocumentRequestInput` 移除 `use_vat_template: bool`，新增 `item_names: tuple[str, ...] = ()`。Service create_request 直接用 `payload.item_names`，不再 hardcode VAT_ITEMS 查表。`VAT_ITEMS` 保留為 module-level 常數供 UI consume。
- [已確認] **新增 `DocumentItemTemplateDialog`**：建立索件批次時跳 checklist，列出 VAT_ITEMS 的 9 個 checkbox（預設全勾，保留舊行為），含「全選 / 全不選」按鈕、自訂項目 input + list、確定/取消。OK 鍵透過 `accept()` 持久化選擇到 `app_settings.ui.doc_request_template.vat`（JSON `{"checked": [...], "custom": [...]}`，500 字元上限）；下次再開自動還原。
- [已確認] **DocumentRequestsPage `_on_new_request` 流程**：picker engagement 後（全域）或直接（單案件）跳 template dialog → 選定後才呼叫 `create_request(item_names=...)`。取消對話 = 整個流程中止（不建空 doc_request）。
- [已確認] **批量刪除文件項目**：item_table 改 `ExtendedSelection`，toolbar 新增「批量刪除項目」按鈕（多筆選取時 enabled）。新 service `delete_items_bulk(item_ids: list[int]) -> int` 逐筆刪除、收集 affected request_ids、每個父 request 只重算狀態一次、單一 audit `doc_request_item.bulk_delete` 紀錄 `{"item_ids": [...], "deleted_count": N}`。
- [已確認] **新 app_settings key**：新增 `ui.doc_request_template.vat` 到 DEFAULT_SETTINGS（自動進入 ALLOWED_KEYS whitelist）。
- [已確認] **既有 12 個 `use_vat_template=True` 測試呼叫**全部改為 `item_names=VAT_ITEMS`。
- [已確認] **新 autouse fixture `_auto_mock_doc_item_template_dialog` in conftest.py**：對 `DocumentItemTemplateDialog.exec` patch 回傳 Accepted，讓 Slice 4/4.5/19A/20A 既有的 `_on_new_request()` 測試不會在 21A 之後因 modal exec 而 hang。21A 自己的 dialog tests 直接呼叫構造器與方法（不走 exec），不受影響。

### 新增/修改檔案

- `src/taxops/services/document_requests.py`：dataclass 改寫、`create_request` 用 `item_names`、新增 `delete_items_bulk()`。
- `src/taxops/ui/dialogs/document_item_template_dialog.py`（NEW）：完整 checklist 對話。
- `src/taxops/ui/pages/document_requests_page.py`：新 import、新 `_bulk_delete_items_btn` + handler、`_on_new_request` 改用 dialog、item_table ExtendedSelection、新 `_selected_item_ids` helper。
- `src/taxops/repositories/app_settings.py`：DEFAULT_SETTINGS 加 `ui.doc_request_template.vat`。
- `tests/test_slice21a_doc_request_template_and_bulk_delete.py`（NEW，18 tests）。
- `tests/test_document_requests.py`：12 個 caller 改為 `item_names=VAT_ITEMS`。
- `tests/conftest.py`：autouse fixture 修 modal-exec hang。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.9.0 → 0.10.0。

### 驗證紀錄

- **925/925 passed** in 930.17s（2026-05-26，含 18 個新 Slice 21A 測試）
- PyInstaller EXE build + smoke + hygiene
- `dist/TaxOpsControlDesk-v0.10.0-windows.zip`；v0.9.0 zip 已刪除

### 下一輪注意事項

- Slice 21A 完整閉環，v0.10.0 穩定。
- **下一輪 Slice 21B（v0.11.0）— 索件管理併入案件管理（master-detail vertical split）**：EngagementsPage 重寫為上下兩段 QSplitter；sidebar 移除 PAGE_DOC_REQUESTS；main_window 不再 instance DocumentRequestsPage；Dashboard 卡片已導 PAGE_ENGAGEMENTS 無需改；Tests 大改動。
- **再之後 Slice 21C（v0.12.0）— 欄位顯示控制 + 欄寬持久化**：4 表（合併後的案件/索件批次、文件項目、待辦）。
- **最後 Slice 21D（v0.13.0）— 待辦 parent/child + bulk CRUD 三件套**：migration 0018 self-FK，三個新對話，TasksPage multi-select 與 indented title display。

---

## Latest Handoff Update (2026-05-25 — Slice 20C 固定開立 UX 重設, v0.9.0)

### 本輪完成事項

- [已確認] **`create_plan_with_lines(plan_inp, lines_inp)` atomic transaction**：`RecurringBillingService` 新方法；驗證 plan 與每一條 line 後一次性透過 repo `insert_plan_with_lines` 寫入；任一錯誤（plan 驗證、line 驗證、DB 寫入）整批 rollback，不留半成品；audit 一次紀錄 `recurring_billing.plan.create_with_lines` 含 `line_count`。
- [已確認] **`parse_bulk_lines(text)` 純函式**：解析 tab 分隔的 bulk paste 文字（`bill_to\tamount\ttax_type\tdescription`），空行跳過、錯誤列回傳 `(行號, 訊息)` tuple；錯誤列不寫入 valid 列表（caller 決定是否整批中止）。Slice 20C policy：UI 任一錯誤就拒絕整批。
- [已確認] **`RecurringBillingRepository.insert_plan_with_lines(plan_dict, lines_list)` atomic 方法**：單一 sqlite transaction；try/except 包圍 + `self._conn.rollback()` on error 保證 plan 與 lines 一致。
- [已確認] **`PlanDialog` create-mode 重寫為兩段佈局**：上半 QGroupBox「合約資訊」（客戶、方案名、頻率、開立日、月份、起訖、提醒天數、合約編號、備註）；下半 QGroupBox「固定開立明細」含「新增列」「刪除選取列」「批量貼上」按鈕 + QTableWidget（4 欄：開立對象/金額/稅別/說明）。儲存時呼叫 `create_plan_with_lines` 原子。Edit-mode 保留原有 update_plan 流程。
- [已確認] **`_BulkPasteDialog` 二級彈窗**：QTextEdit 接受 tab 分隔輸入；OK 時 caller 呼叫 `parse_bulk_lines`、解析錯誤顯示行號清單（最多 20 行）並拒絕整批；解析成功則填入 lines table。
- [已確認] **Occurrence confirm 保留 expected vs confirmed 區別**：`ConfirmOccurrenceDialog` 預填合約 line.amount，使用者輸入實際金額；audit 紀錄 `confirmed_amount` 欄。新增 Slice 20C 測試驗證 audit detail JSON 含 `confirmed_amount`。
- [已確認] **i18n 新增** `recurring_billing.amount.invalid` 與 `recurring_billing.lines.empty` 兩個錯誤碼。

### 新增/修改檔案

- `src/taxops/services/recurring_billing.py`：新增 module-level `parse_bulk_lines()` + `RecurringBillingService.create_plan_with_lines()`。
- `src/taxops/repositories/recurring_billing.py`：新增 `insert_plan_with_lines()` atomic 方法（try/commit/except/rollback）。
- `src/taxops/i18n/errors.py`：兩個新錯誤碼。
- `src/taxops/ui/dialogs/recurring_billing_dialogs.py`（重寫 PlanDialog + 新增 _BulkPasteDialog）：兩段 QGroupBox 佈局 + lines table + 批量貼上 + 原子儲存；其餘三個 dialogs (LineDialog / ConfirmOccurrenceDialog / SkipOccurrenceDialog) 保留。
- `tests/test_slice20c_recurring_billing.py`（NEW，16 tests）：atomic create (5) + parse_bulk_lines (6) + confirm audit (1) + PlanDialog (4)。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.8.0 → 0.9.0。

### 驗證紀錄

- [已確認] `python -m pytest -q` → **907/907 passed**（2026-05-25，含 16 個新 Slice 20C 測試）。
- [已確認] `python -m build_tools.package_windows` → 成功；第一次因舊 EXE 進程鎖住 dist 失敗，已只關閉該 TaxOpsControlDesk.exe 後重跑成功。
- [已確認] `python -m build_tools.smoke_test_exe` → 成功；EXE 啟動且 temp LOCALAPPDATA 建立 SQLite。
- [已確認] `python -m build_tools.check_resource_hygiene` → 未列出 TaxOpsControlDesk / pytest / pyinstaller 殘留進程；TIME_WAIT = 15。
- [已確認] `dist/TaxOpsControlDesk-v0.9.0-windows.zip` 已重新壓縮（2026-05-25 22:12）；v0.8.0 zip 已刪除。
- [已確認] Codex review 修正 release 風險：`insert_plan_with_lines()` read-back check 不再使用 `assert`，改為明確 `RuntimeError`，避免 Python `-O` 移除防護。

### 下一輪注意事項

- Slice 20C 完整閉環，v0.9.0 穩定。Slice 20 系列（A/B/C 上下文自主化）全部完成。
- 下一輪可選方向：
  - **真實 Windows 桌面驗收**：v0.9.0 EXE 在 1366×768 / 1920×1080 / 125% / 150% DPI 下的手動 UI checklist；尤其新 PlanDialog 兩段佈局、bulk paste 對話、line table 編輯體驗。
  - **Traditional Chinese user manual**：`docs/user_manual_zh_tw.md` 已待寫項目；可從 dashboard、客戶管理、案件管理、索件、待辦、固定開立 6 大模組依序撰寫。
  - **GCIS 線上查詢**：需先查官方 API 文件，不靠記憶實作（DECISIONS.md 已記錄）。
  - **Supply Chain Locking**：pyproject.toml 中 PySide6 / Jinja2 / openpyxl / pytest / pyinstaller 全未 pin；正式交付前應 pin。
- 不要把 `create_plan` 舊單行流程移除 — 它仍用於 EDIT mode 與 LineDialog 個別新增明細；`create_plan_with_lines` 只是新增的「create-with-lines」並行 API。

---

## Latest Handoff Update (2026-05-24 — Slice 20B 代辦事項客戶選擇, v0.8.0)

### 本輪完成事項

- [已確認] **Migration 0017_workflow_tasks_client_id**：`ALTER TABLE workflow_tasks ADD COLUMN client_id INTEGER REFERENCES clients(id)`；UPDATE backfill 從 `engagements.client_id` 回填既有 task 行（idempotent）；新增 index `idx_workflow_tasks_client`。
- [已確認] **TaskRow 加 client_id 欄**：`repositories/tasks.py` 的 `TaskRow` dataclass 加 `client_id: int | None`；`_row_to_task` 同步；`insert()` 接受 client_id；新增 `get_engagement_client_id(engagement_id)`、`client_exists(client_id)`、`list_by_client(client_id, ...)` 三個 helper 方法。
- [已確認] **TasksService.create_task client_id 自動同步**：若 `engagement_id` 提供，從 `get_engagement_client_id()` 取得 client_id 並覆寫任何 caller 提供的 client_id（engagement 為單一真相來源）；若僅 client_id 提供，先驗證 `client_exists` 否則 raise `task.client_not_found`；兩者皆 None 時建立完全獨立的 task。audit log detail 追加 client_id 欄。
- [已確認] **TasksService.list_by_client(client_id)** 新方法：回傳該 client 所有任務（含 engagement-bound 與只綁 client 的）。
- [已確認] **i18n 新增 `task.client_not_found = "找不到指定客戶，待辦無法建立"`**。
- [已確認] **TasksPage 客戶+案件 cascade**：新增 `_client_combo`（全部客戶 + 全部 active clients）；`_eng_combo` 依 client 選取重新載入（list_by_client / list_all）；三段 filter 邏輯：DUE_TODAY/OVERDUE filter_key → list_due_today/list_overdue；指定案件 → list_by_engagement；指定客戶 + 全部案件 → list_by_client；全部 → list_all。`refresh_context()` 同時 reload client + engagement combos，可看到新建客戶。
- [已確認] **NewTaskDialog cascade**：新增 `clients_service` + `preset_client_id` 參數；fixed engagement mode 保留（無 combos）；cascade mode 顯示「關聯客戶」combo（含「不指定客戶」哨兵 `_NO_CLIENT = -1`）+ 「關聯案件」combo（含「不綁案件」哨兵 `_NO_ENGAGEMENT = -1`）。`on_save()` 依 combo 值組裝 `CreateTaskInput.engagement_id` 與 `client_id`，service 層負責同步。
- [已確認] **test_slice5_ui.py _FakeContainer 補 dependencies**：加 `system_log` + `clients` services，符合 Slice 20B 的 TasksPage 新依賴。

### 新增/修改檔案

- `src/taxops/db/migrations/_m0017_workflow_tasks_client_id.py`（NEW）：ALTER TABLE + UPDATE backfill + CREATE INDEX。
- `src/taxops/db/migrations/__init__.py`：註冊新 migration。
- `src/taxops/repositories/tasks.py`：`TaskRow.client_id`、`_row_to_task` mapping、`insert(... client_id=None)`、`get_engagement_client_id()`、`client_exists()`、`list_by_client()`。
- `src/taxops/services/tasks.py`：`CreateTaskInput.client_id` 欄、`create_task` client_id 自動同步邏輯、`list_by_client()` wrapper。
- `src/taxops/i18n/errors.py`：`task.client_not_found` 中文錯誤碼。
- `src/taxops/ui/pages/tasks_page.py`（重寫）：客戶 combo + 案件 combo cascade、三段 filter、`refresh_context()` 同步 reload。
- `src/taxops/ui/dialogs/new_task_dialog.py`（重寫）：cascade UI、fixed engagement mode 保留、客戶 + 案件 sentinels。
- `tests/test_slice20b_tasks_client.py`（NEW，20 tests）：schema / backfill / service / list_by_client / TasksPage cascade / NewTaskDialog cascade。
- `tests/test_db_migrations.py`：versions list 追加 0017，count 16→17。
- `tests/test_slice5_ui.py`：`_FakeContainer` 加 system_log + clients。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.7.0 → 0.8.0。

### 驗證紀錄

- **891/891 passed** in 831.68s（2026-05-24，含 20 個新 Slice 20B 測試）
- PyInstaller EXE build 成功、smoke 通過、hygiene 無殘留
- `dist/TaxOpsControlDesk-v0.8.0-windows.zip`；v0.7.0 zip 已刪除

### 下一輪注意事項

- Slice 20B 完整閉環，v0.8.0 穩定。
- **下一輪實作 Slice 20C — 固定開立 UX 重設**（v0.9.0）：
  - service `create_plan_with_lines(plan_payload, lines_payload)` 原子 transaction：建 plan + 多 line 同時建，任一失敗 rollback；audit 一次紀錄 plan + line_count。
  - `PlanDialog` 改成兩段：上半合約資訊（客戶、方案名、頻率、起訖、提醒天數、合約編號）；下半 line table 可新增多列（開立對象、金額、稅別、說明）。
  - bulk paste 支援：tab 分隔 `開立對象\t金額\t稅別\t說明`，每列驗證並顯示行號錯誤訊息；任一錯誤不寫 DB（全 rollback）。
  - Occurrence confirm 流程保留 expected vs confirmed amount 區別；audit 紀錄兩個值。
- 不要把 `workflow_tasks.client_id` 改回 NOT NULL — Slice 20B 設計支援「不綁客戶也不綁案件」的獨立 task。

---

## Latest Handoff Update (2026-05-24 — Slice 20A 索件管理上下文自主化, v0.7.0)

### 本輪完成事項

- [已確認] **DocumentRequestsPage 新增案件 combo**：頁面頂部新增案件篩選 combo（第一項「全部案件」+ 全部 active engagements），label 格式「客戶名 — 案件名 — 期別」；切換 combo 立即刷新索件列表，使用者不需要回案件管理頁。
- [已確認] **全域模式新增索件批次不再 silent return**：原 `_on_new_request()` 在 `_engagement_id is None` 時 silent return；現改為彈出 `QInputDialog.getItem` engagement picker；無 engagement 時顯示 info dialog 引導使用者先建案件。選定案件後自動切到該案件視圖。
- [已確認] **item 操作後同步刷新父層 request 表**：`_on_edit_item` / `_on_set_item_status` / `_on_delete_item` 均改為呼叫 `_refresh_requests()`（含 `_fill_request_table` 的選取保留邏輯），並強制 `_load_items_for_selected()` 以確保 item 表也更新；保留原本選取的 request 行，避免刷新後跳掉。
- [已確認] **錯誤處理升級**：所有 mutation 路徑的 catch-all 改為 `system_log.error(...)` + QMessageBox，不再 silent return；新增 picker 失敗 / engagement 不存在 / 無案件三種情境均顯示中文訊息。
- [已確認] **新增索件批次 / 匯出按鈕 always enabled**：兩者都不再依賴 `_engagement_id`（picker 與 global export 已能處理 None 情境）；舊「load 前 disabled」smoke test 已配套更新為「只對 row-dependent 按鈕做斷言」。

### 新增/修改檔案

- `src/taxops/ui/pages/document_requests_page.py`（重寫）：新增 `_ALL_ENGAGEMENTS = -1`、`_engagement_combo`、`_populate_engagement_combo()`、`_on_engagement_combo_changed()`、`_render_current_view()` / `_render_global_view()` / `_render_engagement_view()`、`_pick_engagement_id()`、`_fill_request_table(reqs, saved_req_id)`（含選取保留）。
- `tests/test_slice20a_doc_requests_context.py`（NEW，15 tests）：combo presence / label format / switch / global new request picker / item refresh sync / preserve selection / clear_filter 回 global。
- `tests/test_slice4_ui_smoke.py`：`test_document_requests_page_buttons_disabled_before_load` 移除 過時的「新增索件批次 disabled」斷言（Slice 20A 已合理化為 always enabled）。
- `pyproject.toml` + `src/taxops/__init__.py`：版號 0.6.1 → 0.7.0。

### 驗證紀錄

- **871/871 passed** in 852.33s（2026-05-24，含 15 個新 Slice 20A 測試）
- PyInstaller EXE build 成功（`dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`，6.9 MB）
- `python -m build_tools.smoke_test_exe` 通過：EXE 啟動且建立 SQLite 於 temp `LOCALAPPDATA\TaxOpsControlDeskDev`
- `python -m build_tools.check_resource_hygiene` 通過：無 TaxOps/pytest/pyinstaller 殘留進程
- `dist/TaxOpsControlDesk-v0.7.0-windows.zip`（70 MB）；v0.6.1 zip 已刪除

### 下一輪注意事項

- Slice 20A 完整閉環，v0.7.0 穩定。
- **下一輪建議實作 Slice 20B — 代辦事項客戶選擇**：
  - migration 0015 加 `workflow_tasks.client_id INTEGER NULL`（含 FK→clients.id）
  - 若 task 綁 `engagement_id`，service 層 `create_task` 自動同步 `client_id` 為該 engagement.client_id
  - `TasksPage` 加客戶 combo（全部客戶 / 指定客戶 / 指定客戶下指定案件三段過濾）
  - `NewTaskDialog` 加客戶 combo（過濾案件 combo），支援「不綁案件，只綁客戶」
  - 舊資料 migration 填回 `client_id`（engagement_id 不為 null 的情況）
- **再之後 Slice 20C — 固定開立 UX 重設**：
  - service `create_plan_with_lines()` 原子 transaction（plan + 多 line 同時建，任一失敗 rollback）
  - `PlanDialog` 兩段（合約資訊 + 多筆明細 table）
  - bulk paste 支援（行格式 `開立對象\t金額\t稅別\t說明`，錯誤列顯示行號不部分成功）
  - Occurrence confirm 保留 expected_amount → confirmed_amount 核定流程
- 不要把「新增索件批次」按鈕還原為「load 前 disabled」— 那是 Slice 20A 修復的 SLOP 之一。

---

## Latest Handoff Update (2026-05-23 — Slice 19 hotfix, v0.6.1)

### 本輪完成事項

- [已確認] **`_derive_request_status()` 空集合防衛**：`frozenset().issubset(任何集合)` 恆為 True，導致刪完所有 items 後 request status 誤判 "accepted"。已在函數頂部加 `if not statuses: return "requested"` guard。
- [已確認] **`delete_item()` 重算父層狀態**：原本 `delete_item()` 僅刪除 item 並記 audit，不更新父層 document_request.status。現在補呼叫 `_recompute_request_status()` + `update_request_status()`。
- [已確認] **test_document_requests.py 補 2 個測試**：`test_delete_item_recomputes_request_status`、`test_delete_all_items_returns_request_to_requested_not_accepted`。
- [已確認] **test_slice19d_recurring_billing.py 補 2 個行為測試**：全部客戶 → info dialog；指定客戶 → PlanDialog.exec。
- [已確認] **版本號統一**：pyproject.toml + __init__.py = 0.6.1；git tag v0.6.1。
- [已確認] **dist zip**：`dist/TaxOpsControlDesk-v0.6.1-windows.zip`（71 MB）；v0.6.0 zip 已刪除。

### 驗證紀錄

- **856/856 passed** in 835.51s（2026-05-23）。
- EXE build + smoke test + hygiene check 全部通過。

### 下一輪注意事項

- Slice 19 hotfix 完整閉環，v0.6.1 穩定。
- 可進行下一個新 Slice。

---

## Latest Handoff Update (2026-05-21 — three correctness fixes, v0.5.0 final)

### 本輪完成事項

- [已確認] **DateField.InvalidInput + validated_value()**：新增 `DateField.InvalidInput` exception class；`validated_value()` 方法對非空但無效的輸入直接 raise 並設置 inline error label，不再靜默回傳 None。
- [已確認] **6 個 consumer 更新**：`new_client_dialog`、`edit_client_dialog`、`new_engagement_dialog`、`edit_engagement_dialog`、`new_task_dialog`、`late_fee_page._on_calculate()` 全部改用 `validated_value()`，catch `InvalidInput` 後 re-enable 保存按鈕並 return。
- [已確認] **滯納金反向日期不再是假成功**：`calculate_overdue_days()` 移除 `max(..., 0)`，反向日期（actual < last）直接 raise `late_fee.date.range_invalid`；`calculate_and_save()` 改呼叫 `calculate_overdue_days()`，反向日期不寫 DB。
- [已確認] **新錯誤碼**：`late_fee.date.range_invalid` = "實際繳款日不可早於最後繳款日，請確認日期輸入" 加入 `i18n/errors.py`。
- [已確認] **版本號統一**：`pyproject.toml` → `0.5.0`；`src/taxops/__init__.py` → `0.5.0`；git tag `v0.5.0` 指向最新 commit `7d370d4`。
- [已確認] **EXE 重建**：`dist/TaxOpsControlDesk-v0.5.0-windows.zip` 重新打包（含所有 DateField 與 validated_value 修正）。

### 驗證紀錄

- [已確認] `python -m compileall -q src tests` 無語法錯誤。
- [已確認] `python -m pytest tests/test_date_field.py tests/test_late_fee.py tests/test_clients.py tests/test_engagements.py tests/test_tasks.py -q` → 172/172 passed。
- [已確認] `python -m pytest tests/test_ui_regressions.py tests/test_slice8_ui.py -q` → 19/19 passed。
- [已確認] `python -m pytest -q` 全套執行中（結果待確認）。
- [已確認] EXE smoke test 通過。

### 行為保證

- optional DateField 空白 → `validated_value()` 回傳 None（合法）。
- 手打 "not-a-date" → `validated_value()` raise InvalidInput，error label 顯示，保存按鈕 re-enabled，DB 不寫入。
- actual_payment_date = last_payment_date → 0 天（合法）。
- actual_payment_date < last_payment_date → raise `late_fee.date.range_invalid`，DB 0 rows。

### 下一輪注意事項

- `value()` 仍保留舊語義（空/invalid 都回傳 None）——用於唯讀顯示；儲存路徑必須用 `validated_value()`。
- 若新增日期欄位的 dialog/page，save 路徑一定用 `validated_value()`，不得用 `value()`。

---

## Latest Handoff Update (2026-05-21 — DateField SLOP refactor + date validation)

### 本輪完成事項

- [已確認] **DateField widget** (`src/taxops/ui/widgets/date_field.py`)：取代所有 sentinel 日期（1752/1900/2000-01-01/minimumDate）邏輯；提供 `required=True`（預設今天，無清除鈕）及 `required=False`（空白，有清除鈕，value=None）兩種模式。
- [已確認] **sentinel 清除**：`_shared.py` 移除 `_SENTINEL_DATE`、`_YearJumpCalendar`、`make_nullable_date_edit()`、`date_edit_value()`、`set_date_edit_value()`；現在只含 `TAX_TYPE_CHOICES`。
- [已確認] **6 個 consumer 更新**：`edit_client_dialog.py`、`new_client_dialog.py`、`edit_engagement_dialog.py`、`new_engagement_dialog.py`、`new_task_dialog.py`、`late_fee_page.py` 全部改用 `DateField`。
- [已確認] **日期集中驗證**：`src/taxops/core/dates.py`（新增）：`parse_optional_iso_date()` 和 `date_range_is_valid()`，被 ClientsService / EngagementsService / DocumentRequestsService / LateFeeService 使用。
- [已確認] **error codes 新增**：`client.lease_date.invalid`、`client.lease_range.invalid`、`engagement.due_date.invalid`、`doc_request.due_date.invalid`、`late_fee.date.required_pair`。
- [已確認] **LateFeeService**：只給一個日期（last 或 actual）直接 raise `late_fee.date.required_pair`；反向日期（actual < last）明確回傳 overdue_days=0 不掩蓋輸入錯誤。
- [已確認] **tests/test_date_field.py**（新增，46 tests）：涵蓋 optional/required 初始狀態、2000-01-01 真實日期、clear/set_error API、sentinel 缺席稽核、所有 dialog 構造、calendar popup 行為、late_fee service pair 驗證。
- [已確認] **tests/test_dates.py**（新增，14 tests）：核心日期 parser 與 range 驗證。
- [已確認] **tests/test_ui_regressions.py**：舊 sentinel 測試替換為 DateField 等效測試。

### 驗證紀錄

- [已確認] `python -m compileall -q src tests` 無語法錯誤。
- [已確認] `python -m pytest tests/test_dates.py tests/test_date_field.py -v` 46/46 passed。
- [已確認] `python -m pytest tests/test_clients.py tests/test_engagements.py tests/test_document_requests.py tests/test_late_fee.py -q` 118/118 passed。
- [已確認] `python -m pytest tests/test_slice4_ui_smoke.py tests/test_slice45_ui.py tests/test_slice5_ui.py tests/test_ui_regressions.py -q` 45/45 passed。
- [已確認] sentinel grep：src/ 無 `_SENTINEL_DATE` 或 `make_nullable_date_edit` 殘留。

### 仍待驗證

- [待驗證] EXE rebuild（PyInstaller）尚未在本輪執行；需重新打包。
- [待驗證] 真實 Windows 桌面 DateField 操作：日曆彈出、年份跳轉、DPI 125%/150%、1366x768 popup 不超出螢幕邊界。

### 下一輪注意事項

- DateField API：`value()` 回傳 ISO str 或 None；`raw_text()` 保留原始輸入；不得靜默清除。
- 新增任何日期欄位必須使用 `DateField`；禁止 `QDateEdit` + sentinel 模式。
- `core/dates.py` 是所有日期 parse/validate 唯一入口；service 層不得自行 try/except fromisoformat。

---

## Latest Handoff Update (2026-05-17 — Resource hygiene closeout + 643/643 passed)

### 本輪完成事項

- [已確認] 完成「開發/測試造成網路異常、port 被佔用、進程殘留、socket 耗盡」專項修復閉環。
- [已確認] `src/taxops/services/registry_download.py`：非預期 download stream 例外也會清掉 `*.part`，再原樣拋出例外。
- [已確認] `src/taxops/ui/pages/settings_page.py`：QThread worker 在 success/error slot 結束時呼叫 `worker.deleteLater()`，補明確 QObject cleanup。
- [已確認] `build_tools/check_resource_hygiene.py`（NEW）：固定輸出 TaxOps/PyTest/PyInstaller 相關進程、TCP state counts、Listen ports；只檢查，不自動 kill。
- [已確認] `tests/test_slice3_download.py`：新增 timeout 傳遞與 unexpected read error `.part` cleanup regression tests。
- [已確認] `tests/test_resource_cleanup.py`：新增 QThread cleanup hook 與 resource hygiene script regression tests。
- [已確認] `.ai/RESOURCE_CLEANUP_AUDIT.md` 已加入本輪 Root Cause / Impact / Fix Strategy / Verification / Evidence。

### 驗證紀錄

- [已確認] `python -m pytest tests/test_resource_cleanup.py tests/test_slice3_download.py tests/test_packaging_tools.py -q` => 29 passed in 11.16s。
- [已確認] `python -m pytest -x --tb=short` => 643 passed in 585.37s。
- [已確認] `python -m build_tools.check_resource_hygiene` 已執行；未列出 TaxOpsControlDesk / pytest / pyinstaller 殘留進程，僅列出巡檢命令自身 Python process。
- [已確認] 測後 TCP states：Bound=35, CloseWait=2, Established=30, Listen=33, TimeWait=18。未見 TIME_WAIT 異常爆量。

### 仍待驗證

- [待驗證] 真實 Windows 桌面連續操作 QThread / QFileDialog / QProgressDialog / QMessageBox 的長時間資源表現。
- [待驗證] 真實官方 BGMOPEN1.zip 線上下載在慢速網路、斷線、代理/防毒攔截下的人工驗收。

### 下一輪注意事項

- 開工前先讀 `.ai/RESOURCE_CLEANUP_AUDIT.md`。
- 跑完整測試或 EXE smoke 後，執行 `python -m build_tools.check_resource_hygiene` 並把 process/TCP/listen port 摘要寫入 handoff。
- 不要殺掉未證明由本輪測試建立的 chrome/node/其他系統進程。

---

## Latest Handoff Update (2026-05-17 — Windows EXE packaging pre-closeout + 639/639 passed)

### 本輪完成事項

- [已確認] `TaxOpsControlDesk.spec` 已建立並可用 PyInstaller 6.11.1 產出 one-dir build：`dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`。
- [已確認] `build_tools/clean_package.py`：清理 `build/`, `dist/TaxOpsControlDesk/`, `__pycache__/`, `*.pyc`, `*.pyo`, `*.spec.bak`，不碰資料庫、附件、cache bundle、source、docs。
- [已確認] `build_tools/package_windows.py`：執行 `python -m PyInstaller TaxOpsControlDesk.spec --noconfirm --clean`，並確認 EXE 存在。
- [已確認] `build_tools/smoke_test_exe.py`：用 temp `LOCALAPPDATA` + `TAXOPS_DEV=1` 啟動 EXE，確認 process alive 與 SQLite 建立，最後 terminate/kill 並 wait。
- [已確認] 修正 PyInstaller entrypoint：原 spec 指向 `src/taxops/__main__.py` 時會因 relative import 造成 windowed EXE 假啟動但不建 DB；已新增 `build_tools/pyinstaller_entry.py` 使用 `from taxops.ui.app import run` absolute import。
- [已確認] `tests/test_packaging_tools.py` 新增 3 個 regression tests，避免 spec 回退到 relative-import entrypoint，並確認 smoke test force-kill 後會 wait。
- [已確認] 驗證結果：`python -m build_tools.package_windows` 成功；`python -m build_tools.smoke_test_exe` 成功；`python -m pytest -x --tb=short` => **639/639 passed**。
- [已確認] 測後無 `TaxOpsControlDesk` / `python` / `pytest` / `pyinstaller` 殘留進程；TCP 狀態檢查：TIME_WAIT=39, CloseWait=1（未見測試殘留進程）。

### 仍待驗證

- [待驗證] 人工 Windows UI checklist 尚未完成：主視窗標題、11 個繁中導覽、sidebar 收合/展開、設定頁路徑按鈕、客戶新增持久化、audit log、無假資料、1366x768 + 125%/150% DPI。
- [待驗證] 正式 production data root（未設 `TAXOPS_DEV`）尚未以人工方式確認；automated smoke 目前只測 temp `LOCALAPPDATA` + dev root。
- [待驗證] GCIS 線上查詢仍 disabled，需查官方文件後才能實作。

### 下一輪優先任務

1. 依 `build_tools.smoke_test_exe` 印出的 manual checklist 做真實 Windows UI 驗收。
2. 補 `docs/user_manual_zh_tw.md`，只記錄已實作且已驗證功能。
3. 若要做 GCIS 線上查詢，先查官方 API 文件，不靠記憶實作。

---

## Latest Handoff Update (2026-05-17 — Slice 14 Dashboard 篩選補完 + /simplify 修正 + 636/636 passed)

### Slice 14 篩選補完 + /simplify 修正

- [已確認] `navigate_to_page = Signal(str, str)` — (page_id, filter_key)；`_CARD_DEFS` 改為 5-tuple 含 `FilterKey.*`。
- [已確認] `action_registry.py`：新增 `FilterKey` class（DUE_TODAY / OVERDUE / UPCOMING / OPEN / HIGH_RISK）；移除"前往案件索件" PAGE_DASHBOARD contract（已改為"前往案件管理"）。
- [已確認] `waiting_client` 和 `missing_item_requests` 卡片改指向 `PAGE_ENGAGEMENTS`（`DocumentRequestsPage` 需要 engagement context，無法做全局篩選）。
- [已確認] `TasksPage.set_filter(FilterKey)`, `EngagementsPage.set_filter(FilterKey)`, `ReviewNotesPage.set_filter(FilterKey)` 三個頁面新增篩選接口。
- [已確認] Repos 新增：`tasks.list_due_today`, `engagements.list_upcoming/list_overdue`, `review_notes.list_open_all/list_high_risk_all`；對應 service wrappers。
- [已確認] `MainWindow.navigate_to(page_id, filter_key="")` 在 filter_key 非空時呼叫 `page.set_filter()`。
- [已確認] `/simplify` 修正：`today_iso()` 取代 inline datetime；`import datetime` 移至 module level；`NAV_ORDER.index()` 不再轉 list；raw filter strings 改用 `FilterKey.*`。
- [已確認] `python -m pytest` → **636/636 passed**（2026-05-17）。

### 關鍵注意事項（給下一個 Agent）

- `FilterKey.DUE_TODAY = "due_today"` 等；比對時用 `== FilterKey.X`，不要用 raw string。
- `waiting_client` / `missing_item_requests` 兩張卡片 filter_key=""（誠實導向 PAGE_ENGAGEMENTS，不假裝有篩選）。
- `DocumentRequestsPage` 需 `load_engagement(id)` 才能顯示；後續若要做全局 doc_requests 視圖需另開新頁。
- "upcoming" branch：`today = today_iso()`，`until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=7)).isoformat()`（避免午夜邊界問題）。

### 下一輪優先任務

1. **Windows EXE packaging**（PyInstaller，Section 24 必要項目）。
2. **Traditional Chinese user manual**（`docs/user_manual_zh_tw.md`）。
3. **GCIS 線上查詢**（需查官方 API 文件後才可實作，目前 disabled）。

---

## Latest Handoff Update (2026-05-17 — Slice 14 Dashboard 控制台完整化 + 636/636 passed)

### Slice 14 完成事項（控制台 8 張真實統計卡片）

- [已確認] `src/taxops/repositories/dashboard.py`（NEW）：`DashboardRepository` — 8 個 COUNT 查詢（tasks due today / overdue / waiting_client workflow tasks / open review notes / missing item requests / upcoming engagements / overdue engagements / high risk engagements）；全部唯讀參數化 SQL；today/overdue 邊界：`due_date < today` 為逾期，`due_date = today` 為今日。
- [已確認] `src/taxops/services/dashboard.py`（NEW）：`DashboardCounts` frozen dataclass + `DashboardService.get_counts(today=None)`；`_UPCOMING_DAYS = 7`；`today` 可注入供測試；upcoming window = [today, today+7]（含兩端）。
- [已確認] `src/taxops/services/container.py`：新增 `dashboard: DashboardService` 欄位；`build_container()` 掛載。
- [已確認] `src/taxops/ui/pages/dashboard_page.py` (NEW): `DashboardPage`; this older Slice 14 record was superseded by the filtering supplement above, where `navigate_to_page = Signal(str, str)`.
- [已確認] `src/taxops/ui/main_window.py`：新增 `PAGE_DASHBOARD` + `DashboardPage` import；`_build_pages()` 新增 `elif page_id == PAGE_DASHBOARD`；連接 `navigate_to_page.connect(self.navigate_to)`。
- [已確認] `src/taxops/ui/action_registry.py`：新增 5 個 PAGE_DASHBOARD enabled contracts（重新整理 / 前往待辦事項 / 前往案件索件 / 前往覆核意見 / 前往案件管理）；移除舊 `_disabled("重新整理", PAGE_DASHBOARD)` stub。
- [confirmed] `tests/test_slice14_dashboard.py` (NEW): 31 tests - Repository (14), Service (4), UI (8), contracts (4).
- [已確認] `python -m pytest` → **636/636 passed**（2026-05-17）；無 python/pytest 殘留；TIME_WAIT = 8。

### 關鍵注意事項（給下一個 Agent）

- `DashboardRepository` 8 個方法均為唯讀 COUNT；不寫入任何表。
- 逾期邊界：`due_date < today`（嚴格小於）；今日：`due_date = today`（等於）。
- `_UPCOMING_DAYS = 7`：upcoming window 為 [today, today+7]（含兩端）。
- [superseded] Initial dashboard buttons only navigated; Slice 14 filtering supplement later added `FilterKey` and `set_filter()`.
- 舊 `_disabled("重新整理", PAGE_DASHBOARD)` 已移除，不要再加回來。

### 下一輪優先任務

1. **Windows EXE packaging**（PyInstaller，Section 24 必要項目）。
2. **Traditional Chinese user manual**（`docs/user_manual_zh_tw.md`）。
3. **GCIS 線上查詢**（需查官方 API 文件後才可實作，目前 disabled）。

---

## Latest Handoff Update (2026-05-17 — Slice 13 工商/稅籍查詢頁完整化 + 605/605 passed)

### Slice 13 完成事項（本地稅籍快取查詢 + 套用至客戶主檔）

- [已確認] `src/taxops/ui/pages/registry_page.py`（NEW）：`RegistryPage` — 標題 + 查詢條件 group（`_query_edit` + 「查詢本地快取」按鈕 + 「GCIS 工商查詢」disabled）+ status label + result group（初始隱藏）+ apply group（`_client_combo` + 「套用至客戶主檔」按鈕，搜尋成功前 disabled）；`_clear_result()` 私有方法統一三處重置邏輯；`_on_search_local()` 呼叫 `container.tax_registry_repo.search(query, limit=1)`；`_on_apply_to_client()` 開啟 `RegistryApplyDialog`。
- [已確認] `src/taxops/ui/dialogs/registry_apply_dialog.py`（NEW）：`RegistryApplyDialog` — `_MAPPABLE_FIELDS`（client_name↔business_name, address↔business_address, tax_id↔tax_id）；只顯示有差異的欄位 + QCheckBox（預設全勾）；無差異時 OK 按鈕停用；`_on_save()` 建立 `UpdateClientInput`，呼叫 `container.clients.update_client()` 自動寫 `client.update` audit log；`container` 型態已補 `ServiceContainer`；`has_diff` 改用 `bool(self._checkboxes)` 取代。
- [已確認] `src/taxops/ui/main_window.py`：新增 `PAGE_REGISTRY` import + `RegistryPage` import；`_build_pages()` 新增 `elif page_id == PAGE_REGISTRY` 分支。
- [已確認] `src/taxops/ui/action_registry.py`：新增 2 個 enabled contracts（「查詢本地快取」handler=`RegistryPage._on_search_local`，service=`TaxRegistryRepository.search`；「套用至客戶主檔」handler=`RegistryPage._on_apply_to_client`，service=`ClientsService.update_client`，audit_action=`client.update`）；「GCIS 工商查詢」保留 `disabled=True`。
- [已確認] `src/taxops/i18n/errors.py`：新增 4 個錯誤碼（`registry.apply.no_client`, `registry.apply.no_fields`, `registry.apply.no_diff`, `registry.apply.failed`）。
- [已確認] `tests/test_slice13_registry.py`（NEW）：22 tests — 含「公司不存在」禁用驗證、diff dialog 無差異停用 OK、audit log 驗證（`audit_logs` 表）、GCIS disabled 合約驗證。
- [已確認] `/simplify` 修正：`container` param 補 `ServiceContainer` type；`has_diff` → `bool(self._checkboxes)`；抽出 `_clear_result()`；移除 `# ---` 說明 WHAT 的注釋。
- [已確認] `python -m pytest` → **605/605 passed**（2026-05-17）；無 python/pytest 殘留；TIME_WAIT = 12。

### ⚠️ GCIS 線上查詢尚未完成（不在 Slice 13 完成範圍內）

- 「GCIS 工商查詢」按鈕保持 `disabled=True`，tooltip「此功能尚未開放」。
- 根據 `.ai/DECISIONS.md`：GCIS 不得靠記憶實作，需先查官方 API 文件。
- 此項仍保留於 TASKS.md TODO。

### 關鍵注意事項（給下一個 Agent）

- `_NOT_FOUND_MSG = "本地快取查無此統一編號，可能是快取未更新或資料來源未涵蓋。"` — 查無資料時禁止顯示「公司不存在」。
- `RegistryApplyDialog` 的 `container: ServiceContainer`；測試中 fake container 需含 `clients` 屬性。
- `update_client()` 已在內部寫 `client.update` audit log，dialog 不須再另外呼叫 audit。
- `_MAPPABLE_FIELDS` 是 diff 邏輯的單一來源；`_on_save()` 的三個 `new_*` 賦值目前仍需與 tuple 手動同步（中期技術債）。
- `registry_page._clear_result(status_msg)` 統一重置；任何新增清空邏輯應走此方法。

### 下一輪優先任務

1. **Dashboard**（唯一剩餘 placeholder 頁；FTS5 + registry + audit 均穩定，可接真實資料）。
2. **Windows EXE packaging**（PyInstaller，Section 24 最後一項）。
3. **Traditional Chinese user manual**。
4. **GCIS 線上查詢**（需查官方 API 文件後才可實作）。

---

## Latest Handoff Update (2026-05-17 — Slice 12 FTS5 全文搜尋 + 使用者補強 + 583/583 passed)

### Slice 12 FTS5 全文搜尋完成事項（Section 21）

- [已確認] `src/taxops/db/migrations/_m0012_fts5.py`：`fts_clients`（trigram tokenizer，非 contentless，rowid=client.id，6 欄位）+ `fts_engagements`（trigram，rowid=engagement.id）。
- [已確認] `src/taxops/repositories/search.py`：`SearchRepository`；寫方法全部呼叫 `conn.commit()`；DELETE 用 `DELETE FROM fts_... WHERE rowid=?`（標準 FTS5 表自動更新 inverse index；`content=''` contentless 模式已放棄，因其 delete 需原始 column values）。
- [已確認] `src/taxops/services/search.py`：`SearchService`；`is_fts_eligible(q)` → len(q.strip()) >= 3。
- [已確認] `src/taxops/services/clients.py`：create→`_fts_add`（SearchRepository.add_client，insert only）；update→`_fts_update`（SearchRepository.update_client，DELETE+INSERT）；delete→`_fts_delete`；restore→`_fts_add`；所有 FTS 操作均 try/except 不阻塞主流程。
- [已確認] `src/taxops/services/engagements.py`：同上模式（create/update/delete）。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer.search: SearchService`；clients/engagements services 傳入 `search_repo`。
- [已確認] `src/taxops/ui/pages/clients_page.py`：`on_refresh()` — query >= 3 chars 走 `container.search.search_clients(query)`；短查詢 fallback 原 LIKE；FTS 結果仍用 `id` 欄（stable id）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_CLIENTS 新增「搜尋客戶」enabled contract。
- [已確認] `tests/test_fts5.py`（30 tests，含使用者補強 2 個回歸測試）；`tests/test_db_migrations.py` 更新至 12（count 11→12，EXPECTED_TABLES 加 fts_clients/fts_engagements）。
- [已確認] 使用者補強（2026-05-17）：(1) `repositories/search.py` 所有 FTS 寫方法（add/update/delete/rebuild）加 try/except → rollback → raise，防止 DELETE 後 INSERT 失敗時半套狀態被後續 commit 提交；(2) `services/clients.py` + `services/engagements.py` FTS 失敗改為 `_log.warning(..., exc_info=True)` — 不再 `pass` 靜默吞掉。
- [已確認] `python -m pytest` → **583/583 passed**（2026-05-17）；無 python.exe 殘留。

### 關鍵注意事項（給下一個 Agent）

- FTS5 使用標準（非 contentless）virtual table；刪除用 `DELETE FROM fts_... WHERE rowid = ?`，不用 `INSERT INTO t(t, rowid) VALUES ('delete', ?)` command（後者 contentless-only 且需原始欄位值）。
- create 用 `add_client`（只 INSERT），update 用 `update_client`（DELETE + INSERT）；若把 add 誤改成也做 DELETE，會觸發 FTS5 SQLITE_CORRUPT（對不存在的 rowid 執行 delete）。
- FTS 查詢只在 query >= 3 chars 時觸發；短查詢 fallback 到 LIKE 搜尋（trigram 需至少 3 字元索引）。
- `_fts_quote()` 把使用者輸入包成 `"..."` phrase literal，防 FTS5 query syntax injection。
- `container.search` 是 `SearchService` 實例；測試用的 `_FakeContainer` 需視需求加此屬性。
- `SearchRepository` 所有寫方法均為 try/except → rollback → raise；`update_client/update_engagement` 是 DELETE + INSERT，若 INSERT 失敗 rollback 確保舊索引保留（不可讓 DELETE 在無 rollback 下被後續 commit 提交）。
- `ClientsService` / `EngagementsService` FTS 失敗以 `_log.warning("... FTS ... failed", exc_info=True)` 記錄，不靜默 pass；失敗不阻塞主流程，但可在 log 中追查。

### 下一輪優先任務

1. **Windows EXE packaging**（PyInstaller，Section 24 最後一項）。
2. **Dashboard**（真實查詢卡片，現在 FTS5 穩定後可接真實資料）。
3. **Traditional Chinese user manual**。

---

## Previous Handoff (2026-05-17 — Slice 11 備份/還原 + 553/553 passed)

### Slice 11 備份/還原完成事項（Section 20）

- [已確認] `src/taxops/db/migrations/_m0011_backup.py`：`backup_records(id, filename, backup_path, file_size, notes, created_at)` + `idx_backup_records_created` 索引。
- [已確認] `src/taxops/db/migrations/__init__.py`：新增 `_m0011_backup` import 與 `("0011_backup", ...)` tuple entry。
- [已確認] `src/taxops/repositories/backup.py`：`BackupRow` frozen dataclass + `BackupRepository(insert / list_all / get)`。
- [已確認] `src/taxops/services/backup.py`：`BackupError(code)` + `BackupService(conn, repo, audit)` — `create_backup(paths)` 使用 SQLite backup API 產生 `office_desk_YYYYMMDD_HHMMSS.sqlite`，寫 backup_records + audit；`restore_backup(backup_path, paths)` 驗證檔案 → 建立 `before_restore_YYYYMMDD_HHMMSS.sqlite` 安全快照（失敗則 abort）→ `src_conn.backup(self._conn)` 原地替換 → re-apply migrations → audit。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer.backup: BackupService` 欄位；`build_container()` 建立並掛載。
- [已確認] `src/taxops/i18n/errors.py`：新增 5 個備份錯誤碼。
- [已確認] `src/taxops/ui/pages/settings_page.py`：`_build_backup_group()` + `on_backup()` + `on_restore()`（兩段確認）。
- [已確認] `src/taxops/ui/action_registry.py`：`立即備份` + `還原備份` 兩個 enabled contracts。
- [已確認] `tests/test_backup.py`（17 tests）：create/restore/validation/before_restore failure/contract 全覆蓋。
- [已確認] `tests/test_db_migrations.py`：updated for migration 0011 (count 10→11, EXPECTED_TABLES adds backup_records).
- [已確認] `python -m pytest` → **553/553 passed**（2026-05-17）；無 python.exe 殘留。

### 關鍵注意事項（給下一個 Agent）

- `BackupService.restore_backup` 的 `sqlite3.connect` 第一次呼叫是 validation，第二次才是 before_restore。monkeypatch 若要模擬 before_restore 失敗，需在 call_count==2 時 raise。
- restore 後 `backup_records` 回到備份當時的狀態（before_restore 記錄消失），但 FILE 仍在磁碟——此為預期行為。
- `ServiceContainer.backup` 欄位型態為 `BackupService`；測試用 `_FakeContainer` 需自行加此屬性。

### 下一輪優先任務

1. **FTS5 搜尋**（Section 24 必交）。
2. **Windows EXE packaging**。
3. **Traditional Chinese user manual**。

---

## Previous Handoff (2026-05-17 — Excel 匯出 + 536/536 passed)

### Excel 匯出完成事項（Slice 10 / Section 19 + 23）

- [已確認] `src/taxops/security/csv_guard.py`：`safe_spreadsheet_cell(value)` — `value.lstrip()[0:1]` 判斷前導空白後公式頭（=, +, -, @），命中時前綴 `'`；保留原值、不截斷空白。
- [已確認] `src/taxops/repositories/document_requests.py`：新增 `list_missing_items_for_export(engagement_id=None)` — JOIN document_request_items + document_requests + engagements + clients；filter item_status IN (missing, incomplete, invalid, pending_confirm)；LIMIT 100,000；支援按案件篩選；回傳 list[dict]。
- [已確認] `src/taxops/services/export.py`：`ExportService.export_missing_items_xlsx(output_path, engagement_id=None)` — 呼叫 repo query、openpyxl 寫入 XLSX（header 粗體、工作表名「缺件清單」）、每格套 `safe_spreadsheet_cell`、audit `export.missing_items`；回傳 row count；`ExportValidationError(code)` 例外。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer` 新增 `export: ExportService` 欄位；`build_container()` 建立並掛載。
- [已確認] `src/taxops/i18n/errors.py`：新增 `export.query_failed` / `export.save_failed` / `export.no_rows` 三個中文錯誤碼。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「匯出缺件清單」QPushButton（載入案件後 enabled）；`_on_export()` 開 `QFileDialog.getSaveFileName`、呼叫 `container.export.export_missing_items_xlsx()`、顯示完成筆數或空白提示。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增 `匯出缺件清單` enabled contract（`audit_action="export.missing_items"`，service + repository 均完整）。
- [已確認] `tests/test_export_security.py`（24 tests）：safe_spreadsheet_cell（含前導空白/tab 注入）、query filter（排除 accepted/deleted）、欄位完整性、engagement 篩選、XLSX 產出、formula injection 逃逸、audit 記錄、空結果仍產出合法 XLSX、UI handler 整合（`_on_export()` 實際走通 + 取消不寫 audit）、action_registry 合約。
- [已確認] `python -m pytest` → **536/536 passed**（2026-05-17 Excel 匯出 closeout）。

### 仍待驗證

- [待驗證] 真實 Windows 桌面驗收仍未執行（所有 Slice 2–10）。

### 下一輪第一優先任務

1. **備份/還原**（Section 24 必交範圍）。
2. **FTS5 搜尋**（Section 24）。
3. **Windows EXE packaging**。
4. **Traditional Chinese user manual**。

### 給下一個 Agent 的注意事項

- `safe_spreadsheet_cell` 用 `value.lstrip()[0:1]` 偵測前導空白後的公式頭，原值前綴 `'` 不裁切。
- `ExportService` 依賴 `DocumentRequestsRepository`（非 DocumentRequestsService），container 中為 `doc_requests_repo`（build_container 內的局部變數）。
- `ServiceContainer.export` 欄位型態為 `ExportService`，測試中若用 `_FakeContainer` 需自行加此屬性。

---

## Previous Handoff (2026-05-17 — Slice 9 Closeout Correction + 512/512 passed)

### Slice 9 Closeout 修正事項

- [已確認] **上傳原子性**：`AttachmentsRepository.insert_with_version()` 將 attachment + attachment_versions INSERT 合併為單一 transaction（一次 commit）。`AttachmentsService.upload_attachment()` 在 `shutil.copy2` 後以 try/except 包覆 `insert_with_version()` + `audit.record()`；任一失敗均刪除已複製檔案（`dest.unlink(missing_ok=True)`）。
- [已確認] **request_id 跨案件驗證**：`AttachmentsRepository.request_belongs_to_engagement(request_id, engagement_id)` 新增；service 在 `inp.request_id is not None` 時強制驗證；`attachment.request_not_found` 錯誤碼新增至 i18n。
- [已確認] **Qt.PlainText 防 XSS**：`attachments_page.py` 新增 `_plain_label(text)` helper（`setTextFormat(Qt.TextFormat.PlainText)`）；`_AttachmentInfoDialog` 所有 9 個不可信字串 QLabel 改走此 helper。
- [已確認] **Regression tests**：`test_upload_db_failure_no_orphan_file`、`test_upload_audit_failure_no_orphan_file`、`test_upload_request_wrong_engagement_rejected`、`test_upload_request_correct_engagement_allowed`、`test_info_dialog_labels_plain_text`。
- [已確認] `python -m pytest` → **512/512 passed**（2026-05-17 Slice 9 closeout）。

### 仍待驗證

- [待驗證] 真實 Windows 桌面驗收仍未執行（所有 Slice 2–9）。

### 下一輪第一優先任務

1. **Excel 匯出 + CSV formula injection defense**（Section 24 必交範圍）。
2. **備份/還原**（Section 24）。
3. **FTS5 搜尋**（Section 24）。
4. **安全測試**（XSS/HTML injection, CSV formula injection, resource limits）。
5. **Windows EXE packaging**。

### 給下一個 Agent 的注意事項

- `insert_with_version()` 取代原先 `insert()` + `insert_version()` 兩步驟；`upload_attachment()` 已不再呼叫 `insert_version()` 個別方法。
- `request_belongs_to_engagement(request_id, engagement_id)` 查詢 `document_requests` 表的 `engagement_id` 欄位。
- 所有附件 metadata QLabel 必須透過 `_plain_label()` 建立（`setTextFormat(Qt.TextFormat.PlainText)`）。
- `attachment.request_not_found` 是新增的錯誤碼（i18n/errors.py）。

---

## Previous Handoff (2026-05-17 — Slice 9：附件證據鏈 MVP + 507/507 passed)

### Slice 9 完成事項（MVP）

- [已確認] migration 0010（attachments + attachment_versions，3+1 索引）；`security/file_guard.py`；AttachmentsRepository；AttachmentsService；AttachmentsPage；action_registry 3 個 enabled contracts；test_file_guard.py（27 tests）+ test_attachments.py（23 tests）+ test_slice9_ui.py（12 tests）；507/507 passed。

---

## Previous Handoff (2026-05-17 — Slice 8：覆核意見 + 滯納金試算 + 437/437 passed)

### Slice 8 完成事項

- [已確認] migrations 0008 (review_notes) + 0009 (late_fee_records) — 均有 FK constraint。
- [已確認] ReviewNotesRepository + ReviewNotesService：狀態機 open→responded/waived→resolved/reopened；critical 不可 waive；waive 需 reason；create/transition 均有 audit trail。
- [已確認] LateFeeRepository + LateFeeService：calculate_penalty_percent 純函數（≤3天 = 0%，每 3 天加 1%，上限 10%）；labor_health → needs_manual_review=True, penalty=0。
- [已確認] ReviewNotesPage + LateFeePage UI pages：路由 main_window；4 enabled contracts (review_notes) + 1 (late_fee) 取代原 disabled stubs。
- [已確認] i18n/errors.py 新增 13 個錯誤碼；status_labels.py 新增 labor_health + severity + review note status 標籤。
- [已確認] 測試：test_review_notes.py (21) + test_late_fee.py (17 含 11 parametrize) + test_slice8_ui.py (12) = 50 新測試；全套 437/437 passed。

---

## Previous Handoff (2026-05-17 — Slice 7 閉環 + closeout correction + 381/381 passed)

### 本輪完成事項

- [已確認] `src/taxops/db/migrations/_m0007_generated_messages.py`：generated_messages 表 + idx_generated_messages_request 索引。
- [已確認] `src/taxops/repositories/generated_messages.py`：`GeneratedMessageRow` + `GeneratedMessagesRepository`（insert/get/list_by_request）。
- [已確認] `src/taxops/services/generated_messages.py`：`GeneratedMessagesService`；`build_variables(request_id)` 組裝 11 個 ALLOWED_VARIABLES（4 個未來欄位 payment_due_date / office_owner / reviewer / last_followed_up_at 已於 Slice 15 安全修正中移除）；`generate()` 呼叫 build_variables + render_template + repo.insert + audit，TemplateValidationError → GeneratedMessageValidationError 轉傳 code。
- [已確認] `src/taxops/ui/dialogs/generate_message_dialog.py`：`GenerateMessageDialog`；`__init__` 呼叫 `build_variables()` 預載；模板 combo `currentIndexChanged` 觸發即時 render；`_copy_btn` / `_save_btn` 初始 disabled，render 成功才 enable；`_on_save()` 呼叫 `generate()` 後 `accept()`。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「產生訊息」按鈕至 toolbar；`_on_req_selection_changed()` 更新 enabled；`_on_generate_message()` 開啟 dialog。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增「產生訊息」enabled contract。
- [已確認] `src/taxops/services/container.py`：ServiceContainer 新增 `gen_messages` 欄位；`build_container()` 完整連線。
- [已確認] `src/taxops/i18n/errors.py`：5 個 gen_message 錯誤碼。
- [已確認] `tests/test_generated_messages.py`（15 tests）+ `tests/test_slice7_ui.py`（10 tests，含選模板→預覽→儲存→DB→audit 完整整合路徑）。
- [已確認] `tests/test_db_migrations.py`：migration 版本更新至 7，EXPECTED_TABLES 加入 generated_messages，idempotent count 6→7。
- [已確認] **Closeout correction（2026-05-17）**：補 generated_messages FK（REFERENCES document_requests / message_templates）；補 test_generated_messages_fk_columns 驗證；補 UI 整合測試 2 個（select→save→DB/audit）；build_variables() 未來欄位加注釋說明。
- [已確認] `python -m pytest` → **381/381 passed**（2026-05-17 closeout）。

### 仍待驗證

- [待驗證] 真實 Windows 桌面驗收仍未執行（所有 Slice 2–7）。
- [待驗證] 客戶管理新功能桌面互動。

### 下一輪第一優先任務

1. **附件證據鏈**（Attachments Slice）。
2. **Review notes**、**滯納金試算**（Late Fee）。
3. **Excel 匯出 + CSV formula injection defense**、**備份還原**、**FTS5 搜尋**。
4. **安全測試**（XSS/HTML injection, CSV formula injection, attachment guard）。

### 給下一個 Agent 的注意事項

- `build_variables(request_id)` 永遠回傳 11 個鍵；4 個未來欄位（payment_due_date / office_owner / reviewer / last_followed_up_at）已從 ALLOWED_VARIABLES 移除（Slice 15 安全修正），不再支援。
- `generate()` 的 TemplateValidationError → GeneratedMessageValidationError 轉傳保留原始 code；UI 可直接用 `error_message(exc.code)` 顯示中文錯誤。
- `GenerateMessageDialog` 的 `_variables` 在 `__init__` 組裝一次；模板 combo 切換時重用同一份 variables dict。
- `ClientRow.contact_name` 對應模板變數 `contact_person`（兩者名稱不同，已在 `build_variables()` 做轉換）。

---

## Latest Handoff Update (2026-05-16 — Slice 6 閉環 + closeout correction + 357/357 passed)

### 本輪完成事項

- [已確認] `src/taxops/db/migrations/_m0006_message_templates.py`：message_templates 表 + is_builtin 旗標；`INSERT OR IGNORE` seed 兩筆內建模板（首次索件 id=1 / 催件通知 id=2）。
- [已確認] `src/taxops/repositories/templates.py`：`TemplateRow` frozen dataclass + `TemplatesRepository`（insert/get/list_all/update/delete）；UPDATE/DELETE 均加 `AND is_builtin = 0` 防改寫內建。/simplify 清除 `_row_to_template()` 內的死碼分支（`keys = row.keys()` 條件）；函式本身仍在使用，由 `get()` 和 `list_all()` 呼叫。
- [已確認] `src/taxops/services/templates.py`：`TemplatesService`（create_template/update_template/delete_template/get_template/list_all/render_template）；`ALLOWED_VARIABLES` frozenset 11 個變數（4 個未來欄位已於 Slice 15 安全修正中移除，見下方注意事項）；`StrictUndefined`（缺少變數時拋 `template.variable.missing`，不靜默空字串）；`_validate_body()` 重用 `self._env` 解析 AST。
- [已確認] `src/taxops/i18n/status_labels.py`：新增 `TEMPLATE_TYPE_LABELS`（首次索件 / 催件通知 / 自訂）。
- [已確認] `src/taxops/ui/dialogs/template_form_dialog.py`：`TemplateFormDialog` 合併新增/編輯；is_builtin 時所有欄位 + save 停用；`_BODY_FOCUS_ERRORS` frozenset。
- [已確認] `src/taxops/ui/pages/templates_page.py`：`TemplatesPage`（QSplitter 表格 + 預覽）；`_body_cache: dict[int, str]` O(1) lookup，不做 per-selection DB 查詢。
- [已確認] `src/taxops/ui/main_window.py`：連接 `TemplatesPage`。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_TEMPLATES 4 個 enabled contract。
- [已確認] `src/taxops/services/container.py`：補 `templates_repo` + `templates_service` build 連線。
- [已確認] `tests/test_templates.py`（35 tests，Slice 6 closeout 後升至 35：新增 6 個 render 缺值 / 擴充變數測試）+ `tests/test_slice6_ui.py`（12 tests）+ migration version count 更新至 6。
- [已確認] `python -m pytest` → **357/357 passed**（2026-05-16 Slice 6 closeout correction）。

### 仍待驗證

- [待驗證] 真實 Windows 桌面驗收仍未執行（所有 Slice 2–6）。
- [待驗證] 客戶管理新功能桌面互動。

### 下一輪第一優先任務（Slice 6 已完成後）

~~1. Slice 7：已完成（2026-05-17）。~~
1. **附件證據鏈**（Attachments）、**Review notes**、**滯納金試算**。
2. **Excel 匯出 + CSV formula injection defense**、**備份還原**、**FTS5 搜尋**。
3. **安全測試**（XSS/HTML injection, CSV formula injection, attachment guard）。

### 給下一個 Agent 的注意事項

- `TemplatesService.render_template(template_id, variables)` 使用 `StrictUndefined`；缺少模板用到的任何變數時拋 `template.variable.missing`（不靜默成空字串）。
- `ALLOWED_VARIABLES` 現有 **11 個**：client_name, period_name, tax_type_name, missing_items, invalid_items, incomplete_items, due_date, tax_id, contact_person, engagement_name, notes。（payment_due_date, office_owner, reviewer, last_followed_up_at 已於 Slice 15 安全修正中移除，這 4 個欄位的 schema 尚未實作。）
- 內建模板 id=1（首次索件）+ id=2（催件通知）需要：client_name, period_name, tax_type_name, missing_items, due_date。
- `TemplateFormDialog` 傳 `existing=None` 新增、傳 `TemplateRow` 編輯；`is_builtin=True` 時所有欄位唯讀。
- `TemplatesPage._body_cache` 在 `_refresh()` 刷新；選取行改變時用 cache 顯示預覽，不做 DB 查詢。

---

## Latest Handoff Update (2026-05-15 — Slice 5 閉環 + 303/303 passed)

### 本輪完成事項

- [已確認] `src/taxops/db/migrations/_m0005_workflow_tasks.py`：workflow_tasks 表 + 4 索引（engagement_id, status, due_date, assignee）。
- [已確認] `src/taxops/repositories/tasks.py`：`TaskRow` frozen dataclass + `TasksRepository`（insert/get/list_by_engagement/list_all/list_overdue/update/update_status/complete/delete/engagement_exists）。
- [已確認] `src/taxops/services/tasks.py`：`TasksService`（create_task/complete_task/set_status/delete_task/list_by_engagement/list_all/list_overdue）；`VALID_PRIORITIES`、`VALID_TASK_STATUSES` 白名單；`_ALLOWED_TASK_TRANSITIONS` 狀態機；每個 mutation 寫 audit。
- [已確認] `src/taxops/repositories/engagements.py` + `src/taxops/services/engagements.py`：補 `list_all()` 供 TasksPage engagement 篩選 combo 使用。
- [已確認] `src/taxops/ui/pages/tasks_page.py`：`TasksPage`（engagement combo 篩選、任務表格 7 欄、新增/完成/切換狀態/刪除/重新整理、空狀態 label）。
- [已確認] `src/taxops/ui/dialogs/new_task_dialog.py`：`NewTaskDialog`（標題必填 + 負責人 + 到期日 QDateEdit + 優先級 combo + 下一步 + 備註）。
- [已確認] `src/taxops/ui/main_window.py`：連接 TasksPage 至 `_build_pages()`。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_TASKS 4 個 enabled contract（新增/完成/切換狀態/刪除待辦）。
- [已確認] `src/taxops/i18n/errors.py`：11 個 task 錯誤碼。
- [已確認] `src/taxops/i18n/status_labels.py`：`PRIORITY_LABELS` 中文對照。
- [已確認] `tests/test_tasks.py`（33 tests）：schema + create/complete/set_status/delete/list/overdue 全路徑 + audit。
- [已確認] `tests/test_slice5_ui.py`（13 tests）：widget smoke + table populate + complete/delete → DB → audit 閉環。
- [已確認] `tests/test_db_migrations.py`：更新至 5 個 migration 版本。
- [已確認] `python -m pytest` → **303/303 passed**（2026-05-15）。

### 仍待驗證

- [待驗證] 真實 Windows 桌面驗收仍未執行（所有 Slice 2–5 的 QFileDialog、QProgressDialog、QMessageBox、QThread、案件編輯、項目狀態切換、待辦操作）。
- [待驗證] 客戶管理新功能（批量匯入、編輯、刪除、衝突審查）桌面互動。

### 下一輪第一優先任務

1. **真實 Windows 桌面驗收**：開啟 app，選客戶，建案件，建待辦，完成待辦，切換狀態，刪除待辦。
2. **GCIS query**：工商查詢頁（仍 disabled）。
3. **Excel export / backup-restore / FTS5 search**（Section 24 必交範圍）。
4. **安全測試**（XSS/HTML injection, CSV formula injection, attachment guard）。

### 下一輪不要做什麼

- 不要假設測試通過代表桌面 UI 功能正確；必須人工點一遍。
- 不要在真實 Windows 驗收前宣稱任何 Slice 完整交付。
- 不要把 dialog logging 尚未寫入 SQLite `system_logs` 的改善項目當作不存在。

### 給下一個 Agent 的注意事項

- `_ALLOWED_TASK_TRANSITIONS` 在 `services/tasks.py`；`todo → done` 是非法的（必須先過 `doing`）；`complete_task()` 比 `set_status("done")` 多設 `completed_at`。
- `_ALLOWED_TRANSITIONS` 在 `services/engagements.py`；狀態切換必須透過 `set_status()`。
- `VALID_ITEM_STATUSES` 在 `services/document_requests.py`；item 狀態切換透過 `set_item_status()`，會自動重算 request-level status。
- VAT_ITEMS 模板在 `services/document_requests.py`；建立索件時可帶 `use_vat_template=True`。
- `EngagementsService.list_all()` 已新增，TasksPage engagement combo 現在可以正確顯示全部案件。

---

## Latest Handoff Update (2026-05-11 - Slice 3 Resource Cleanup Remediation)

### 本輪完成事項

- [已確認] 完成「網路異常、port 被佔用、進程殘留、socket 耗盡」專項檢查與補救。
- [已確認] `src/taxops/services/registry_download.py` 改為 `.part` 原子寫入、500 MB `MAX_DOWNLOAD_BYTES`、Content-Length 與 streaming byte 雙重檢查、失敗清理 partial file。
- [已確認] `src/taxops/i18n/errors.py` 新增 `registry.download.too_large` 使用者訊息。
- [已確認] `tests/conftest.py` 新增 autouse fixture，將 `tempfile.mkdtemp()` 導入 pytest per-test `tmp_path/_tempfile`。
- [已確認] `tests/test_slice3_download.py` 新增下載 atomic write、過大檔案拒絕、stream 超限清理、SettingsPage 真實 closure 成功路徑測試。
- [已確認] `tests/test_resource_cleanup.py` 新增 tempfile 隔離回歸測試。
- [已確認] 新增 `.ai/RESOURCE_CLEANUP_AUDIT.md`，記錄 Root Cause / Impact / Fix Strategy / Minimal Patch / Regression Risk / Verification / Regression Test / Rollback Plan / Evidence。

### 本輪未完成事項

- [待驗證] 真實 Windows 桌面驗收仍未執行：QFileDialog、QProgressDialog、QMessageBox、正式網路下載 BGMOPEN1.zip、EXE 內下載流程。
- [已確認] GCIS query 尚未實作。

### 目前正在處理的問題

- [已確認] 本輪沒有留下 DOING 中的程式修改；完整 pytest 已通過。

### 已知 bug / 風險

- [待驗證] 官方 BGMOPEN1.zip 若未來超過 500 MB，HTTP 下載會拒絕；此限制與既有 ZIP import guard 一致。
- [待驗證] UI worker 的取消機制仍未設計；目前 QProgressDialog 無取消按鈕，避免中途取消造成 SQLite import 狀態不明。長任務只能等待完成或關閉 app，正式交付前需決定是否增加可安全取消的任務模型。
- [已確認] 測試未啟動 server/browser；測後無 `python` / `pytest` 殘留；TIME_WAIT = 8。

### 已經嘗試過但無效的方法

- [已確認] 第一次完整 pytest 因既有 mock response 永遠回傳 `b"data"`，在 `.part` 寫入修補後卡住並被工具層 timeout；已確認 command line 後終止殘留 pytest 進程。
- [已確認] 修正方式不是增加 timeout，而是修正測試 mock 為有限讀取並用不存在 parent path 觸發 IO error。

### 下一輪第一優先任務

1. [待驗證] 做真實 Windows 桌面驗收，特別是 Slice 3 HTTP download 的正式 BGMOPEN1.zip 下載、匯入、audit、tmp cleanup。
2. [待驗證] 若使用者確認 Slice 4，可進入下一個垂直切片；但不要把 GCIS query 誤標為完成。

### 下一輪不要做什麼

- [已確認] 不要把「183/183 pytest passed」等同於正式交付；它不涵蓋真實桌面互動與 EXE/實網下載。
- [已確認] 不要殺掉未證明屬於測試的 node/chrome 進程。
- [已確認] 不要新增 pytest-timeout 依賴，除非使用者同意新增 dev dependency。

### 測試與驗收方式

- [已確認] 已執行：`python -m pytest tests/test_slice3_download.py tests/test_resource_cleanup.py -x --tb=short -vv` => 22/22 passed。
- [已確認] 已執行：`python -m pytest -x --tb=short` => 183/183 passed in 198.26s。
- [已確認] 已執行測後檢查：`Get-Process` 無 `python` / `pytest`；`Get-NetTCPConnection` TIME_WAIT = 8。

### 給下一個 Agent 的注意事項

- [已確認] 開工先讀 `.ai/RESOURCE_CLEANUP_AUDIT.md`，它是本輪資源清理修復閉環的權威紀錄。
- [已確認] `.ai/CURRENT_STATE.md` / `.ai/TASKS.md` / `.ai/HANDOFF.md` 下方仍保留部分舊內容且有編碼毀損，請以 2026-05-11 置頂區塊為最新狀態。

## Latest Handoff Update (2026-05-10 — Slice 2.6 客戶管理與主框架可用性強化 + 159/159 passed)

### 本輪完成事項（Slice 2.6）

**客戶管理列表搜尋/排序/分頁**
- [已確認] `ClientsRepository.search_clients(query, order_by, order_dir, limit, offset)`：LIKE 搜尋 client_code/client_name/tax_id；order_by 白名單防 SQL injection；limit/offset 分頁。
- [已確認] `ClientsRepository.count_clients(query)`：同查詢條件回傳總筆數。
- [已確認] `ClientsService.search_clients()` + `count_clients()`：pass-through；`list_clients()` 保留向後相容。
- [已確認] `clients_page.py` 重寫：搜尋列（QLineEdit + 搜尋/清除 + 總筆數）、排序（點擊欄位標題 + setSortIndicator）、分頁（◀上一頁/下一頁▶ + 第X–Y筆）；`_selected_client_id()` 永遠讀 id 欄，不用 row index。

**稅籍編號確認**
- [已確認] 「稅籍編號」= 統一編號。現有 `tax_id` 欄位即是，TABLE_HEADERS 已顯示「統一編號」，無重複欄位。

**Sidebar 收合/展開持久化**
- [已確認] `app_settings.py`：`ui.sidebar_collapsed` 加入 DEFAULT_SETTINGS（預設 `"0"`）。
- [已確認] `main_window.py`：nav 包進 sidebar QWidget；toggle 按鈕 ◀/▶；`_apply_collapsed/expanded(save=True/False)` 讀寫 setting；init 時還原；失敗靜默，不崩潰。

**不新增假待辦數**：sidebar 無任何計數徽章；待辦數待 workflow_tasks backend 完成後才可顯示。

**新增測試** `tests/test_slice26_clients_search.py`（15 tests）：全部 passed。

**Closeout correction（同輪）**
- `_page_label` 改顯示「第 X–Y 筆 / 共 Z 筆」（合併兩標籤語意）；有搜尋條件時 `_count_label` 顯示「符合 Z 筆」，無條件時清空。
- `_apply_collapsed/expanded(save=True)` 的 `except Exception: pass` 改為 `system_log.warn("sidebar ... setting save failed", detail=...)`。
- 新增 `test_page_label_format_combined` + `test_sidebar_save_failure_logs_warning`（2 tests）。

**已實際驗證**：`python -m pytest -x --tb=short` → **161/161 passed in 312.34s**

### 下一步建議
1. **真實 Windows 桌面驗收**：搜尋欄、分頁導覽、sidebar 收合/展開、中文字型、DPI 縮放。
2. **Slice 3**：HTTP download + URL allowlist + 兩段確認 + GCIS query。
3. **Dialog 錯誤改寫入 SQLite system_logs**（目前用 Python logging）。

---

## Prior Handoff Update (2026-05-10 — 稅籍查詢帶入 + 錯誤保護 + 批量匯入可捲動 + 143/143 passed)

### 本輪完成事項

**稅籍資料庫查詢帶入（新增客戶）**
- [已確認] `TaxRegistryRepository.search(query, limit)`: 統編精確比對 → 名稱 LIKE fallback，最多 20 筆。
- [已確認] `NewClientDialog`: 有快取時顯示查詢面板（QGroupBox），結果下拉顯示 tax_id + 名稱，tooltip 放完整地址，選取後按「帶入欄位」填 client_name / tax_id / address。
- [已確認] `CreateClientInput`: 新增 `registry_source_tax_id`、`registry_cache_version` 可選欄位。
- [已確認] `ClientsService.create_client()`: audit detail 若有 prefill 則增加 `registry_prefill_used`, `source_tax_id`, `cache_version`。

**稅籍查詢錯誤保護**
- [已確認] `clients_page.on_new_client()`: try/except 包 `count()`，失敗時 `system_log.warn()` + `registry_repo=None`；新增客戶流程不受快取損壞阻擋。
- [已確認] `NewClientDialog._on_search()`: try/except 包 `search()`，失敗時中文警告 + `_log.error()`，不傳播例外。

**批量匯入視窗可捲動**
- [已確認] `BulkImportWizard._build_step1()`: 改回傳 QScrollArea，底部按鈕在 stack 外部永遠可見；150% DPI 縮放下可捲動到範本按鈕。

**軟刪除 UI 文案修正**
- [已確認] `clients_page.on_delete_client()`: 停用確認文案改為「請聯絡系統維護人員」。

**新增測試**
- `tests/test_registry_lookup_in_new_client.py`（7 tests）、`tests/test_registry_error_guard.py`（4 tests）。

**已實際驗證**：`python -m pytest -x --tb=short` → **143/143 passed in 354.03s**

---

## Prior Handoff Update (2026-05-10 — Slice 2.5-A 批量匯入說明強化 + B 回退 + 132/132 passed)

### 本輪完成事項（Slice 2.5-A）

**批量匯入 Step 1 操作說明強化**

- [已確認] `src/taxops/ui/dialogs/bulk_import_wizard.py`：Step 1 新增多列格式說明 QLabel（說明必填欄位與第二列以後怎麼輸入），3 列 placeholder（header + 2 data rows），複製貼上範本按鈕（`_PASTE_TEMPLATE` 常數，tab 分隔 header + 2 筆），下載 Excel 範本按鈕（disabled，DISABLED_TOOLTIP）。
- [已確認] `tests/test_clients_page_smoke.py`（NEW）：3 個 A 相關 smoke tests（format hint、template header+rows、copy button exists）。

**放棄 B（客戶列表補地址與稅籍對照欄位）— 已回退**

- [已放棄] 使用者決定不在客戶列表顯示地址與財政部比對欄位。
- [已回退] `clients_page.py`：`_COLUMN_ORDER` 還原為原本 9 欄位；移除 match_status_to_label、REGISTRY_SOURCE_MOF 匯入；移除 on_refresh() 的 match_repo 區塊。
- [已回退] `labels.py`：`TABLE_HEADERS["clients"]` 移除 address、match_status、matched_name、matched_address。
- [已回退] `status_labels.py`：移除 MATCH_STATUS_LABELS、UNKNOWN_MATCH_STATUS_TEXT、match_status_to_label。
- [已回退] `i18n/__init__.py`：移除 3 個 match status export。
- [已回退] `container.py`：ServiceContainer 移除 match_repo 欄位（build_container() 內部仍建立 match_repo 給 RegistryMatcher 使用）。
- [已回退] `test_i18n_labels.py`：raw_field_names 還原為原本 9 欄。

**已實際驗證**：`python -m pytest -x --tb=short` → **132/132 passed**（含軟刪除 6 tests）

---

## Prior Handoff Update (2026-05-10 — 錯誤訊息修正 + parser 測試 + 124/124 passed)

### 本輪完成事項（2026-05-10 第二輪）

**錯誤訊息修正 + parser 測試**（4 個問題，全部修復並驗證）

- [已確認] `bulk_import_wizard.py:402`：raw `str(exc)` 改為 `error_message(exc.code)`；`BulkParseError` 與 generic `Exception` 分別處理；原始錯誤寫 `_log.error()`。
- [已確認] `mismatch_review_dialog.py:230`：`except (ClientValidationError, Exception)` 拆開；`ClientValidationError` → `error_message(exc.code)` + `_log.warning()`；generic → `error_message("system.unexpected")` + `_log.error()`。
- [已確認] `mismatch_review_dialog.py:123`：`_parse_diffs()` 靜默 `pass` 改為 `_log.warning()` + 保守回 `{}`。
- [已確認] `tests/test_clients_bulk_parse.py`（NEW）：9 tests，涵蓋 parse_excel（valid / blank_rows_skipped / header_only_raises / file_not_found_raises）+ parse_csv（utf-8-sig / utf-8 / cp950 / tab / header_only_raises）。
- [已確認] `tests/test_dialog_acceptance.py`（MODIFIED）：新增 `test_mismatch_dialog_malformed_diffs_json_returns_empty`。

**已實際驗證**：`python -m pytest -x --tb=short` → **124/124 passed in 281.80s**

**記錄為待改善（不影響本輪修正）**：
- 兩個 dialog 的錯誤目前寫 Python `logging`，未寫入 SQLite `system_logs`。嚴格符合規格需把 `SystemLogService` 傳進 dialog 或由 page 包裝記錄。

---

### 本輪完成事項（2026-05-10 第一輪）

**客戶管理功能閉環**（批量匯入 + 編輯/刪除 + 衝突審查 + 全域 UI 樣式）

- [已確認] `src/taxops/services/clients_bulk.py`（NEW）：批量匯入服務，支援 Excel/CSV/貼上文字，欄位自動對應，驗證，寫入（skip / overwrite policy），TOCTOU 安全處理。
- [已確認] `src/taxops/ui/dialogs/bulk_import_wizard.py`（NEW）：6 步驟批量匯入精靈，`_step_history` stack 實現正確 Back 導航。
- [已確認] `src/taxops/ui/dialogs/mismatch_review_dialog.py`（NEW）：衝突審查對話框，8 欄表格，採用/保留 checkbox；全部失敗時不呼叫 `accept()`。
- [已確認] `src/taxops/ui/style.py`（NEW）：全域 QSS + QPainter app icon（藍色圓角矩形 + 白色 "T"）。
- [已確認] `src/taxops/ui/pages/clients_page.py`（MODIFIED）：新增編輯、刪除、批量匯入按鈕；雙擊列開啟 EditClientDialog。
- [已確認] `src/taxops/services/container.py`（MODIFIED）：ServiceContainer 新增 `clients_repo` 欄位。
- [已確認] `src/taxops/ui/action_registry.py`（MODIFIED）：新增 3 個 UIActionContract（儲存變更 / 刪除客戶 / 批量匯入）。
- [已確認] `src/taxops/services/registry/matcher.py`（MODIFIED）：新增 `list_mismatches()`。
- [已確認] `src/taxops/ui/pages/settings_page.py`（MODIFIED）：`on_regenerate_matches` 完成後詢問是否開衝突審查視窗。
- [已確認] `src/taxops/ui/app.py`（MODIFIED）：啟動時呼叫 `apply_style(app)`。
- [已確認] `docs/ui_action_contract.md`（MODIFIED）：新增 3 個 contract。

**接受度測試（本 session 新增）**

- [已確認] `tests/test_dialog_acceptance.py`（NEW）：10 個 offscreen acceptance tests（EditClientDialog 3, MismatchReviewDialog 4, BulkImportWizard 3）全部 passed。
- [已確認] `tests/test_clients.py`（MODIFIED）：新增 14 個測試（4 update + 2 delete + 8 bulk service）。

**審計結果（本 session）**

已修復 HIGH（3 個）：
1. TOCTOU：`import_validated` overwrite path `find_by_code()` 回 None 時 fall-through 到 create；已補 `else` branch。
2. MismatchReviewDialog：全部失敗時仍呼叫 `accept()`；已修正為 warning + `return`。
3. BulkImportWizard Back：`_jump_to(4)` 後 Back 回 step 3；已改 `_step_history` stack。

已修復 MEDIUM（2 個）：
- ~~`_parse_diffs()` 靜默吞 JSON parse 錯誤~~ → [已修復] `_log.warning()` + 保守 `{}`。
- ~~`parse_excel()` / `parse_csv()` 無測試覆蓋~~ → [已修復] `tests/test_clients_bulk_parse.py` 9 tests。

待改善（非 blocker）：
- 兩個 dialog 的錯誤使用 Python `logging`，未寫入 SQLite `system_logs`。

### 已驗證 vs 未驗證

**已實際驗證（pytest passed）**
- 10 個 acceptance tests 全部 passed（第一輪）。
- 3 個 HIGH 修復各有對應測試覆蓋且 passed。
- 4 個 MEDIUM 問題修復後補測試（第二輪）。
- **最終確認：124/124 passed in 281.80s**（2026-05-10 驗證）。

**已確認不存在**
- `/frontend-design` 和 `/huashu-design` skills 不存在（`~/.claude/skills/` 無此目錄）；UI 樣式改善改透過 `style.py` 直接實作。

**仍需人工桌面驗收（無法自動化）**
- EditClientDialog / BulkImportWizard / MismatchReviewDialog 真實視窗顯示與中文字型。
- QFileDialog 選檔（批量匯入 Excel/CSV）。
- Slice 2：QProgressDialog 進度視窗、QMessageBox 中文顯示、QThread 整合。
- 真實 Windows 縮放（100%/125%/150%）、hover tooltip、剪貼簿。

### 目前未解決問題 / 風險

- [已修復] ~~`_parse_diffs()` 靜默吞 JSON 錯誤~~（MEDIUM → 已修復，第二輪）。
- [已修復] ~~`parse_excel()` / `parse_csv()` 無測試~~（MEDIUM → 已修復，第二輪）。
- [待驗證] 真實 Windows 桌面 UI 驗收（全功能）。
- [待改善] 兩個 dialog 的錯誤使用 Python `logging`，未寫入 SQLite `system_logs`。
- [待優化] Bundle 匯出/匯入 in-memory CSV 在低規硬體的記憶體穩定性。

### 下一輪不要做

- 不要說「客戶管理新功能一般事務所人員已可使用」—— 真實桌面驗收前保持 [待驗證]。
- 不要嘗試呼叫 `/frontend-design` 或 `/huashu-design` skill —— 不存在。
- 不要跳過 Slice 3 的 URL allowlist + 兩段確認就啟用 HTTP download。
- 不要把 dialog logging 尚未寫入 SQLite `system_logs` 的改善項目當作不存在。

### 下一步建議

1. **真實 Windows 桌面驗收**：Slice 2（5 個按鈕）+ 客戶管理（編輯、刪除、批量匯入、衝突審查）。
2. **Slice 3**：HTTP download（URL allowlist + 兩段確認）+ GCIS query。
3. **待改善**：Dialog 錯誤改寫入 SQLite `system_logs`（目前用 Python `logging`）。
4. **EXE packaging**：`docs/packaging_checklist.md`。
5. **MVP 模組**：Engagements / doc-request / tasks 等（Section 24）。

### 下一輪應先讀

1. `.ai/spec-kit.md`
2. `.ai/CURRENT_STATE.md`
3. `.ai/TASKS.md`
4. `.ai/DECISIONS.md`
5. 相關程式碼：`src/taxops/ui/pages/clients_page.py`、`src/taxops/services/clients_bulk.py`、`src/taxops/ui/dialogs/`、`src/taxops/ui/style.py`

### 驗證紀錄

```
# 2026-05-10 第二輪（本輪）
python -m pytest -x --tb=short
124 passed in 281.80s

# 2026-05-10 第一輪（前輪 bsa6ipv4h task output）
104 passed in 251.17s  →  含 test_dialog_acceptance.py 後為 114 → 本輪補 10 tests → 124
```

---

## Prior Handoff (2026-05-10 — Slice 2 Closeout Correction)

### 本輪完成事項

**Slice 2 Offscreen 自動化驗收**

- [已確認] `tests/test_settings_page_smoke.py` 新增 7 個 offscreen 測試：SettingsPage 建構、空快取標籤、5 按鈕啟用、下載按鈕停用、verify_cache 呼叫 QMessageBox、真實 BGMOPEN1.zip 匯入後狀態更新（1,705,060 筆）與 verify 報告「✓ 快取完整」。
- [已確認] offscreen 全部 7/7 passed；原始 83 tests 仍全部 pass。

**Slice 2 Closeout Correction**

- [已確認] `src/taxops/ui/pages/settings_page.py` `_RegistryWorker.run()` 補強：conn 在 build_container 前失敗時明確 close。
- [已確認] `tests/test_registry_cache_ui.py` 新增 2 個 thread smoke tests。
- [已確認] `docs/ui_action_contract.md` 對齊 `action_registry.py` 真實值。

### 已驗證 vs 未驗證

**已實際驗證成功（pytest 83/83）**
- 5 個 action contract 啟用；ZIP importer guard；背景執行緒 fresh-connection pattern。

**已 offscreen 自動化驗收**
- 7/7 SettingsPage smoke tests（含真實 BGMOPEN1.zip 1,705,060 筆）。

**仍需人工桌面驗收**
- QFileDialog 選檔、QProgressDialog 進度視窗、QMessageBox 中文字型。
- QThread 執行期間按鈕禁用、完成後重新啟用。
- `on_regenerate_matches`：確認對話 + QThread + histogram 報告。

**已確認但仍標為待優化**
- Bundle 匯出/匯入 in-memory CSV（StringIO），170 萬筆在開發機可跑；低規硬體記憶體穩定性尚未驗證。

### 驗證紀錄

```
python -m pytest -x --tb=short
============================= 83 passed in 17.20s ==============================
```

Slice 2 後端：1,705,060 筆真實 BGMOPEN1.zip smoke 匯入成功，cache_version=20260509。
