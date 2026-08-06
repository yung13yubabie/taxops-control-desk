# DECISIONS

## 2026-08-06 - 工作型物件的職責邊界與單一事實來源

### 決策

系統中帶有「狀態、期限、下一步」語意的物件，職責固定如下，不得互相取代：

| 物件 | 資料表 | 職責 |
| --- | --- | --- |
| 年度工作 | `annual_work_items` | 法遵與年度例行工作的主控項目，是該年度該客戶合規狀態的唯一事實來源 |
| 案件 | `engagements` | 對客戶交付的具體業務案件，是各工作型物件唯一的共同交會點 |
| 待辦 | `workflow_tasks` | 跨案件的個人短期行動，不保存完整業務流程 |
| 流程範本 | `workflow_templates_v2` | 案件或年度工作可套用的步驟模板，不自成另一套案件 |
| 流程執行 | `workflow_runs` | 範本的一次套用紀錄 |
| 固定開立 | 固定開立方案與待開立紀錄 | 獨立的週期性開立排程 |

期限的權威來源依物件而定：年度工作以 `annual_work_items.due_date` 為準（`suggested_due_date`
僅為系統建議，見 2026-07-18 決策）；待辦的 `due_date` 只約束該筆個人行動，不代表法遵期限。

### 理由

實測目前的關聯狀態（2026-08-06，`feature/v030-annual-workbench`）：

- `annual_work_items.engagement_id` 可為 NULL，單向指向案件。
- `workflow_tasks.annual_work_item_id`（`_m0028`）建立了年度工作與待辦的雙向連結，
  `AnnualWorkService.create_linked_task` 會驗證兩者的客戶與案件一致，不一致則拒絕。
- `workflow_runs` 只連到 `client_id` 與 `engagement_id`，與年度工作之間沒有任何欄位或
  服務層程式碼；其步驟狀態存在 `stages_json` 內，該表本身沒有 status 欄位。
- 固定開立與上述任何物件都沒有關聯。
- `AnnualWorkService.complete_item` 只更新 `annual_work_items.work_status`，
  不變更任何連結待辦的狀態。

因此「同一件營所稅結算申報同時出現在多處」是可能的，且完成其中一處不會同步其他處。
在職責邊界未寫明前，任何介面改動都只是把同一份模糊語意排得更整齊。

### 影響

- 年度工作是法遵狀態的唯一事實來源。介面呈現法遵狀態時必須讀年度工作，不得改讀待辦或流程執行。
- 待辦不得再擴充為第二套業務流程系統；`next_step` 是自由文字備註，不是流程步驟的資料結構。
- 流程執行在下列問題有答案前，不得新增功能：

  - `[NEEDS CLARIFICATION]` 年度工作完成時，連結待辦是否應一併完成？目前不會，兩者狀態可長期矛盾。
  - `[NEEDS CLARIFICATION]` 流程執行狀態是否應回寫年度工作或案件？目前完全不回寫。
  - `[NEEDS CLARIFICATION]` 流程執行的步驟與待辦子項是否為同一概念？目前是兩套獨立資料結構。
  - `[NEEDS CLARIFICATION]` 流程圖片屬正式作業指引或單純附件？決定它是否需要版本與稽核。

- 上述問題屬產品意圖，不得由實作端自行假設。

## 2026-07-31 - Qt coverage evidence uses explicit process isolation

### Decision

QObject test doubles connected to production `deleteLater()` must consume
their own `DeferredDelete` event while the owning widget is still alive. The
full Windows branch-coverage run may split Qt-heavy test files across fresh,
sequential Python processes and append one coverage database, but it may not
omit tests or accept a native crash as a pass.

### Rationale

Two controlled worker doubles left deferred deletes behind. A later registry
test's legitimate global cleanup then triggered a PySide6 native abort. One
long process therefore mixed product coverage with stale native test state.

### Impact

Release evidence records file count and passed-test totals for every segment,
then applies one branch-aware fail-under gate to the merged data. Test doubles
that emit `finished` require explicit lifetime assertions.

