# TaxOps Control Desk

給台灣會計與稅務事務所使用的本機工作桌：管理客戶、案件、索件、附件、待辦及年度工作。資料存在本機 SQLite，核心工作不需登入雲端。

> 目前為 **0.33.0rc1 候選版，尚未發布**。保留已發布 v0.31.0 及其後的年度工作與介面功能；Windows 乾淨離線驗收尚未完成。

試用前請先看 [候選試用說明](docs/candidate_tryout.md)，使用空白測試環境，不要直接開啟正式工作資料。第三方元件的固定版本 [原始碼取得與替換說明](assets/third_party_licenses/SOURCE_ACCESS.txt) 隨套件提供。

## 從哪裡開始

- **收件核對**：先看待處理附件，再進入所屬客戶、案件或索件核對。
- **待辦與索件提醒**：找出要跟進的待辦與索件提醒，直接開啟原資料。
- **年度工作**：依客戶與作業年度管理年度工作、申報/文件/稅額/服務費狀態與交易。
- **資料與工具 → 客戶管理**：維護登記與聯絡地址、多筆租約、業別及備註。
- **資料與工具 → 設定 → 備份與還原**：建立完整備份，或還原既有備份。

收件與索件品項目前仍需人工核對；系統不會假稱附件已自動對應品項。完成待辦不等於完成案件或年度工作，這些狀態各自保留稽核記錄。

其他功能仍保留：案件與協作管理、工作流程與紀錄、畫布筆記、訊息模板、滯納金試算、固定開立、工商登記查詢與稽核紀錄。功能入口對照見 [功能與入口對照](docs/ui_v032_function_retention.md)。

## 離線使用範圍

- 可離線：客戶/租約/案件/索件/附件/待辦/年度工作與交易、現有模板、已下載工商快取查詢、本地 ZIP 快取匯入、備份與還原。
- 需連網：下載新的官方工商資料、GCIS 即時補查。
- 不會把資料未更新當成已即時查證；離線查詢使用本機已有資料。

最終交付要求是：下載單一 EXE，在支援的 Windows 電腦沒有網路、沒有預裝 Python、Qt、Visual Studio 或其他額外元件時，直接開啟即可執行核心工作。EXE 執行時會把隨附元件解壓到暫存目錄；一般使用者不需安裝開發工具。目前仍需通過該驗收；候選 CI、EXE 自測與實機清單見 [Windows 候選驗證](docs/windows_candidate_gate.md)。

## 備份與資料位置

設定頁建立 `.taxops.zip`，包含 SQLite、附件、流程圖片與畫布圖片。還原前驗證檔案及引用完整性；包含租約附件與全部年度資料。舊 `.sqlite` 仍可還原，但只有資料庫，不能補回遺失的附件或圖片。

- 正式模式資料：`%LOCALAPPDATA%\TaxOpsControlDesk`
- 預設備份：使用者 `Documents\TaxOpsBackups`
- 還原前保留目前資料庫快照，原資產與失敗還原的檔案區域 也保留供復原。多次還原會增加磁碟用量；本輪不自動清理。
- 備份未加密，請依事務所規範保管，並另存到可復原的位置。只有同一硬碟上的備份不能防止整顆硬碟故障。

## 本輪修正與驗證

- 採用選定的「帳冊」應用程式圖示，提供 16–256 px 七種尺寸，沿用現有視窗／EXE 圖示路徑；[圖示與識別契約](docs/application_icon_contract.md) 已有真 Qt 抽查，已驗 EXE 的七個圖示資源均與選定圖檔一致；實機釘選仍待驗。
- 完整備份與乾淨目錄還原；提交後暫存清理失敗顯示成功與警告。
- 混合索件狀態不再因「已接收 → 已確認」倒退。
- 工商匯入與下載來源稽核同一交易；完成後釋放進度對話框。
- 驗證本機稅籍資料會提交本次稽核並釋放寫入鎖；呼叫者原本有交易時保留由呼叫者決定提交或回復，不提前提交其他資料。
- 打包資源定位、未知資料庫版本的非破壞拒絕與啟動失敗連線清理。
- 保留啟動期間再次開啟的要求，視窗準備完成後再顯示；完整傳送與分段接收有明確界線，仍由新 Windows 同步雙開測試驗收。
- 一般啟動讀寫失敗會顯示白話提示並停止開啟，不自動重建原資料；處理方法及本機診斷紀錄見[啟動資料恢復指引](docs/startup_storage_recovery.md)。
- 保留上游已修好的批次索件交易及附件複製失敗清理。
- 年度設定讀取失敗時禁止儲存，避免預設值蓋過原資料；指定客戶、待辦關聯與未存內容在重試或取消時保留。
- 長表單與展開說明可捲動，儲存／取消留在可見位置；日期填錯會回到該欄位，空白欄位補上用途提示。
- 操作提示、錯誤、空畫面與選檔視窗改用白話繁中；保留原本的客戶名稱、檔名與路徑。英文系統語言下的標準按鈕、月曆與選檔文字另有實際視窗檢查。

