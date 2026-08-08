# No Silent Failure / No Fake Empty

專案不可違反的 invariant：

> **Empty is a valid business state. Error is a system state.**
> 空集合只能代表「資料來源成功回應，且確認集合為空」。任何取得資料的失敗——unexpected
> None、schema 不符、timeout、資料庫錯誤、權限錯誤——都必須進入獨立的 error state，不得
> 轉成空值後照常 render。

這份文件是規範與審查依據。它記錄的是 **Python 與 PySide6 的實際模式**，不是 TypeScript
的 `.catch(() => [])`——那個語法在本專案不存在，照字面搜尋會得到零結果並得出「沒有靜默
失敗」的錯誤結論。

## 六種狀態必須分開

| 狀態 | 何時發生 | UI 呈現 |
| --- | --- | --- |
| `loading` | 查詢已送出，尚未回應 | 載入指示；**不得先 render 空表格** |
| `success` | 成功回應，`count > 0` | 資料 |
| `empty` | 成功回應，`count == 0`，且無搜尋條件 | EmptyState，說明尚無資料與下一步 |
| `no_results` | 成功回應，`count == 0`，但有搜尋或篩選條件 | 「查無符合條件」＋清除條件的動作 |
| `stale` | 重新整理失敗，但仍持有先前成功的資料 | 保留舊資料 ＋ 標示最後成功時間 ＋ 重新整理 |
| `error` | 取得資料失敗 | 錯誤說明 ＋ 可執行的恢復動作 |

`empty` 與 `no_results` 共用同一個「沒有資料」畫面是錯的：前者要引導建立第一筆，後者要
引導放寬條件。`error` 與 `empty` 共用同一個畫面是最嚴重的錯，因為它把系統故障說成業務
事實。

## Python 反模式對照

TypeScript 的模式在本專案的對應形式：

| TS 反模式 | 本專案的對應形式 |
| --- | --- |
| `.catch(() => [])` | `except Exception: return []` / `return ()` / `return {}` |
| `.catch(() => null)` | `except Exception: return None` |
| `?? []` · `\|\| []` | `value or []` · `dict.get(key, [])` · `getattr(obj, name, None)` |
| `catch {}` | `except Exception: pass` |
| silent `console.error` | `_log.warning(...)` 之後照常回傳空值，使用者看不到任何訊息 |
| ignored Promise rejection | `QThread` / worker 的 signal 只接成功路徑，錯誤 signal 未接 |
| 未檢查的 nullable response | repository 回傳 `Row \| None`，呼叫端直接當有值使用 |

## 判斷一處 fallback 是否合法

不要機械式刪除所有 fallback。逐處問三個問題：

1. **這個「空」是業務上真實可能的答案嗎？**
   `int("abc")` 失敗回傳 `None` 代表「這不是數字」——合法。
   `json.loads(stored_json)` 失敗回傳 `{}` 代表「資料損壞」——**不合法**，那是 INVALID_DATA。

2. **呼叫端能區分「沒有」與「讀不到」嗎？**
   若兩者拿到同一個回傳值，就無法區分，必須改為拋出具名例外或回傳明確的錯誤型別。

3. **使用者看得到失敗嗎？**
   只寫 log 不算。使用者必須看到保留操作語境的訊息（「客戶資料儲存失敗」而非「發生錯誤」）。

三題都通過才是合法的 optional value。任一題失敗，轉為 typed error。

## 實測現況（2026-08-08）

掃描 `src/taxops`：

- **246 處 `except Exception`，橫跨 59 個檔案。** 資料層約 60 處，其中
  `services/annual_work.py` 21 處、`services/work_records.py` 8 處、
  `services/backup.py` 6 處、`services/annual_transactions.py` 5 處。
- **已確認的 fake empty（錯誤被轉成空集合）：**

  | 位置 | 現況 | 判定 |
  | --- | --- | --- |
  | `services/work_records.py:104` | `except json.JSONDecodeError: return {}`，**無任何 log** | 違規。資料損壞被當成「沒有內容」，且無痕跡 |
  | `dialogs/mismatch_review_dialog.py:131` | `except Exception:` 記 warning 後 `return {}` | 違規。使用者看到「無差異」，真相是差異讀不出來 |