## 2026-07-31 - Acceptance ZIP must prove the extracted EXE path

### Decision

Windows acceptance requires both build-tree EXE smoke and a second smoke from
a freshly extracted delivery ZIP. Both use isolated `LOCALAPPDATA`, remain
alive through the startup interval, and verify the latest schema migration.

### Rationale

Checking only that a database file exists, or only running the pre-ZIP EXE,
can report success for an old schema or a broken archive.

### Impact

Packaging handoff includes ZIP entry readback, forbidden-path scan, checksum,
extracted-EXE startup, latest-migration evidence, and an explicit manual UI
boundary.

## 2026-07-28 - Annual collaboration reuses formal workflow data

### Decision

The annual workbench does not create parallel request, attachment, or task
records. It links one annual item to a formal engagement and uses the existing
request, attachment, and workflow-task services with their original SQLite
IDs. Every unbounded-looking UI list is exposed through count plus bounded
pagination.

### Rationale

Parallel tables or UI-only success state would diverge from the application's
normal pages and could produce false success, duplicate work, or missing audit
evidence.

### Impact

Changes made from either the annual workbench or the normal workflow pages are
visible after readback. A committed operation whose readback fails must lock
mutation controls and offer retry without resubmitting.

## 2026-07-28 - Fixed desktop size uses reachable scroll containers

### Decision

The annual collaboration dialog has a real 900x540 minimum and hosts the
request, attachment, and task pages in widget-resizable scroll areas.
Destructive attachment archive and annual-task delete actions require explicit
confirmation.

### Rationale

Qt child size hints previously expanded the shown dialog beyond the advertised
height, hiding the fixed-desktop failure from coordinate-only tests.

### Impact

Geometry tests must assert the actual shown window size. Content may scroll,
but actions must remain reachable without silently expanding or clipping the
window.

## 2026-07-18 - Compliance deadlines remain explicit suggestions

### Decision

Annual compliance generation stores only deterministic suggested dates for
the ordinary rules represented in the code. It does not infer holiday
extensions, network-fetched changes, or client exceptions. Verified
special-fiscal-year corporate-income-tax and undistributed-earnings windows
use the month ending the fifth month after fiscal year-end; provisional-tax
windows use the month ending the ninth fiscal month. The fiscal start year is
derived backward from the operation year so every suggested date occurs in
that workbench year.

### Rationale

The Ministry of Finance guidance defines these non-calendar filing windows,
while the exact holiday extension can vary. Encoding the verified base window
but not an inferred extension keeps offline generation useful, reproducible,
and independent of current network state.

### Impact

Generated dates are planning aids rather than legal guarantees. A future rule
change requires explicit source review and regression-test updates; holiday or
client-specific extensions must not be introduced as implicit date arithmetic.

## 2026-07-12 - Fixed-billing plan delete preserves issued history

### Decision

The UI exposes a physical `刪除方案` action. A plan may be physically deleted
only when it has no confirmed occurrence. The plan, its lines, pending rows,
and audit record are one SQLite transaction. Confirmed history blocks deletion
instead of being silently removed or converted to an archive.

### Rationale

The user explicitly wants delete rather than archive, while issued history is
accounting evidence and must remain immutable. Transactional deletion prevents
partial data and false success.

### Impact

Schedule edits reconcile only mutable pending occurrences. Confirmed, skipped,
and cancelled rows are preserved. A future force-delete feature requires a new
explicit retention decision.

## 2026-07-12 - Batch reconciliation confirms exact pending selections

### Decision

Batch reconciliation validates every selected pending occurrence before any
write, then confirms all rows atomically using the line amount and scheduled
issue date. Any invalid row or audit failure rolls back the whole batch.

### Rationale

Partial confirmation would create duplicate work and a false-success state.

### Impact

This feature records that invoices were checked as issued; it is not an
accounts-receivable or payment reconciliation ledger.

## 2026-07-12 - GCIS is an official per-tax-id online fallback

### Decision

