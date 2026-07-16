# Annual Compliance Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one idempotent annual workspace per client and operation year, generate correct period work, track independent states, and calculate tax and fee balances from audited transaction rows.

**Architecture:** Introduce a compliance domain beside engagements rather than overloading them. A generation service creates stable item keys from a client profile, while work items optionally link to existing engagements and tasks through foreign keys.

**Tech Stack:** Python dataclasses, SQLite transactions and constraints, existing audit/service container, pytest with branch coverage.

---

### Task 1: Create compliance schema and database constraints

**Files:**
- Create: `src/taxops/db/migrations/_m0028_annual_compliance.py`
- Modify: `src/taxops/db/migrations/__init__.py`
- Create: `tests/test_annual_compliance_migration.py`

- [ ] **Step 1: Write failing schema and uniqueness tests**

```python
def test_only_one_active_workspace_per_client_and_operation_year(conn, client_id):
    run_all_migrations(conn)
    conn.execute(
        "INSERT INTO annual_workspaces(client_id, operation_year, fiscal_year_start_month_snapshot, status, created_at, updated_at) "
        "VALUES (?, 2026, 1, 'active', 't', 't')",
        (client_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO annual_workspaces(client_id, operation_year, fiscal_year_start_month_snapshot, status, created_at, updated_at) "
            "VALUES (?, 2026, 1, 'active', 't', 't')",
            (client_id,),
        )
```

- [ ] **Step 2: Run the migration test and confirm tables are absent**

Run: `python -m pytest tests/test_annual_compliance_migration.py -q`

Expected: FAIL with `no such table: annual_workspaces`.

- [ ] **Step 3: Add profile, workspace, item, transaction, and task-link schema**

```sql
CREATE TABLE compliance_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id),
    fiscal_year_start_month INTEGER NOT NULL DEFAULT 1 CHECK(fiscal_year_start_month BETWEEN 1 AND 12),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE compliance_profile_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES compliance_profiles(id) ON DELETE CASCADE,
    work_type TEXT NOT NULL,
    frequency TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, work_type)
);
CREATE TABLE annual_workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    operation_year INTEGER NOT NULL CHECK(operation_year BETWEEN 1912 AND 9999),
    fiscal_year_start_month_snapshot INTEGER NOT NULL CHECK(fiscal_year_start_month_snapshot BETWEEN 1 AND 12),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE UNIQUE INDEX ux_annual_workspaces_active
    ON annual_workspaces(client_id, operation_year) WHERE deleted_at IS NULL;
CREATE TABLE annual_work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES annual_workspaces(id),
    item_key TEXT NOT NULL,
    work_type TEXT NOT NULL,
    title TEXT NOT NULL,
    tax_year INTEGER,
    period_code TEXT,
    suggested_due_date TEXT,
    due_date TEXT,
    work_status TEXT NOT NULL DEFAULT 'not_started',
    filing_status TEXT NOT NULL DEFAULT 'not_filed',
    document_status TEXT NOT NULL DEFAULT 'not_requested',
    tax_status TEXT NOT NULL DEFAULT 'unconfirmed',
    fee_status TEXT NOT NULL DEFAULT 'not_billed',
    engagement_id INTEGER REFERENCES engagements(id),
    exception_reason TEXT,
    notes TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE UNIQUE INDEX ux_annual_work_items_active
    ON annual_work_items(workspace_id, item_key) WHERE deleted_at IS NULL;
CREATE TABLE annual_work_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES annual_work_items(id),
    category TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount >= 0),
    transaction_date TEXT NOT NULL,
    reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
ALTER TABLE workflow_tasks ADD COLUMN annual_work_item_id INTEGER REFERENCES annual_work_items(id);
CREATE INDEX idx_workflow_tasks_annual_item ON workflow_tasks(annual_work_item_id);
```

- [ ] **Step 4: Run schema tests, foreign-key checks, and migration idempotence**

Run: `python -m pytest tests/test_annual_compliance_migration.py tests/test_migrations.py -q`

Expected: PASS with `PRAGMA foreign_key_check` returning no rows.

- [ ] **Step 5: Commit the schema slice**

```powershell
git add src/taxops/db/migrations tests/test_annual_compliance_migration.py
git commit -m "feat: add annual compliance schema"
```

