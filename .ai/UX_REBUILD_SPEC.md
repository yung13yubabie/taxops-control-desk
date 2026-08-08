# Enterprise Desktop UX Rebuild Spec

資訊架構、操作層級、空狀態與資料密度的重建。不是配色調整——判準是：改完之後使用者一天
重複操作數百次是否更快，而不是畫面是否更好看。

Baseline: `feature/v030-annual-workbench`, v0.32.0 test build, commit `1a0d0a0`.
前置規範：`docs/no_silent_failure.md`（狀態模型的權威定義）、
`docs/product_object_model.md`（物件責任）、`.ai/UI_REDESIGN_AUDIT.md`（畫面盤點）。

## 頁面母版：三個，不是四個

母版是 deep module——小介面（頁面宣告資料與動作），大實作（版面、狀態、空狀態、contextual
actions 藏在裡面）。判斷一個母版是否該存在，用實際使用者數量：

| 母版 | 使用者 | 狀態 |
| --- | --- | --- |
| List–Detail | 客戶、案件、待辦、訊息模板、附件、資料夾（≥6） | 建立 |
| Editor | 編輯客戶、模板編輯、固定開立方案（≥3） | 建立 |
| Workspace | 年度工作檯、協作管理（2） | 建立 |
| Record Detail | 年度工作明細（1） | **不建立** |

Record Detail 只有一個使用者。抽出來會是 shallow module——介面與實作一樣複雜，卻沒有第二個
呼叫端攤提學習成本。年度工作明細直接實作其結構；第二個 Record Detail 出現時再抽。

`widgets/page_shell.py` 與 `widgets/inspector.py` 已通過 deletion test：刪掉它們，複雜度會
在 13 個頁面重現。母版建立在它們之上，不另起一套。

## QueryState：狀態是一個值，不是四個布林

六種狀態必須能被單一型別表達，否則頁面會用 `if rows: ... elif loading: ...` 的組合來猜，而
error 與 empty 必然在某條分支上合流。

```python
@dataclass(frozen=True)
class QueryState:
    kind: Literal["loading", "success", "empty", "no_results", "stale", "error"]
    rows: tuple[object, ...] = ()
    error: LoadFailure | None = None      # kind == "error" | "stale" 時必有
    last_success_at: str | None = None    # kind == "stale" 時必有
    query: str = ""                       # 用來區分 empty 與 no_results
```

規則：

- `empty` 只在查詢成功且 `count == 0` 且無搜尋條件時產生。
- `no_results` 在查詢成功、`count == 0`、有搜尋或篩選條件時產生。
- `stale` 保留上一次成功的 `rows`，同時帶 `error` 與 `last_success_at`。
- `error` 的 `rows` 必為空，且 UI 不得呈現任何資料列。

頁面只需要一個方法：`render_state(state)`。介面小，實作大。

**這個型別就是測試 seam。** 測試注入 `QueryState(kind="error", ...)` 即可斷言 UI 顯示錯誤而
非空狀態，不需要真的弄壞資料庫。「測試必須確認 error 不會被 render 成 Empty」由此成為可寫的
斷言，而非人工檢查。

## 密度規格

寫入 `tokens.py`，頁面從那裡讀值。

| 元素 | 值 |
| --- | --- |
| sidebar 展開 | 240–260（現行 220，調整為 248） |
| list pane | 300–380 |
| table row（純文字） | 40–44 |
| entity list row | 48–52 |
| input | 36–40 |
| button | 32–36 |
| section gap | 24 |
| field row gap | 10–12 |
| panel radius | 8 |

目標是 Dense Professional Desktop UI：資訊密度高、掃讀快。不使用大型 dashboard card、
gradient、glassmorphism。

## 狀態呈現的視覺分離

selection、hover、keyboard focus 三者現在共用亮藍框，必須分開：

- **selected row**：淡色背景 ＋ 左側 2–3px accent indicator，不用外框。
- **hover**：更淡的背景，無 indicator。
- **keyboard focus**：focus ring，只在鍵盤操作時出現。

## 欄位寬度：依內容長度決定

短欄位用固定或最大寬度，讓橫向空間留給真正需要的欄位：

| 欄位 | 寬度 |
| --- | --- |
| 客戶代號、狀態 | 固定 120 |
| 統一編號、電話 | 固定 140 |
| 簡稱 | 最大 200 |
| 客戶名稱、Email | 最大 320，可延伸 |
| 地址、備註、特殊要求 | 全寬 |