GCIS online lookup remains separate from the MOF BGMOPEN1 offline cache. It is
an HTTPS/domain-allowlisted, bounded, per-tax-id lookup for company, business,
and branch registration. The application does not scrape public query pages.

### Rationale

GCIS and MOF have different coverage and semantics. Some GCIS detail endpoints
require agency IP authorization, which must be shown as an authorization error
instead of being misreported as not found.

### Impact

Full nationwide offline GCIS data still requires a separate schema/importer.
Network, malformed response, redirect, size, and authorization failures remain
visible and never produce a success result.

## 2026-06-07 - Recurring billing line delete semantics

- A recurring billing line delete is a soft deactivation, not a physical delete.
- Pending occurrences for that line are cancelled in the same service
  transaction, because they are no longer valid after the line is removed from
  the active contract.
- Confirmed occurrences remain as audit/history; they must not be rewritten by
  a later line deletion.
- The UI must expose edit/delete on the line itself, not only on generated
  occurrence rows.

## 2026-06-07 - Fixed billing is not accounts receivable

- `recurring_billing_occurrences.status = 'pending'` means the scheduled invoice
  occurrence has not been confirmed as issued.
- It must not be presented as customer debt or an unpaid invoice.
- Client master remains the owner of stable client identity/contact fields, but
  mutable balances must not be copied onto the client row.
- A future debt-collection feature requires a separate receivables/payment
  ledger and explicit payment reconciliation.
- Until that ledger exists, message templates may remind users about pending
  fixed-billing issuance only.

> [已確認] 2026-05-09 交接整理註記：本輪只補充每項長期決策的「不應再重複討論、待驗證風險、證據來源」欄位；沒有新增暫定方案為正式決策。

## 2026-05-29 - Remove Dashboard/Control Panel

### Decision

The dashboard/control-panel feature is removed from the app UI and service wiring. Sidebar navigation is now the only primary module entry path.

### Rationale

The control panel duplicated the sidebar and created two perceived paths into the same modules. Removing it lowers UI ambiguity and maintenance surface.

### Impact

Do not reintroduce `PAGE_DASHBOARD`, `DashboardPage`, `DashboardService`, `DashboardRepository`, a dashboard dock, or `ui.dashboard_dock_visible` without a new explicit product decision.

## 2026-05-29 - Payment Follow-Up Belongs To Client Context

### Decision

Payment/debt follow-up data is treated as client-led receivables context, with optional case/document links later. Message templates can render payment variables from client-scoped recurring billing occurrences.

### Rationale

Debt can span multiple cases, so putting it only under case management would fragment the receivable view and create wrong collection messages.

### Impact

First implementation adds `payment_follow_up` templates and variables derived from client recurring-billing data. Future richer ledgers should still keep the client as the primary owner and expose filtered views inside cases.

## 2026-05-29 - GCIS Data Must Be Separate From MOF Tax Cache

### Decision

MOF `BGMOPEN1.zip` remains the tax-registration cache source. Nationwide company/business registration and business-item data should be modeled as a separate MOEA/GCIS integration.

### Rationale

Official GCIS Swagger exposes company/business registration and business-item APIs that are different in fields, query shape, and data semantics from BGMOPEN1.

### Impact

Do not extend the current BGMOPEN1 importer by mixing GCIS rows into `tax_registry_cache`. Add a separate schema/importer when full company/business registration data is implemented.

## 2026-05-28 - [已被 2026-05-29 決策取代] Dashboard Is A Sidebar Summary, Not A Separate Workflow

### Decision

控制台是側邊欄模組的精簡摘要版。控制台 rows 必須與 `NAV_ORDER` 對齊；點擊控制台 row 等同點擊側邊欄同一模組，不得暗中套用不同 filter 或走另一套頁面狀態。

### Rationale

使用者明確指出控制台項目與側邊欄代表同一種入口，但點擊後呈現兩條線，造成使用者理解成本與狀態不一致。

### Impact