### Task 2: Implement profiles and period generation rules

**Files:**
- Create: `src/taxops/services/compliance_rules.py`
- Create: `src/taxops/repositories/compliance_profiles.py`
- Create: `src/taxops/services/compliance_profiles.py`
- Create: `tests/test_compliance_rules.py`
- Create: `tests/test_compliance_profiles.py`

- [ ] **Step 1: Write failing calendar and special-year tests**

```python
def test_bimonthly_vat_generates_six_periods_for_calendar_year():
    drafts = build_standard_drafts(2026, fiscal_start_month=1, enabled={"vat": "bimonthly"})
    assert [(d.tax_year, d.period_code, d.suggested_due_date) for d in drafts] == [
        (2026, "01-02", "2026-03-15"),
        (2026, "03-04", "2026-05-15"),
        (2026, "05-06", "2026-07-15"),
        (2026, "07-08", "2026-09-15"),
        (2026, "09-10", "2026-11-15"),
        (2026, "11-12", "2027-01-15"),
    ]

def test_may_work_keeps_operation_year_separate_from_tax_year():
    drafts = build_standard_drafts(2026, fiscal_start_month=1, enabled={"corporate_income_tax": "annual"})
    item = drafts[0]
    assert item.operation_year == 2026
    assert item.tax_year == 2025
```

- [ ] **Step 2: Run rule tests and confirm missing-module failure**

Run: `python -m pytest tests/test_compliance_rules.py tests/test_compliance_profiles.py -q`

Expected: FAIL because compliance rule/profile modules do not exist.

- [ ] **Step 3: Implement stable draft values and explicit built-in rules**

```python
@dataclass(frozen=True)
class WorkDraft:
    item_key: str
    operation_year: int
    work_type: str
    title: str
    tax_year: int | None
    period_code: str | None
    suggested_due_date: str | None

def _draft(operation_year, work_type, title, tax_year, period_code, due_date):
    key = f"{work_type}:{tax_year or '-'}:{period_code or '-'}"
    return WorkDraft(key, operation_year, work_type, title, tax_year, period_code, due_date)
```

Implement explicit functions for monthly bookkeeping, VAT monthly/bimonthly, withholding payments, annual withholding statements, corporate income tax, undistributed earnings, provisional tax, payroll/insurance, and company annual work. Use `datetime.date` arithmetic only; do not call the network or infer holiday extensions.

- [ ] **Step 4: Implement validated profile upsert**

Reject unknown work types/frequencies, enforce start month 1..12, and preserve disabled profile rows. Audit `compliance_profile.update` with only type/frequency values, never client notes.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_compliance_rules.py tests/test_compliance_profiles.py -q`

Expected: PASS.

```powershell
git add src/taxops/services/compliance_rules.py src/taxops/repositories/compliance_profiles.py src/taxops/services/compliance_profiles.py tests
git commit -m "feat: define client compliance profiles"
```

### Task 3: Create idempotent annual workspaces and preview generation

**Files:**
- Create: `src/taxops/repositories/annual_work.py`
- Create: `src/taxops/services/annual_work.py`
- Modify: `src/taxops/services/container.py`
- Create: `tests/test_annual_work_generation.py`

- [ ] **Step 1: Write failing preview, duplicate, and rollback tests**

```python
def test_confirm_preview_is_idempotent(container, client):
    preview = container.annual_work.preview(client.id, 2026)
    first = container.annual_work.confirm_preview(client.id, 2026, preview)
    second = container.annual_work.confirm_preview(client.id, 2026, preview)
    assert second.workspace.id == first.workspace.id
    assert [row.item_key for row in second.items] == [row.item_key for row in first.items]

def test_confirm_preview_rolls_back_workspace_when_item_insert_fails(container, client, monkeypatch):
    monkeypatch.setattr(container.annual_work._repo, "insert_item", Mock(side_effect=sqlite3.Error("boom")))
    with pytest.raises(AnnualWorkError):
        container.annual_work.confirm_preview(client.id, 2026, container.annual_work.preview(client.id, 2026))
    assert container.annual_work._repo.find_workspace(client.id, 2026) is None
