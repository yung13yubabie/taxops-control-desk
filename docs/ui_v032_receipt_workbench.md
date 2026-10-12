# v0.32 收件工作區第一輪交付

基底：`f02dc5d62ab06b4cd1214ca2044477b5a78e4420`。檔名 v032 指移植來源，不是新候選發行版號。Python / PySide6；UI 沒有修改 schema、service 或 repository。

## 首屏與操作順序

- 主入口：收件核對、待辦、年度工作、案件、固定開立。資料與工具按「客戶資料／工作資源／查詢與試算／系統」分組（分類標題是否畫出由平台 Qt 樣式決定；Linux offscreen 只顯示分隔線與入口）；全部 12 個目的頁逐項核對見 [功能保留表](ui_v032_function_retention.md)。
- 收件首屏：來源及案件範圍 → 搜尋 → 待核對／已驗收／已退回／全部有效附件 → 文件清單與預覽。
- 每筆文件同時顯示檔名、客戶代碼與名稱、案件或租約。選取後顯示附件狀態、索件期限、全案缺件／不完整／待確認數，以及一個主要下一步。
- 狀態摘要明確標示「全案」，不假稱只屬於選取批次；無索件期限顯示未設定，不借用案件期限，也不推算年度法遵期限。
- 附件未建立個別 `document_item_id` 關聯。「開啟索件核對」帶案件／批次 ID 到既有索件頁；驗收附件不會完成索件項目。說明按需展開，失效／讀取錯誤直接顯示。
- 租約附件接受空 `engagement_id`。顯示客戶及租約，追加檔案走既有租約附件服務；管理入口開既有客戶編輯器、依 lease_id 選取租約。取消保留原資料。

## 響應、键盤與回饋

- 1180 邏輯寬度以下摺疊左側提醒，頁首始終顯示數量與最近日期；按鈕開獨立提醒對話框。
- 1000 邏輯寬度以下文件列表與預覽切換，保留返回列表、歸屬、期限和主要操作，不把三欄硬縮在一起。
- F6 聚焦主導覽，Ctrl+F 聚焦收件搜尋；表格及提醒清單可用鍵盤選取／Enter。保留 Tab 順序、原生選單、焦點邊框及中文 accessibleName。
- 檔案資訊、系統開啟、檔案位置、複製本機 URL、可恢復刪除置於「更多」。無選取時隱藏操作區；有選取時人工核對為唯一 primary，新增附件退為 secondary。
- 空資料與搜尋無結果分開；讀取失敗清除不可信的舊收件列並顯示錯誤。失效案件 scope 不默認變成全部資料。
- 提醒載入失敗保留上一次成功結果並標「未更新」及時間；初次失敗不顯示空白成功。篩選中的附件深連結會重設阻擋該 ID 的舊篩選再定位。
- 模態編輯、頁面 leave guard、索件已提交待讀回鎖定均優先於導流；取消不跳轉。動作前重新核對 attachment、engagement、request、client、lease ID，防止失效或換歸屬後操作舊上下文。

## 測試與圖證

2026-10-12 首輪固定 `e77c574` 本地分檔執行，13 檔共 **336 passed**：

| 檔案 | passed |
|---|---:|
| test_v032_today_queue.py | 61 |
| test_v032_today_panel.py | 26 |
| test_workbench_v032_navigation.py | 44 |
| test_v032_receipt_workbench.py | 20 |
| test_slice9_ui.py | 43 |
| test_annual_workbench_navigation.py | 5 |
| test_slice26_clients_search.py | 18 |
| test_ui_layout_stability.py | 16 |
| test_ui_action_contracts.py | 12 |
| test_ui_design_system.py | 50 |
| test_ui_page_shell.py | 22 |
| test_client_leases_ui.py | 8 |
| test_client_lease_attachments.py | 11 |

後續 `a6b72c6` 只調整操作區高度，36 個收件／layout 回歸通過；`75a5f4f` 補封存附件舊選取 guard，案件及租約各新增一例，收件 22＋舊附件 43＋導航 44，共 109 通過。這些批次有重疊，不相加為總測試數。

執行方式：`QT_QPA_PLATFORM=offscreen python -m pytest -q tests/<檔名>`。新資料均為隔離 tmp_path SQLite 合成資料，不讀使用者資料。

附圖為 PySide6 真實 widgets，1366×768、1093×614、911×512 邏輯尺寸，以及窄窗預覽、提醒與租約附件畫面；不是 HTML 示意圖。底部明示「Linux offscreen，非 Windows DPI 驗收」。本轮 Ruff 修改檔、compileall、diff whitespace check 通過。

## 明確未驗證及後續 gate

- 這是 UI 第一輪候選，仍需獨立 review 及主整合回歸；不等同全 suite、發行或既有資料遷移驗收。
- 長中文實測可保留狀態、期限、缺件數與主要下一步；1093 寬度遇特別長檔名及客戶／案件文字時，文件預覽起點較低，需要捲動 Inspector。
- 未在實體 Windows 驗證 100／125／150% DPI、中文 IME、Narrator、QtPdf 或檔案總管整合；offscreen 不能代替這些檢查。
- 保留現有案件完整快照與附件全量讀取，再做本地 50 筆 UI 分頁；提醒正確讀完 200 筆索件分頁。這些讀取目前同步，沒有大型資料集延遲／可取消背景工作承諾，極大量資料需另做量測与背景化設計。
- 不新增外網資源；使用既有本地 SVG 與系統字型。工商線上查詢、快取下載與離線 EXE 打包維持原功能與其他工作項的驗收範圍。