- Dashboard row navigation emit `(page_id, "")`。
- 空 filter 導航必須清除目標頁既有 filter，與 sidebar 導航一致。
- Dashboard 可顯示摘要數字，但不得讓摘要卡片變成另一套 workflow。

## 2026-05-28 - [已確認] Five-Slice Delivery Roadmap For Next UI/Workflow Work

### Decision

接下來採 5 個可交付 slice：

1. v0.16.0 Dashboard/Sidebar 一致化。
2. v0.17.0 案件 + 索件 UX 重構。
3. v0.18.0 待辦 UX + 下一步子待辦。
4. v0.19.0 工作紀錄：流程 + 錯誤回顧。
5. v0.20.0 工作紀錄：畫布筆記。

### Rationale

此順序先解決目前最高痛點（導航一致性、案件/索件、待辦），再進入資料模型較大的工作紀錄與畫布筆記，降低技術風險與單次變更負擔。

### Impact

每個 slice 需各自完成實作、測試、code simplification、code review、`.ai` 更新；完整交付前仍需 full suite、EXE smoke 與人工 Windows UI 驗收。

## 2026-05-28 - [已確認] Work Records Context Linking Rules

### Decision

「工作紀錄」模組的流程、筆記、錯誤回顧共用 context linking：

- 可綁 `client_id`。
- 可綁 `engagement_id`。
- 可全域（兩者皆空）。
- 若綁案件，系統自動推導客戶，不允許手動選到不一致的客戶。
- 允許改綁。
- 軟刪客戶/案件時保留關聯，UI 顯示已封存/已刪除；同時儲存 `context_snapshot` 供未來永久刪除或解除綁定後保留可讀脈絡。

### Rationale

使用者需要筆記、流程、錯誤回顧能在客戶/案件頁反向調閱；自動推導客戶可避免 dirty data。

### Impact

後續工作紀錄資料表與共用 Context Selector UI 必須遵守此規則。

## 2026-05-28 - [已確認] Workflow Templates And Runs Are Separate

### Decision

流程分頁需分成流程範本與執行中流程：

- Template 保存 SOP 結構、stages、items、version。
- Run 是從 template 建立的執行快照，可綁客戶/案件/全域。
- Run items 保存 checked 狀態、完成時間、備註與本地修改。
- Run 可臨時新增/修改/刪除步驟。
- 使用者可將目前 Run 整包覆蓋回原範本（template version +1），或另存為新範本；不做主管審核、不做 diff。

### Rationale

範本與執行狀態混在一起會造成版本與執行中案件混亂。單人本機模式下，直接覆蓋或另存最符合效率需求。

### Impact

v0.19.0 實作時需建立 template/run/stage/item 層次，並確保既有 run 不受 template 後續修改自動影響。

## 2026-05-28 - [已確認] Canvas-First Notes Instead Of Markdown Or QTextEdit Notes

### Decision

筆記分頁不做 Markdown，也不採標準 QTextEdit Word-like 文件。第一版採 QGraphicsScene 畫布導向編輯器：

- 工作區可縮放/平移。
- 畫布中放置固定 A4 page frames。
- 資料庫存 scene JSON。
- 圖片實體存 `note_assets/` 本機資料夾，不存 SQLite blob。
- PDF 以 A4 page frames 逐頁 render。
- 第一版物件：`text_box`（受控 HTML 富文本）、`image`、`freehand`、`shape`（空心紅框 / 黃色螢光筆矩形）。
- 預設 8px grid snap。

### Rationale

使用者實際需求是自由排版、貼圖、手繪標記、直接輸出 PDF 報告；Markdown 或純 QTextEdit 無法提供足夠直覺的報告編輯體驗。

### Impact

v0.20.0 需把筆記視為畫布場景與資產管理問題，而非文字文件問題。

## 2026-05-28 - [已確認] Error Reviews Close The Loop By Appending Guard Steps To Workflow Templates

### Decision

錯誤回顧第一版支援關聯流程範本，並可把防呆步驟追加到指定 stage 最後。追加後範本 version +1，錯誤回顧記錄 created template item id。