```

- [ ] **Step 2: Run generation tests and confirm missing-service failure**

Run: `python -m pytest tests/test_annual_work_generation.py -q`

Expected: FAIL because the annual repository/service do not exist.

- [ ] **Step 3: Implement repository reads and bounded queries**

Provide `find_workspace`, `list_workspaces(limit, offset)`, `insert_workspace`, `insert_item_if_missing`, `list_items`, and `search_overview(filters, limit, offset)`. All dynamic sort fields use an allowlist; all values remain query parameters.

- [ ] **Step 4: Implement preview and transactional confirm**

```python
def confirm_preview(self, client_id, operation_year, drafts):
    normalized = self._validate_preview(client_id, operation_year, drafts)
    with self._conn:
        workspace = self._repo.find_workspace(client_id, operation_year)
        if workspace is None:
            workspace = self._repo.insert_workspace(client_id, operation_year, self._profile_start_month(client_id))
        for draft in normalized:
            self._repo.insert_item_if_missing(workspace.id, draft)
        items = self._repo.list_items(workspace.id)
        self._audit.record(
            action="annual_workspace.confirm",
            target_type="annual_workspace",
            target_id=str(workspace.id),
            detail={"operation_year": operation_year, "item_count": len(items)},
        )
    return AnnualWorkspaceResult(workspace, items)
```

On unique conflicts, re-read and return the existing workspace; never emit a created flag unless this transaction inserted it.

- [ ] **Step 5: Run generation tests and commit**

Run: `python -m pytest tests/test_annual_work_generation.py -q`

Expected: PASS, including repeated calls and injected item failure.

```powershell
git add src/taxops/repositories/annual_work.py src/taxops/services/annual_work.py src/taxops/services/container.py tests/test_annual_work_generation.py
git commit -m "feat: generate annual work idempotently"
```

### Task 4: Validate independent statuses and abnormal completion

**Files:**
- Modify: `src/taxops/services/annual_work.py`
- Modify: `src/taxops/repositories/annual_work.py`
- Create: `tests/test_annual_work_status.py`

- [ ] **Step 1: Write failing status-transition tests**

```python
def test_completion_with_open_risk_requires_reason_and_remains_risky(container, work_item):
    with pytest.raises(AnnualWorkValidationError) as error:
        container.annual_work.complete_item(work_item.id, exception_reason="")
    assert error.value.code == "annual_work.exception_reason.required"
    completed = container.annual_work.complete_item(work_item.id, exception_reason="客戶尚未補件")
    assert completed.work_status == "completed_with_exception"
    assert container.annual_work.search_overview(risk="exception")[0].id == completed.id
```

- [ ] **Step 2: Run status tests and verify the new behavior is absent**

Run: `python -m pytest tests/test_annual_work_status.py -q`

Expected: FAIL because status transitions are not implemented.

- [ ] **Step 3: Implement allowlisted independent status updates**

Each status setter validates against a frozen set, verifies the active item, writes one audit event, and leaves the other four status columns unchanged. Unknown stored states are returned to the UI as unknown labels and logged rather than coerced.

- [ ] **Step 4: Implement deletion/cancellation policy**

`delete_item()` hard-deletes only when no transaction, engagement, document request, attachment, or linked task exists. Otherwise `cancel_item(reason)` sets cancelled fields. `restore_item()` clears cancellation but never recreates hard-deleted rows.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_annual_work_status.py -q`

Expected: PASS.

```powershell
git add src/taxops/services/annual_work.py src/taxops/repositories/annual_work.py tests/test_annual_work_status.py
git commit -m "feat: track annual work states independently"
```

### Task 5: Add audited transaction ledger and derived balances

**Files:**
- Create: `src/taxops/repositories/annual_transactions.py`
- Create: `src/taxops/services/annual_transactions.py`
- Modify: `src/taxops/services/container.py`
- Create: `tests/test_annual_transactions.py`

- [ ] **Step 1: Write failing partial-collection and payment tests**

