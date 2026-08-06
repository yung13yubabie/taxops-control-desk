# CURRENT_STATE

## 2026-08-06 UI redesign stage one: design system (uncommitted)

- Worktree: `.worktrees/v030-annual-workbench` on `feature/v030-annual-workbench`,
  synced to `origin`, HEAD `e0c7db7`. All changes are uncommitted and no commit,
  push, tag, or release has been made. `git diff --check` is clean.
- The rebuild targets this branch, not `main`. `main` (v0.29.0) has no annual
  workbench, no compliance-profile dialog, and no lease editor, and the packaged EXE
  under `dist/` is v0.29.0. The screenshots correspond to this worktree's source.
- A verifiable design system now exists. `src/taxops/ui/tokens.py` holds colour,
  type, sizing, spacing, and radius tokens; `src/taxops/ui/style.py` composes the
  stylesheet from them and re-exports the legacy names pages already import.
- Buttons carry one of seven roles through a `role` dynamic property, applied by
  `src/taxops/ui/widgets/buttons.py`, which repolishes the widget so a role assigned
  after construction actually paints. The bare `QPushButton` rule is secondary, so
  nothing is brand blue by default.
- Each of the eleven navigation pages that owns a create-or-run action declares
  exactly one primary. Settings and recurring billing are deliberately exempt until
  their own stages. `DocumentRequestsPage` declares none because `EngagementsPage`
  embeds two instances of it.
- Checkbox and radio indicators are painted by the platform style again, so checked
  state shows a real tick. Measured: any box-model property on `QCheckBox`,
  `background-color: transparent` included, moves indicator painting into the
  stylesheet and drops the unchecked border from 64 painted pixels to zero.
- `src/taxops/ui/icons.py` provides a 39-role inline SVG set. Unknown roles raise
  `UnknownIconRole`. No Qt standard pixmap remains anywhere in `src/taxops/ui`.
- Type floor restored to the rule already in `.ai/DESIGN.md`: 14px body, 13px table
  headers. The sheet had shipped 13px body and 12px headers.
- Control heights land on their tokens now that box-model overhead is subtracted; a
  32px token previously rendered a 46px button.
- Sidebar is 220px expanded and 56px collapsed, keeps every module icon when
  collapsed, moves labels to tooltips, uses a 32x32 quiet toggle, and marks the
  active row with a left indicator instead of a saturated block.
- Inventory measured over `src/taxops/ui`: 35 `QDialog` subclasses, 306
  `QPushButton` references, 163 `QTableWidget`, 109 `QDialogButtonBox`, 47
  `QGroupBox`, 26 `QScrollArea` across 11 files, 24 `FlowLayout` across 9 pages, and
  101 inline `setStyleSheet` calls.
- Stage 2 added the shared page structure: `widgets/page_shell.py` (`PageHeader`,
  `ActionBar` with a five-action ceiling and overflow menu, `build_page_layout`),
  `widgets/inspector.py`, and a reworked `widgets/empty_state.py`. Ceilings raise at
  construction rather than relying on review.
- Stage 3 rebuilt the clients page as the master-detail template: header primary,
  action bar with search plus a 篩選 menu, six visible table columns, a `QSplitter`
  with an inspector, contextual actions in the panel, destructive actions behind 更多,
  notes and leases hidden until a row is selected, and chevron pagination.
- Tests: 50 design-system contracts, 22 page-shell and inspector contracts, 76
  clients-suite tests, and 127 UI-suite tests all pass.
  `python -m compileall -q src tests` passes and `git diff --check` is clean.
- **Full sequential suite: 2,733 passed, 0 failed, 1,769s (29:29).** That run began
  with only stage 1 in place and stages 2–3 landed during it, so it does not serve as
  the final regression; stage 16 must re-run it.
- Coverage has **not** been re-measured this round. The last recorded gate is
  90.1157% combined branch coverage over 2,682 tests across 112 independently
  executed files (2026-08-01).
- Unresolved risks: 101 inline `setStyleSheet` calls still override the role system
  per page, so those surfaces keep their old colours until stage two migrates them;
  the custom date picker is only partly addressed (icons and fill fixed, ±year
  buttons and the confirm step remain); double-scroll and modal-depth defects are
  untouched.
- No visual, DPI, or workflow acceptance is claimed. Automated geometry assertions
  are not a substitute for the running application at 100/125/150% scaling.
- Next work item: stage two — shared `PageHeader`, `ActionBar` with a five-action
  ceiling and overflow menu, `EmptyState`, and `Inspector`, replacing `FlowLayout`
  as a toolbar across nine pages. Full plan and screen register:
  `.ai/UI_REDESIGN_AUDIT.md`. Object ownership: `docs/product_object_model.md`.

## 2026-08-01 v0.30 manual-acceptance refresh

- The current worktree adds the requested office workflows: consistent client
  address widths, lease-count markers with collapsible details, an annual
  compliance-profile editor reachable from the annual workbench, atomic
  multi-client engagement creation, default task-column sorting, grouped work
  record/template/image panels with double-click zoom, and message-template
  previews sourced from a real selected client plus annual-workbench fields.
- A clean, sequential, branch-aware run passes all 2,682 collected tests across
  112 test files. It includes both real 65,963,079-byte BGMOPEN1 imports and
  measures 90.11569881344029% combined coverage (22,011 statements and 5,042
  branches). Evidence is `.ai/coverage-v031-clean-20260801.json`, SHA-256
  `6BCA83814AD714DCF33BABE410E6E037C33417E90A105D54DA23CA22FC5A8431`.
- Release dependency audit found `PYSEC-2026-3447` in setuptools 80.9.0. The
  exact release pin is now 83.0.0; `pip-audit` reports no known vulnerabilities.
  Plain-text Jinja templates also use `SandboxedEnvironment` in addition to the
  existing AST/variable allowlists. Bandit reports no Medium/High findings when
  B608 is excluded after manual confirmation that dynamic SQL identifiers are
  fixed fragments or allowlisted and all values remain parameterized.
- The final EXE is rebuilt in an isolated Python 3.11.9 environment with
  PyInstaller 6.11.1, PySide6 6.10.2, and setuptools 83.0.0. Build-tree and
  ZIP-extracted smoke both stay alive for eight seconds, create isolated
  SQLite, and apply migration `0028_annual_compliance`. FileVersion and
  ProductVersion remain `0.30.0.0`.
- Manual-acceptance artifact:
  `dist/TaxOpsControlDesk-v0.30.0-win64.zip` (50,116,927 bytes), SHA-256
  `39D09F530AE7FD42DA64103F814883D1AC4B0699454B4428CFA5C52D04204C7D`.
  All 191 files read back, exactly match the build tree, and contain no root
  source/test/private paths or user database files.
- `codex-security` was upgraded globally from 0.1.4 to 0.1.5, but three deep
  scan attempts failed before analysis because the inner scan agent did not
  create `scan-manifest.json`, `findings.json`, or `coverage.json`. Latest scan
  ID: `11e96785-ec4a-4065-83e0-a8c566cb4c8e`; status is `failed`, not passed.
- Visible mouse/keyboard behavior, SmartScreen, long-running production data,
  and 100/150/200% host-DPI rendering remain owner manual-acceptance items.

## 2026-07-31 v0.30 manual-acceptance candidate

- The annual workbench, client-year generation, editable annual detail,
  transaction ledger, formal engagement/request linkage, and annual
  collaboration tabs are implemented on `feature/v030-annual-workbench`.
- Annual collaboration uses the same SQLite IDs as the existing request,
  attachment, and task modules. Request options, attachments, and tasks are
  bounded and paginated; request #201 is selectable for attachment scope.
- Embedded request create/delete immediately refreshes the attachment selector
  and annual summary. Readback failures clear stale rows, lock mutations, and
  expose read-only retry without resubmitting the committed operation.
- The real shown collaboration dialog remains 900x540 and wraps each tab in a
  scroll area. Attachment archive and annual-task delete require confirmation.
- Ruff 0.15.15 is pinned. Compileall, `ruff check src tests build_tools`, and
  `git diff --check` pass.
- A clean branch-aware measurement passes at 90.18%: 2663 tests pass across
  111 test files, including the two real 1.7-million-row registry imports.
  Qt-heavy registry files run in fresh sequential processes so native object
  state cannot cross file boundaries; no test is omitted.
- Normal-entry and high-risk user-path smoke passes 92 tests. It exposed and
  fixed an app-stylesheet-only 13px annual-action regression that the earlier
  alphabetical full suite did not expose.
- A requirement-focused replay passes 368 data/service tests and 184 real Qt
  UI tests. It directly covers the split registered/contact addresses,
  atomic multiple leases, offline industry search/application, annual draft
  generation and custom rows, exact six-category tax/fee ledger balances,
  navigation, error feedback, and fixed-desktop geometry.
- Native Windows Qt rendering at the host's actual 125% DPI produces a
  1366x768 logical annual workbench (1708x960 physical pixels) with 34 real
  generated rows. Create/filter/refresh/detail/paging controls remain visible
  and inside the page. A 760x720 client edit dialog keeps registered and
  contact addresses reachable, scrolls to two leases, and retains fixed save
  actions. This is widget-render evidence, not owner mouse/SmartScreen
  acceptance or proof of 100/150/200% host settings.
- The v0.30.0 onedir EXE is built with isolated Python 3.11.9,
  PyInstaller 6.11.1, and PySide6 6.10.2. Both the build-tree EXE and the EXE
  extracted from the delivery ZIP stay alive for eight seconds, create an
  isolated SQLite database, and contain migration `0028_annual_compliance`.
  Windows reports FileVersion/ProductVersion `0.30.0.0`, ProductName
  `TaxOps Control Desk`, and OriginalFilename `TaxOpsControlDesk.exe`.
- Manual-acceptance artifact:
  `dist/TaxOpsControlDesk-v0.30.0-win64.zip` (50,095,302 bytes), SHA-256
  `C42ADDC2761C6748252D91B9B35F73F7952229A94F9CF082CA4DA559AE0F4E9A`.
  All 192 entries (191 files) read back; the archive exactly matches the build
  tree, and forbidden source/test/private paths are absent.
- Visible DPI, clipping, SmartScreen, long-running office workflow, and real
  user-data acceptance remain manual and must not be reported as complete.

## 2026-07-16 v0.30 implementation worktree

- Active work is isolated in `.worktrees/v030-annual-workbench` on
  `feature/v030-annual-workbench`; it targets a real offline Windows EXE.
- The accepted design uses one annual parent per client and operation year,
  with independent work, filing, document, tax, and service-fee states.
