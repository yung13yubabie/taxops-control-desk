# Annual Workbench UI and Offline EXE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved annual workbench as a real PySide6 page, verify end-to-end user paths and non-clipping layouts, keep total branch coverage at least 90%, and package a working offline Windows EXE.

**Architecture:** Build the workbench from focused widgets over the compliance services, not duplicated UI state. Use bounded queries, explicit refresh hooks, scroll areas and splitters; the release chain rebuilds the executable only after tests and code review pass.

**Tech Stack:** PySide6, SQLite-backed services, pytest/pytest-cov, PyInstaller, PowerShell release tooling.

---

### Task 1: Register the annual workbench as a real navigation page

**Files:**
- Modify: `src/taxops/ui/action_registry.py`
- Modify: `src/taxops/i18n/labels.py`
- Modify: `src/taxops/ui/main_window.py`
- Create: `src/taxops/ui/pages/annual_workbench_page.py`
- Create: `tests/test_annual_workbench_navigation.py`

- [ ] **Step 1: Write a failing navigation smoke test**

```python
def test_main_window_opens_real_annual_workbench(qtbot, container):
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.navigate_to(PAGE_ANNUAL_WORKBENCH)
    page = window._stack.currentWidget()
    assert isinstance(page, AnnualWorkbenchPage)
    assert page.title_label.text() == "年度工作台"
```

- [ ] **Step 2: Run the test and confirm the page constant/class are missing**

Run: `python -m pytest tests/test_annual_workbench_navigation.py -q`

Expected: FAIL because `PAGE_ANNUAL_WORKBENCH` and `AnnualWorkbenchPage` do not exist.

- [ ] **Step 3: Add the page constant, Chinese label, and page factory branch**

```python
PAGE_ANNUAL_WORKBENCH = "annual_workbench"
NAV_ORDER = (
    PAGE_CLIENTS,
    PAGE_ANNUAL_WORKBENCH,
    PAGE_ENGAGEMENTS,
    PAGE_TASKS,
    PAGE_WORK_RECORDS,
    PAGE_TEMPLATES,
    PAGE_REGISTRY,
    PAGE_LATE_FEE,
    PAGE_ATTACHMENTS,
    PAGE_FOLDER_BOOKMARKS,
    PAGE_RECURRING_BILLING,
    PAGE_SETTINGS,
)
```

The page constructor receives the existing `ServiceContainer`. It exposes `refresh_context()`, `clear_filter()`, and `set_filter()` in the same style as existing pages.

- [ ] **Step 4: Run navigation tests and commit**

Run: `python -m pytest tests/test_annual_workbench_navigation.py tests/test_main_window.py -q`

Expected: PASS.

```powershell
git add src/taxops/ui/action_registry.py src/taxops/i18n/labels.py src/taxops/ui/main_window.py src/taxops/ui/pages/annual_workbench_page.py tests
git commit -m "feat: add annual workbench navigation"
```

### Task 2: Implement the bounded office-wide overview

**Files:**
- Create: `src/taxops/ui/widgets/annual_overview_table.py`
- Modify: `src/taxops/ui/pages/annual_workbench_page.py`
- Create: `tests/test_annual_workbench_overview_ui.py`

- [ ] **Step 1: Write failing filter and exact-content UI tests**

```python
def test_overview_filters_by_risk_and_shows_exact_unpaid_tax(qtbot, seeded_annual_page):
    page = seeded_annual_page
    page.risk_combo.setCurrentData("unpaid_tax")
    qtbot.mouseClick(page.apply_filter_button, Qt.MouseButton.LeftButton)
    assert page.table.rowCount() == 1
    assert page.table.item(0, COL_CLIENT).text() == "晨岳設計有限公司"
    assert page.table.item(0, COL_UNPAID_TAX).text() == "NT$ 22,000"
```

- [ ] **Step 2: Run overview tests and confirm the empty page fails**

Run: `python -m pytest tests/test_annual_workbench_overview_ui.py -q`

Expected: FAIL because filters, metrics, and table are not implemented.

- [ ] **Step 3: Build filters, computed metrics, and a paginated table**