### Rationale

錯誤回顧的目標是把踩雷經驗轉成 SOP 防呆制度。第一版只做最快閉環，不做複雜 diff 或任意位置插入。

### Impact

v0.19.0 需實作錯誤回顧與流程範本的關聯，以及「追加防呆步驟」操作與測試。

## 2026-05-28 - [已確認] Engagements And Tasks Use Master-Detail Instead Of Wide Tables

### Decision

案件管理與待辦事項改為左側雙行清單 + 右側詳情/操作面板，不再以寬表格作為主要資訊架構。

### Rationale

使用者明確指出現有欄位排列太 RWD、上下文不足，尤其看不出項目屬於哪個客戶。雙行清單可顯示客戶/案件/狀態與關鍵次要資訊，右側詳情承載操作。

### Impact

v0.17.0 和 v0.18.0 需重構 UI，但保留既有服務與資料安全規則。右鍵欄位設定不再是這兩頁的核心互動。

## 2026-05-28 - [已確認] Document Requests Need A request_name Field

### Decision

索件批次新增正式欄位 `request_name`，不可再以 `period_name` 硬當使用者可讀名稱。新增索件批次時自動生成預設名稱，且可編輯。

### Rationale

`period_name` 是稅務期間，不是批次名稱。缺少 `request_name` 導致案件管理中的索件批次不可辨識。

### Impact

v0.17.0 需新增 migration、repository/service/input/UI/tests，並在索件批次清單顯示名稱、狀態、缺件數/總項目、截止日、催件次數。

## 2026-05-28 - [已確認] Task Next Step Creates A Context-Inheriting Child Task

### Decision

待辦的「下一步」不再只是純文字欄位。第一版新增「新增下一步」操作，從目前待辦建立子待辦：

- 自動繼承 `client_id`。
- 自動繼承 `engagement_id`。
- 設定 `parent_task_id = current_task.id`。
- 新待辦可追蹤、完成、逾期並出現在待辦列表。

### Rationale

純文字 `next_step` 無法追蹤與完成，也不會進入控制台或逾期邏輯。子待辦更符合工作流管理。

### Impact

v0.18.0 需新增 UI 與 service helper，並測試上下文繼承與 parent/child 限制。

## 2026-05-10 - [已確認] 放棄 Slice 2.5-B：客戶列表不顯示地址與財政部比對欄位

### Decision

使用者決定放棄「在客戶列表加入 address、match_status、matched_name、matched_address 欄位」。相關程式碼（`_COLUMN_ORDER` 擴充、match_repo block、status_labels match 區塊、container.match_repo 欄位）已全部回退。

### Rationale

UI 驗收後使用者認為該功能不符合當前優先順序；客戶列表維持原本 9 個欄位。

### Implication

- 客戶列表不顯示財政部名稱、地址或比對狀態。衝突審查仍透過 MismatchReviewDialog 進行。
- `match_repo` 仍作為 build_container() 內部區域變數，供 RegistryMatcher 使用；不再暴露於 ServiceContainer 欄位。
- 若未來重啟此功能，需重新實作上述 4 個欄位。



## 2026-05-08 - [已確認] MVP Scope Includes Full Section 24

### Decision

[已確認] The MVP must include every requirement listed in section 24 of the source specification.

### Rationale

[已確認] The product goal is to prevent impressive but unusable UI. A partial module-only MVP would not satisfy the intended first release definition.

### Impact

[已確認] Implementation may be phased for engineering safety, but the project must not claim MVP completion until all section 24 requirements are implemented and verified.

## 2026-05-08 - [已確認] No WSTP Backup Reading In MVP

### Decision

[已確認] The MVP does not include WSTP backup reading, WSTP reverse engineering, automatic filing, or automatic LINE/Email sending.

### Rationale

[已確認] The source specification explicitly excludes these areas, and they carry higher operational and compliance risk.

### Impact

[已確認] Any WSTP-related future work must be separately specified and approved.