- The clean pre-feature baseline passes 1454 tests in 939.71 seconds.
- Migration 0027 is implemented and independently approved. It backfills
  registered/contact addresses, adds multiple leases and client industries,
  preserves attachment/version data and AUTOINCREMENT high-water marks, and
  enforces lease/client ownership with a composite foreign key.
- Repository/service work for leases, industries, and guarded lease
  attachments is implemented and independently approved. Archived leases keep
  their existing attachment evidence readable, while archived leases cannot
  receive new files and deleted clients remain isolated. Registered/contact
  address behavior is separated across CRUD, bulk import, and registry
  matching. The shared client profile and multiple-lease UI is implemented
  with atomic profile saves and focused widget regression coverage; independent
  review is still pending. Lease-expiry reminders now query active,
  non-archived client leases in one deduplicated query rather than reading
  legacy client scalar dates. Archived leases remain visible as read-only
  history with owner-guarded attachment evidence. Registry search uses the
  tax-ID index before any broad LIKE work, covers all four official industry
  slots, and presents only a source-declared primary
  industry. Registry application updates registered address without replacing
  exact contact-address text, and applies client fields, industries, FTS, and
  audit rows atomically. Non-tax-id searches in both registry entry points use
  a shared bounded read-only SQLite worker; focused regression passes, while
  independent review is still pending. Migration 0028 adds the annual
  compliance profile, client-year workspace, work-item, transaction-ledger,
  and optional workflow-task link schema. It enforces active uniqueness,
  bounded integer years/months/amounts, forward-compatible status storage,
  and evidence-preserving foreign keys while retaining existing task rows and
  sequence high-water marks. Client purge preflight includes both compliance
  profiles and annual workspaces, so retained annual data produces the stable
  validation error rather than a raw SQLite FK exception. Compliance profile
  repositories, pure period rules, and atomic partial-upsert service are now
  implemented with focused regression coverage; independent review remains
  pending. Disabled and omitted profile rows are retained, unchanged saves do
  not write or audit, and verified special fiscal-year filing windows are
  derived from the operation year without holiday-extension inference.
  Remaining annual repositories/services/UI,
  full coverage measurement, DPI acceptance, and EXE packaging are not yet
  verified and must not be reported as complete.

## 2026-07-12 fixed-billing manual-acceptance EXE (uncommitted)

- Fixed billing now exposes plan edit/add/delete actions before expansion,
  supports discoverable start-date edits, physically deletes plans without
  confirmed history, and blocks deletion when confirmed history exists.
- Editing a plan reconciles mutable pending dates while preserving confirmed,
  skipped, and cancelled history. Batch reconciliation validates and confirms
  the exact selection atomically; audit failure rolls back every row.
- `PlanDialog` is scrollable at 680x500, uses both sides for contract fields,
  arranges months in a grid, and reuses an existing blank row on repeated
  `新增列` clicks.
- Client notes remain multiline in SQLite, are visible by default in the client
  table, use a compact single-row display, and retain exact newlines in tooltip.
- Template editor explains that available fields are placeholders populated by
  client/case/request/fixed-billing data during message generation.
- Registry page has an official per-tax-id GCIS online fallback for company,
  business, and branch data. It is separate from MOF BGMOPEN1, does not scrape,
  and surfaces IP authorization/network/response failures.
- Fresh branch-coverage gate passes at **90.20%**: 1437 passed, 2 large
  BGMOPEN1 import smoke tests deselected. Evidence:
  `.ai/coverage-post-acceptance-final-20260712.json`.
- Changed-surface regression passes 261/261; native Qt/app lifecycle passes
  9/9; compileall and `git diff --check` pass.
- Windows Computer Use visual acceptance is blocked because its native pipe is
  unavailable. Visible DPI/manual acceptance is not claimed.
- The corrected worktree is rebuilt from the exact-pinned isolated Python
  3.11.9 environment. Automated EXE smoke passes: alive after eight seconds,
  isolated SQLite created, then process terminated without a TaxOps residual.
- Acceptance artifact:
  `dist/TaxOpsControlDesk-v0.28.0-acceptance-20260712-r2-win64.zip`
  (49,769,899 bytes), SHA-256
  `93530F5181AEA30CFCABF5B5F07E210D713F9D40845FB66999F2B1BF8F3D160C`.
- ZIP readback passes for all 192 entries with no test, `.ai`, Git, Python
  source, or bytecode entries. GCIS is present in the PyInstaller module graph.
- This is an unsigned acceptance build, not a release. No commit, push, tag, or
  GitHub Release was performed.

## 2026-07-12 v0.28.0 manual-acceptance package (uncommitted)

- The current 90.02%-coverage worktree is packaged as a Windows PyInstaller
  one-dir EXE from an isolated Python 3.11.9 release environment using the
  exact versions in `requirements-release.txt`.
- Isolated `pip check` reports no broken requirements. The first shared-Python
  build was discarded because its module graph picked up unrelated global
  packages and emitted a Requests dependency warning.
- Automated EXE smoke passes: the process remains alive after eight seconds and
  creates an isolated `TaxOpsControlDeskDev/taxops.sqlite`; the smoke process is
  then terminated.
- Acceptance artifact:
  `dist/TaxOpsControlDesk-v0.28.0-acceptance-20260712-win64.zip` (49,755,794
  bytes), SHA-256
  `DE814ABDC9DC4ECAC84E20D3E27BFB99B00946246476A257956D0030F804D1CC`.
- ZIP readback passes for all 192 entries. The EXE is not digitally signed, so
  Windows SmartScreen behavior remains an expected manual-acceptance risk.
- This is an acceptance build, not a release: visible UI workflows, DPI,
  upgrade/reinstall, and a separate clean/offline Windows machine remain
  unverified. No commit, push, tag, or GitHub Release was performed.

## 2026-07-12 Happy-path audit and 90% branch-coverage gate (uncommitted)

- The shortened full branch-coverage gate now passes at **90.02%**:
  `1393 passed, 2 deselected`; the only deselections are the two 65MB real
  BGMOPEN1 ZIP smoke tests. Evidence is `.ai/coverage-final-20260712.json`.
- Real-widget/error-path integration regression passed: `479 passed`.
- Native Qt worker/runtime regression was run without coverage instrumentation:
  `9 passed`.
- Work Records no longer constructs hidden canvas/error-review widgets solely
  for tests. Those unavailable actions are disabled in the action registry;
  the underlying canvas/error services and security tests remain.
- Confirmed happy-path defects fixed in this campaign include:
  - Bulk import no longer advances to the success screen after an import error.
  - Document-request stale item rows are cleared after load failure, and its
    context-banner stylesheet is valid.
  - Attachment stale selections cannot leave action buttons enabled; Windows
    open failures now show visible feedback.
  - The unused navigation placeholder fallback was removed so unmapped pages
    fail fast instead of silently appearing unfinished.
- Real dialog/button paths now cover clients, tasks, templates, document
  requests, recurring billing, attachments, Work Records workflows, registry,
  late fee, settings download/import, bulk import, and canvas PDF/security.
- `compileall` and `git diff --check` pass. Global `pip check` remains red due
  unrelated shared-environment conflicts in pip-audit/semgrep/transformers;
  no global packages were mutated to hide that result.
- The worktree remains uncommitted. No EXE build, package, tag, push, or release
  was performed.

## 2026-07-11 Deep bug and branch-coverage campaign (uncommitted)

- The current worktree contains correctness fixes and regression tests; it is
  not committed or released.
- Verified full branch-coverage gate: 1191 passed, 1 failed, total 80.60%.
  The failure was an order-dependent ClientsPage compact-header height breach;
  both pagination labels now have a 40px maximum height, and the full layout
  test file subsequently passed 16/16.
- Verified shortened coverage measurement (excluding two 65MB real-registry
  import smoke tests and the separately verified Qt worker lifecycle file):
  1214 passed, 2 deselected, 83.42% branch coverage.
- The 90% gate is not met. Current shortened-run gap is 1,932 missing lines and
  818 missing branches; about 1,092 additional coverage points must be covered.
- Core fixes include task completion timestamps, archived-record mutation
  guards, client/engagement context consistency, client purge reference guards,
  registry transaction atomicity, streaming registry bundles, import resource
  limits, backup DDL validation, stale document-item clearing, bounded text
  attachment preview, SettingsPage mutation locking, worker diagnostics, and
  forced app exit after database restore.
- Latest focused regression set: 223 passed. No build/package/release was run.

## 2026-06-08 Post-v0.27.0 correctness fixes (unpushed)

- Four commits on `main` are not yet pushed to `origin/main`:
  - `1c92532` fix: move FTS operations inside transaction and fix work_records
    split commit
  - `e8c9b22` fix: repo SQL correctness — late_fee missing dr deleted_at,
    doc_request item update guard, recurring billing get_plan archived filter
  - `7687385` fix: blockSignals around setRowCount to prevent mid-refresh
    signal race conditions
  - `05ab451` fix: stable-ID attachment selection, clear_filter for
    late_fee/tasks pages
- Verification:
  - Targeted (attachments/late_fee/tasks): 81 passed.
  - Full `python -m pytest -q` => 1118 passed (exit code 0).
- Working tree is clean; no EXE rebuild performed for these correctness patches.
- Push to origin and tag are pending.

## 2026-06-07 v0.27.0 — Recurring billing line management + template semantics

- Version: `0.27.0`.
- Fixed recurring billing line management after plan creation:
  - Active lines are visible inside expanded plans.
  - Users can edit or delete the wrong line directly.
  - Delete soft-deactivates the line, cancels pending occurrences, preserves
    confirmed history, and audits the cancelled pending count.
  - Expanded client/plan state is preserved after refresh.
- Template provenance and fixed-billing semantics from the previous update are
  included in this release.
- Late-fee parameter layout correction is included in this release.
- Verification:
  - Targeted recurring-billing/action-contract regression: 138 passed.
  - Broader targeted gate: 200 passed.
  - Full regression: `python -m pytest -q` => 1118 passed.
  - `python -m build_tools.package_windows` => rebuilt EXE.
  - `python -m build_tools.smoke_test_exe` => passed.
  - `python -m pip_audit -r requirements-release.txt` => No known
    vulnerabilities found.
- Release artifact:
  `dist/TaxOpsControlDesk-v0.27.0-windows.zip` (68.1 MB).
- SHA-256:
  `d32d22aeffcea8077f10038c86c8d9070ac89560be897727d19ce7a542c0003d`.
- Old `v0.26.0` ZIP and `.sha256` were removed after the new archive passed
  readback verification.
