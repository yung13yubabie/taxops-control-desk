# v0.32 收件工作區：功能保留與入口對照

核對日期：2026-10-12。檔名 v032 指移植來源基底，不是新候選發行版號。這是本機 UI 整合工作樹的保留檢查，不是發行或 Windows 驗收證明。

## 比較基準與判準

- 導覽集合以實際 `v0.31.0` tag 的 `src/taxops/ui/action_registry.py` 為基準；已解析並逐項比較 `NAV_ORDER`，與目前工作樹的 12 個 ID 及順序完全相同。
- 本輪程式變更以 `f02dc5d` 為起點。它已包含後續 v0.32 的年度工作、客戶主從頁、日期欄位、訊息模板與滯納金頁改版；本輪沒有用較舊頁面覆蓋這些實作。
- 「保留」須同時核對：入口能到達原本的真實頁面、核心操作仍接既有 handler/service、資料身分與安全邊界未被導覽改寫。只有頁數相同或測試總數增加，不構成功能保留證據。
- 本輪差異不包含 `services/`、`repositories/`、`db/`、`i18n/`。這只能證明這些原始碼未被本輪修改，不能代替業務流程回歸測試。
- 導覽來源：[MainWindow](../src/taxops/ui/main_window.py)、[WorkspaceNavigation](../src/taxops/ui/widgets/workspace_navigation.py)、[action registry](../src/taxops/ui/action_registry.py)。登錄中的 `test_marker` 是情境提示，本文只引用實際存在的測試函式。

v0.31 的真實集合為：

`clients`、`annual_workbench`、`engagements`、`tasks`、`work_records`、`templates`、`registry`、`late_fee`、`attachments`、`folder_bookmarks`、`recurring_billing`、`settings`。

`doc_requests` 原本就內嵌於案件，不是第 13 個導覽目的地；`review_notes` 早已退役，也不算本輪移除功能。

## 12 個目的地對照表

舊入口均為左側導覽。新版有五個常用主入口，另外七個在分組的「資料與工具」選單；年度工作沒有被藏進選單。分類文字由平台 Qt 樣式決定；Linux offscreen 實測只畫分隔線及七個入口，沒有畫四個分類標題。下列路徑按實際點擊層級列出，括號內是分組，不是額外子選單。