## 2026-05-08 - [已確認] Tax Registration Source Uses Official Open Data

### Decision

[已確認] The MVP uses official sources:

- [已確認] Ministry of Economic Affairs GCIS open data APIs for business registry data.
- [已確認] Ministry of Finance `BGMOPEN1.zip` open dataset for tax registration cache.

[已確認] The app must not scrape the Ministry of Finance public query website in MVP.

### Rationale

[已確認] Official open data sources are more stable and appropriate for offline cache workflows than browser scraping.

### Impact

[已確認] The implementation must include provider interfaces, configurable official URLs, domain allowlisting, download metadata, and offline cache import.

## 2026-05-08 - [已確認] Tax Cache Bundle Excludes Customer Match Results

### Decision

[已確認] Tax registration cache bundles are not encrypted and must not include customer match results or internal customer data.

### Rationale

[已確認] The user does not want password-based encryption. To keep the bundle safe enough for practical handling, it must contain only government public data and metadata.

### Impact

[已確認] Customer match results are regenerated locally after cache import and stored in SQLite.

## 2026-05-08 - [已確認] Registry Match Results Are Stored And Regenerable

### Decision

[已確認] Customer-to-registry match results are stored in SQLite and can be regenerated when cache data changes.

### Rationale

[已確認] Persisting match results supports UI filtering, manual review, and auditability without repeatedly scanning large cache tables.

### Impact

[已確認] The schema must include `registry_match_results` or an equivalent table.

## 2026-05-08 - [已確認] Single Local User Mode

### Decision

[已確認] The MVP does not include login, roles, or permissions. Audit actor is fixed as `local_user`, with an optional display name in settings.

### Rationale

[已確認] The first user is a single local user. Role management would add complexity without immediate value.

### Impact

[已確認] Audit logs still record an actor, but there is no `app_users` requirement in MVP.

## 2026-05-08 - [已確認] Windows EXE Packaging Is Required

### Decision

[已確認] MVP completion includes a Windows executable build that can be tested during development.

### Rationale

[已確認] The target user may not run Python commands. Development also needs repeated EXE testing to catch packaging issues early.

### Impact

[已確認] Packaging commands, clean-package workflow, and smoke tests must be documented and implemented.

## 2026-05-08 - [已確認] Premium Simple UI Direction

### Decision

[已確認] The UI should prioritize a premium, simple, and clearly legible desktop workbench style. The project may reference the local `awesome-design-md` library, primarily Apple, Tesla, Linear, and Stripe style documents.

### Rationale

[已確認] The target user needs a trustworthy accounting-office operations tool, not a decorative demo. The selected references support restraint, clarity, and operational polish.

### Impact

[已確認] `.ai/DESIGN.md` is the project-owned design authority. External style references must not be copied directly and must not introduce brand names, logos, or trademarked identity.

## 2026-05-10 - [已確認] Wizard Back Navigation Uses History Stack

### Decision

[已確認] BulkImportWizard Back navigation uses `_step_history: list[int]` (push on advance, pop on back) instead of linear `current_step - 1` arithmetic.

### Rationale

[已確認] When step 3 (duplicate policy) is skipped via `_jump_to(4)` (no duplicates), step 3 must not appear in the Back chain. Linear arithmetic cannot express this; a history stack correctly omits any jumped step.

### Impact

[已確認] Any future wizard step additions must use `_advance_to(idx)` / `_jump_to(idx)` — never manipulate `_stack.setCurrentIndex()` directly without also updating `_step_history`.

## 2026-05-10 - [已確認] UI Style Applied Via style.py, Not External Skills

### Decision

[已確認] Global UI style is applied via `src/taxops/ui/style.py` using PySide6 QSS + QPainter icon generation. `/frontend-design` and `/huashu-design` skill invocations are not available in this environment.

### Rationale

[已確認] `~/.claude/skills/frontend-design/` and `~/.claude/skills/huashu-design/` directories do not exist. The user requested UI redesign; the closest feasible approach was a self-contained `style.py` module with a documented palette.