- Release closure completed:
  - Commit: `3464616 feat: ship v0.27.0 recurring billing line management`.
  - Branch: `main` pushed to `origin`.
  - Tag: `v0.27.0` pushed to `origin`.
  - GitHub Release:
    https://github.com/yung13yubabie/taxops-control-desk/releases/tag/v0.27.0
  - Release assets uploaded: ZIP + `.sha256`.

## 2026-06-07 Template provenance and late-fee layout correction

- Template fields now expose their real source and empty-value behavior in the
  editor instead of presenting an unexplained list of labels.
- Recurring-billing `pending` occurrences are treated as not-yet-confirmed
  invoice issuance schedules, not as unpaid customer debt.
- Built-in template id 3 is updated by migration
  `0026_fix_payment_template_semantics` to `固定開立提醒`.
- Existing custom templates using the old payment placeholder labels remain
  compatible through a legacy label-to-variable mapping.
- Payment variables now distinguish all pending issue schedules
  (`outstanding_amount`) from overdue pending issue schedules
  (`overdue_amount`); the overdue detail list contains only due occurrences.
- Late-fee input controls now use both sides of the parameter area.
- A true accounts-receivable/payment ledger is not implemented. Client master
  data must not be used as a duplicate balance store.
- Package metadata was consistently `0.26.0` in `pyproject.toml` and
  `src/taxops/__init__.py`.
- Final verification: `python -m pytest -q` => 1114 passed.

## 2026-06-07 v0.26.0 — Anti-Slop Quality Pass

- Version: `0.26.0`.
- Final full regression: `python -m pytest -q` => 1108 passed, exit code 0.
- Anti-slop 7-dimension audit applied: keyboard accessibility (setTabOrder for 9 dialogs,
  setDefault for 5 dialogs), brand consistency (DANGER_COLOR, TEXT_MUTED, PRIMARY_COLOR
  tokens replace 15+ hardcoded colors), cross-page data sync (RecurringBillingPage
  refresh_context/clear_filter), design system (folder_bookmarks EmptyState), data
  integrity (tasks service C1 error log, clients_page C2 tax registry UI warning),
  style.py PRIMARY_COLOR/PRIMARY_HOVER exported.
- Estimated quality improvement: 4.1/10 → 6.8/10 post-wave-1-4 fixes.
- EXE packaging pending.

## 2026-06-07 v0.25.0 release candidate

- Version: `0.25.0`.
- Final full regression: `python -m pytest -q` => 1108 passed, exit code 0,
  in 762.02 seconds.
- Release dependencies are exactly pinned in `requirements-release.txt`.
- `pip-audit -r requirements-release.txt` => 15 dependencies audited,
  0 known vulnerabilities.
- EXE was built from a fresh temporary virtual environment with
  PyInstaller 6.11.1 and PySide6 6.10.2.
- Automated EXE smoke passed: process remained alive, an isolated SQLite
  database was created, and the smoke process was terminated.
- Release artifact:
  `dist/TaxOpsControlDesk-v0.25.0-windows.zip` (49,565,977 bytes).
- SHA-256:
  `da5e034248867a8c72dcf79b5d2718e062cdd1ae9d1a3bcb93d04ca2ad6aad76`.
- Old `dist/TaxOpsControlDesk-v0.24.0-windows.zip` was removed only after the
  new archive passed full ZIP readback.
- Windows Computer Use acceptance was attempted twice but the connector failed
  during initialization with `failed to write kernel assets` / OS error 3.
  Therefore 100/125/150/200 percent DPI remains manual acceptance evidence,
  not an automated claim.
- Release closure target: commit and push `main`, then publish tag and GitHub
  Release `v0.25.0` with the verified ZIP and SHA-256 file.

## 2026-06-07 Security, correctness, and SLOP audit

- Multi-agent UI, security, architecture, test-governance, and spec audits were
  completed and integrated into the current uncommitted worktree.
- P0/P1 fixes cover stable-ID UI refresh, backup restore hardening, image
  resource limits and lifecycle cleanup, deleted-owner isolation, atomic task
  bulk operations, atomic registry imports, registry redirect allowlisting,
  recurring-billing contract/error-state fixes, packaging migration discovery,
  real cross-process single-instance testing, and DPI-aware minimum sizing.
- Evidence and residual risks: `.ai/AUDIT_2026-06-07.md`.
- PowerShell command rules: `.ai/COMMAND_EXECUTION_RULES.md`.
- Final `python -m pytest -q`: 1100 passed, exit code 0, in 825.52 seconds.
- No EXE packaging, Git push, tag, or release was performed in this audit pass.

## 2026-06-05 Current Development State - v0.24.0 UI Slop Follow-up

- v0.24.0 UI Slop follow-up is implemented in the current worktree, not committed.
- Completed S1-S4 handoff items that were still actionable:
  - S1 design tokens are in `src/taxops/ui/style.py`; recurring billing / late fee hardcoded status colors were replaced with tokens.
  - S2 added a reusable `EmptyState` widget and CTA wiring for clients, engagements, tasks, templates, document requests, and work-record workflow templates.
  - S3 added `src/taxops/ui/widgets/table_builder.py` and safely applied it to TasksPage + TemplatesPage first.
  - S4 split the Work Records workflow-template dialog into `src/taxops/ui/dialogs/work_records_dialogs.py`; `DocumentItemTemplateDialog` was already split before this pass.
- Slice 15 regression remains fixed: `GenerateMessageDialog._on_copy()` persists `generated_messages`, writes audit through the service, and copies authoritative DB `row.body`.
- Verification:
  - `python -m compileall -q src tests` => passed.
  - Targeted UI/data tests => 47 passed + 125 passed.
  - Full `python -m pytest -q` => **1013 passed, 1 skipped**.
- Remaining acceptance: real Windows manual UI acceptance across 1366x768, 1920x1080, DPI 100%/125%/150%.

---

## 2026-06-04 Current Development State - v0.23.0 Bug Audit Fix Wave + UI Slop Review

- v0.23.0 bug-audit fixes are implemented in the current worktree, not committed.
- `.ai/BUG_AUDIT_2026-06-04.md` remains the source issue list, but `.ai/TASKS.md` and `.ai/HANDOFF.md` now mark C1/H1-H21 style fixes as completed or triaged.
- v0.24.0 UI Slop work was later completed in the 2026-06-05 follow-up above.
- Codex review found and fixed a Slice 15 regression: `GenerateMessageDialog._on_copy()` now persists `generated_messages`, writes audit via service, and copies authoritative DB `row.body` instead of stale preview text.
- Verification for the latest worktree completed in the 2026-06-05 follow-up above.

---

## 2026-06-04 Current Development State - v0.22.0 DB Atomic Audit Fix

- v0.22.0 DB atomicity fix is implemented in the current worktree, not committed.
- Fixed DB mutation + audit non-atomicity across all 18 service files and 13 repository files.
  - Removed `self._conn.commit()` from all business-data repository mutation methods (clients, engagements, document_requests, tasks, templates, late_fee, attachments, generated_messages, folder_bookmarks, recurring_billing, work_records, canvas_notes, audit_logs).
  - Each service method now wraps `repo.mutation() + audit.record()` in a single `with self._conn:` block ensuring atomic commit or rollback.
  - FTS (search.py) and infrastructure repos (app_settings, system_logs, backup, tax_registry) retain their own commit() semantics.
  - `insert_request_with_items` retains explicit `rollback()` in its except block for direct repo usage (bypassing service layer).
- Verification pending: full `python -m pytest -q` suite running.
- Version bumped from 0.21.2 → 0.22.0 (significant architectural fix).

## 2026-06-02 Current Development State - v0.21.1 Codex Fixes

- v0.21.1 code fixes are implemented in the current worktree, not committed.
- Fixed late-fee service-layer validation:
  - `LateFeeService.calculate_and_save()` now rejects invalid `period_code`.
  - Partial period fields (`period_year` without `period_code`, or `period_code` without `period_year`) are rejected before any DB write.
  - Regression tests verify invalid/partial period payloads write zero `late_fee_records`.
- Fixed direct `date.today()` SLOP in UI/service-facing pages:
  - `LateFeePage` default year now uses project `today_iso()`.
  - `RecurringBillingPage` accordion date window now uses project `today_iso()`.
  - Static scan over `src/taxops/ui/pages` and `src/taxops/services` found no remaining `date.today()` / `datetime.date.today()` usages.
- Completed Work Records workflow UX correction:
  - Main Work Records surface no longer exposes a `QTabWidget`; hidden notes/error widgets remain only for existing canvas/error handlers and tests.
  - Workflow detail is now a `QTreeWidget` with stage -> step rows and done/undone status.
  - The workflow step button now toggles the selected run step, not the first step.
  - Workflow images are copied into app data `workflow_assets/images/`; DB context stores only safe relative path plus width/height metadata.
  - Clipboard screenshot paste saves a PNG asset and records the same relative-path metadata.
- Verification:
  - `python -m pytest tests/test_late_fee.py tests/test_late_fee_page.py tests/test_db_migrations.py -q --tb=short` => 61 passed.
  - `python -m pytest tests/test_slice18b_ui.py -q --tb=short` => 21 passed.
  - `python -m pytest tests/test_slice27_work_records.py -q --tb=short` => 10 passed.
  - `python -m pytest tests/test_slice28_canvas_notes.py -q --tb=short` => 11 passed.
  - `python -m pytest tests/test_ui_action_contracts.py tests/test_slice4_ui_smoke.py tests/test_slice5_ui.py tests/test_slice21e_tasks_ui.py tests/test_ui_layout_stability.py -q --tb=short` => 55 passed.
  - `python -m compileall -q src tests` => passed.
  - Full `python -m pytest -q` => **1004 passed, 1 skipped**.
- Release packaging:
  - Version is `0.21.1` in `pyproject.toml` and `src/taxops/__init__.py`.
  - `python -m build_tools.package_windows` rebuilt `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` passed; EXE stayed alive and created temp SQLite.
  - `dist/TaxOpsControlDesk-v0.21.1-windows.zip` was created with Python `zipfile` and passed `ZipFile.testzip()`.
  - Older v0.21.0 zip was removed from `dist/`.
  - Resource hygiene after packaging found no TaxOps / pytest / PyInstaller process residue.
- Remaining acceptance:
  - Real Windows manual UI acceptance across DPI/screen sizes remains pending.

## 2026-06-02 Current Development State

- v0.21.0 仍在進行中（未 commit）。
- 本輪完成三模組 UIUX SLOP 修正；模組 3（工作紀錄）尚未動工。
- 新增 migration `0025_late_fee_period_breakdown`（late_fee_records 加 5 欄）。
- 跨模組 targeted 驗證：138 passed（test_slice4/21b/22/21e/20b/ui_layout/late_fee/late_fee_page/date_field/slice27/db_migrations）。
- Full `python -m pytest -q` → **998 passed, 1 skipped**（2026-06-02 乾淨全套，含 21 個本輪新測試）。