```python
def test_tax_and_fee_balances_are_independent(container, work_item):
    add = container.annual_transactions.add
    add(work_item.id, "tax_liability", 62000, "2026-05-10")
    add(work_item.id, "client_tax_collection", 43400, "2026-05-12")
    add(work_item.id, "tax_payment", 40000, "2026-05-15")
    add(work_item.id, "fee_receivable", 5000, "2026-05-01")
    add(work_item.id, "fee_receipt", 2000, "2026-05-13")
    balance = container.annual_transactions.balance(work_item.id)
    assert balance.client_collection_shortfall == 18600
    assert balance.unpaid_tax == 22000
    assert balance.outstanding_fee == 3000
```

- [ ] **Step 2: Run ledger tests and confirm missing-service failure**

Run: `python -m pytest tests/test_annual_transactions.py -q`

Expected: FAIL because the transaction service does not exist.

- [ ] **Step 3: Implement validated add/update/soft-delete operations**

Accept only the six documented categories, integer values from 0 through `9_000_000_000_000`, ISO dates, sanitized reference/notes, and active work items. Each mutation and audit write shares one transaction.

- [ ] **Step 4: Implement a single aggregate query for balances**

```sql
SELECT
  COALESCE(SUM(CASE WHEN category='tax_liability' THEN amount ELSE 0 END), 0) AS liability,
  COALESCE(SUM(CASE WHEN category='client_tax_collection' THEN amount ELSE 0 END), 0) AS collected,
  COALESCE(SUM(CASE WHEN category='tax_payment' THEN amount ELSE 0 END), 0) AS paid,
  COALESCE(SUM(CASE WHEN category='tax_credit_or_refund' THEN amount ELSE 0 END), 0) AS credits,
  COALESCE(SUM(CASE WHEN category='fee_receivable' THEN amount ELSE 0 END), 0) AS fees,
  COALESCE(SUM(CASE WHEN category='fee_receipt' THEN amount ELSE 0 END), 0) AS fee_receipts
FROM annual_work_transactions
WHERE work_item_id = ? AND deleted_at IS NULL
```

Return `max(0, liability - credits - collected)`, `max(0, liability - credits - paid)`, and `max(0, fees - fee_receipts)` as separate values.

- [ ] **Step 5: Run ledger tests and commit**

Run: `python -m pytest tests/test_annual_transactions.py -q`

Expected: PASS.

```powershell
git add src/taxops/repositories/annual_transactions.py src/taxops/services/annual_transactions.py src/taxops/services/container.py tests/test_annual_transactions.py
git commit -m "feat: calculate annual tax and fee balances"
```

### Task 6: Link annual work to existing engagements, requests, attachments, and tasks

**Files:**
- Modify: `src/taxops/services/annual_work.py`
- Modify: `src/taxops/repositories/annual_work.py`
- Modify: `src/taxops/services/tasks.py`
- Modify: `tests/test_annual_work_integration.py`

- [ ] **Step 1: Write failing bidirectional-link tests**

```python
def test_request_created_from_annual_work_is_same_row_seen_by_request_service(container, work_item):
    linked = container.annual_work.create_linked_request(
        work_item.id,
        request_name="03–04 月營業稅憑證",
        item_names=("進項發票", "銷項發票"),
    )
    assert container.document_requests.get_request(linked.request.id).id == linked.request.id
    summary = container.annual_work.document_summary(work_item.id)
    assert (summary.total, summary.missing) == (2, 2)
```

- [ ] **Step 2: Run integration tests and verify missing orchestration**

Run: `python -m pytest tests/test_annual_work_integration.py -q`

Expected: FAIL because annual work cannot create or link requests.

- [ ] **Step 3: Implement shared-row orchestration**

Create or reuse one engagement, insert the request/items through existing repositories, update `annual_work_items.engagement_id`, and record one orchestration audit event. Use the same SQLite transaction; if any step raises, roll back all inserted rows.

- [ ] **Step 4: Implement document summary and optional linked task creation**

Document summary queries existing request/item/attachment tables by the work item's engagement. Task creation sets `annual_work_item_id` and `client_id`; it never auto-completes when work completes.

- [ ] **Step 5: Run integration tests and commit**

Run: `python -m pytest tests/test_annual_work_integration.py tests/test_document_requests.py tests/test_tasks.py -q`

Expected: PASS with exact same IDs visible from both services.

```powershell
git add src/taxops/services/annual_work.py src/taxops/repositories/annual_work.py src/taxops/services/tasks.py tests
git commit -m "feat: link annual work to existing workflows"
```