Use operation year, client query, work type, and risk controls. Fetch at most 100 rows per page. Summary metrics use one aggregate query and show loading/error/success states. No enabled button may be disconnected.

- [ ] **Step 4: Preserve full text without arbitrary reflow**

Set stable widths for status/date/money columns, stretch client and title columns, enable horizontal scrolling, apply full-text tooltips, and display selected-row full details outside the table. Unknown status values use the canonical unknown label and system log.

- [ ] **Step 5: Run overview UI tests and commit**

Run: `python -m pytest tests/test_annual_workbench_overview_ui.py -q`

Expected: PASS.

```powershell
git add src/taxops/ui/widgets/annual_overview_table.py src/taxops/ui/pages/annual_workbench_page.py tests/test_annual_workbench_overview_ui.py
git commit -m "feat: show annual compliance risks"
```

### Task 3: Implement preview-first annual creation

**Files:**
- Create: `src/taxops/ui/dialogs/annual_workspace_dialog.py`
- Modify: `src/taxops/ui/pages/annual_workbench_page.py`
- Create: `tests/test_annual_workspace_dialog.py`

- [ ] **Step 1: Write failing double-click and rollback UI tests**

```python
def test_confirm_button_double_click_creates_one_workspace(qtbot, container, client):
    dialog = AnnualWorkspaceDialog(container, preselected_client_id=client.id, operation_year=2026)
    qtbot.addWidget(dialog)
    dialog.load_preview()
    qtbot.mouseDClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert len(container.annual_work.list_workspaces(client_id=client.id, operation_year=2026)) == 1
    assert dialog.result() == QDialog.DialogCode.Accepted
```

- [ ] **Step 2: Run dialog tests and verify the class is missing**

Run: `python -m pytest tests/test_annual_workspace_dialog.py -q`

Expected: FAIL because the creation dialog does not exist.

- [ ] **Step 3: Implement profile defaults and editable preview rows**

The dialog requires a client and operation year, defaults to calendar year, lists each proposed item with a checkbox, supports adding custom title/tax year/period/due date, and validates before calling `confirm_preview()`.

- [ ] **Step 4: Make success evidence-driven**

Disable confirm during service execution. After return, re-read the workspace and items; show `已建立` only when `created=True`, otherwise show `已開啟既有年度，未新增重複資料`. On error, keep the dialog open with all input rows intact.

- [ ] **Step 5: Run dialog tests and commit**

Run: `python -m pytest tests/test_annual_workspace_dialog.py -q`

Expected: PASS.

```powershell
git add src/taxops/ui/dialogs/annual_workspace_dialog.py src/taxops/ui/pages/annual_workbench_page.py tests/test_annual_workspace_dialog.py
git commit -m "feat: preview annual work before creation"
```

### Task 4: Build the client-year detail editor with shared requests and attachments

**Files:**
- Create: `src/taxops/ui/widgets/annual_item_detail.py`
- Create: `src/taxops/ui/dialogs/annual_item_dialog.py`
- Create: `src/taxops/ui/dialogs/annual_transaction_dialog.py`
- Modify: `src/taxops/ui/pages/annual_workbench_page.py`
- Create: `tests/test_annual_item_detail_ui.py`
- Create: `tests/test_annual_request_bidirectional_ui.py`

- [ ] **Step 1: Write failing user-path tests for request editing from the workbench**

```python
def test_add_missing_item_in_workbench_is_visible_in_request_page(qtbot, container, work_item):
    page = AnnualWorkbenchPage(container)
    qtbot.addWidget(page)
    page.open_item(work_item.id)
    page.detail.add_request("03–04 月憑證", ["進項發票", "銷項發票"])
    request = container.document_requests.list_by_engagement(work_item.engagement_id)[0]
    assert [row.item_name for row in container.document_requests.list_items(request.id)] == ["進項發票", "銷項發票"]
```

- [ ] **Step 2: Run detail tests and confirm workbench actions are absent**

Run: `python -m pytest tests/test_annual_item_detail_ui.py tests/test_annual_request_bidirectional_ui.py -q`