## 2026-05-29 Current Development State

- v0.21.0 is in progress in the current worktree.
- Version is `0.21.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- Dashboard/control-panel UI has been removed: no dashboard/sidebar-dashboard toggle, no `QDockWidget`, no dashboard page/service/repository, no `PAGE_DASHBOARD` action contracts, and no `ui.dashboard_dock_visible` default setting. The normal sidebar collapse/expand toggle remains.
- Tasks bulk-create now selects the newly created tasks after refresh so batch delete/edit actions are immediately available.
- Work Records workflow UX is being simplified:
  - Workflow templates can be added, edited, deleted, and assigned a preview image from the workflow tab.
  - Workflow editing uses a modal dialog where stage titles are plain lines and steps are `-` lines.
  - The workflow tab now has a left templates/runs list and a right detail/preview panel.
- Work Records notes now give the canvas most of the width; the note ID column is hidden.
- Work Records canvas notes now defensively sanitize stored HTML and validate image asset paths again at UI/PDF render time, so direct SQL/old-data scene JSON cannot bypass the service-layer sanitizer.
- Error review creation now reselects and scrolls to the newly created review row.
- Message Templates now include payment follow-up support:
  - New template type `payment_follow_up`.
  - New built-in template `欠款催繳通知` via migration `0024_payment_follow_up_template`.
  - New variables: `payment_records`, `outstanding_amount`, `overdue_amount`, `payment_due_date`.
  - Payment variables are derived from existing client-scoped recurring billing occurrences; debts remain client-led, not single-case-led.
- Official registry data source check:
  - Context Hub had no strong match for Taiwan GCIS docs.
  - Official sources confirm MOF `BGMOPEN1.zip` is a tax-registration cache source, while nationwide company/business registration and business-item data should use MOEA/GCIS open-data APIs.
  - GCIS Swagger exposes `公司行號營業項目代碼表`, `公司登記基本資料-應用三`, and `商業登記基本資料` endpoints; this should be modeled separately from the existing BGMOPEN1 importer.
- Verified so far:
  - `python -m compileall -q src tests` => passed after the 2026-05-31 security review.
  - `python -m pytest tests/test_slice14_dashboard.py tests/test_slice23_dashboard_dock.py tests/test_ui_action_contracts.py -q` => 14 passed.
  - `python -m pytest tests/test_templates.py tests/test_generated_messages.py tests/test_db_migrations.py -q` => 64 passed.
  - `python -m pytest tests/test_slice19a_navigation.py -q` => 14 passed.
  - `python -m pytest tests/test_slice21e_tasks_ui.py tests/test_slice27_work_records.py tests/test_slice28_canvas_notes.py -q` => 26 passed.
- Full suite rerun on 2026-05-31: `python -m pytest -q` => 977 passed, 1 skipped.
- Additional grouped verification passed:
  - 158 registry/recurring/packaging/cache tests passed.
  - 48 attachment/audit/backup tests passed.
  - 59 client/date tests passed.
  - 48 registry/slice UI tests passed.
  - 51 slice20 tests passed.
  - 26 slice21A/B tests passed.
  - 39 slice21C/D/22 tests passed.
  - 5 non-real-import settings smoke tests passed; the 2 real BGMOPEN1 import smoke tests were not rerun because the single file exceeded the timeout while importing the large real ZIP.
  - 58 slice24/26/3 tests passed.
  - 87 slice4/5/6/7/9 UI tests passed.
  - 53 status/tasks/text/ui-regression tests passed.
- Windows package rebuild for v0.21.0 succeeded at `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
- `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
- Release zip exists at `dist/TaxOpsControlDesk-v0.21.0-windows.zip`.
- Offscreen UI geometry audit covered all 11 pages at 1366x768 and 1920x1080; no visible widget clipping was detected. Headless screenshots rendered CJK as square glyphs because the offscreen environment lacked the UI font, so this is not a substitute for manual Windows font/DPI acceptance.
- Manual UI acceptance is not yet rerun for v0.21.0.

## 2026-05-29 Current Release State

- v0.20.0 is release-ready in the current worktree.
- Version is `0.20.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- The packaged desktop app has been rebuilt at `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
- The v0.20.0 release zip exists at `dist/TaxOpsControlDesk-v0.20.0-windows.zip`.
- Release verification completed:
  - `git diff --check` => passed.
  - `python -m pytest tests/test_slice28_canvas_notes.py tests/test_slice27_work_records.py tests/test_db_migrations.py tests/test_ui_action_contracts.py -q --tb=short` => 30 passed.
  - `python -m pytest -q` => 1008 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning still observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.

## 2026-05-28 Current Verified State

- v0.20.0 Work Records A4 canvas notes is implemented.
- Work Records now includes usable `流程`, `筆記`, and `錯誤回顧` tabs.
- Notes use an A4 page-based `QGraphicsScene` canvas:
  - Fixed A4 page frame on a pannable/zoomable workspace.
  - `text_box`, `image`, `freehand`, and `shape` objects are stored as scene JSON.
  - Text boxes store controlled sanitized HTML.
  - Shapes support red outline rectangles and yellow highlight rectangles.
  - 8px grid snap is enabled for movable text and shape objects.
  - Images are copied to local `note_assets/` under the app data root, not stored in SQLite.
  - PDF export renders A4 pages with `QPdfWriter`.
- Version is currently `0.20.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- v0.20.0 verified:
  - `python -m pytest tests/test_slice28_canvas_notes.py tests/test_slice27_work_records.py tests/test_db_migrations.py tests/test_ui_action_contracts.py tests/test_slice14_dashboard.py tests/test_slice23_dashboard_dock.py tests/test_slice19a_navigation.py -q --tb=short` => 82 passed.
  - After security/simplification fixes: `python -m pytest tests/test_slice28_canvas_notes.py tests/test_slice27_work_records.py tests/test_db_migrations.py tests/test_ui_action_contracts.py -q --tb=short` => 30 passed.
  - `python -m pytest -q` => 1008 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning still observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.

## 2026-05-28 Current Verified State

- v0.19.0 Work Records workflow/error review is implemented.
- Sidebar/Dashboard now include the new `work_records` module as `工作紀錄`.
- Work Records first version includes three tabs: `流程`, `筆記`, and `錯誤回顧`.
- The `筆記` tab is a v0.20.0 placeholder only; the A4 QGraphicsScene canvas editor is not implemented yet.
- Workflow Templates and Workflow Runs are separate:
  - Templates store staged checklist JSON and version.
  - Runs snapshot a template and can be edited independently.
  - A Run can overwrite its original template or be saved as a new template.
- Structured Error Reviews support severity, phenomenon, root cause, short/long guards, and can append a guard step to a selected workflow template stage, bumping the template version.
- Version is currently `0.19.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- v0.19.0 verified:
  - `python -m pytest tests/test_slice27_work_records.py tests/test_db_migrations.py tests/test_ui_action_contracts.py tests/test_slice14_dashboard.py tests/test_slice23_dashboard_dock.py tests/test_slice19a_navigation.py -q --tb=short` => 74 passed.
  - `python -m pytest -q` => 999 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning still observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.
- Active roadmap now continues with v0.20.0 Work Records A4 canvas notes.

## 2026-05-28 Current Verified State

- v0.18.0 Tasks UX + context-inheriting next-step child task is implemented.
- Tasks UI now follows the left list plus right detail panel pattern, while preserving existing table APIs used by tests.
- A new `新增下一步` action creates a new child task from the selected parent task instead of storing a plain text next-step note only.
- `TasksService.create_child_task(parent_task_id, title)` inherits `client_id`, `engagement_id`, assignee, and priority from the parent task, enforces the existing two-level hierarchy cap, and records `task.create_child`.
- Version is currently `0.18.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- v0.18.0 verified:
  - `python -m pytest tests/test_tasks.py tests/test_slice20b_tasks_client.py tests/test_slice21d_tasks_parent_bulk.py tests/test_slice21e_tasks_ui.py tests/test_slice5_ui.py tests/test_ui_action_contracts.py -q --tb=short` => 109 passed.
  - `python -m pytest -q` => 991 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning still observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.
- Active roadmap now continues with v0.19.0 workflow/error review and v0.20.0 A4 canvas notes.

## 2026-05-28 v0.17.0 Verified State