- **完全靜默的捕捉（`except ...: pass`）：** `annual_workspace_dialog.py:224`、
  `document_requests_page.py:1363`、`annual_workbench_page.py:423` 與 `:604`、
  `new_client_dialog.py:224`、`recurring_billing_page.py:721`、
  `recurring_billing_dialogs.py:349`、`single_instance.py:121`。
  其中部分是 Qt 物件生命週期防護（widget 已被銷毀時忽略），屬合法；需逐處標註理由。

- **合法的 optional，不要動：** `security/domains.py:24`（驗證回傳 False）、
  `widgets/date_field.py:68`（日期解析回傳 None，代表「不是有效日期」）、
  `templates_page.py:295`、`tasks_page.py:387`、`attachments_page.py:341`
  （皆為 `int()` 解析失敗回傳 None）。

## 審查優先順序

由資料來源往外，因為越靠近資料來源，錯誤被轉成空值後越難分辨：

1. `src/taxops/repositories/` — 資料庫存取
2. `src/taxops/services/` — 業務邏輯，特別是 `annual_work.py`、`work_records.py`、
   `annual_transactions.py`、`backup.py`
3. `src/taxops/ui/workers/` — 背景查詢，錯誤 signal 是否被接
4. `src/taxops/ui/` — 顯示層；此層多數 `except Exception: pass` 是 Qt 生命週期防護

## 寫入操作

Create、Update、Delete、Complete、Import、批次操作都需要 `pending` / `success` /
`error` 三態，並在資料庫確認成功前不得呈現為成功。

帳務資料避免 optimistic mutation。若使用，必須實作 rollback 並明確通知使用者。

成功必須有可感知的回饋；失敗不得只有 log。錯誤訊息保留操作語境。

## 批次操作

不得以單一 boolean 表示整批結果。回傳並顯示 `total` / `succeeded` / `failed` /
`skipped`，partial success 必須明確呈現，並可查看失敗項目。

`services/clients_bulk.py` 與索件批次操作是此規則的主要適用處。

## Schema validation

repository 或 API 回應的結構與預期不符時，視為 `INVALID_DATA`，不得用 `getattr` 預設值
或 `or {}` 把結構錯誤轉成空值。**unexpected None 不等於 empty。**

## Last Known Good Data

重新整理失敗但已有先前成功資料時，不清空畫面。保留舊資料、標示 stale 狀態與最後成功
更新時間，並提供重新整理。

## Logging

開發模式記錄 operation、entity、entityId、error type，足以定位。使用者介面不顯示
stack trace，只顯示可理解的訊息與恢復動作。

## 測試要求

Client、Annual Work、Case、Transaction、Attachment 五個核心流程，各需覆蓋：

- 成功且有資料
- 成功但空集合
- 搜尋後 0 筆
- 資料庫錯誤
- 無效回應（schema 不符）
- 寫入失敗
- 批次部分失敗
- 重新整理失敗但保留 stale 資料

每組測試必須斷言 **error 不會被 render 成 empty**——這是這批測試存在的唯一理由。

## Review blocker

以下情形在 code review 中直接退回，不接受「先合併之後再修」：

- `src/taxops/repositories/` 或 `src/taxops/services/` 中出現 `except ...: return []`、
  `return {}`、`return ()`、`return None`，而該空值無法與「查無資料」區分
- 新增 `except Exception: pass` 而未在同一行或上一行註明為何忽略是正確的
- 捕捉例外後只寫 log，未讓使用者知道操作失敗
- 批次操作回傳單一 boolean

## 尚未完成

這份規範已建立，但 **246 處捕捉點尚未逐一審查完成**。已確認並修正的只有本文件
「實測現況」列出的部分。其餘依上述優先順序分批處理，每批附測試。

規範先行是刻意的：沒有判準之前逐處修改，只會把一種隨意換成另一種。
