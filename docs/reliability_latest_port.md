# 最新功能基底的可靠性修復

## 基底與範圍

本輪以 `feature/v030-annual-workbench` 的 `f02dc5d62ab06b4cd1214ca2044477b5a78e4420` 為基底。它包含已發布 `v0.31.0` (`aac6dcedca174221ecbd52022628c9c56b1feabd`) 的功能及其後 15 個提交。`main` 的 v0.29 修復試作只供選取補丁，不能當成最新產品的驗證結果。既有 0.32 owner 測試建置、Windows smoke 與歷史測試數，也不能代表本輪候選版已驗收。

- 保留 schema 0027/0028、客戶雙地址、租約與業別、年度法遵/年度工作/交易、既有 UI 設計系統、模板 sandbox 與依賴版本。
- 保留上游已修好的批次索件交易及 `with_request` 回傳合約、附件 guarded-copy。
- 最小移植：完整備份、索件 accepted 混合狀態、下載來源稽核與匯入同一交易、完成匯入後釋放進度對話框。
- 維持 Python/PySide6。沒有新增年度狀態自動同步或新的稅法計算規則。

## 完整備份與復原保留物

設定頁現在產生 `.taxops.zip`：一致的 SQLite 快照、附件、流程圖片及畫布圖片。manifest 列出每檔大小與 SHA-256；所有 active attachment（包括沒有案件的租約/客戶附件）及圖片引用必須完整，才會建立成功紀錄。資料庫本身保留全部年度與租約關聯。

還原先在暫存區驗證、遷移及檢查外鍵，接著將檔案放入新的 `restored_<id>` namespace，最後切換資料庫。原有檔案不覆寫也不自動刪除；`restore_history` 記錄時間、來源、引用、對照、狀態與原 DB 回復快照。失敗前已複製的 namespace 與原資產是復原保留物，可能占用磁碟。多次還原會累積空間；本輪不自動清理它們。磁碟寫入失敗在 DB 提交前保持原資料，提交後單純暫存清理失敗會顯示成功與警告，不會刪除已完成備份或誤稱還原未發生。

舊 `.sqlite` 繼續可還原，但只含資料庫，不能憑空補回附件。UI 在確認前明示此限制。請將備份另存到可復原的位置；同一硬碟上的檔案無法防止整顆硬碟故障。本格式未加密，應依事務所存取與保存規範保管。

## 本輪第一段驗證（2026-10-12）

使用 Linux / Python 3.12 / PySide6 6.10.2 與全合成資料。每個 pytest 檔案使用新的 process；先執行下列 7 檔，共 **159 passed、1 skipped**：

- `test_backup.py`: 25 passed
- `test_backup_cleanup_boundaries.py`: 6 passed
- `test_backup_compatibility.py`: 16 passed
- `test_backup_current_domains.py`: 3 passed
- `test_reliability_lifecycle.py`: 3 passed
- `test_reliability_regressions.py`: 77 passed
- `test_settings_page_user_paths.py`: 29 passed、1 skipped（Windows `os.startfile`）

另外逐檔執行 6 個既有領域測試：`test_document_requests.py` 69、`test_attachments.py` 32、`test_client_lease_attachments.py` 11、`test_annual_transactions.py` 51、`test_annual_work_integration.py` 33、`test_annual_tasks_backend.py` 23，合計 219 passed。第一段 13 檔總計 **378 passed、1 skipped**，仍不是全套。

執行方式：設定 `QT_QPA_PLATFORM=offscreen`，對每一檔分別執行 `python -m pytest -q tests/<file>.py`。後續整合另做全套、合併 branch coverage，仍維持實值至少 90% 門檻。以上為聚焦檢查，未計算全套覆蓋率。

新增 schema-28 回歸逐值比對雙地址、兩個租約、兩個業別、法遵設定、年度工作、六類交易、索件與 linked task；乾淨目錄還原、重新啟動、再次備份後，三個附件的 bytes 與餘額均一致。另驗缺少 active 租約附件、未來 manifest 格式會在提交前拒絕。

真 `v0.31.0` checkout 以合成資料建立 SQLite，再以本輪程式開啟並完整備份/還原：28 筆 migration ledger 逐值不變、13 個業務表資料一致、3 個附件 hash 一致、外鍵檢查空白。本次 v0.31 → 最新基底 schema 都是 28，屬相容開啟，沒有虛稱發生新的資料遷移。

初次移植測試的 fixture 名稱/錯誤碼及錯誤注入 import 經修正後重新執行；沒有把初次紅燈算成通過。受限的安全對抗項目維持未完成，未重試。Windows 乾淨離線安裝、無 Python 的 EXE、DPI/螢幕閱讀器與實際發布都尚未驗收。

## 資源定位與 schema 保護整合

後續整合 frozen asset path 與未知 migration 拒絕／bootstrap 失敗關閉連線的最小修復；保留 28 項 migrations、既有 UI tokens 與 Windows 版本資源。固定 `909ddcb` 上逐檔重跑備份與新增領域、相容/cleanup、原可靠性、frozen resources、startup guard、annual migration 與 packaging，共 **187 passed**。此數與上段重疊，不相加為獨立案例數。全套與 Windows gate 仍待整合後執行。