- v0.17.0 Cases + Document Requests UX is implemented.
- `document_requests.request_name` is added through migration `0021_document_request_name`, with legacy backfill and default name generation on create.
- Document request batches now support update/edit through `DocumentRequestsService.update_request()` and `DocumentRequestsRepository.update_request_metadata()`.
- Document Requests UI now surfaces batch names directly, includes an edit-batch action, and uses a left request list plus right detail/item panel.
- Cases UI now includes client context in the left list and a right detail panel for the selected case.
- Version was `0.17.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- v0.17.0 verified:
  - `python -m pytest -q` => 986 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning still observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.
- Roadmap continued with v0.18.0 Tasks UX + context-inheriting child task next step, v0.19.0 workflow/error review, and v0.20.0 A4 canvas notes.

## 2026-05-28 v0.16.0 Verified State

- v0.16.0 Dashboard/Sidebar consistency is implemented.
- Dashboard rows now mirror sidebar `NAV_ORDER` and navigate with `(page_id, "")`, so Dashboard and sidebar entry points land on the same page state.
- `MainWindow.navigate_to(page_id, filter_key="")` clears stale page filters when navigating without a filter, including same-page navigation.
- Dashboard action contracts now cover the same sidebar modules and no longer expose the removed ReviewNotes route.
- Version is currently `0.16.0` in `pyproject.toml` and `src/taxops/__init__.py`.
- Verified:
  - `python -m pytest tests/test_slice14_dashboard.py tests/test_slice23_dashboard_dock.py tests/test_slice19a_navigation.py tests/test_ui_action_contracts.py tests/test_date_field.py -q --tb=short` => 101 passed.
  - `python -m pytest -q` => 977 passed, 1 skipped.
  - `python -m build_tools.package_windows` => built `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`.
  - `python -m build_tools.smoke_test_exe` => automated EXE smoke passed.
  - `python -m pytest tests/test_packaging_tools.py -q --tb=short` => 6 passed.
- Packaging warning observed during PyInstaller build: `RequestsDependencyWarning` about urllib3/chardet/charset_normalizer compatibility. Build and smoke still passed; keep this visible for dependency cleanup.
- Real Windows manual UI acceptance across screen sizes/DPI remains unverified.
- Active roadmap remains v0.17.0 Cases/Document Requests, v0.18.0 Tasks, v0.19.0 workflow/error review, and v0.20.0 A4 canvas notes.

## 2026-05-11 Verified Current State

- [已確認] Slice 3 HTTP download 已完成補救修正：下載服務改為 `.part` 原子寫入、500 MB 上限、失敗清理 partial file。
- [已確認] 測試資源清理已補強：`tests/conftest.py` 將 `tempfile.mkdtemp()` 導入每個測試的 `tmp_path/_tempfile`，避免使用者 TEMP 累積。
- [已確認] 新增 Slice 3 成功路徑測試，直接觸發 `SettingsPage.on_download_registry()` 的真實 closure，驗證 import、audit、tmp cleanup。
- [已確認] 最新驗證：`python -m pytest -x --tb=short` => 183/183 passed in 198.26s。
- [已確認] 測後環境檢查：`python -m build_tools.check_resource_hygiene` 已執行；未列出 TaxOpsControlDesk / pytest / pyinstaller 殘留進程，僅列出巡檢命令本身；TIME_WAIT = 18；未發現 pytest 新增 server/browser/listen port。
- [待驗證] 真實 Windows 桌面操作仍需人工驗收：QFileDialog、QProgressDialog、QMessageBox、正式網路下載 BGMOPEN1.zip、EXE 內相同行為。
- [已確認] GCIS query 仍未完成；若 Slice 3 定義只限 HTTP download，Slice 3 可視為通過；若 Slice 3 包含 GCIS，則 GCIS 仍是 TODO。
- [已確認] 詳細資源清理稽核與修復閉環記錄在 `.ai/RESOURCE_CLEANUP_AUDIT.md`。

> [已確認] 2026-05-10 Slice 3 HTTP download 完成：下載財政部稅籍資料按鈕啟用，URL allowlist + 兩段確認 + audit trail + DownloadError。pytest 175/175 passed。

## Project Goal

- [已確認] 專案目標是建立 TaxOps Control Desk，一個 Windows-first、離線優先的台灣會計／稅務事務所營運桌面工具。
- [已確認] 產品定位包含事務所案件營運、客戶索件與缺件追蹤、稅務工作流管理、附件證據鏈、內部覆核、離線資料與待辦控制台。
- [已確認] MVP 不可宣稱完成，直到來源規格第 24 節全部完成並驗證。

## Current Status

- [已確認] Slice 1、Slice 2（稅籍快取）、客戶管理功能閉環（批量匯入 + 編輯/刪除 + 衝突審查）、Slice 2.6（搜尋/排序/分頁 + sidebar 收合）、Slice 3（HTTP download）、Slice 4（案件 + 索件）、Slice 4.5（案件編輯 + 索件項目狀態 UI）、Slice 5（待辦事項）、Slice 6（訊息模板）、Slice 7（產生催件訊息）、Slice 8（覆核意見 + 滯納金試算）、Slice 9（附件證據鏈 MVP + closeout correction）、Slice 10（Excel 匯出缺件清單 + CSV formula injection defense）、Slice 11（備份 / 還原）、Slice 12（FTS5 全文搜尋）、Slice 13（本地工商 / 稅籍查詢頁）、Slice 14（Dashboard 真實統計 + 篩選導向補完）均已完成實作。
- [已確認] `python -m pytest` 最後完整確認通過：972/972 passed（2026-05-27 Slice 21E v0.14.0 + attachment file URL）。v0.14.1 SLOP patch round 全套執行中（pid b4qq4d848）；子集已通過 single_instance 5 + doc_requests 92 + slice9_ui 20 + recurring_billing 26。
- [已確認] G-1~G-15 UIUX 修復已完成：WA_DeleteOnClose、anti-double-click、toolbar_icon、error label、silent failure 修正等；dashboard high_risk_engagements 導向修正為 PAGE_REVIEW_NOTES + FilterKey.HIGH_RISK。
- [已確認] Slice 15-rental 新功能：Migration 0013（clients.lease_start/lease_end）、Migration 0014（workflow_tasks.engagement_id nullable）、欄位顯示控制（QMenu）、租約到期通知 dashboard 卡、任務不強制關聯案件。
- [已確認] ALLOWED_VARIABLES 現為 11 個（4 個未來欄位 payment_due_date / office_owner / reviewer / last_followed_up_at 已於 Slice 15 安全修正中移除）。
- [待確認] Supply Chain Locking = UNKNOWN / OPEN：pyproject.toml 中 PySide6、Jinja2、openpyxl、pytest、pyinstaller 均未 pin 版本。
- [已確認] 技術棧：Python 3.11+, PySide6, SQLite, SQLite FTS5, Jinja2, openpyxl, pytest, PyInstaller（Windows one-dir build + automated EXE smoke 已通過；人工 UI 驗收尚未完成）。

## Active Work

- [已確認] 2026-05-28 完成 v0.16.0 Dashboard/Sidebar 一致化：控制台改為 `NAV_ORDER` 的精簡摘要版，列項與側邊欄相同；控制台點擊不再帶隱性 filter，等同側邊欄導航至同一頁。`MainWindow.navigate_to(page_id, filter_key="")` 已補強為空 filter 時清除頁面既有 filter，避免控制台與側邊欄出現兩條路徑。已驗證 targeted suite：`python -m pytest tests/test_slice14_dashboard.py tests/test_slice23_dashboard_dock.py tests/test_slice19a_navigation.py tests/test_ui_action_contracts.py tests/test_date_field.py -q --tb=short` => 101 passed。尚未執行 full suite / EXE build。
- [已確認] 2026-05-28 確認後續 5-slice roadmap：v0.16.0 Dashboard/Sidebar 一致化；v0.17.0 案件 + 索件 UX 重構與 `request_name`；v0.18.0 待辦 UX + 下一步子待辦；v0.19.0 工作紀錄的流程 + 錯誤回顧；v0.20.0 工作紀錄的畫布筆記。每個 slice 完成後需做 targeted tests、code simplification、code review、`.ai` 更新；完整交付前仍需 full suite、EXE smoke 與人工 UI 驗收。
- [已確認] 2026-05-28 完成 v0.15.1 — 全刪 ReviewNotes（migrations 0019 drop table + 刪 repository/service/page/tests/dashboard 2 卡）+ 新增 folder_bookmarks（migration 0020 + repository/service/page，支援本機+UNC 路徑、QDesktopServices.openUrl 開啟）。17 新 tests + cascade updates。pyproject + __init__ 0.15.0 → 0.15.1。
- [已確認] 2026-05-28 完成 v0.15.0 — Dashboard 拆為浮動 QDockWidget：8 大卡 → 9 compact rows、MainWindow QDockWidget host（預設右側、可拖/float/close）、NAV_ORDER 移除 PAGE_DASHBOARD（11→10）、sidebar header 加 📊 toggle、`ui.dashboard_dock_visible` 持久化。10 新 tests + 全套 996 passed, 1 skipped。pyproject + __init__ 0.14.3 → 0.15.0。
- [已確認] 2026-05-28 完成 v0.14.3 — 案件→索件→文件 drill-down 三層架構：`DocumentRequestsPage` 加 view_mode + drill_to_items signal + load_request_items；`EngagementsPage` 重寫為 QStackedWidget 三頁 + breadcrumb。11 新 tests + 138 子集回歸 passed。pyproject + __init__ 0.14.2 → 0.14.3。
- [已確認] 2026-05-27 完成 v0.14.2 — 固定開立 toolbar 改 FlowLayout（RWD）。中繼點：v0.14.3-v0.15.2 (案件 drill-down / Dashboard dock / ReviewNotes→folder_bookmarks / notes+obsidian) + Codex review 留下次 session，roadmap 見 HANDOFF.md。
- [已確認] 2026-05-27 完成 SLOP patch round v0.14.1：（1）EXE 多開鎖（`SingleInstanceGuard` via `QLocalServer`/`QLocalSocket`，第二個 process 觸發既有實例 raise）；（2）`DocumentRequestsPage` context banner（藍底高對比，global/engagement 模式各自顯示「現在顯示：全部案件（N 筆）」或「現在顯示：[客戶名] — [案件名]」）+ 「所屬案件」column（global 預設顯示、engagement 模式自動隱藏）；（3）RWD：新檔 `widgets/flow_layout.py`，DocumentRequestsPage / EngagementsPage toolbar 改用 FlowLayout，按鈕自動換行；（4）附件 URL 整併：刪預覽區 URL row，「檔案位置」按鈕右鍵選單加「複製 file:// URL」；（5）中央化按鈕設計 token：`style.py` 加 `BTN_PRIMARY_SM` / `BTN_SECONDARY_SM` / `BTN_DANGER_SM`，recurring_billing alias 到中央 tokens 解決「編輯方案 / 新增明細」對比 SLOP。版號 0.14.1。
- [已確認] 2026-05-26 完成 Slice 21E：TasksPage 接上 21D backend UI（批量新增/編輯/刪除、設為子待辦、父子縮排、multi-select、action contracts）；附件管理新增 PDF 內嵌預覽、「檔案位置」按鈕、`file:///` URL 顯示/複製/開啟，並修正切換到空附件案件時舊 URL 未清除的狀態同步問題。14 個新 UI 測試。版號 0.14.0。full suite 972/972 passed；EXE build + smoke passed；resource hygiene 無殘留。
- [已確認] 2026-05-26 完成 Slice 21D backend：workflow_tasks.parent_task_id migration；TasksService parent/child + bulk CRUD；Codex 接手補 context_mismatch guard 與 bulk update validation/sanitize。16 個新測試；targeted + full backend suite 通過。
- [已確認] 2026-05-26 完成 Slice 21C：新 `ColumnSettings` helper widget（右鍵 header 選單 + 自動 persist hidden/widths）；8 個新 app_settings keys；4 表全接入（engagements/doc_requests/doc_items/tasks）；核心欄保護不可隱藏。9 個新測試。
- [已確認] 2026-05-26 完成 Slice 21B：EngagementsPage 重寫為 master-detail vertical split（上半案件清單、下半嵌入式 DocumentRequestsPage(embedded=True)）；sidebar 移除「索件管理」入口（NAV_ORDER 12→11）；main_window 不再 instance DocumentRequestsPage；DocumentRequestsPage 加 embedded 參數隱藏 back/combo；EngagementsPage 移除 _doc_btn 與 open_doc_requests signal。8 個新測試。
- [已確認] 2026-05-26 完成 Slice 21A：CreateDocumentRequestInput breaking API（`item_names` 取代 `use_vat_template`）；新 DocumentItemTemplateDialog 含 checklist + 自訂項目 + 持久化（per-tax-type）；DocumentRequestsPage 加批量刪除文件項目；conftest autouse mock 修 modal-exec hang。18 個新測試。Slice 21 系列開始（A 完成，B/C/D 進行中）。
- [已確認] 2026-05-25 完成 Slice 20C：RecurringBillingService.create_plan_with_lines atomic transaction；module-level parse_bulk_lines helper；PlanDialog 兩段佈局（合約資訊 + 固定開立明細 table）+ 批量貼上對話；ConfirmOccurrenceDialog 保留 expected vs confirmed amount；audit 一次記 plan + line_count。16 個新測試。Slice 20 系列（A/B/C）全部完成。
- [已確認] 2026-05-24 完成 Slice 20B：workflow_tasks 加 client_id nullable（migration 0017，含 backfill）；TasksService.create_task 從 engagement 自動同步 client_id；TasksPage / NewTaskDialog 客戶 + 案件 cascade；新增 list_by_client、client_exists、get_engagement_client_id helpers；20 個新測試。下一輪 Slice 20C（固定開立 UX 重設）。詳見 .ai/HANDOFF.md。
- [已確認] 2026-05-24 完成 Slice 20A：DocumentRequestsPage 加案件 combo（全部案件 / 指定案件兩段）、全域模式新增索件批次彈出 engagement picker 不再 silent return、item 操作後同步刷新 request table 且保留選取；新增 15 個 UI 行為測試。Slice 20A 屬上下文自主化系列，B（代辦客戶選擇）與 C（固定開立 UX 重設）尚未開始。詳見 .ai/HANDOFF.md。
- [已確認] 2026-05-23 完成 Slice 19A/B/C/D + hotfix v0.6.1：Dashboard filter 污染修復、各頁全域視圖、索件項目批量操作、附件刪除、固定開立新增入口；hotfix 補修 delete_item 未重算父層狀態 + 空 item 集誤判為 accepted。詳見下方 Slice 19 記錄。
- [已確認] EXE packaging 檔案已建立：`TaxOpsControlDesk.spec`, `build_tools/pyinstaller_entry.py`, `build_tools/clean_package.py`, `build_tools/package_windows.py`, `build_tools/smoke_test_exe.py`, `tests/test_packaging_tools.py`。
- [已確認] PyInstaller 入口曾因 `src/taxops/__main__.py` relative import 造成 EXE 假啟動但不建 DB；已改用 `build_tools/pyinstaller_entry.py` absolute import，並以 regression test 固定。
- [已確認] `python -m build_tools.package_windows` 已產出 `dist/TaxOpsControlDesk/TaxOpsControlDesk.exe`；`python -m build_tools.smoke_test_exe` 已驗證 EXE 啟動且在 temp `LOCALAPPDATA\TaxOpsControlDeskDev\taxops.sqlite` 建立 SQLite。
- [已確認] Slice 14 補完內容包含：`DashboardPage.navigate_to_page = Signal(str, str)`、`FilterKey` 常數、`MainWindow.navigate_to(page_id, filter_key="")`、三個目標頁 `set_filter()`、以及 tasks / engagements / review_notes 的 repository/service 篩選查詢。
- [已確認] Slice 14 `/simplify` 修正包含：`today_iso()` 取代 inline date、`FilterKey.*` 取代 raw filter string、`NAV_ORDER.index()` 不再轉成 list 後查找。
- [待驗證] Slice 2/3/4/4.5 真實 UI 互動（QFileDialog、QProgressDialog、下載進度、中文 QMessageBox、案件編輯、項目狀態切換）尚未在真實 Windows 桌面驗收。
- [待驗證] 客戶管理新功能（批量匯入、編輯、刪除、衝突審查對話框）尚未在真實 Windows 桌面驗收。
- [待優化] Bundle 匯出/匯入使用 in-memory CSV（StringIO），170 萬筆在開發機可跑；一般事務所低規硬體記憶體穩定性尚未驗證。

