# DECISIONS

> [已確認] 2026-05-09 交接整理註記：本輪只補充每項長期決策的「不應再重複討論、待驗證風險、證據來源」欄位；沒有新增暫定方案為正式決策。

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
- 證據來源：[已確認] 使用者對話；`.ai/DESIGN.md`; 本機 reference path `C:\Users\LIN\.codex\references\awesome-design-md`.