## 全套基底量測與獨立審查

固定 `08dedda220c2ff501b18715d4fd58553464ae125`，逐檔 126/126 全部執行；3035 項為 **3029 passed、5 failed、1 skipped**，沒有未跑、timeout 或 native crash。合併 branch coverage 實值 **90.51584148153266%**，門檻通過，但整體 matrix 仍標示 failed。

5 個失敗均在 `test_single_instance.py`，本環境 `QLocalServer.listen` 回報 `Unknown error 1`：first acquire、second acquire、release/reacquisition、cross-process activation、unrelated payload。該檔另 2 passed；未排除或改為 skip，也未修改環境安全設定。Windows `os.startfile` 1 項按平台 skip。候選 Windows CI 必須再執行同一整套取得平台證據。

repo 既有公開 `tmp/BGMOPEN1.zip` fixture 未被排除；含兩次約 170 萬列匯入的 settings smoke 檔 7 passed。新增業務回歸則全部使用合成資料。這次數字不能冒充最後 UI/self-test 整合版結果，後續固定 SHA 必須 fresh 重測。

獨立審查固定 `0679f58`：119 pytest 全過，另由真 v0.31 程式建立 schema28 合成資料後，多輪開啟、還原、重啟、再備份及第二次還原一致。審查包含 worker 所屬 thread 的連線關閉檢查及案件/租約部分複製失敗後重試。

其中有意義而未直接覆蓋的契約已加入原測試：worker 關閉後須在原 thread 確認 closed database；取消不得開新連線；部分複製失敗連續三次不得改動既有 bytes/資料列/版本/稽核，重試只新增一份。沿用原 lifecycle 3 案例及擴充既有 copy case 為兩種 owner，淨新增 1 項，未整包複製 14 項重複測試。這輪相關 5 檔 103 passed，包含正式 runner 14 與 artifact/self-test 契約 24；仍屬聚焦重疊結果。

## 候選版本命名

下一候選使用 Python/package `0.33.0rc1`，規劃候選 tag `v0.33.0-rc.1`，與歷史 0.32 owner 測試 ZIP 區分。Windows 固定數字版本 `0,33,0,1`、顯示字串 `0.33.0rc1`，並設 prerelease flag；測試同時比對 pyproject、runtime 與 Windows metadata。依 [Microsoft VERSIONINFO 定義](https://learn.microsoft.com/en-us/windows/win32/menurc/versioninfo-resource)，固定數字與顯示字串分別處理。此命名不代表已建立 tag 或 Release。

## UI/self-test 整合版完整矩陣與最後修補

固定 `773efd46633b37b31ad2ce61a50ca7eaf7948cb0` 的正式 runner 完成 132/132 檔：**3225 = 3219 passed + 5 failed + 1 skipped**，無未跑、timeout 或 native crash；branch coverage 實值 **90.65248785611134%**。仍是前述同 5 個 single-instance 環境失敗與 1 個 Windows-only skip；整體 matrix 如實標 failed。公開大型 fixture 保留，沒有更動環境安全設定。

之後只新增兩項 UI 修補：寬窗操作區縮成兩排，以及在殘留選取已封存附件時阻止案件/租約導流。程式固定 `87b49acf32ffe9a38358e8342df354e0ea9daf40`；9 檔 fresh 相關回歸 **251 passed**：receipt 22、layout 16、navigation 44、today projection 61、today panel 26、既有附件 UI 43、artifact self-test 24、packaging 10、frozen resources 5。這是相關回歸，未再次執行整套或重新計算 final tree coverage，不把 773efd4 的百分比改標為最後 SHA 的實測。正式 Windows 候選 CI 將對最終 SHA 跑全套及 raw coverage。

最終 UI 獨立審查在來源 `75a5f4f`：28 自寫與 8 檔 253 通過且程序正常退出，封存 guard 的案件與租約兩條已複驗。另 59 個代表性功能流程正常退出；保留 12 個 NAV ID 和 135 個 enabled handler pair 是靜態保留證據，並非所有功能已全面驗證。這些結果與 repo 測試有重疊，不累加成一個宣傳數字。

### 既有 Qt 單選測試清理限制

`tests/test_settings_page_user_paths.py::test_import_and_export_bundle_buttons_run_services` 單獨執行時，在 `f02dc5d` 與 `773efd4` 都出現斷言通過後 exit -11；faulthandler 位於 pytest unconfigure 的 garbage collection。普通非 pytest 對照加明確 DeferredDelete 後 exit 0，但同時改變 runner 與清理方式，不能據此宣稱根因已確定或已修復。完整逐檔矩陣未 crash 與此單選結果不矛盾，兩者都保留。

最終 self-test 在 Linux source 模式檢查 16 項，包括完整目前領域及圖片/附件還原；`frozen=false`，不是 Windows EXE。尚未在本輪實測乾淨離線 Windows、DPI、IME/Narrator、publisher signing/SmartScreen 或完整安全對抗。歷史 0.31/0.32 EXE 證據不可挪作候選驗收。