Expected: FAIL because the detail editor does not exist.

- [ ] **Step 3: Implement independent status, dates, exception, and notes editing**

The form edits operation/tax periods separately, displays suggested and adopted due dates, presents five status controls, and requires an exception reason before abnormal completion. Save failures keep every value and focus the first invalid field.

- [ ] **Step 4: Embed shared request and attachment operations**

Use existing request/item/attachment services directly. Show actual IDs/counts, allow add/edit/status/upload/preview/archive, refresh after each mutation, and never maintain a second in-memory truth after saving.

- [ ] **Step 5: Embed transaction rows and derived balances**

Show every transaction with category/date/reference, expose add/edit/remove through the transaction service, and re-read balances after each mutation. Total fields are labels, never editable controls.

- [ ] **Step 6: Run detail and existing-page regression tests**

Run: `python -m pytest tests/test_annual_item_detail_ui.py tests/test_annual_request_bidirectional_ui.py tests/test_engagements_page.py tests/test_attachments_ui.py -q`

Expected: PASS with the same database IDs visible from both pages.

- [ ] **Step 7: Commit the detail slice**

```powershell
git add src/taxops/ui/widgets/annual_item_detail.py src/taxops/ui/dialogs/annual_item_dialog.py src/taxops/ui/dialogs/annual_transaction_dialog.py src/taxops/ui/pages/annual_workbench_page.py tests
git commit -m "feat: edit annual work and shared requests"
```

### Task 5: Verify non-clipping behavior at supported desktop sizes

**Files:**
- Modify: `src/taxops/ui/pages/annual_workbench_page.py`
- Modify: `src/taxops/ui/widgets/annual_item_detail.py`
- Modify: `src/taxops/ui/dialogs/annual_workspace_dialog.py`
- Create: `tests/test_annual_workbench_layout.py`

- [ ] **Step 1: Write failing geometry and complete-text tests**

```python
@pytest.mark.parametrize("size", [(900, 540), (1156, 648), (1728, 972)])
def test_workbench_actions_and_full_warning_remain_reachable(qtbot, page, size):
    page.resize(*size)
    page.show()
    qtbot.waitExposed(page)
    assert page.create_button.isVisible()
    assert page.detail.save_button.isVisible()
    assert page.detail.warning_label.wordWrap()
    assert "尚有 3 項憑證未收到" in page.detail.warning_label.text()
```

- [ ] **Step 2: Run layout tests and capture current failures**

Run: `python -m pytest tests/test_annual_workbench_layout.py -q`

Expected: FAIL for widgets that are clipped or missing scroll containers.

- [ ] **Step 3: Apply scroll and splitter constraints**

Use a `QSplitter` for overview/detail, `QScrollArea(widgetResizable=True)` for long forms, no fixed-height explanatory labels, and a bottom action bar outside the scroll content. Keep minimum control sizes compatible with the existing 900×540 window minimum.

- [ ] **Step 4: Run layout tests at 100%, 125%, and 150% logical sizes**

Run: `python -m pytest tests/test_annual_workbench_layout.py -q`

Expected: PASS for all parameterized sizes with full warning text available.

- [ ] **Step 5: Commit the layout hardening slice**

```powershell
git add src/taxops/ui tests/test_annual_workbench_layout.py
git commit -m "fix: keep annual workbench content reachable"
```

### Task 6: Update collaboration docs and version metadata

**Files:**
- Modify: `.ai/CURRENT_STATE.md`
- Modify: `.ai/TASKS.md`
- Modify: `.ai/DECISIONS.md`
- Modify: `.ai/HANDOFF.md`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Record only verified current behavior**

Document the new page, migration versions, shared-data invariants, offline behavior, manual acceptance still required, and exact verification commands/results. Do not describe unrun packaging or UI checks as passed.

- [ ] **Step 2: Set version to 0.30.0 only after feature tests pass**

Update `pyproject.toml` and any existing product-version source together. Add a changelog entry covering addresses, leases, industries, annual work, transactions, and bidirectional request integration.

- [ ] **Step 3: Run metadata regression tests and commit**

