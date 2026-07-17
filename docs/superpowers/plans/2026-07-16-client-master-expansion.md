# Client Master Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add registered/contact addresses, multiple leases, lease attachments, and persistent client industry lists while preserving all v0.29.0 data.

**Architecture:** Extend the client aggregate with focused lease and industry repositories/services. Keep the legacy address and lease columns readable only for migration compatibility, and make registry application replace industries transactionally without overwriting contact addresses.

**Tech Stack:** Python 3.11, SQLite migrations, PySide6, pytest, existing TaxOps repository/service/audit patterns.

---

### Task 1: Upgrade v0.29.0 client data without loss

**Files:**
- Create: `src/taxops/db/migrations/_m0027_client_master_expansion.py`
- Modify: `src/taxops/db/migrations/__init__.py`
- Test: `tests/test_client_master_migration.py`
- Modify: `tests/test_db_migrations.py`

- [ ] **Step 1: Write migration tests that fail before migration 0027 exists**

```python
def test_client_master_migration_backfills_addresses_and_legacy_lease(v029_conn):
    client_id = v029_conn.execute(
        "INSERT INTO clients(client_code, client_name, address, lease_start, lease_end, created_at, updated_at) "
        "VALUES ('C1', '測試公司', '臺北市舊址', '2025-01-01', '2026-12-31', 't', 't')"
    ).lastrowid
    apply_migrations(v029_conn)
    client = v029_conn.execute(
        "SELECT registered_address, contact_address, contact_address_same FROM clients WHERE id = ?",
        (client_id,),
    ).fetchone()
    assert tuple(client) == ("臺北市舊址", "臺北市舊址", 1)
    leases = v029_conn.execute(
        "SELECT lease_name, start_date, end_date FROM client_leases WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    assert [tuple(row) for row in leases] == [("既有租約", "2025-01-01", "2026-12-31")]

def test_client_master_migration_preserves_existing_attachment_versions(v029_conn):
    attachment_before = tuple(v029_conn.execute("SELECT * FROM attachments").fetchone())
    version_before = tuple(v029_conn.execute("SELECT * FROM attachment_versions").fetchone())
    apply_migrations(v029_conn)
    attachment_after = tuple(
        v029_conn.execute(
            "SELECT id, engagement_id, request_id, original_filename, stored_filename, "
            "file_hash_sha256, file_size, mime_type, extension, uploaded_by, uploaded_at, "
            "source, status, notes, accepted_by, accepted_at FROM attachments"
        ).fetchone()
    )
    version_after = tuple(v029_conn.execute("SELECT * FROM attachment_versions").fetchone())
    assert attachment_after == attachment_before
    assert version_after == version_before

def test_client_master_migration_preserves_attachment_sequence_high_water(v029_conn):
    # Arrange sqlite_sequence above MAX(id), migrate, then verify the next IDs
    # remain above the pre-migration high-water mark so audit target IDs cannot
    # become ambiguous through ID reuse.
    ...

def test_lease_attachment_owner_is_enforced_by_database(v029_conn):
    apply_migrations(v029_conn)
    # A lease belonging to client A cannot be inserted as an attachment owned
    # by client B, even through direct SQL that bypasses the service layer.
    ...
```

Build `v029_conn` explicitly with `open_connection()` and
`MIGRATIONS[:26]`, then insert realistic v0.29 rows. Do not reuse the global
`db_conn` fixture because it immediately applies every migration. Cover a
request-owned attachment, a multi-row `supersedes_id` chain, partial legacy
lease dates, `NULL` address, an empty database, `PRAGMA foreign_key_check`, no
temporary migration tables, all required indexes, and a second
`apply_migrations()` no-op.

- [ ] **Step 2: Run the migration tests and verify the missing-column/table failure**

Run: `python -m pytest tests/test_client_master_migration.py -q`

Expected: FAIL because migration 0027 and the new columns/tables do not exist.

- [ ] **Step 3: Add migration 0027 and register it**