### 實際驗證進度

- 較早的完整資料夾套件已通過 Windows 回歸及 17 項 EXE 自測；它是歷史基準，不能當作單一 EXE 已驗收。固定版本、雜湊及歷次結果見 [Windows 候選驗證](docs/windows_candidate_gate.md)。
- 第一個真正單檔 EXE 已由 [run 38280844680](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38280844680) 建出：來源完整 152 檔、3807 項通過，實值 coverage（含分支收集） 91.05698731866956%。該 EXE 的受控 CRT 中止沒有得到預期退出碼，因此整體驗收失敗，沒有作為成品發布。
- 故障注入現明確模擬不經正常清理的本人程序中止，仍須取得退出碼 77、重啟及資料／鎖恢復、18 項實際 EXE 自測。原 CRT/PySide 異常證據保留，不能以新模型聲稱已修好 PySide。[run 38293931640](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38293931640) 的 153 檔、3838 項來源測試通過，但新 EXE 在同步雙開時未將通知送達勝方視窗，整體仍失敗，尚未執行新中止控制及後續 18 項自測。此通知問題、本機稅籍資料交易與測試準備修正均須以新固定來源重驗。
- 本機原設定頁回歸重複匯入同一份 1,705,060 筆公開資料，超過原 900 秒限制。測試現共享一次完整真匯入，各測項使用獨立 SQLite 複本，保留兩組原斷言；沒有縮減資料、刪除失敗或提高時限。後續固定版本的本機回報見下段。

較新的 [run 38298961816](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38298961816) 已取得 155 檔、3897 項全部通過，原始合併行／分支覆蓋率 91.1487758945386%。該新 EXE 的雙開通知、中止碼 77、重啟資料保留及 18 項功能檢查通過；完整驗收仍失敗，原因是末端模組快照出現 8 個宿主 Tortoise 元件。另一次 [獨立 Shell 觀察](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38303276207) 在相同 runner 映像的不同虛擬機重現相同路徑與檔案雜湊；它沒有改寫原驗收失敗或豁免核心元件來源。

本機重組後續回報完整來源測試及修改後 qgif 小型探針通過，設定頁 8 項回歸在原 900 秒內結束；但封裝被不同來源的系統 DLL 擋下，沒有產出合格重組 EXE。目前修正建置工具繼承的 DLL 搜尋路徑，以及驗收材料缺件的預檢。這些新修正仍須固定來源的完整回歸和新 Windows 建置；尚未完成的重組／乾淨離線驗收保留。

前一輪 [run 38330485769](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38330485769) 已通過 Windows 全部 159 檔、4136 項，實值 coverage（含分支收集） 91.17232302340885%，並成功建出新的單一 EXE。完整驗收仍失敗：同步雙開時，第二個程序的通知雖交給 Qt，卻未在寫入等待期限內送完，因此顯示「程式尚未就緒」並返回 1；第一個程序已開啟視窗但沒有收到啟用通知。本輪未執行後續中止、18 項自測及重組套件匯出。

[獨立 Windows 傳送診斷](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38334298605) 確認：接收端尚未接受連線時，額外的 500 ms 寫入期限會提前結束通知；接受連線後，即使接收端事件迴圈暫停，資料仍能送完。候選修補改用原本單一 3000 ms 總預算，不重送通知，也不把送出當作視窗已顯示。[修後 Windows 對照](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38335606087) 已確認延後接受連線的通知能完整送達且只觸發一次；一直未接受連線及提前關閉的情境仍正確失敗。這項來源修效另由下述新 EXE 回驗，歷史失敗不改判。