Run: `python -m pytest tests/test_version_consistency.py tests/test_docs_paths.py -q`

Expected: PASS.

```powershell
git add .ai pyproject.toml README.md CHANGELOG.md
git commit -m "docs: prepare v0.30.0 annual workbench release"
```

### Task 7: Run five-axis code review and fix all required findings

**Files:**
- Review: every path changed from `d57a006..HEAD`
- Modify: only files needed to resolve confirmed findings
- Test: regression tests added for each correctness finding

- [ ] **Step 1: Review tests before implementation**

Confirm each user-visible behavior has a regression test that would fail without the feature: migration, idempotence, rollback, cross-page IDs, partial money, unknown states, no-industry source, and constrained layout.

- [ ] **Step 2: Review implementation across five axes**

Use `$code-review-and-quality` and record findings by severity:

- Correctness: state transitions, transaction boundaries, null/boundary values.
- Readability: focused files, clear names, no obsolete compatibility code beyond the documented migration window.
- Architecture: no parallel request/attachment store and no UI-to-repository bypass.
- Security: parameterized SQL, sanitized inputs, safe attachment paths, no raw exception disclosure.
- Performance: paginated overview, aggregate balance queries, no per-row client/request N+1 calls.

- [ ] **Step 3: Fix every Critical and required finding with a failing test first**

For each finding, add a test that reproduces the issue, run it to fail, implement the minimal correction, and rerun the focused suite.

- [ ] **Step 4: Run dead-code scan and request removal only for uncertain artifacts**

Use `rg` for superseded address/lease code and static import checks. Remove clearly unreachable code introduced by this branch; list uncertain pre-existing code instead of silently deleting it.

- [ ] **Step 5: Commit review fixes**

```powershell
git add src tests .ai
git commit -m "fix: address annual workbench review findings"
```

### Task 8: Prove coverage, UI workflow, packaging, and offline startup

**Files:**
- Modify: tests or production files only when a real verification failure identifies a defect
- Generate: `dist/TaxOpsControlDesk-v0.30.0-win64.zip`

- [ ] **Step 1: Run compile and focused security checks**

Run: `python -m compileall -q src tests build_tools`

Expected: exit 0.

Run available local scanners without installing new unapproved dependencies; always run repository secret/path checks and parameterized-SQL review.

- [ ] **Step 2: Run the full branch-coverage suite**

Run: `python -m pytest --cov=taxops --cov-branch --cov-report=term-missing --cov-fail-under=90`

Expected: all tests PASS and TOTAL branch coverage ≥ 90.00%.

- [ ] **Step 3: Run real PySide6 user-path smoke**

Open the app through its normal entry point with an isolated data root; create a client with separate addresses and two leases, apply industries, create a 2026 annual workspace, add a request and partial tax/payment rows, close and reopen, and assert exact persisted content.

- [ ] **Step 4: Run resource hygiene after UI/test processes exit**

Run: `python -m build_tools.check_resource_hygiene`

Expected: no TaxOps, pytest, PyInstaller, test browser, or test-owned listener remains.

- [ ] **Step 5: Build the Windows executable**

Run the repository's documented PyInstaller build command from a clean `build/` and `dist/`. Do not reuse the v0.29.0 executable.

Expected: a new v0.30.0 executable with current modification time and version metadata.

- [ ] **Step 6: Smoke the packaged executable with isolated LOCALAPPDATA**

Launch the EXE with a fresh temporary `LOCALAPPDATA`, verify it stays alive for at least eight seconds, creates the expected SQLite schema through the final v0.30.0 migration, and terminates cleanly without residual process.

- [ ] **Step 7: Create ZIP, checksum, and readiness report**

Package the executable and required runtime files as `dist/TaxOpsControlDesk-v0.30.0-win64.zip`, compute SHA-256, and record file size, checksum, test count, total branch coverage, UI smoke evidence, EXE smoke evidence, and unresolved manual checks.

- [ ] **Step 8: Commit final evidence and handoff**

```powershell
git add .ai README.md CHANGELOG.md
git commit -m "release: verify offline annual workbench v0.30.0"
```
