# 新手工具表單修復（2026-10-12）

基底：bf1872b48f4403d0bbaea9576c9b476a4c4ca15a。Python/PySide6，僅 UI 與測試；未更動計算、下載、資料來源或預設業務值。

## 真 Qt 重現與修復

- 訊息模板：760×540 連續展開真實預覽與來源說明後，原 layout 強制擴高為 859。改為表單內容可捲動、儲存／取消固定在 footer；640×480 展開後仍維持原視窗大小。欄位名稱／內容增加可存取名稱，名稱範例只放 placeholder。
- 工商查詢：640×480 注入合成長中文名稱與地址後原視窗擴高為637。改為內容可捲動，短窗仍能捲至套用動作，不改本地查詢或 GCIS 執行。
- 固定開立：批量貼上原 minimum 680×520，改為520×380（偏好仍680×520）；文字輸入有可存取名稱、短窗仍可按確定／取消。方案、合約、明細、跳過原因增加範例或輸入說明；沒有新增選項或填入實際值。
- 流程模板：原 minimum680×520改為560×380（偏好680×520），說明換行、補名称範例與可存取名稱，原平台英文OK/Cancel改為儲存流程／取消。
- 設定：操作者名稱增加 placeholder，沒有更動既有儲存值／備份流程。

## 驗證

新增 `tests/test_novice_tool_forms.py`：5 passed，涵蓋模板雙展開＋固定footer＋取消、貼上短窗＋取消、流程重複空白驗證＋取消、工商長中文結果＋清空查詢、placeholder 不填入業務資料。

逐檔獨立 Qt process：模板38、固定開立dialogs25、固定開立page19、滯納金34+16、工作流程49、canvas28、設定29+1 skipped、工商18+36，共292 passed／1 skipped。另新增5項共297 passed。這是聚焦回歸，不是全套或 Windows EXE 驗收；canvas 是既有服務測試，不宣稱啟用尚未開放畫布UI。既有設定skip保持原條件。

Qt圖／geometry／完整log在本輪工作環境 `taxops-novice-tool-evidence`；截圖是 Linux offscreen 真 Qt widget，非 Windows DPI／螢幕閱讀器驗收。合成 SQLite／圖片由暫存目錄隔離，連線有close，沒有啟動下載worker或外網查詢。Ruff、git diff --check通過。未push、merge或release。
