# UI Action Contract

This document mirrors the source-of-truth registry in
`src/taxops/ui/action_registry.py`. Every visible button in the UI must
have a contract here AND in the registry; tests in
`tests/test_ui_action_contracts.py` keep them in sync.

## Contract format

```text
按鈕名稱：
所在頁面：
觸發 function：
呼叫 service：
呼叫 repository：
成功結果：
失敗結果：
audit log：
測試：
啟用狀態：
```

## Rules

- Every enabled button must have a contract.
- Every contract must have a real action handler (`handler != "placeholder"`).
- Every action handler must call a service unless the action is purely local
  UI state (e.g. close dialog, copy to clipboard).
- Every data-changing service must call a repository.
- Every data-changing operation must write an audit log.
- Unimplemented actions must be disabled and show `此功能尚未開放`.
- Disabled placeholder actions still appear in the registry and the UI so
  the user can see what is coming.

## Slice 1 contracts

### 客戶管理 (`clients`)

- 按鈕名稱：新增客戶
  - 觸發 function：`ClientsPage.on_new_client`
  - 呼叫 service：—（開啟對話框）
  - 呼叫 repository：—
  - 成功結果：對話框開啟
  - 失敗結果：—
  - audit log：—
  - 測試：`test_open_new_client_dialog`
  - 啟用狀態：啟用

- 按鈕名稱：重新整理
  - 觸發 function：`ClientsPage.on_refresh`
  - 呼叫 service：`ClientsService.list_clients`
  - 呼叫 repository：`ClientsRepository.list_clients`
  - 成功結果：表格更新；空表時顯示空狀態
  - 失敗結果：「無法載入客戶列表，請稍後再試」
  - audit log：—（讀取）
  - 測試：`test_clients_list`
  - 啟用狀態：啟用

- 按鈕名稱：儲存（新增客戶對話框）
  - 觸發 function：`NewClientDialog.on_save`
  - 呼叫 service：`ClientsService.create_client`
  - 呼叫 repository：`ClientsRepository.insert`
  - 成功結果：寫入後關閉，回到列表並重新整理
  - 失敗結果：「客戶新增失敗，請確認輸入後再試」；游標移至首個無效欄位
  - audit log：`client.create`
  - 測試：`test_create_client`
  - 啟用狀態：啟用

- 按鈕名稱：取消（新增客戶對話框）
  - 觸發 function：`NewClientDialog.on_cancel`
  - 呼叫 service：—
  - 呼叫 repository：—
  - 成功結果：對話框關閉
  - 失敗結果：—
  - audit log：—
  - 測試：`test_dialog_cancel`
  - 啟用狀態：啟用

- 按鈕名稱：儲存變更（編輯客戶對話框）
  - 觸發 function：`EditClientDialog.on_save`
  - 呼叫 service：`ClientsService.update_client`
  - 呼叫 repository：`ClientsRepository.update`
  - 成功結果：寫入後關閉，回到列表並重新整理
  - 失敗結果：「客戶資料更新失敗，請確認輸入後再試」；游標移至首個無效欄位
  - audit log：`client.update`
  - 測試：`test_edit_client`
  - 啟用狀態：啟用

- 按鈕名稱：刪除客戶
  - 觸發 function：`ClientsPage.on_delete_client`
  - 呼叫 service：`ClientsService.delete_client`
  - 呼叫 repository：`ClientsRepository.delete`
  - 成功結果：刪除後重新整理列表
  - 失敗結果：「客戶刪除失敗，請稍後再試」
  - audit log：`client.delete`
  - 測試：`test_delete_client`
  - 啟用狀態：啟用（選取列時）；未選取時禁用

- 按鈕名稱：批量匯入
  - 觸發 function：`ClientsPage.on_bulk_import`
  - 呼叫 service：`ClientsService.create_client`（逐筆）
  - 呼叫 repository：`ClientsRepository.insert`
  - 成功結果：完成後重新整理列表，顯示匯入結果報告
  - 失敗結果：「批量匯入失敗，請確認檔案格式後再試」
  - audit log：`client.create`（逐筆）
  - 測試：`test_bulk_import_clients`
  - 啟用狀態：啟用

### 設定 (`settings`)

啟用：

