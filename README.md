# TaxOps Control Desk

給台灣會計與稅務事務所使用的本機工作桌：管理客戶、案件、索件、附件、待辦及年度工作。資料存在本機 SQLite，核心工作不需登入雲端。

> **[v0.33.0-rc.1 候選版已發布](https://github.com/yung13yubabie/taxops-control-desk/releases/tag/v0.33.0-rc.1)**，可 [下載單一 EXE](https://github.com/yung13yubabie/taxops-control-desk/releases/download/v0.33.0-rc.1/TaxOpsControlDesk.exe)。這是未簽署的試用候選；Windows 乾淨離線驗收尚未完成，穩定版仍為 v0.31.0。

試用前請先看 [候選試用說明](docs/candidate_tryout.md)，使用空白測試環境，不要直接開啟正式工作資料。第三方元件的固定版本 [原始碼取得與替換說明](https://github.com/yung13yubabie/taxops-control-desk/blob/4b135c42a25bc64ade191095e7bce722cd2b8a08/assets/third_party_licenses/SOURCE_ACCESS.txt) 隨套件提供。

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
- 保留啟動期間再次開啟的要求，視窗準備完成後再顯示；完整傳送與分段接收有明確界線，已由本輪 Windows 單一 EXE 同步雙開測試回驗。
- 一般啟動讀寫失敗會顯示白話提示並停止開啟，不自動重建原資料；處理方法及本機診斷紀錄見[啟動資料恢復指引](docs/startup_storage_recovery.md)。
- 保留上游已修好的批次索件交易及附件複製失敗清理。
- 年度設定讀取失敗時禁止儲存，避免預設值蓋過原資料；指定客戶、待辦關聯與未存內容在重試或取消時保留。
- 長表單與展開說明可捲動，儲存／取消留在可見位置；日期填錯會回到該欄位，空白欄位補上用途提示。
- 操作提示、錯誤、空畫面與選檔視窗改用白話繁中；保留原本的客戶名稱、檔名與路徑。英文系統語言下的標準按鈕、月曆與選檔文字另有實際視窗檢查。

### 實際驗證進度

- 最新一般候選 [run 38352573945](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38352573945) 的兩個 Windows 工作均通過：完整 164 檔、4474 項全部通過，零失敗、錯誤、略過及未跑檔；原始合併行／分支覆蓋率為 91.17176972014165%，保留未四捨五入的 90% 門檻。
- 同一 EXE 已通過 18 項 frozen 檢查、同步雙開的一次啟用、受控外層退出碼 77 與同資料恢復、正常暫存清理、核心元件實載來源及同次獨立 Shell 分類。成品、七個帳冊圖示資源與精確來源重組材料均經獨立覆核。
- [固定材料重組 run 38355622300](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38355622300) 從上述實際匯出 kit 重新通過全部 164 檔、4474 項及原覆蓋率門檻，並以 MSVC／Ninja 真正編譯修改後 Qt qgif、嵌入修改後 PySide6.support，再執行重建 EXE 的完整 gate；workflow 與獨立成品覆核均通過。這份修改後 EXE 是工程重組證據，不另作日常試用版本。

一般 EXE／kit 的精確來源、大小、SHA-256 與重組結果集中在 [最新單檔與重組證據](docs/windows_onefile_gate.md#latest-normal-candidate-and-modified-component-proof)。這次文件更新發生在建置之後，不是 EXE 的建置來源，也不改寫原 kit。

較早的通知傳送、末端模組分類與 CMake 路徑失敗保留為 [歷史證據](docs/windows_onefile_gate.md#observed-simultaneous-start-failure)，不代表最新候選仍停在該階段。原 CRT/PySide 中止反例仍未解；新的受控中止模型通過不等於修好該原生異常。較早的資料夾 ZIP 也不替代本次單一 EXE。

[候選 Release](https://github.com/yung13yubabie/taxops-control-desk/releases/tag/v0.33.0-rc.1) 提供已核對的單一 EXE、與它相符的原始碼／重組 kit、SHA256SUMS.txt 及 TRYOUT-zh-TW.txt。kit 供有需要的接收者重建第三方元件，不是一般使用者的安裝前提。授權通知可在「資料與工具 → 設定 → 第三方授權」離線閱讀及匯出；完整範圍見 [第三方元件說明](docs/third_party_licenses.md)。

已知限制：Hosted Windows 測試不是乾淨離線 Windows 10/11 實機；人工 DPI、輸入法、列印、輔助功能及實際桌面／工作列釘選仍待驗；EXE 未簽署，也未驗收 SmartScreen 信任。原生 Windows 合成中文字形抽查已通過，但不代表所有姓名或字集；小尺寸月曆在 offscreen 第六週文字下緣仍略裁切。缺繁中翻譯檔時只有有限按鈕後備，EXE gate 仍要求完整翻譯資產。

可靠性契約見 [驗證紀錄](docs/reliability_latest_port.md)。完整逐檔獨立 process 與實值 coverage（含分支收集） **90%** 門檻保留；Linux 的既有 IPC 環境失敗仍如實標記，不能當作 Windows 結果。

已發布版本可在 [GitHub Releases](https://github.com/yung13yubabie/taxops-control-desk/releases) 核對。repo 的 `dist/` 是建置輸出，不是永久下載來源。`docs/v0.32.0_test_checklist.md` 記錄較早 內部測試建置，並非本輪驗收。

## 開發

維持 Python / PySide6 / SQLite，仍由 PyInstaller 封裝單一 EXE。CMake／Ninja／MSVC 用於選擇自行重建修改後 Qt 元件；CMake 也用於其建置腳本的來源測試，不是應用程式架構遷移，一般使用者不必安裝。安裝開發依賴後，用 `python -m build_tools.run_test_matrix --help` 查看參數，再執行逐檔測試與合併 coverage；Windows 發行套件使用隔離環境及 `requirements-release.txt` 固定版本。

在另一部 Windows 驗收既有 EXE 時，請使用同一份建置產物的完整收據；工具會在啟動 EXE 前列出缺件。材料與命令見 [跨主機驗收輸入](docs/onefile_acceptance_inputs.md)。

封裝工具將子程序的 DLL 搜尋路徑限定於既定工具來源，並以完整相依驗證處理可缺席的系統 API 合約檔案；實作界線及仍會拒絕的不同來源 bytes 見 [Windows 建置可攜性](docs/windows_build_input_portability.md)。這不是對任意 Windows 或編譯環境的相容保證。

開始改碼前閱讀 [CONTRIBUTING](CONTRIBUTING.md)、[安全政策](SECURITY.md) 與 [公開開發契約](docs/development_contract.md)。物件責任見 `docs/product_object_model.md`；錯誤必須可見，不能以空資料掩蓋失敗，見 `docs/no_silent_failure.md`。新增測試使用合成資料；既有公開工商 fixture 也保留在完整回歸中。不得提交真實客戶、會計資料或私人操作紀錄；新測試與截圖使用合成資料。

版本差異見 [CHANGELOG](CHANGELOG.md)；較早的功能與 EXE 證據見 [v0.31 歷史 README](https://github.com/yung13yubabie/taxops-control-desk/blob/v0.31.0/README.md)。UI 文件中的 v032 只表示移植來源基底，不是本候選版號。