```python
SQL = """
ALTER TABLE clients ADD COLUMN registered_address TEXT;
ALTER TABLE clients ADD COLUMN contact_address TEXT;
ALTER TABLE clients ADD COLUMN contact_address_same INTEGER NOT NULL DEFAULT 1
    CHECK(contact_address_same IN (0, 1));

UPDATE clients
   SET registered_address = address,
       contact_address = address
 WHERE address IS NOT NULL;

CREATE TABLE client_leases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    lease_name TEXT NOT NULL,
    premises_address TEXT,
    landlord_name TEXT,
    start_date TEXT,
    end_date TEXT,
    monthly_rent INTEGER CHECK(monthly_rent IS NULL OR monthly_rent >= 0),
    deposit_amount INTEGER CHECK(deposit_amount IS NULL OR deposit_amount >= 0),
    reminder_days INTEGER NOT NULL DEFAULT 60 CHECK(reminder_days BETWEEN 0 AND 3650),
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(id, client_id)
);
CREATE INDEX idx_client_leases_client ON client_leases(client_id);
CREATE INDEX idx_client_leases_end_date ON client_leases(end_date);

INSERT INTO client_leases(
    client_id, lease_name, start_date, end_date, status, created_at, updated_at
)
SELECT id, '既有租約', lease_start, lease_end, 'active', updated_at, updated_at
  FROM clients
 WHERE lease_start IS NOT NULL OR lease_end IS NOT NULL;

CREATE TABLE client_industries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    industry_code TEXT NOT NULL,
    industry_name TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    source_version TEXT,
    applied_at TEXT NOT NULL,
    UNIQUE(client_id, industry_code)
);
CREATE INDEX idx_client_industries_client ON client_industries(client_id, sort_order);

CREATE TEMP TABLE _m0027_sequence_high_water (
    name TEXT PRIMARY KEY,
    seq INTEGER NOT NULL
);
INSERT INTO _m0027_sequence_high_water(name, seq)
SELECT 'attachments', MAX(
    COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'attachments'), 0),
    COALESCE((SELECT MAX(id) FROM attachments), 0)
);
INSERT INTO _m0027_sequence_high_water(name, seq)
SELECT 'attachment_versions', MAX(
    COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'attachment_versions'), 0),
    COALESCE((SELECT MAX(id) FROM attachment_versions), 0)
);

CREATE TABLE attachments_v030_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id INTEGER REFERENCES engagements(id),
    request_id INTEGER REFERENCES document_requests(id),
    client_id INTEGER REFERENCES clients(id),
    lease_id INTEGER,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_hash_sha256 TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    uploaded_by TEXT NOT NULL DEFAULT 'local_user',
    uploaded_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'uploaded',
    notes TEXT,
    accepted_by TEXT,
    accepted_at TEXT,
    FOREIGN KEY(lease_id, client_id) REFERENCES client_leases(id, client_id),
    CHECK(
      (engagement_id IS NOT NULL AND client_id IS NULL AND lease_id IS NULL)
      OR
      (engagement_id IS NULL AND request_id IS NULL AND client_id IS NOT NULL AND lease_id IS NOT NULL)
    )
);
INSERT INTO attachments_v030_new(
    id, engagement_id, request_id, original_filename, stored_filename,
    file_hash_sha256, file_size, mime_type, extension, uploaded_by,
    uploaded_at, source, status, notes, accepted_by, accepted_at
)
SELECT id, engagement_id, request_id, original_filename, stored_filename,
       file_hash_sha256, file_size, mime_type, extension, uploaded_by,
       uploaded_at, source, status, notes, accepted_by, accepted_at
  FROM attachments;
CREATE TABLE attachment_versions_v030_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attachment_id INTEGER NOT NULL REFERENCES attachments_v030_new(id),
    supersedes_id INTEGER REFERENCES attachments_v030_new(id),
    created_at TEXT NOT NULL
);
INSERT INTO attachment_versions_v030_new SELECT * FROM attachment_versions;
DROP TABLE attachment_versions;
DROP TABLE attachments;
ALTER TABLE attachments_v030_new RENAME TO attachments;
ALTER TABLE attachment_versions_v030_new RENAME TO attachment_versions;
DELETE FROM sqlite_sequence
 WHERE name IN ('attachments', 'attachment_versions');
INSERT INTO sqlite_sequence(name, seq)
SELECT name, seq FROM _m0027_sequence_high_water;
DROP TABLE _m0027_sequence_high_water;
CREATE INDEX idx_attachments_engagement ON attachments(engagement_id);
CREATE INDEX idx_attachments_request ON attachments(request_id);
CREATE INDEX idx_attachments_client ON attachments(client_id);
CREATE INDEX idx_attachments_lease ON attachments(lease_id);
CREATE INDEX idx_attachments_status ON attachments(status);
CREATE INDEX idx_attachment_versions_attachment ON attachment_versions(attachment_id);
"""
```

Register `("0027_client_master_expansion", _m0027_client_master_expansion.SQL)` after migration 0026.

- [ ] **Step 4: Run migration and full migration-regression tests**