View mode 顯示文字，不用 disabled input 模擬。只有進入 Edit mode 才成為 input。

## 四個畫面

### 1. 客戶管理（List–Detail）

左側列表只負責定位：**客戶代號 ＋ 簡稱**。統編、全名、聯絡人、電話、備註都移出列表。

右側摘要負責理解，採 2–3 欄 compact information grid；地址、Email、特殊備註才用全寬。
加入關聯資訊摘要：租約數、年度工作數、案件數、附件數——每個都是可點擊的入口。

摘要不使用「一個 label 一行、一個 value 一行」的垂直排列。

### 2. 年度工作檯（Workspace）

頂部：年度、工作類型、狀態、客戶搜尋。加 compact summary strip 顯示工作數、未開始、
進行中、逾期——是一條文字帶，不是 KPI cards。

左側列表：客戶、工作名稱、主要期限、狀態。
右側摘要依資訊群組：工作身份、期限、狀態、關聯案件、核心帳務。

contextual actions：開啟、編輯、複製下一年度、取消／封存。刪除進 overflow menu 並顯示
影響範圍（會連帶影響幾筆交易、幾個案件）。

`逾期` 的定義仍待確認（`.ai/DECISIONS.md` 2026-08-08）。在答案出現前，summary strip 顯示
可算的項目，不顯示逾期。

### 3. 年度工作明細

頁首：工作名稱、客戶、年度、主要狀態、primary actions。
以下 tabs：概覽、交易、帳務核對、案件、文件、活動紀錄。

概覽用 definition grid（label–value 對），不用 input。狀態依群組呈現，不是所有欄位同一
視覺重量。

### 4. 協作管理

評估合併為年度工作明細的「案件」tab，而不是另開視窗。資訊模型是
**客戶 → 年度工作 → 案件 → 文件／待辦**，不是資料庫表格層級的視窗化。

無案件時顯示 Empty State，說明目前沒有案件並提供「建立第一筆案件」「連結既有案件」。
不 render 空 DataGrid、不 render 灰掉的按鈕、不 render「尚未選取案件批次」的佔位面板。

選取案件後才出現案件的 contextual actions；選取文件項目後才出現文件的。**沒有 selection
的動作不顯示，而不是顯示為 disabled。**

## 每個畫面完成後的自查

七問，逐題回答並寫進報告：

1. 使用者第一眼知道主體是誰嗎？
2. 知道當前最重要的狀態嗎？
3. 知道下一步可以做什麼嗎？
4. 沒有資料時是否仍提供下一步？
5. 是否存在未充分利用的水平空間？
6. 是否存在因 backend schema 而生、對使用者無價值的欄位或按鈕？
7. 是否存在 3 個以上連續 disabled actions？

第 7 題答「有」時，重新設計 context，不調樣式。

## No Silent Failure 分批計畫

246 處 `except Exception`，59 個檔案。由資料來源往外分批，每批附測試，每批獨立 commit。

| 批次 | 範圍 | 數量 |
| --- | --- | --- |
| B1 | `repositories/` 全部 | ~3 |
| B2 | `services/annual_work.py` | 21 |
| B3 | `services/work_records.py`（已修 1 處）、`annual_transactions.py` | 13 |
| B4 | `services/backup.py`、`export.py`、`attachments.py` | 11 |
| B5 | `services/` 其餘 | ~12 |
| B6 | `ui/workers/` | ~2 |
| B7 | `ui/` 顯示層 | 其餘 |

每批的流程：

1. 逐處套用 `docs/no_silent_failure.md` 的三題判準。
2. 合法的 optional value 加一行註解說明為何合法，不改行為。
3. 不合法的轉為 typed error，並在 `i18n/errors.py` 補人類可讀訊息。
4. 為每個轉換寫測試，斷言**後果**而非回傳值形狀。
5. 跑該批觸及的既有套件。

B7 是顯示層，多數 `except Exception: pass` 是 Qt 物件生命週期防護（widget 已銷毀時忽略
signal），屬合法；該批的產出主要是註解而非行為變更。

## 不變更

業務邏輯、資料庫語意、稽核流程、權限規則、法定計算。這是介面與錯誤處理工作。任何觸及
上述的需求，記錄為待確認而不自行決定。

## 測試執行

本機記憶體不足以單一程序跑完整套件，必須 per-file 程序隔離——見 `.ai/HANDOFF.md`。