### Impact

[已確認] Future UI slice work should read `.ai/DESIGN.md` and `src/taxops/ui/style.py` before making visual changes. Do not attempt to invoke non-existent `/frontend-design` or `/huashu-design` skills.

## Non-Decisions

- [推測] Slice 3 (HTTP download + GCIS query) is the likely next implementation slice based on current TODO, but this remains unstarted and unconfirmed by the user for the next session.

## Decision Detail Matrix

### [已確認] MVP Scope Includes Full Section 24

- 決策內容：[已確認] MVP 必須包含來源規格第 24 節全部要求。
- 決策原因：[已確認] 使用者明確要求一次包含第 24 節全部功能，且核心目標是避免假 UI。
- 影響範圍：[已確認] 所有 slice 可分階段實作，但不可把部分 slice 宣稱為 MVP 完成。
- 不應再重複討論的內容：[已確認] 不要再把較小 slice 宣稱為 MVP 完成。
- 待驗證風險：[待驗證] 第 24 節全部功能尚未實作與驗收。
- 證據來源：[已確認] 使用者對話要求；`docs/implementation_spec.md`; `.ai/TASKS.md`.

### [已確認] No WSTP Backup Reading In MVP

- 決策內容：[已確認] MVP 不含 WSTP 備份讀取、逆向、自動申報、自動 LINE/Email。
- 決策原因：[已確認] 使用者確認回到第 24 節不做 WSTP 備份；來源規格亦排除。
- 影響範圍：[已確認] registry/tax cache 或其他未來 slice 不得偷加 WSTP 備份讀取。
- 不應再重複討論的內容：[已確認] 不要在 MVP 內加入 WSTP 備份讀取。
- 待驗證風險：[待驗證] 若使用者未來重新提出 WSTP 需求，需要重新規格化。
- 證據來源：[已確認] 使用者對話；來源規格第 24 節；`docs/implementation_spec.md`.

### [已確認] Tax Registration Source Uses Official Open Data

- 決策內容：[已確認] MVP 使用 GCIS open data 與 MOF `BGMOPEN1.zip`，不爬公示查詢頁。
- 決策原因：[已確認] 官方開放資料較適合離線快取流程；使用者確認採用。
- 影響範圍：[已確認] 需 provider/interface、官方 URL 設定、domain allowlist、metadata、offline import。
- 不應再重複討論的內容：[已確認] MVP 不應改成爬財政部稅籍登記資料公示查詢頁。
- 待驗證風險：[待驗證] GCIS endpoint subset 尚未確定；官方 URL 未來可能變更。
- 證據來源：[已確認] 官方來源查詢結果；`docs/registry_cache_workflow.md`; `src/taxops/security/domains.py`.

### [已確認] Tax Cache Bundle Excludes Customer Match Results

- 決策內容：[已確認] 稅籍快取包不加密，且不得包含客戶對照結果或內部客戶資料。
- 決策原因：[已確認] 使用者不要密碼；為降低風險，未加密包只能包含政府公開資料與 metadata。
- 影響範圍：[已確認] 客戶對照結果需在本機重新產生與保存。
- 不應再重複討論的內容：[已確認] 不要把客戶對照結果放進未加密快取包。
- 待驗證風險：[待驗證] 快取包 manifest、hash 驗證、staging rollback 尚未實作。
- 證據來源：[已確認] 使用者選擇方案 A；`docs/registry_cache_workflow.md`.

### [已確認] Registry Match Results Are Stored And Regenerable

- 決策內容：[已確認] 客戶與登記/稅籍資料的對照結果保存於 SQLite，且可重新產生。
- 決策原因：[已確認] 使用者明確同意保存到資料庫但可重新產生。
- 影響範圍：[已確認] 後續 schema 需包含 `registry_match_results` 或等效表。
- 不應再重複討論的內容：[已確認] 不要改成每次即時計算且完全不保存，除非重新決策。
- 待驗證風險：[待驗證] 表與比對規則尚未實作測試。
- 證據來源：[已確認] 使用者對話；`.ai/CURRENT_STATE.md`; `docs/registry_cache_workflow.md`.