Run: `python -m pytest tests/test_client_master_migration.py tests/test_db_migrations.py -q`

Expected: PASS, including updated 27-version expectations, clean foreign-key
checks, preserved attachment/version sequences, and a second application of
`apply_migrations()` without a duplicate lease.

- [ ] **Step 5: Commit the migration slice**

```powershell
git add src/taxops/db/migrations tests/test_client_master_migration.py
git commit -m "feat: migrate client addresses leases and industries"
```

### Task 2: Add lease and industry repositories with validated services

**Files:**
- Create: `src/taxops/repositories/client_leases.py`
- Create: `src/taxops/repositories/client_industries.py`
- Create: `src/taxops/services/client_leases.py`
- Modify: `src/taxops/repositories/attachments.py`
- Modify: `src/taxops/services/attachments.py`
- Create: `tests/test_client_leases.py`
- Create: `tests/test_client_industries.py`
- Create: `tests/test_client_lease_attachments.py`
- Modify: `src/taxops/services/container.py`

- [ ] **Step 1: Write failing repository/service behavior tests**

```python
def test_client_can_have_overlapping_active_leases(container):
    client = make_client(container)
    first = container.client_leases.create(
        client.id,
        LeaseInput("登記辦公室", "臺北市中山區", "甲", "2026-01-01", "2027-12-31", 38000, 76000, 60, ""),
    )
    second = container.client_leases.create(
        client.id,
        LeaseInput("工作室", "新北市板橋區", "乙", "2026-03-01", "2027-02-28", 22000, 44000, 90, ""),
    )
    assert [row.id for row in container.client_leases.list_for_client(client.id)] == [first.id, second.id]

def test_replace_client_industries_is_atomic(container):
    client = make_client(container)
    rows = container.client_industries.replace_from_registry(
        client.id,
        [("7409", "其他專門設計業", True), ("7310", "廣告業", False)],
        source="mof_cache",
        source_version="2026-06",
    )
    assert [(row.code, row.is_primary) for row in rows] == [("7409", True), ("7310", False)]

def test_lease_attachment_uses_existing_guarded_attachment_directory(container, tmp_path):
    client = make_client(container)
    lease = make_lease(container, client.id)
    source = tmp_path / "lease.pdf"
    source.write_bytes(b"%PDF-1.4\nlease")
    row = container.attachments.upload_lease_attachment(client.id, lease.id, source)
    assert row.engagement_id is None
    assert row.client_id == client.id
    assert row.lease_id == lease.id
    assert container.attachments.resolve_file_path(row.id).is_file()
```

- [ ] **Step 2: Run focused tests and confirm import failures**

Run: `python -m pytest tests/test_client_leases.py tests/test_client_industries.py tests/test_client_lease_attachments.py -q`

Expected: FAIL because the repositories and services are not defined.

- [ ] **Step 3: Implement focused immutable row types and parameterized CRUD**

```python
@dataclass(frozen=True)
class ClientLeaseRow:
    id: int
    client_id: int
    lease_name: str
    premises_address: str | None
    landlord_name: str | None
    start_date: str | None
    end_date: str | None
    monthly_rent: int | None
    deposit_amount: int | None
    reminder_days: int
    status: str
    notes: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None

def list_for_client(self, client_id: int) -> list[ClientLeaseRow]:
    rows = self._conn.execute(
        "SELECT * FROM client_leases WHERE client_id = ? AND deleted_at IS NULL ORDER BY start_date, id",
        (client_id,),
    ).fetchall()
    return [_row_to_lease(row) for row in rows]
```

Service validation must sanitize text, parse ISO dates, permit overlap, reject end-before-start, reject negative money, verify the active client, wrap mutations and audit in `with self._conn:`.

Extend `AttachmentRow` with nullable `engagement_id`, `client_id`, and `lease_id`. Add `insert_for_lease()` and `list_by_lease()` repository methods. The service verifies that the lease belongs to the active client, then reuses `validate_attachment_file()`, safe relative path resolution, hashing, atomic copy cleanup, status changes, and audit behavior from engagement attachments.

- [ ] **Step 4: Implement atomic industry replacement**