| 穩定 NAV_ID | v0.31 入口 | 新版入口與位置變動 | 真實目的地 | 保留的核心流程 | 具體證據 |
|---|---|---|---|---|---|
| `clients` | 客戶管理 | 資料與工具 → 客戶管理（客戶資料組）；入口搬移，頁面不替換 | `ClientsPage` | 查詢、排序、分頁、新增/編輯、批次匯入、刪除/復原/清除；詳細資料與租約管理 | [客戶與租約](#客戶與租約) |
| `annual_workbench` | 年度工作檯 | 頂端「年度工作」；一鍵主入口，頁內標題仍是年度工作檯 | `AnnualWorkbenchPage` | 年度篩選、建立工作、法遵設定、工作明細與協作 | [年度工作](#年度工作) |
| `engagements` | 案件管理 | 頂端「案件」；原有案件頁與三級索件流程保留 | `EngagementsPage` | 新增/編輯/切換狀態/刪除案件；案件 → 索件批次 → 文件項目 | [案件與索件](#案件與索件) |
| `tasks` | 待辦事項 | 頂端「待辦」；另可由今日待辦定位指定 ID | `TasksPage` | 新增、狀態、完成、刪除、批量操作、下一步與父子關係 | [待辦](#待辦) |
| `work_records` | 工作紀錄 | 資料與工具 → 工作紀錄（工作資源組）；入口搬移 | `WorkRecordsPage` | 流程範本、執行清單、步驟進度、圖片、覆寫/另存範本 | [工作紀錄](#工作紀錄) |
| `templates` | 訊息模板 | 資料與工具 → 訊息模板（工作資源組）；入口搬移 | `TemplatesPage` | 新增/編輯/試用、真實客戶預覽、變數插入；內建模板唯讀 | [訊息模板](#訊息模板) |
| `registry` | 工商 / 稅籍查詢 | 資料與工具 → 工商 / 稅籍查詢（查詢與試算組）；入口搬移 | `RegistryPage` | 本地快取查詢、同名候選、官方 GCIS 補查、比對後套用客戶 | [工商與稅籍](#工商與稅籍) |
| `late_fee` | 滯納金試算 | 資料與工具 → 滯納金試算（查詢與試算組）；入口搬移 | `LateFeePage` | 手動/案件來源、日期與金額輸入、試算、分段明細、歷史 | [滯納金與日期欄位](#滯納金與日期欄位) |
| `attachments` | 附件管理 | 頂端「收件核對」，成為預設頁；頁面改為收件工作區 | `AttachmentsPage` | 上傳、預覽、驗收/退回、封存、資訊、檔案位置；新增案件/索件核對入口與租約上下文 | [附件與收件核對](#附件與收件核對) |
| `folder_bookmarks` | 資料夾管理 | 資料與工具 → 資料夾管理（工作資源組）；入口搬移 | `FolderBookmarksPage` | 新增/編輯/刪除書籤、搜尋、開啟位置與錯誤回饋 | [資料夾](#資料夾) |
| `recurring_billing` | 固定開立 | 頂端「固定開立」；一鍵主入口 | `RecurringBillingPage` | 方案/明細、產生待開立、確認/跳過/退回、批量確認與歷史 | [固定開立](#固定開立) |
| `settings` | 設定 | 資料與工具 → 設定（系統組）；入口搬移 | `SettingsPage` | 使用者設定、資料路徑、備份/還原、快取匯入/匯出/驗證/下載 | [設定](#設定) |

全表共同的可執行證據位於 [test_workbench_v032_navigation.py](../tests/test_workbench_v032_navigation.py)：

- `test_all_twelve_destinations_are_present_once_with_true_labels`：檢查集合、唯一性、實際中文文字、tooltip、圖示與按鈕 role。
- `test_real_buttons_and_tools_actions_open_all_twelve_real_pages`：實際點擊五個按鈕及觸發七個選單 action，逐一斷言真實頁面類別與選取狀態，並非只檢查 registry。
- `test_annual_is_one_click_primary_and_new_clients_page_is_unchanged`：年度工作主入口及原 `ClientsPage` inspector 都存在。

## 核心流程與測試對照

以下每個測試名稱均已在目前測試檔中核對存在。「既有測試」不代表本文件編寫時已全部重新執行；實際執行範圍見後面的驗證紀錄。

### 客戶與租約

本輪未改動 [clients_page.py](../src/taxops/ui/pages/clients_page.py)、[edit_client_dialog.py](../src/taxops/ui/dialogs/edit_client_dialog.py)。客戶頁保留主從表格、inspector、註記、地址、租約數與租約詳細資料。`_leases_btn` 仍接 `on_edit_client`，由既有客戶編輯器處理多筆租約，不另造一套租約資料。

- `tests/test_clients_page_user_paths.py::test_search_sort_and_pagination_buttons_follow_real_rows`
- `tests/test_clients_page_user_paths.py::test_new_and_edit_buttons_submit_real_dialog_widgets`
- `tests/test_clients_page_user_paths.py::test_delete_restore_and_purge_buttons_cover_client_lifecycle`
- `tests/test_client_profile_ui.py::test_new_dialog_actual_save_persists_multiline_profile_and_two_leases`
- `tests/test_client_profile_ui.py::test_clients_page_exposes_exact_addresses_and_lease_entry_without_n_plus_one`
- `tests/test_client_leases_ui.py::test_edit_dialog_stages_update_archive_and_create_in_one_save`
- `tests/test_client_leases_ui.py::test_archived_lease_reopens_as_read_only_history_with_attachment`
- `tests/test_client_lease_attachments.py::test_mismatched_client_or_archived_owner_leaves_no_artifact`

收件區的租約附件顯示「管理此客戶租約」，開啟既有 `EditClientDialog(container, client)` 並捲至租約區。這是原客戶租約管理入口，並以 lease_id 預選該筆租約；取消不保存。無租約上下文時仍可導向原客戶頁；未新增 `client_id`/`lease_id` 的跨頁 NavigationTarget API。

### 年度工作

本輪未改動 [annual_workbench_page.py](../src/taxops/ui/pages/annual_workbench_page.py)，保留 `_open_create_dialog`、`_open_profile_dialog`、`_open_selected_detail` 及原有年份、工作類型、風險篩選與分頁。年度工作仍是年度法遵狀態的主控資料；收件/待辦的狀態沒有取代它。

- `tests/test_annual_workbench_navigation.py::test_annual_workbench_exposes_enabled_create_action`
- `tests/test_annual_workbench_navigation.py::test_navigation_reuses_page_and_runs_refresh_clear_filter_contract`
- `tests/test_ui_stage_6_annual_workbench.py::test_double_click_opens_the_selected_work_item`
- `tests/test_ui_stage_6_annual_workbench.py::test_inspector_labels_the_adopted_and_suggested_deadlines_apart`
- `tests/test_annual_workspace_dialog.py::test_edited_standard_subset_and_custom_row_are_persisted_exactly`
- `tests/test_annual_item_detail_ui.py::test_detail_loads_real_item_context_and_saves_exact_multiline`
- `tests/test_annual_collaboration_ui.py::test_annual_attachment_upload_reads_back_exact_database_id`
- `tests/test_annual_collaboration_ui.py::test_annual_task_create_and_complete_use_same_database_id`
- `tests/test_annual_collaboration_ui.py::test_annual_collaboration_panels_reach_201st_rows`

### 案件與索件

[engagements_page.py](../src/taxops/ui/pages/engagements_page.py) 仍保留案件主表、requests-only 與 items-only 三層內容；[document_requests_page.py](../src/taxops/ui/pages/document_requests_page.py) 的建立、修改、狀態、催收、刪除、訊息與匯出 handler 沒有被收件頁取代。

新增 `open_context(engagement_id, request_id)` 先查驗身分，使用 `select_request_id` 跨頁定位；不把當前列號當作 ID。有效案件不因不在下拉選項首批而退回全部案件。已失效的案件 scope 顯示明確訊息，保留原 scope 並清空資料，直到使用者明確清除篩選。

- `tests/test_document_requests_real_user_paths.py::test_new_request_button_drives_real_template_fields_sqlite_and_audit`
- `tests/test_document_requests_real_user_paths.py::test_items_only_real_buttons_edit_status_and_delete_exact_sqlite_rows`
- `tests/test_document_requests_real_user_paths.py::test_export_button_surfaces_exact_terminal_outcome`
- `tests/test_workbench_v032_navigation.py::test_exact_case_scope_survives_hidden_master_refresh`：完整/截短選項 × 舊選取/無選取 × 案件/批次，共八種組合。
- `tests/test_workbench_v032_navigation.py::test_request_after_first_page_is_selected_through_public_api`
- `tests/test_workbench_v032_navigation.py::test_pending_postcommit_recovery_locks_survive_request_navigation`
- `tests/test_workbench_v032_navigation.py::test_deleted_scoped_case_stays_scoped_until_explicit_clear`

### 待辦

[tasks_page.py](../src/taxops/ui/pages/tasks_page.py) 保留原所有任務操作。新增指定待辦 scope、清楚的「返回全部待辦」入口；以真實 ID 載入目標，包含只有客戶、沒有案件的待辦及全域待辦。新待辦對話框的 client/engagement 預填跟隨已定位的真實上下文，並保留未儲存的 modal 輸入。

- `tests/test_slice21e_tasks_ui.py::test_single_task_toolbar_click_path_creates_statuses_completes_and_deletes`
- `tests/test_slice21e_tasks_ui.py::test_bulk_create_real_dialog_widgets_reach_page_handler`
- `tests/test_slice21e_tasks_ui.py::test_bulk_edit_button_updates_selected_tasks`
- `tests/test_slice21e_tasks_ui.py::test_next_step_button_creates_context_inheriting_child`
- `tests/test_workbench_v032_navigation.py::test_task_target_keeps_exact_id_scope_and_new_task_prefills`
- `tests/test_workbench_v032_navigation.py::test_modal_unsaved_input_blocks_every_navigation_path`

### 工作紀錄

[work_records_page.py](../src/taxops/ui/pages/work_records_page.py) 未被本輪修改。保留範本/執行清單及步驟圖片；不將待辦擴充成另一套流程系統，也未把原本隱藏或未開放的功能偽裝成可用入口。

- `tests/test_slice27_work_records.py::test_workflow_toolbar_click_path_covers_full_run_lifecycle`
- `tests/test_slice27_work_records.py::test_workflow_create_and_edit_buttons_use_real_dialog_fields_and_persist_audit`
- `tests/test_slice27_work_records.py::test_workflow_selected_step_file_button_persists_template_and_run_assets`
- `tests/test_slice27_work_records.py::test_hidden_work_record_features_are_not_advertised_as_enabled_actions`

### 訊息模板

[templates_page.py](../src/taxops/ui/pages/templates_page.py) 與現有新版模板編輯器保留。新增仍是頁面主要操作；編輯/試用仍在 inspector，刪除仍在更多選單；內建模板維持唯讀。

- `tests/test_ui_stage_12_templates.py::test_edit_and_trial_live_in_the_inspector_not_the_toolbar`
- `tests/test_ui_stage_12_templates.py::test_delete_is_reachable_only_through_the_overflow_menu`
- `tests/test_ui_stage_12_templates.py::test_builtin_template_dialog_is_readonly_and_says_why`
- `tests/test_ui_stage_12_templates.py::test_choosing_a_test_client_previews_against_real_data`
- `tests/test_ui_stage_12_templates.py::test_double_click_inserts_exactly_the_advertised_text`
- `tests/test_templates.py::test_plain_text_rendering_uses_sandbox_without_html_escaping`

### 工商與稅籍

[registry_page.py](../src/taxops/ui/pages/registry_page.py) 的本地查詢、worker、官方補查與套用主檔操作均保留。核心離線可用的說明不代表 GCIS 或下載已可離線執行。

- `tests/test_slice13_registry.py::test_local_name_search_runs_in_worker_and_offers_multiple_results`
- `tests/test_slice13_registry.py::test_gcis_button_queries_official_service_and_displays_result`
- `tests/test_slice13_registry.py::test_apply_real_dialog_updates_exact_client_and_reports_success`
- `tests/test_slice13_registry.py::test_client_filter_can_find_customer_outside_initial_dropdown`

### 滯納金與日期欄位

[late_fee_page.py](../src/taxops/ui/pages/late_fee_page.py) 未被本輪改動；手動與案件來源、試算結果、可展開分段明細及歷史仍是新版實作。試算沿用原服務與法定計算函式，沒有由收件工作區重算。

- `tests/test_ui_stage_13_late_fee.py::test_switching_to_manual_preserves_what_the_user_typed`
- `tests/test_ui_stage_13_late_fee.py::test_displayed_numbers_equal_the_statutory_functions`
- `tests/test_ui_stage_13_late_fee.py::test_segment_rows_mirror_build_penalty_schedule`
- `tests/test_ui_stage_13_late_fee.py::test_manual_review_tax_type_refuses_to_show_a_number`

共用 [date_field.py](../src/taxops/ui/widgets/date_field.py) 同樣未被本輪改動。保留直接選日期、欄內清除與日曆按鈕、中文月份、鍵盤調整、日期驗證、彈窗邊界和原公開 API；沒有恢復舊版「確認」步驟或 ±年按鈕。

- `tests/test_ui_stage_5_date_field.py::test_clicking_a_date_applies_it_and_closes_the_popup`
- `tests/test_ui_stage_5_date_field.py::test_field_is_wide_enough_for_the_date_and_both_icons`
- `tests/test_ui_stage_5_date_field.py::test_popup_header_names_the_month_in_chinese`
- `tests/test_ui_stage_5_date_field.py::test_public_api_signatures_are_frozen`

### 附件與收件核對

[attachments_page.py](../src/taxops/ui/pages/attachments_page.py) 是本輪實際重排的主要頁面。保留既有上傳/版本、驗收、退回、封存、預覽及檔案位置。工作區新增搜尋/狀態佇列、附件歸屬與人工核對上下文；案件附件導向原案件/索件資料，租約附件導向既有客戶租約編輯器。

- `tests/test_slice9_ui.py::test_upload_persists_to_db_and_creates_version`
- `tests/test_slice9_ui.py::test_accept_persists_to_db_and_audits`
- `tests/test_slice9_ui.py::test_delete_button_archives_row_and_audits`
- `tests/test_slice9_ui.py::test_attachment_toolbar_click_path_uploads_reviews_opens_and_deletes`
- `tests/test_slice9_ui.py::test_pdf_attachment_uses_embedded_preview`
- `tests/test_slice9_ui.py::test_malicious_stored_filename_cannot_preview_open_or_copy`
- `tests/test_workbench_v032_navigation.py::test_attachment_target_opens_real_case_and_exact_file`

驗收附件不等於完成索件、案件、待辦或年度工作。表格沒有文件項目關聯時，不宣稱已自動核對清單。封存仍須確認；檔案開啟/位置操作仍依檔案安全檢查。新增工作區不擴張原有資料分享或外部連線行為。

### 資料夾

[folder_bookmarks_page.py](../src/taxops/ui/pages/folder_bookmarks_page.py) 未被本輪修改；分組選單保留真實頁面入口，並非已退役的覆核意見頁。

- `tests/test_slice24_folder_bookmarks.py::test_new_button_click_creates_bookmark_and_refreshes_table`
- `tests/test_slice24_folder_bookmarks.py::test_edit_button_click_updates_selected_bookmark`
- `tests/test_slice24_folder_bookmarks.py::test_delete_button_click_requires_confirmation_and_removes_row`
- `tests/test_slice24_folder_bookmarks.py::test_open_button_success_and_desktop_rejection`

### 固定開立

[recurring_billing_page.py](../src/taxops/ui/pages/recurring_billing_page.py) 未被本輪修改。它是週期開立排程，沒有改稱應收帳款；方案、明細、已確認歷史與防重複產生仍依原服務。

- `tests/test_recurring_billing_page_user_paths.py::test_global_add_plan_button_drives_real_dialog_sqlite_and_audit`
- `tests/test_recurring_billing_page_user_paths.py::test_plan_and_line_edit_buttons_drive_real_dialog_fields_and_audit`
- `tests/test_recurring_billing_page_user_paths.py::test_pending_row_confirm_and_skip_buttons_use_real_dialogs_and_persist`
- `tests/test_recurring_billing_page_user_paths.py::test_bulk_confirm_selected_pending_rows_uses_real_page_action`
- `tests/test_recurring_billing_page_user_paths.py::test_generate_button_second_click_reports_idempotent_result`

### 設定

[settings_page.py](../src/taxops/ui/pages/settings_page.py) 未被本輪修改；快取與備份操作沒有移入收件頁。MainWindow 仍在匯入/下載進行時拒絕關閉，保留 settings/registry worker 的生命周期守衛。

- `tests/test_settings_page_user_paths.py::test_save_buttons_persist_user_values`
- `tests/test_settings_page_user_paths.py::test_import_and_export_bundle_buttons_run_services`
- `tests/test_settings_page_user_paths.py::test_backup_button_success_and_domain_failure`
- `tests/test_settings_page_user_paths.py::test_restore_button_cancel_confirm_and_success`
- `tests/test_settings_page_user_paths.py::test_download_button_runs_download_import_cleanup_audit_and_exact_success`

## 跨頁行為與資料安全

以下新增測試同在 `tests/test_workbench_v032_navigation.py`：

| 必須維持的行為 | 具體測試 |
|---|---|
| 重複跳轉不新增或修改客戶、案件、附件、待辦、索件/項目與年度工作資料 | `test_repeated_exact_links_and_generic_client_route_do_not_mutate_business_records` |
| 已刪除待辦、案件、客戶、索件與已封存附件不改變目前頁面 | `test_deleted_target_keeps_source_page_and_data` |
| 同名資料仍以 ID 定位；錯誤案件歸屬不得跳轉 | `test_wrong_case_target_keeps_source_and_business_data` |
| 不完整/無效 ID 不被解讀成「全部資料」 | `test_invalid_or_incomplete_target_does_not_change_source` |
| 模態視窗未儲存內容不被主導覽或深連結丟棄 | `test_modal_unsaved_input_blocks_every_navigation_path` |
| 頁面拒絕離開時不能以另一入口繞過 | `test_page_leave_guard_blocks_deep_link_and_global_entry` |
| 已提交、尚未讀回核對的索件操作持續鎖住變更按鈕 | `test_pending_postcommit_recovery_locks_survive_request_navigation` |
| 讀回失敗不宣稱已開啟指定工作 | `test_failed_request_readback_does_not_switch_page` |
| F6 聚焦導覽而不改變資料頁 | `test_f6_focuses_active_navigation_without_changing_page` |

## 已執行的驗證與未驗證範圍

### 本文件編寫前直接執行的證據

環境：Linux、PySide6、`QT_QPA_PLATFORM=offscreen`，使用專案隔離測試資料庫。以下測試檔各自獨立程序執行；數字是當時通過的案例數，不能替代上面的逐項契約。

| 測試檔 | 通過案例數 |
|---|---:|
| `test_workbench_v032_navigation.py` | 44 |
| `test_ui_design_system.py` | 50 |
| `test_slice21e_tasks_ui.py` | 36 |
| `test_slice21b_merged_engagements.py` | 8 |
| `test_document_requests_real_user_paths.py` | 37 |
| `test_slice19a_navigation.py` | 14 |
| `test_annual_collaboration_ui.py` | 14 |
| `test_annual_request_bidirectional_ui.py` | 29 |
| `test_tasks.py` | 62 |
| `test_document_requests.py` | 69 |
| `test_slice21d_tasks_parent_bulk.py` | 24 |

導航工作的新測試 44 個與相關既有測試 343 個均通過。導航相關的七個修改/新增檔案同時通過 Ruff、compileall 與 `git diff --check`。以上是整合期間的定點結果；其他平行修改及最後凍結版本仍需整合重跑，不能當作完整套件或發行驗證。

### 中文、尺寸與 Windows 限制

- 新導航使用繁體中文操作標籤，原頁面 `NAV_LABELS` 不變；主入口的短名稱透過 tooltip 對應原完整名稱。完整 12 個目的地名稱有實際斷言。
- `test_navigation_labels_fit_without_tiny_fonts` 在 900、1093、1366 邏輯寬度檢查五個主入口及工具入口可見、不重疊、文字至少 14px。這只證明導航列的 offscreen 幾何，不代表 12 頁所有對話框均可在 900 寬度完整操作。
- 本文件未確認 Windows 100%、125%、150%、200% 實機縮放、真實中文字型、中文輸入法、焦點可見性、滑鼠/鍵盤長流程或螢幕閱讀器。
- PDF/影像預覽在實際 Windows QtPdf、系統開啟/檔案總管、UNC 路徑、SmartScreen、EXE 打包、安裝和既有使用者資料遷移均未由這份導航證據驗收。
- 真實 GCIS 補查與快取下載連線不在這次離線導航測試範圍；對應既有測試不能視為正式環境服務可用性證明。
- 本輪未執行完整 suite 或重新計算全專案 branch coverage；本文件編寫時尚未凍結；最終 UI commit 與補跑結果另見交付記錄。未 push、merge、tag、打包或發布。