### [已確認] Single Local User Mode

- 決策內容：[已確認] MVP 不做登入、角色、權限；audit actor 固定 `local_user`，設定可有顯示名稱。
- 決策原因：[已確認] 使用者明確表示只有自己用。
- 影響範圍：[已確認] 不建立 `app_users` 作為 MVP 必要需求。
- 不應再重複討論的內容：[已確認] 不要在 MVP 加入登入/角色/權限系統。
- 待驗證風險：[待驗證] 未來多人使用時需另行 migration 或設計。
- 證據來源：[已確認] 使用者對話；`src/taxops/repositories/app_settings.py`; `.ai/DECISIONS.md`.

### [已確認] Windows EXE Packaging Is Required

- 決策內容：[已確認] MVP 完成標準包含 Windows EXE，可於開發時測試。
- 決策原因：[已確認] 使用者需要開發時測試 EXE，也面向不一定會跑 Python 指令的一般使用者。
- 影響範圍：[已確認] 需要 packaging commands、clean workflow、smoke tests。
- 不應再重複討論的內容：[已確認] 不要把 MVP 視為只需 `python -m taxops` 可跑。
- 待驗證風險：[待驗證] PyInstaller 實作與 EXE smoke 尚未完成；字型渲染需驗證。
- 證據來源：[已確認] 使用者對話；`docs/packaging_checklist.md`.

### [已確認] Premium Simple UI Direction

- 決策內容：[已確認] UI 方向為高奢、簡潔、清楚明瞭；`.ai/DESIGN.md` 是實作權威。
- 決策原因：[已確認] 使用者要求優先參考本機 `awesome-design-md`，但要清楚可用。
- 影響範圍：[已確認] 所有 UI slice 需先讀 `.ai/DESIGN.md`。
- 不應再重複討論的內容：[已確認] 不要直接複製品牌名稱、logo 或品牌識別。
- 待驗證風險：[待驗證] 真實 UI 尚未完成桌面視覺驗收。
- 證據來源：[已確認] 使用者對話；`.ai/DESIGN.md`; 開發環境提供的設計參考資料。

## 2026-07-12 - 固定開立確認紀錄可退回但保留完整稽核快照

### 決策

已確認紀錄可由使用者明確退回待確認；退回會清除目前紀錄上的確認欄位，但必須先把原發票號碼、確認日期、金額、時間與備註完整寫入 audit。方案只有在目前不存在 confirmed 紀錄時才可永久刪除。

### 理由

事務所需要更正誤確認並刪除錯誤方案，但不能讓「確認 → 退回 → 刪除」成為抹去發票歷史的捷徑。

### 影響

任何未來的會計狀態回退都必須保存回退前快照；不得只記錄 target id 或結果狀態。

## 2026-07-12 - 大型登記名稱查詢不得在 UI thread 執行

### 決策

非 8 位統編的本機名稱查詢一律使用獨立 read-only SQLite worker，設定 10 秒 deadline，搜尋期間鎖住輸入並驗證 callback 的原查詢。GCIS 與本機查詢互斥。

### 理由

正式資料約 170 萬筆；同步 count、LIKE 或排序即使測試資料很快，也會在正式機造成假死。名稱索引在正式資料副本建立超過三分鐘未完成，因此不放入啟動 migration。

### 影響

未來名稱索引只能放在有進度、可取消的資料維護流程，不得於啟動時無提示建立。

## 2026-07-12 - 申報期限與異常工作以客戶為主體

### 決策

未來功能以 `client_id` 為必要歸屬，並可選擇連到案件或索件；異常狀態採事件／工作紀錄，不把所有流程欄位塞回客戶主檔。

### 理由

期限與例外需要在客戶總覽追蹤，同時保留案件脈絡、責任與歷史。

### 影響

功能尚未實作；後續規格需包含到期提醒、異常原因、處理人、解除時間、客戶篩選與 audit。