```python
def replace_from_registry(self, client_id, industries, *, source, source_version):
    normalized = _normalize_industries(industries)
    with self._conn:
        self._repo.delete_for_client(client_id)
        rows = self._repo.insert_many(
            client_id,
            normalized,
            source=source,
            source_version=source_version,
            applied_at=now_iso(),
        )
        self._audit.record(
            action="client.industries.replace",
            target_type="client",
            target_id=str(client_id),
            detail={"count": len(rows), "source": source, "source_version": source_version or ""},
        )
    return rows
```

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_client_leases.py tests/test_client_industries.py tests/test_client_lease_attachments.py -q`

Expected: PASS.

```powershell
git add src/taxops/repositories src/taxops/services tests/test_client_leases.py tests/test_client_industries.py tests/test_client_lease_attachments.py
git commit -m "feat: manage client leases and industries"
```

### Task 3: Move client address behavior to registered/contact fields

**Files:**
- Modify: `src/taxops/repositories/clients.py`
- Modify: `src/taxops/services/clients.py`
- Modify: `src/taxops/services/clients_bulk.py`
- Modify: `src/taxops/services/registry/matcher.py`
- Modify: `tests/test_clients.py`
- Modify: `tests/test_clients_bulk_parse.py`
- Verify: `tests/test_bulk_import_wizard_user_path.py`
- Modify: `tests/test_registry_matcher.py`

- [ ] **Step 1: Add failing address preservation and registry matching tests**

```python
def test_registry_address_updates_registered_address_without_touching_contact(container):
    client = make_client(container, registered_address="舊登記地", contact_address="寄件地址", contact_address_same=False)
    updated = container.clients.update_registered_address(client.id, "新登記地")
    assert updated.registered_address == "新登記地"
    assert updated.contact_address == "寄件地址"
```

- [ ] **Step 2: Run address tests and confirm dataclass/input failures**

Run: `python -m pytest tests/test_clients.py tests/test_clients_bulk_parse.py tests/test_bulk_import_wizard_user_path.py tests/test_registry_matcher.py -q`

Expected: FAIL because the new fields are not exposed.

- [ ] **Step 3: Extend row/input types while keeping the legacy address mirror explicit**

```python
@dataclass(frozen=True)
class ClientRow:
    address: str | None  # v0.29 compatibility mirror; new logic must not read it
    registered_address: str | None = None
    contact_address: str | None = None
    contact_address_same: bool = True
```

Create/update SQL writes `registered_address`, `contact_address`, and `contact_address_same`; it also mirrors `registered_address` into legacy `address` only during the v0.30 compatibility window. New services and UI read `registered_address`; registry matcher compares the registry address to `registered_address`. Existing call sites that still read `address` are enumerated and migrated before the compatibility mirror is removed in a later version.

- [ ] **Step 4: Update bulk import/export headers without losing old 地址 files**

Map `設籍地址` and legacy `地址` to `registered_address`; add `聯絡地址` and `聯絡地址同設籍` fields. Export only the explicit new headers.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_clients.py tests/test_clients_bulk_parse.py tests/test_bulk_import_wizard_user_path.py tests/test_registry_matcher.py -q`

Expected: PASS.

```powershell
git add src/taxops/repositories/clients.py src/taxops/services/clients.py src/taxops/services/clients_bulk.py src/taxops/services/registry/matcher.py tests
git commit -m "feat: separate registered and contact addresses"
```

### Task 4: Expose full client editing and multiple leases in PySide6

**Files:**
- Create: `src/taxops/ui/widgets/client_profile_form.py`
- Create: `src/taxops/ui/dialogs/client_lease_dialog.py`
- Modify: `src/taxops/ui/dialogs/new_client_dialog.py`
- Modify: `src/taxops/ui/dialogs/edit_client_dialog.py`
- Modify: `src/taxops/ui/pages/clients_page.py`
- Modify: `src/taxops/services/clients.py`
- Modify: `src/taxops/services/client_leases.py`
- Modify: `src/taxops/services/container.py`
- Create: `tests/test_client_profile_ui.py`
- Create: `tests/test_client_leases_ui.py`
- Create: `tests/test_client_profile_atomic.py`

- [ ] **Step 1: Write failing real-widget tests**

```python
def test_edit_client_keeps_full_contact_address_and_adds_two_leases(qtbot, container):
    client = make_client(container)
    dialog = EditClientDialog(container, client)
    qtbot.addWidget(dialog)
    dialog.profile_form.registered_address.setText("臺北市設籍地")
    dialog.profile_form.contact_same.setChecked(False)
    dialog.profile_form.contact_address.setText("新北市聯絡地\n收件人：王小姐")
    dialog.add_staged_lease(LeaseInput("辦公室", "臺北市", "甲", "2026-01-01", "2027-01-01", 1, 1, 60, ""))
    dialog.add_staged_lease(LeaseInput("倉庫", "桃園市", "乙", "2026-02-01", "2027-02-01", 1, 1, 60, ""))
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    saved = container.clients.get_client(client.id)
    assert saved.contact_address == "新北市聯絡地\n收件人：王小姐"
    assert len(container.client_leases.list_for_client(client.id)) == 2
```