歷史 [run 38336220402](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38336220402) 已通過全部 159 檔、4148 項 Windows 來源回歸，原始合併行／分支覆蓋率 91.17176972014165%。該單一 EXE 的同步雙開、本人中止碼 77、重啟資料保留及 18 項 frozen 自測通過，但完整驗收因末端模組分類失敗。原失敗不改判；精確來源及雜湊見 [歷史單檔驗收紀錄](docs/windows_onefile_gate.md#latest-notification-repair-and-remaining-module-classification-failure)。

最新一般候選 [run 38343015308](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38343015308) 的兩個 Windows 工作均通過。完整來源回歸為 164 檔、4421 項，零失敗、錯誤及略過，實值 coverage（含分支收集） 91.17176972014165%。真正單一 EXE 已通過雙開的一次啟用、退出碼 77 與同資料恢復、18 項 frozen 檢查、核心元件實載來源及同次獨立 Shell 分類；有匯出與該 EXE／來源身分精確相符的重組材料，且成品、圖示與材料已獨立核對。

隨後 [固定匯出材料重組 run 38348191958](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38348191958) 也重新通過原 164 檔、4421 項及原覆蓋率門檻，但在真正編譯修改後 qgif 前，CMake 拒絕了建置腳本傳入的 Windows 反斜線路徑。這是重組腳本的可攜性缺陷；該材料不能稱為已完成修改元件重建。修正後必須重新產生同來源身分的候選 EXE 與材料，再從新材料重驗；原一般候選的通過和本次重組的失敗分別保留。詳見 [一般候選通過與重組路徑缺陷](docs/windows_onefile_gate.md#accepted-hosted-candidate-and-exported-kit-path-failure)。

**候選尚未發布。** 最終 Release 必須附重新驗證的單一 EXE，以及必要的第三方授權通知與原始碼／重組材料；不以舊 ZIP 或只有原始碼代替 EXE。原始碼重組材料供有需要的接收者使用，不是一般使用者的安裝前提。具體方案見 [單檔 EXE 與重組驗收](docs/windows_onefile_gate.md) 和 [第三方元件說明](docs/third_party_licenses.md)。

已知限制：Hosted Windows 測試不是乾淨離線 Windows 10/11 實機；人工 DPI、輸入法、列印、輔助功能及簽署／SmartScreen 仍需核對。原生 Windows 合成中文字形抽查已通過，但不代表所有姓名或字集；小尺寸月曆在 offscreen 第六週文字下緣仍略裁切。缺繁中翻譯檔時只有有限按鈕後備，EXE gate 仍要求完整翻譯資產。

可靠性契約見 [驗證紀錄](docs/reliability_latest_port.md)。完整逐檔獨立 process 與實值 coverage（含分支收集） **90%** 門檻保留；Linux 的既有 IPC 環境失敗仍如實標記，不能當作 Windows 結果。

已發布版本可在 [GitHub Releases](https://github.com/yung13yubabie/taxops-control-desk/releases) 核對。repo 的 `dist/` 是建置輸出，不是永久下載來源。`docs/v0.32.0_test_checklist.md` 記錄較早 內部測試建置，並非本輪驗收。

## 開發

維持 Python / PySide6 / SQLite。安裝開發依賴後，用 `python -m build_tools.run_test_matrix --help` 查看參數，再執行逐檔測試與合併 coverage；Windows 發行套件使用隔離環境及 `requirements-release.txt` 固定版本。

在另一部 Windows 驗收既有 EXE 時，請使用同一份建置產物的完整收據；工具會在啟動 EXE 前列出缺件。材料與命令見 [跨主機驗收輸入](docs/onefile_acceptance_inputs.md)。

封裝工具將子程序的 DLL 搜尋路徑限定於既定工具來源，並以完整相依驗證處理可缺席的系統 API 合約檔案；實作界線及仍會拒絕的不同來源 bytes 見 [Windows 建置可攜性](docs/windows_build_input_portability.md)。這不是對任意 Windows 或編譯環境的相容保證。

開始改碼前閱讀 [CONTRIBUTING](CONTRIBUTING.md)、[安全政策](SECURITY.md) 與 [公開開發契約](docs/development_contract.md)。物件責任見 `docs/product_object_model.md`；錯誤必須可見，不能以空資料掩蓋失敗，見 `docs/no_silent_failure.md`。新增測試使用合成資料；既有公開工商 fixture 也保留在完整回歸中。不得提交真實客戶、會計資料或私人操作紀錄；新測試與截圖使用合成資料。

版本差異見 [CHANGELOG](CHANGELOG.md)；較早的功能與 EXE 證據見 [v0.31 歷史 README](https://github.com/yung13yubabie/taxops-control-desk/blob/v0.31.0/README.md)。UI 文件中的 v032 只表示移植來源基底，不是本候選版號。