## MVP Scope

- [已確認] The MVP scope must include all items listed in section 24 of the source specification.
- [已確認] Implementation is phased internally, but MVP is not complete until every section 24 requirement is satisfied.

## Implemented

### Slice 1 — 基礎骨架
- [已確認] Schema: `schema_migrations`, `app_settings`, `clients`, `audit_logs`, `system_logs`.
- [已確認] Client minimal CRUD (create/list/get) + validation + audit trail + Chinese error labels.
- [已確認] Settings page: data-path, display-name, tax-cache settings skeleton.
- [已確認] 11 個導航項目。已實作頁面：dashboard、clients、engagements、doc_requests、tasks、templates、late_fee、review_notes、attachments、registry、settings（共 11 頁，無 placeholder）。registry 頁已完成（Slice 13）：本地快取查詢 + 套用至客戶主檔 diff dialog；GCIS 線上查詢保持 disabled。dashboard 頁已完成（Slice 14）：9 張真實統計卡片（含租約到期通知）。
- [已確認] UI action contract registry 為 visible button 唯一真相來源。
- [已確認] `.gitignore` 存在，排除 Python cache、build output、SQLite、attachments、cache bundles、`tmp/`。

### Slice 14 — Dashboard 控制台完整化（含篩選 + simplify，2026-05-17）
- [已確認] `src/taxops/repositories/dashboard.py`：`DashboardRepository`（8 個 COUNT 查詢方法，全部唯讀，參數化 SQL）。
- [已確認] `src/taxops/services/dashboard.py`：`DashboardCounts` frozen dataclass + `DashboardService.get_counts(today=None)`（today 可注入供測試）；`_UPCOMING_DAYS = 7`。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer` 新增 `dashboard: DashboardService`；`build_container()` 掛載。
- [已確認] `src/taxops/ui/pages/dashboard_page.py`：`DashboardPage`（8 張卡片 2 欄 QGridLayout）；`navigate_to_page = Signal(str, str)` —（page_id, filter_key）；`_CARD_DEFS` 5-tuple 含 `FilterKey.*` 常數；`_on_refresh()` 呼叫 `container.dashboard.get_counts()`；空 DB 顯示 0，不 hardcode。
- [已確認] `src/taxops/ui/main_window.py`：`navigate_to(page_id, filter_key="")` — 若 filter_key 非空則呼叫 `page.set_filter(filter_key)`；`NAV_ORDER.index()` 不再做多餘 list 轉型。
- [已確認] `src/taxops/ui/action_registry.py`：`FilterKey` class（DUE_TODAY / OVERDUE / UPCOMING / OPEN / HIGH_RISK）；4 個 PAGE_DASHBOARD enabled contracts（重新整理 / 前往待辦事項 / 前往覆核意見 / 前往案件管理）；無 disabled contracts。
- [已確認] `src/taxops/repositories/tasks.py`：新增 `list_due_today(today)` 唯讀查詢。
- [已確認] `src/taxops/repositories/engagements.py`：新增 `list_upcoming(today, until)` / `list_overdue(today)` 唯讀查詢。
- [已確認] `src/taxops/repositories/review_notes.py`：新增 `list_open_all()` / `list_high_risk_all()` 唯讀查詢。
- [已確認] `src/taxops/services/tasks.py`, `engagements.py`, `review_notes.py`：對應 wrapper 方法。
- [已確認] `src/taxops/ui/pages/tasks_page.py`：`set_filter(FilterKey)`；`_refresh()` 分支 due_today / overdue / 原 combo 邏輯；uses `today_iso()`。
- [已確認] `src/taxops/ui/pages/engagements_page.py`：`set_filter(FilterKey)`；`_refresh_engagements()` 分支 upcoming / overdue / 原 client 邏輯；uses `today_iso()`，`datetime.timedelta(days=7)` at module level。
- [已確認] `src/taxops/ui/pages/review_notes_page.py`：`set_filter(FilterKey)`；`_load()` 分支 open / high_risk / 原 engagement 邏輯。
- [confirmed] `tests/test_slice14_dashboard.py` (NEW): 31 tests - DashboardRepository (14), DashboardService (4), DashboardPage UI (8), action contracts (4); 636/636 passed.
- [已確認] 有明確 `FilterKey` 的 Dashboard 卡片會導向並套用篩選；`waiting_client` / `missing_item_requests` 目前 `filter_key=""`，僅誠實導向案件管理，不假裝已套用索件全局篩選；不可 hardcode 已由空 DB 回傳 0 測試驗證。

### Slice 2 — 稅籍快取離線匯入
- [已確認] 後端全閉環：registry parser, importer, bundle export/import, verify, matcher（`registry_match_results` schema）。
- [已確認] UI 5 個離線按鈕已啟用：`on_import_zip`, `on_import_bundle`, `on_export_bundle`, `on_verify_cache`, `on_regenerate_matches`。
- [已確認] ZIP guard：副檔名 `.zip` + 500 MB 大小上限。
- [已確認] 背景執行緒 fresh-connection pattern（QThread，threading.Thread smoke 驗證）。
- [已確認] `下載財政部稅籍資料` 仍 disabled（Slice 3）。
- [待驗證] QThread + QFileDialog + QProgressDialog 真實桌面互動。

### 客戶管理功能閉環（本 session 新增）
- [已確認] `src/taxops/services/clients_bulk.py`：批量匯入服務（Excel/CSV/貼上，欄位對應，驗證，寫入）。
- [已確認] `src/taxops/ui/dialogs/bulk_import_wizard.py`：6 步驟 QDialog 精靈，含 `_step_history` 正確 Back 導航。
- [已確認] `src/taxops/ui/dialogs/edit_client_dialog.py`：Edit client 對話框（先前實作；本 session 測試補齊）。
- [已確認] `src/taxops/ui/dialogs/mismatch_review_dialog.py`：衝突審查對話框（MismatchItem + 8 欄表格 + 採用/保留 checkbox）。
- [已確認] `src/taxops/ui/pages/clients_page.py`：新增編輯、刪除、批量匯入按鈕；雙擊列開啟 EditClientDialog。
- [已確認] `src/taxops/services/container.py`：ServiceContainer 新增 `clients_repo` 欄位。
- [已確認] `src/taxops/ui/action_registry.py`：新增 3 個 UIActionContract（儲存變更 / 刪除客戶 / 批量匯入）。
- [已確認] `src/taxops/ui/style.py`：全域 QSS + QPainter 產生 app icon（藍色圓角矩形 + 白色 "T"，64×64px）。
- [已確認] `src/taxops/ui/app.py`：啟動時呼叫 `apply_style(app)`。
- [已確認] `src/taxops/services/registry/matcher.py`：新增 `list_mismatches()` → 回傳所有 mismatch rows + client pairs。
- [已確認] `src/taxops/ui/pages/settings_page.py`：`on_regenerate_matches` 完成後詢問是否開衝突審查視窗，on Yes 開啟 MismatchReviewDialog。

### Slice 2.6 — 客戶管理與主框架可用性強化（2026-05-10）
- [已確認] `src/taxops/repositories/clients.py`：新增 `search_clients(query, order_by, order_dir, limit, offset)` + `count_clients(query)`；order_by 白名單保護防 SQL injection。
- [已確認] `src/taxops/services/clients.py`：新增 `search_clients()` + `count_clients()` pass-through；`list_clients()` 保留向後相容。
- [已確認] `src/taxops/ui/pages/clients_page.py`：加入搜尋列（QLineEdit + 搜尋/清除按鈕 + 總筆數 label）、欄位點擊排序（sectionClicked + setSortIndicator）、分頁導覽（◀上一頁 / 下一頁▶ + 第X–Y筆）；`_selected_client_id()` 永遠從 id 欄讀取，不用 row index。
- [已確認] `src/taxops/repositories/app_settings.py`：新增 `("ui.sidebar_collapsed", "0")` 到 DEFAULT_SETTINGS；ALLOWED_KEYS 自動包含。
- [已確認] `src/taxops/ui/main_window.py`：sidebar 包進 QWidget；上方加 QPushButton 收合/展開（◀/▶）；`_apply_collapsed()` + `_apply_expanded()` 讀寫 `ui.sidebar_collapsed` setting；重開後還原狀態。
- [已確認] `tests/test_slice26_clients_search.py`（NEW）：15 tests — count/search repo、sort/pagination、edit/delete client_id 安全、sidebar 設定種子與還原。

### 審計 — 已修復 HIGH 問題（本 session）
- [已確認] TOCTOU 競態：`import_validated` overwrite path 在 `find_by_code()` 回 None 時原本 fall-through 到 create；已補 `else: errors.append(...); skipped += 1; continue`。
- [已確認] MismatchReviewDialog `_on_apply()`：全部失敗時原本仍呼叫 `accept()`；已修正為 warning + `return`。
- [已確認] BulkImportWizard Back 導航：`_jump_to(4)` 後 Back 原本回 step 3（應跳過）；已改用 `_step_history` stack。

### 審計 — 已修復 MEDIUM 問題（後續 session）
- [已修復] `mismatch_review_dialog.py` `_parse_diffs()`：`_log.warning()` + 保守回 `{}`；補 `test_mismatch_dialog_malformed_diffs_json_returns_empty`。
- [已修復] `parse_excel()` / `parse_csv()` 無測試：補 `tests/test_clients_bulk_parse.py`（9 tests）。

### Slice 3 — HTTP 下載財政部稅籍資料（2026-05-10）
- [已確認] `src/taxops/services/registry_download.py`：`download_registry_zip(url, dest_path)` + `DownloadError`（含 network_error / io_error）。
- [已確認] `src/taxops/security/domains.py`：`is_allowed_official_url()` 驗證 HTTPS + allowlist 主機名。
- [已確認] `src/taxops/i18n/errors.py`：新增 3 個下載錯誤碼（not_allowed / network_error / io_error）。
- [已確認] `src/taxops/ui/pages/settings_page.py`：`on_download_registry()` 兩段確認（URL 確認 → 覆蓋確認）→ 背景下載+匯入 → audit；`_RegistryWorker.run()` 新增 DownloadError catch；`_set_slice2_buttons_enabled()` 同步禁用/啟用 `_download_btn`。
- [已確認] `src/taxops/ui/action_registry.py`：「下載財政部稅籍資料」改為 `enabled=True`，handler/service/audit_action 完整。
- [已確認] `tests/test_slice3_download.py`（NEW）：14 tests — allowlist 7 tests、DownloadError 2 tests、UI guard 3 tests、contract 2 tests。
- [已確認] 更新舊測試：`test_registry_cache_ui.py` + `test_settings_page_smoke.py` 改斷言按鈕已啟用。

### Slice 12 — FTS5 全文搜尋（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0012_fts5.py`：`fts_clients`（trigram, rowid=client.id, cols: client_code/client_name/tax_id/short_name/contact_name/note）+ `fts_engagements`（trigram, rowid=engagement.id, cols: engagement_name）；標準 FTS5 表（非 contentless）。
- [已確認] `src/taxops/repositories/search.py`：`SearchRepository`（add_client/update_client/delete_client/add_engagement/update_engagement/delete_engagement/search_client_ids/search_engagement_ids/rebuild_clients/rebuild_engagements）；`_fts_quote()` 防 SQL injection；刪除用 `DELETE FROM fts_... WHERE rowid=?`（而非 contentless 'delete' 命令）。
- [已確認] `src/taxops/services/search.py`：`SearchService`（search_clients/search_engagements/is_fts_eligible/rebuild_index）；`is_fts_eligible` → len(query.strip()) >= 3。
- [已確認] `src/taxops/services/clients.py`：新增 optional `search_repo: SearchRepository | None = None`；create_client→`_fts_add`；update_client→`_fts_update`；delete_client→`_fts_delete`；restore_client→`_fts_add`；所有 FTS 操作 try/except best-effort。
- [已確認] `src/taxops/services/engagements.py`：同上模式；create→`_fts_add`；update→`_fts_update`；delete→`_fts_delete`。
- [已確認] `src/taxops/services/container.py`：新增 `search: SearchService`；clients/engagements services 傳入 `search_repo`。
- [已確認] `src/taxops/ui/pages/clients_page.py`：`on_refresh()` query >= 3 chars 時使用 `container.search.search_clients()`；短查詢 fallback 原 LIKE 搜尋；FTS 結果仍使用 stable id（不用 row index）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_CLIENTS 新增「搜尋客戶」enabled contract。
- [已確認] `tests/test_fts5.py`（30 tests，含使用者補強）：FTS 表存在、新增可搜到、編輯舊詞消失/新詞可找、軟刪除不出現、中文子字串搜尋、6 種 injection 字串不爆、LIMIT 限制、engagement FTS、rebuild_index、is_fts_eligible、registry contract；並含 2 個使用者新增回歸測試（FTS update 的 INSERT 失敗時 rollback 舊索引仍保留、ClientsService FTS 失敗記 warning 不靜默）。
- [已確認] `tests/test_db_migrations.py`：EXPECTED_TABLES 加 fts_clients/fts_engagements；版本清單加 0012_fts5；count 11→12。
- [已確認] 使用者補強（2026-05-17）：`repositories/search.py` 所有 FTS 寫方法加 try/except → rollback → raise（防 DELETE 後 INSERT 失敗時半套狀態被後續 commit 提交）；`services/clients.py` 與 `services/engagements.py` FTS 失敗改為 `_log.warning(..., exc_info=True)`（不再靜默 pass）。
- [已確認] `python -m pytest` → **583/583 passed**（2026-05-17 Slice 12 + 使用者補強）。