- 開啟資料庫資料夾 — `SettingsPage.on_open_data_folder` — 開啟 `data_root` —
  失敗訊息：「無法開啟資料夾，請確認路徑存在」
- 開啟附件資料夾 — `SettingsPage.on_open_attachments_folder` —
  開啟 `attachments_dir`
- 複製資料庫路徑 — `SettingsPage.on_copy_db_path` — 寫入剪貼簿
- 複製附件路徑 — `SettingsPage.on_copy_attachments_path` — 寫入剪貼簿
- 儲存使用者顯示名稱 — `SettingsPage.on_save_display_name` —
  service `SettingsService.set_setting` — repo `AppSettingsRepository.upsert` —
  audit `settings.update`
- 儲存查詢模式 — `SettingsPage.on_save_query_mode` —
  同上 — 驗證值必須屬於 `local_only`/`allow_online`

啟用（slice 2 — 離線工作流）：

- 從 ZIP 匯入稅籍資料
  - 觸發 function：`SettingsPage.on_import_zip`
  - 呼叫 service：`TaxRegistryImporter.import_zip`
  - 呼叫 repository：`TaxRegistryRepository.replace_all_from_entries`
  - 成功結果：「已成功匯入稅籍資料」
  - 失敗結果：「匯入失敗，已保留原本快取，請稍後重試」
  - audit log：`tax_cache.import.zip`
  - threading：worker 自行開新 SQLite connection，不共用 UI connection

- 匯入稅籍快取包
  - 觸發 function：`SettingsPage.on_import_bundle`
  - 呼叫 service：`TaxCacheBundleService.import_bundle`
  - 呼叫 repository：`TaxRegistryRepository.replace_all_from_entries`
  - 成功結果：「已成功匯入快取包」
  - 失敗結果：「快取包匯入失敗，已保留原本快取」
  - audit log：`tax_cache.bundle.import`

- 匯出稅籍快取包
  - 觸發 function：`SettingsPage.on_export_bundle`
  - 呼叫 service：`TaxCacheBundleService.export_bundle`
  - 呼叫 repository：`TaxRegistryRepository.iter_all`
  - 成功結果：「已成功匯出快取包」
  - 失敗結果：「快取包匯出失敗，請稍後重試」
  - audit log：`tax_cache.bundle.export`

- 驗證快取
  - 觸發 function：`SettingsPage.on_verify_cache`
  - 呼叫 service：`verify_cache`
  - 呼叫 repository：`TaxRegistryRepository.count`（唯讀）
  - 成功結果：彈出文字報告（version / row_count / freshness）
  - 失敗結果：「驗證失敗，請稍後再試」
  - audit log：`tax_cache.verify`
  - threading：同步執行（主線程安全）

- 重新產生客戶對照結果
  - 觸發 function：`SettingsPage.on_regenerate_matches`
  - 呼叫 service：`RegistryMatcher.regenerate_mof`
  - 呼叫 repository：`RegistryMatchRepository.replace_for_source`
  - 成功結果：「已完成重新產生客戶對照結果」
  - 失敗結果：「重新產生對照結果失敗，請稍後重試」
  - audit log：`tax_cache.match.regenerate`
  - threading：worker 自行開新 SQLite connection（非同步）

停用（slice 3，顯示「此功能尚未開放」tooltip）：

- 下載財政部稅籍資料（HTTP download，需 URL allowlist + 兩段確認，Slice 3 啟用）

### 其他 placeholder 頁面

每頁顯示一個代表性的 disabled 按鈕，搭配「此功能尚未開放」tooltip。後續切片實作時，
本 doc 與 `action_registry.py` 必須同步更新。

| 頁面 | 代表性按鈕 |
|------|------------|
| 首頁儀表板 | 重新整理 |
| 案件管理 | 新增案件 |
| 索件管理 | 新增索件 |
| 待辦事項 | 新增待辦 |
| 訊息模板 | 新增模板 |
| 工商 / 稅籍查詢 | 查詢統一編號 |
| 滯納金試算 | 開始試算 |
| 附件管理 | 上傳附件 |
| 覆核意見 | 新增覆核意見 |

## Synchronization rule

When a button is added, removed, renamed, or has its contract changed:

1. Update `src/taxops/ui/action_registry.py`.
2. Update this document to match.
3. Run `pytest tests/test_ui_action_contracts.py` to verify the registry is
   internally consistent.
