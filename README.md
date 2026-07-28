# TaxOps Control Desk

TaxOps Control Desk 是面向臺灣記帳士／會計師事務所的 Windows 離線桌面工作台。資料預設保存在本機 SQLite，不需登入雲端服務；GCIS 線上補查是可選功能，不影響離線核心流程。

目前版本：`v0.30.0`。本專案已是可執行應用，不是規格骨架。

## 主要功能

- 客戶、案件、索件、任務與工作紀錄管理
- 客戶年度工作台、年度制度預覽、工作明細與收支交易帳
- 固定開立方案、待開立紀錄、批量核對與確認退回
- 客戶特殊要求／備註全文檢視與篩選
- 官方登記資料本機快取、同名多筆選擇與 GCIS 統編補查
- 訊息模板、附件、備份還原與稽核紀錄
- Windows EXE 封裝與啟動 smoke test

## v0.30.0 重點

- 每位客戶每個作業年度只有一個年度工作母體；制度預覽與年度工作台雙向聯動，工作、申報、文件、稅額與服務費狀態分開管理。
- 年度工作明細可編輯、完成、取消、還原與重新開啟；交易帳以正式明細推導應收、已收、代墊與未結餘額。
- 「協作管理」直接連到正式案件、索件、附件與待辦資料；索件選項、附件與待辦均採有上限分頁，可抵達第 201 筆以後的真實資料。
- 索件新增或刪除會立即同步附件範圍；讀回失敗時鎖定異動並提供只讀重試，避免假成功與重複送出。
- 封存附件與刪除年度待辦必須再次確認，並核對精確資料庫 ID 與稽核 target。
- 900×540 協作視窗使用可捲動頁籤，避免 Qt 以內容大小偷偷撐高視窗造成裁切。
- 客戶主檔分開保存登記／聯絡地址、多筆租約與產業資料；歷史附件保留 owner guard，不會跨客戶或跨案件洩漏。

## 驗證狀態

- 全專案 branch coverage 門檻：`90%`
- v0.30.0 發佈候選必須重新完成完整測試與 branch-aware coverage
  `>= 90%`；不得沿用 v0.29.0 的數字。
- 自動化 EXE smoke 只驗證啟動與本機資料庫建立；視覺、縮放、長時間操作與實際事務所流程仍需人工驗收。

## 開發與驗證

開始工作前依序閱讀：

1. `.ai/spec-kit.md`
2. `.ai/CURRENT_STATE.md`
3. `.ai/TASKS.md`
4. `.ai/DECISIONS.md`
5. UI 工作再讀 `.ai/DESIGN.md`

常用命令：

```powershell
python -m pytest
python -m coverage run -m pytest
python -m coverage report --precision=2
python -m taxops
python -m build_tools.clean_package
python -m build_tools.package_windows
python -m build_tools.smoke_test_exe
```

Windows 封裝與人工驗收項目請見 `docs/packaging_checklist.md`。正式發佈檔附在 GitHub Release；repo 內的 `dist/` 是本機建置輸出，不應視為永久下載來源。

## 品質原則

- 不以直接呼叫內部 helper 取代真實按鈕／對話框／資料庫路徑驗證。
- 失敗必須有可見訊息；測試或建置失敗不得描述為成功。
- 會計狀態變更保留稽核軌跡；批次操作需具備交易一致性與冪等保護。
- 不把本機絕對路徑、帳密、token 或客戶資料寫入 repo 與 release notes。