### Slice 10 — Excel 匯出缺件清單（2026-05-17）

- [已確認] `src/taxops/security/csv_guard.py`：`safe_spreadsheet_cell(value)` — `value.lstrip()[0:1]` 偵測前導空白後公式頭（=, +, -, @），命中時原值前綴 `'`，不裁切空白。
- [已確認] `src/taxops/repositories/document_requests.py`：新增 `list_missing_items_for_export(engagement_id=None)` — 4 表 JOIN；item_status IN (missing, incomplete, invalid, pending_confirm)；LIMIT 100,000；支援按案件篩選；回傳 list[dict]。
- [已確認] `src/taxops/services/export.py`：`ExportService`（`ExportValidationError` + `export_missing_items_xlsx(output_path, engagement_id=None)`）；openpyxl 寫入 XLSX（header 粗體，工作表名「缺件清單」）；每格套 `safe_spreadsheet_cell`；audit `export.missing_items`；回傳 row count。
- [已確認] `src/taxops/services/container.py`：`ServiceContainer` 新增 `export: ExportService`；`build_container()` 掛載。
- [已確認] `src/taxops/i18n/errors.py`：新增 `export.query_failed` / `export.save_failed` / `export.no_rows`。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「匯出缺件清單」按鈕 + `_on_export()` handler（QFileDialog.getSaveFileName + 完成筆數提示）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增 1 個 enabled contract（匯出缺件清單，audit_action=export.missing_items）。
- [已確認] `tests/test_export_security.py`（24 tests）：safe_spreadsheet_cell 前導空白/tab 注入、query filter、欄位完整性、engagement 篩選、XLSX 產出、formula injection 逃逸、audit、空結果 XLSX、UI handler 整合、action registry 合約。
- [已確認] `python -m pytest` → **536/536 passed**（2026-05-17）。

### Slice 9 — 附件證據鏈 MVP（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0010_attachments.py`：attachments（16 欄位含 FK→engagements/document_requests、SHA-256、stored_filename、status DEFAULT 'uploaded'、accepted_by/at）+ attachment_versions（attachment_id/supersedes_id）；3+1 索引。
- [已確認] `src/taxops/security/file_guard.py`：`MAX_FILE_SIZE=50MB`、`ALLOWED_EXTENSIONS`（10 種）、`BLOCKED_EXTENSIONS`（13 種）、`FileGuardError(code)`、`check_extension`/`check_file_size`/`resolve_safe_path`（path traversal 防護）/`sha256_file`（串流）。
- [已確認] `src/taxops/repositories/attachments.py`：`AttachmentRow`/`AttachmentVersionRow` frozen dataclass + `AttachmentsRepository`（7 方法含 engagement_exists）。
- [已確認] `src/taxops/services/attachments.py`：`AttachmentsService`；upload 流程：副檔名→大小→FK→sha256→uuid 路徑→copy2→insert→insert_version(supersedes_id=None)→audit；每個 mutation 均 audit（target_type="attachment"）。
- [已確認] `src/taxops/ui/pages/attachments_page.py`：`AttachmentsPage`（案件 combo/6 欄位表格/上傳/驗收/退回/資訊 dialog/開啟 disabled+tooltip）；`_AttachmentInfoDialog`（完整 metadata QFormLayout）。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_ATTACHMENTS 新增 3 個 enabled contracts（新增附件/標記已驗收/標記退回）。
- [已確認] `tests/test_file_guard.py`（27 tests）+ `tests/test_attachments.py`（23 tests）+ `tests/test_slice9_ui.py`（12 tests）+ `tests/test_db_migrations.py` 更新至 0010。
- [已確認] `python -m pytest` → **512/512 passed**（2026-05-17 Slice 9 closeout correction）。

### Slice 7 — 產生催件訊息（2026-05-17）

