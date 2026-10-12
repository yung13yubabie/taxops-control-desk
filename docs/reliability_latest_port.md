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

## 第一輪遠端候選與 Windows 結果

[Draft PR #2](https://github.com/yung13yubabie/taxops-control-desk/pull/2) 指向 `feature/v030-annual-workbench`，未合併或發布。因 Git HTTPS 沒有本機登入憑證，透過既有 GitHub 連接建立等內容 squash commit：本地 `bf1872b48f4403d0bbaea9576c9b476a4c4ca15a` 對應遠端 `20cdc1a5e0ec1eaf6846613e7f1d87e78df47333`；完整 tree 均為 `253979d04dd8f44e635a8a7a5e27ba2af8fc6528`。69 個變更檔的內容 hash 與模式逐一核對，並非把本地提交號冒稱已推送。

[Windows run 38206960124](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38206960124) 的實際 checkout 是 PR merge `c314c6c6f768221e9b555fae9730509c2082caff`，tree 與候選完全相同；job log 和 matrix.source_commit 均已核實。Python 3.11.9 / PySide6 6.10.2，完整 132/132 檔，**3227 = 3223 passed + 4 failed**，0 errors / skipped / 未跑檔，raw branch coverage **90.76079821452015%**。

四項失敗是：收件頁 900 px 被原生控件撐到 913 px；frozen gate 測試的全域 subprocess 替身攔到 Windows `ver` 探測；runner 的 crash / timeout 兩個 JSON 路徑斷言使用不同分隔符。測試失敗正確阻擋 EXE build 和 frozen self-test；診斷 artifact 的存在不能當成已產生 EXE。single-instance **7/7** 與 settings user-path 全檔 **30/30** 本次 Windows 正常退出，但不撤銷上述 Linux 單選測試的 GC 崩潰限制。

## 新手表單與平台修補後的固定來源

固定程式來源 `4985acddf9779db90a8a65e0cfd089c5bc714680` 納入各組修補後，fresh 完整矩陣逐檔跑完 **136/136 檔，3316 = 3310 passed + 5 failed + 1 skipped**，0 errors / 未跑檔，raw branch coverage **90.87923762918129%**。仍是同五個 Linux QLocalServer 環境失敗與一個 Windows 專用 skip；整體 exit 1 保留，未降低 coverage 90% 門檻或排除測試。執行前後核實同一 HEAD 且工作樹乾淨，期間未更動來源；本機未設定 GITHUB_SHA，所以原始 matrix.source_commit 如實為 not_recorded，固定來源以另存的起迄核對紀錄為準。

本輪修正包括：年度 profile 讀取失敗禁存，既有起始月不被預設值覆寫；第 502 筆指定客戶的精準帶入；清單確實超過 500 時顯示正確導引；待辦讀取失敗保留選取 ID／輸入，失效關聯禁存；未存內容的取消確認；日期主動驗證失敗只聚焦該輸入；表單、模板展開及長結果捲動；年度交易欄位提示。一般年度下拉仍限定前 500 加指定客戶，更完整搜尋入口是「建立年度工作 → 設定法遵檔案」，不能宣稱此下拉可瀏覽所有客戶。

另修 Windows 證據所指的三類問題：收件 ActionBar 把空間交給篩選列、解除搜尋框硬性寬度；測試替身限制在被測模組；matrix JSON 統一 POSIX 相對路徑。原 900 px 斷言不變，新增原生控件最小寬度壓力與視圖往返測試。Linux 合成壓力由舊碼 935 px 紅燈到修後 900 px 通過，只是額外可重現證據，不能冒稱 Windows 913 px 已在實機回驗。

同 `4985acd` 獨立新手 QA：**11 個外部自寫 probe 正常退出、38 個結果斷言通過、5 檔 130 pytest 通過**，另保存 63 張固定來源真 Qt 圖像。日期 focus 也以真待辦輸入失敗、修正、一般儲存故障、重試與重複點擊驗證只寫一筆。這是抽樣深查，不是每個表單、選单、日期、縮放組合都已全面驗證；不得與完整矩陣相加成宣傳總數。

`4985acd` source self-test 的 16 項均通過、`frozen=false`，全 repo Ruff、diff check 通過。後續白話繁中文字與 Qt 標準視窗翻譯正在另一片段處理，以上數字不能移標為尚未測量的新來源。乾淨離線 Windows、EXE、DPI、IME、Narrator、簽章與未完成的安全範圍仍保留待驗。

## 繁中文字與真實 Qt 視窗整合量測

固定來源 `247fe2c70ccf07cbfc470ee4602df5c4269037e4` 已整合白話繁中、標準 Qt 翻譯與其後回歸修補，以及 EXE 自測的翻譯檢查。fresh 全套逐檔完成 **137/137 檔，3333 = 3327 passed + 5 failed + 1 skipped**，0 errors / 未跑檔 / timeout / native crash；raw branch coverage **90.93781920326865%**。仍是同五個 Linux IPC 環境失敗與一個 Windows 專用 skip，runner 整體 exit 1，如實保留。

本次明確設定 `GITHUB_SHA=247fe2c70ccf07cbfc470ee4602df5c4269037e4`；原始 `matrix.source_commit`、執行前後 HEAD 與 clean 工作樹一致。命令為 `python -m build_tools.run_test_matrix --output <新的證據目錄>`，並設定 `PYTHONPATH=src`、`QT_QPA_PLATFORM=offscreen`。每一檔獨立 process，沒有挑案例代替完整檔案、刪除測試或降低實值 90% 門檻。公開大型工商 fixture 仍參與完整矩陣。

同 SHA `python -m taxops.diagnostics --report <新的報告檔>` 正常 exit 0，**17/17 檢查通過**，報告明示 `frozen=false`、`platform=linux`、`qt_platform=offscreen`、`network_attempts=[]`。翻譯檢查真的先設英文語言，再建立按鈕、月曆，以及開啟／儲存／選資料夾的 Qt 視窗：逐值驗證提示與可操作按鈕非空且具有正確中文用途、日期與資料夾类型顯示、原檔名／選取路徑／檔案內容不變。不是只比較常量或搜尋是否缺少英文字母。

缺翻譯檔分支使用真正不存在的合成目錄，未刪除安裝檔。有限後備仍提供標準按鈕中文，但選檔提示不保證完整中文，報告明示 `catalogue_loaded=false`、`fully_localized=false`、`status=standard_buttons_only`；最後恢復完整翻譯。Windows 套件檢查同時要求翻譯檔存在與這項完整自測，不能靠後備取得完整中文通過。

整合前，`test_frozen_resources.py` 的四個純 Python application 替身因不符合新增 QObject 翻譯契約而失敗。測試改用真 QApplication 並記錄原方法呼叫，原 icon/path/呼叫數/空圖 fallback 斷言全保留；沒有在應用程式加入測試探針例外。完整該檔 5 項及 `test_frozen_self_test.py` 29 項均在上述矩陣正常通過。

白話繁中來源 `21a336b` 已由獨立審查涵蓋 74 個畫面狀態、8 個中文語意判斷、真選檔的路徑與內容，以及 7 檔 135 項正常退出；這是限定範圍且與完整矩陣重疊，不能累加成總案例數。固定 `247fe2c` 再經獨立複驗：同 74 畫面／8 語意／真選檔檢查通過，完整 5 檔 **58 項**（resources 5、self-test 29、deep Chinese 12、packaging contract 2、packaging tools 10）正常退出；實際 source 自測 17 項通過。另 5 個獨立 gate 反例均正確拒絕：source 非 Windows、完整 QM 缺失、把有限後備標成完整、少語言檢查、套件缺 QM。審查確認圖資測試原斷言沒有削弱；缺 QM 真 probe 保留非空的部分英文提示並正確恢復中文。這些均是 Linux 來源與契約證據，不能代替 Windows EXE。

尚待新整合版 Windows CI 與真正 frozen EXE；第一輪 Windows 的 4 失敗不能自動改稱已在 Windows 修復。乾淨離線 Windows、DPI/IME/Narrator、簽章、安全未完成範圍及既有 Qt 單選 GC 限制仍待驗。另保留 320 px 小月曆第六週文字下緣在 offscreen 畫面略裁切的限制，不將文字抽查宣稱為所有版面完美。