- [ ] **Step 2: Run UI tests and verify the widgets are absent**

Run: `python -m pytest tests/test_client_profile_ui.py tests/test_client_leases_ui.py -q`

Expected: FAIL because the profile widget and lease dialog do not exist.

- [ ] **Step 3: Implement a shared scrollable profile form**

Use `QPlainTextEdit` for both addresses and notes, `setMinimumHeight(72)`, `setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)`, and no maximum height. The contact-same checkbox disables contact editing and copies registered text only at save time.

- [ ] **Step 4: Implement staged lease rows and atomic client save**

New-client leases remain in memory until the client and leases can be created in
one service transaction. Edit-client staged create/update/archive operations use
an explicit orchestration method on a real service boundary. Refactor the
existing client and lease services to expose validation plus uncommitted
repository/audit helpers; do not nest their public `with connection:` methods,
because an inner SQLite context may commit a half-finished profile. Tests must
inject a failure in the second lease mutation and prove the client row, every
lease row, audit rows, and FTS state all roll back. The dialog stays open and
preserves inputs on any validation or persistence error.

- [ ] **Step 5: Run UI tests at normal and constrained geometry**

Run: `python -m pytest tests/test_client_profile_ui.py tests/test_client_leases_ui.py -q`

Expected: PASS, including assertions that the scroll area and save/cancel buttons remain visible at 900×540.

- [ ] **Step 6: Commit the client UI slice**

```powershell
git add src/taxops/ui tests/test_client_profile_ui.py tests/test_client_leases_ui.py
git commit -m "feat: edit client addresses and multiple leases"
```

### Task 5: Search, display, and apply registry industries

**Files:**
- Modify: `src/taxops/repositories/tax_registry.py`
- Modify: `src/taxops/ui/pages/registry_page.py`
- Modify: `src/taxops/ui/dialogs/registry_apply_dialog.py`
- Modify: `src/taxops/ui/dialogs/new_client_dialog.py`
- Modify: `tests/test_tax_registry.py`
- Create: `tests/test_registry_industry_ui.py`

- [ ] **Step 1: Write failing industry search and apply tests**

```python
def test_search_finds_secondary_industry_name(tax_registry_repo):
    rows = tax_registry_repo.search("電腦程式設計業", limit=20)
    assert [row["tax_id"] for row in rows] == ["53821476"]

def test_registry_apply_industries_does_not_clear_contact_address(qtbot, container):
    client = make_client(container, contact_address="指定寄送地址", contact_address_same=False)
    dialog = RegistryApplyDialog(registry_row=registry_row(), client_row=client, container=container)
    dialog.industry_checkbox.setChecked(True)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert container.clients.get_client(client.id).contact_address == "指定寄送地址"
    assert container.client_industries.list_for_client(client.id)[0].code == "7409"
```

- [ ] **Step 2: Run registry tests and verify they fail for missing industry behavior**

Run: `python -m pytest tests/test_tax_registry.py tests/test_registry_industry_ui.py -q`

Expected: FAIL because search only covers names and the UI omits industry fields.

- [ ] **Step 3: Extend parameterized search across four industry slots**

Use a single bounded query with `industry_code_primary`, `industry_code_1..3`, `industry_name_primary`, and `industry_name_1..3`; preserve exact tax-ID and exact company-name precedence. Keep the existing limit and background timeout.

- [ ] **Step 4: Add primary-industry table column and full detail list**

The result table shows `industry_code_primary + industry_name_primary`. Detail shows every non-empty unique code/name pair. For GCIS rows lacking these keys, show `此來源未提供行業資料`.

- [ ] **Step 5: Apply selected industry data transactionally**

Registry apply first updates selected client scalar fields, then replaces industries in the same connection transaction. A failure rolls back both operations and displays a Chinese error without closing the dialog.

- [ ] **Step 6: Run focused tests and commit**

Run: `python -m pytest tests/test_tax_registry.py tests/test_registry_industry_ui.py tests/test_gcis.py -q`

Expected: PASS.

```powershell
git add src/taxops/repositories/tax_registry.py src/taxops/ui tests/test_tax_registry.py tests/test_registry_industry_ui.py
git commit -m "feat: search and apply registry industries"
```