- [已確認] `src/taxops/db/migrations/_m0007_generated_messages.py`：generated_messages 表（id/request_id/template_id/body/generated_at）+ idx_generated_messages_request 索引。
- [已確認] `src/taxops/repositories/generated_messages.py`：`GeneratedMessageRow` frozen dataclass + `GeneratedMessagesRepository`（insert/get/list_by_request）。
- [已確認] `src/taxops/services/generated_messages.py`：`GeneratedMessagesService`；`build_variables(request_id)` 從 doc_request + engagement + client + items 組裝 11 個 ALLOWED_VARIABLES（payment_due_date, office_owner, reviewer, last_followed_up_at 已於 Slice 15 安全修正中移除）；`generate()` render + insert + audit；TemplateValidationError → GeneratedMessageValidationError code 轉傳。
- [已確認] `src/taxops/ui/dialogs/generate_message_dialog.py`：`GenerateMessageDialog`（模板 QComboBox + 即時預覽 QTextEdit + 複製/儲存按鈕）；選模板時即時 render；save 後關閉 dialog。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：新增「產生訊息」QPushButton；選取索件批次後 enabled；`_on_generate_message()` 開啟 GenerateMessageDialog。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_DOC_REQUESTS 新增 1 個 enabled contract（產生訊息）。
- [已確認] `src/taxops/services/container.py`：新增 `gen_messages: GeneratedMessagesService` + build 連線。
- [已確認] `src/taxops/i18n/errors.py`：5 個 gen_message 錯誤碼（request_not_found / engagement_not_found / client_not_found / render_failed / save_failed）。
- [已確認] `tests/test_generated_messages.py`（15 tests，含 FK schema 驗證）+ `tests/test_slice7_ui.py`（10 tests，含 select→save→DB→audit 整合路徑）+ migration 更新至 7 版本 + generated_messages 表加入 EXPECTED_TABLES。
- [已確認] `python -m pytest` → **381/381 passed**（2026-05-17 closeout correction）。

### Slice 4 — 案件 + 索件後端（backend partial，2026-05-14）

- [已確認] Migration `0004_engagements`：3 表 7 索引（engagements, document_requests, document_request_items）；帶 `deleted_at` 軟刪除。
- [已確認] `src/taxops/repositories/engagements.py`：`EngagementRow` + `EngagementsRepository`（insert/get/list_by_client/count_by_client/update/update_status/delete/client_exists）。
- [已確認] `src/taxops/repositories/document_requests.py`：`DocumentRequestRow` + `DocumentRequestItemRow` + `DocumentRequestsRepository`（含原子批次 `insert_request_with_items` + `engagement_exists`）。
- [已確認] `src/taxops/services/engagements.py`：`EngagementsService` 含狀態轉換守衛（`_ALLOWED_TRANSITIONS`）+ FK 驗證（`engagement.client_not_found`）。
- [已確認] `src/taxops/services/document_requests.py`：`DocumentRequestsService` 含 item→request 狀態自動重算（`_derive_request_status`）+ FK 驗證（`doc_request.engagement_not_found`）。
- [已確認] `src/taxops/services/container.py`：新增 `engagements` + `doc_requests` 欄位與 build 連線。
- [已確認] `src/taxops/i18n/errors.py`：新增 engagement / doc_request / doc_request_item 系列錯誤碼。
- [已確認] `tests/test_engagements.py`（22 tests）、`tests/test_document_requests.py`（25 tests）：含 FK 驗證、transition guard、atomicity、5 種 recompute 情境。
- [已確認] `python -m pytest` → **230/230 passed**（2026-05-14 backend）。

### Slice 4.5 — 案件編輯 + 索件項目狀態 UI（2026-05-15）

- [已確認] `src/taxops/ui/dialogs/edit_engagement_dialog.py`（新建）：預填表單（名稱/稅種/期間/負責人/備註），`on_save()` 呼叫 `update_engagement()`，status 保持原值，audit `engagement.update`。
- [已確認] `src/taxops/ui/pages/engagements_page.py`：補「編輯案件」按鈕，無列選取時 disabled；`_on_edit_engagement()` 開啟 EditEngagementDialog，Accept 後 refresh。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：補「切換項目狀態」按鈕，無項目選取時 disabled；`_on_set_item_status()` 透過 `QInputDialog` 選擇新狀態，呼叫 `set_item_status()`，audit `doc_request_item.status_change`；`_on_item_selection_changed()` 管理按鈕 enabled 狀態。
- [已確認] `src/taxops/ui/action_registry.py`：新增 3 個 enabled contract（編輯案件、儲存編輯、切換項目狀態）。
- [已確認] `tests/test_slice45_ui.py`（9 tests）：預填驗證、DB+audit 閉環、按鈕 enabled/disabled；全通過。
- [已確認] `python -m pytest` → **257/257 passed**（2026-05-15）。

### Slice 4 — 案件 + 索件 UI（2026-05-14）

- [已確認] `src/taxops/ui/pages/engagements_page.py`：`EngagementsPage`，client combo filter + 案件列表 + 新增/切換狀態/刪除/管理索件批次；Signal `open_doc_requests(int)` 供 MainWindow 路由。
- [已確認] `src/taxops/ui/dialogs/new_engagement_dialog.py`：`NewEngagementDialog`，表單含案件名稱、稅種、期間、狀態、負責人、備註。
- [已確認] `src/taxops/ui/pages/document_requests_page.py`：`DocumentRequestsPage`，上半索件批次列表 + 下半文件項目表格（QSplitter），Signal `back_to_engagements()` 返回。
- [已確認] `src/taxops/ui/main_window.py`：新增 EngagementsPage / DocumentRequestsPage，`navigate_to()` + `_on_open_doc_requests()` 完成跨頁導航。
- [已確認] `src/taxops/ui/action_registry.py`：PAGE_ENGAGEMENTS 新增 5 個已啟用合約（新增案件/切換狀態/刪除案件/管理索件批次/建立案件），PAGE_DOC_REQUESTS 新增 4 個已啟用合約（新增索件批次/標記已發出/催件+1/刪除批次）。
- [已確認] `src/taxops/services/engagements.py`：新增 `valid_next_statuses(engagement_id)` 方法供 UI 取得有效狀態列表。
- [已確認] `tests/test_slice4_ui_smoke.py`：11 個 smoke test，覆蓋頁面實例化、按鈕存在、啟用/禁用預設。
- [已確認] `python -m pytest` → **241/241 passed**（2026-05-14 UI 閉環）。

## Not Implemented Yet

- [已確認] GCIS query（`data.gcis.nat.gov.tw` Swagger）仍 disabled（`此功能尚未開放`）。
- [已確認] backup/restore 已實作（Slice 11）。
- [已確認] FTS5 search 已實作（Slice 12）。
- [已確認] 安全測試（XSS/HTML injection, resource limits）仍部分未覆蓋（CSV formula injection 已由 test_export_security.py 覆蓋）。
- [已確認] PyInstaller EXE packaging pre-closeout 已完成: one-dir build + automated smoke 通過; 人工 UI checklist 仍待驗證.
- [待驗證] 真實 Windows 桌面驗收（1366×768, 1920×1080, 縮放 100%/125%/150%）尚未執行。

## Frozen / Do Not Change Casually

- [已確認] MVP 範圍必須包含來源規格第 24 節全部項目。
- [已確認] 不做 WSTP 備份讀取、不做自動申報、不做自動 LINE/Email。
- [已確認] 稅籍/工商來源使用官方開放資料；MVP 不爬財政部稅籍登記資料公示查詢頁。
- [已確認] 稅籍快取包不加密且不得包含客戶對照結果。
- [已確認] 單人本機模式，不做登入、角色或權限系統。
- [已確認] UI 方向以 `.ai/DESIGN.md` 為準；不複製品牌識別。

## UI Direction

- [已確認] UI 方向：高奢、簡潔、清楚明瞭；`.ai/DESIGN.md` 為實作權威。
- [已確認] 全域 QSS 已透過 `src/taxops/ui/style.py` + `app.py` 套用（深色 sidebar #1E293B，主色 #2563EB，底色 #F8FAFC）。
- [已確認] `/frontend-design` 和 `/huashu-design` skills 不存在（`~/.claude/skills/` 無此目錄）；UI 改善直接透過 `style.py` 實作。

## Known Bugs / Risks

- [已確認] 目前沒有已確認的測試失敗（583/583 passed）。
- [已修復] `bulk_import_wizard.py` raw exception 露出：已改 `error_message(exc.code)` + `_log.error()`。
- [已修復] `mismatch_review_dialog.py` raw exception 露出：已拆 `ClientValidationError` / generic，UI 顯示中文。
- [已修復] `_parse_diffs()` 靜默吞 JSON 錯誤：已改 `_log.warning()` + 保守回 `{}`。
- [已修復] `parse_excel()` / `parse_csv()` 無測試：已補 `tests/test_clients_bulk_parse.py`（9 tests）。
- [待改善] 兩個 dialog 的錯誤使用 Python `logging`，不是寫入 SQLite `system_logs`。嚴格符合 system log 規格需把 `SystemLogService` 傳進 dialog 或由 page 包裝記錄；不影響「不露 raw exception 給 UI」的目標。
- [待驗證] 真實 Windows 桌面渲染、縮放、hover tooltip、剪貼簿、開啟資料夾。
- [待驗證] PyInstaller EXE 人工 UI 驗收仍需確認字型、版面、對話框、QFileDialog、QProgressDialog、QMessageBox、真實下載流程與客戶 CRUD 持久化。

## Recommended Next Step

1. [建議] 真實 Windows 桌面驗收（Slice 2 五個按鈕 + 客戶管理：編輯、刪除、批量匯入、衝突審查）。
2. [待驗證] Slice 3（HTTP download + URL allowlist + 兩段確認 + GCIS query）。
3. [待改善] Dialog 錯誤改寫入 SQLite `system_logs`（目前用 Python `logging`）。

## 2026-07-12 v0.29.0 release candidate state

- 固定開立顯示完整當年度紀錄；確認列可退回待確認，退回前完整確認資料保存至 audit。
- 客戶管理有特殊要求／備註全文區與「只看有備註」篩選，換行以 plain text 保留。
- 登記名稱搜尋為背景、最多 50 筆同名選擇、10 秒 deadline、stale-result guard；套用客戶可依代碼／名稱篩選。
- 模板編輯器已說明欄位來源；帳款欄位目前是待開立排程，不是收款／欠款帳。
- 最終 fresh branch coverage 90.35%，1,454 tests passed。
- 已知限制：固定開立全客戶展開仍有同步 N+1；名稱 substring search 無專用索引；真實 Windows 視覺與長時間操作仍需人工驗收。
