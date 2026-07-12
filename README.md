# TaxOps Control Desk

TaxOps Control Desk 是 Windows 離線桌面工作台。資料預設保存在本機 SQLite，不需登入雲端服務；GCIS 線上補查是可選功能，不影響離線核心流程。

目前版本：`v0.29.0`。本專案已是可執行應用，不是規格骨架。

## 主要功能

- 客戶、案件、索件、任務與工作紀錄管理
- 固定開立方案、待開立紀錄、批量核對與確認退回
- 客戶特殊要求／備註全文檢視與篩選
- 官方登記資料本機快取、同名多筆選擇與 GCIS 統編補查
- 訊息模板、附件、備份還原與稽核紀錄
- Windows EXE 封裝與啟動 smoke test

## v0.29.0 重點

- 固定開立歷史改為顯示完整當年度，不再只保留最近 90 天；跨年度仍建議後續加入日期範圍選擇器。
- 已確認紀錄可明確「退回待確認」，清除確認欄位並保留稽核紀錄；方案仍需先解除確認紀錄才能刪除。
- 客戶管理新增「只看有特殊要求／備註」與完整換行備註區。
- 登記名稱搜尋一律在背景執行，同名結果最多列出 50 筆供人工選擇；GCIS 與本機查詢互斥，避免競跑與舊結果殘留。
- 模板編輯器直接標示每類欄位的資料來源；帳款欄位目前是待開立排程，不代表實際收款帳。

## 驗證狀態

- 全專案 branch coverage 門檻：`90%`
- 本次完整測試：`1,454 passed`
- 本次量測：`90.35%` branch-aware total coverage
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
