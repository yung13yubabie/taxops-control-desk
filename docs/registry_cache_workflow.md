# Registry Cache Workflow

## Purpose

The app must support business and tax registration lookup for offline accounting-office use.

The workflow must allow a connected machine to download official open data, build a local cache, export a cache bundle, and let an offline office machine import that bundle through UI.

## Official Sources

Business registry:

- Source: Ministry of Economic Affairs, Business Development Agency, GCIS open data.
- Portal: `https://data.gcis.nat.gov.tw/`
- Swagger: `https://data.gcis.nat.gov.tw/resources/swagger/swagger.json`
- Dataset example: `https://data.gov.tw/dataset/108337`

Tax registration:

- Source: Ministry of Finance, Fiscal Information Agency.
- Dataset page: `https://data.gov.tw/dataset/9400`
- Current download URL: `https://eip.fia.gov.tw/data/BGMOPEN1.zip`
- OAS docs: `https://eip.fia.gov.tw/OAI/v2/api-docs`

Do not scrape the Ministry of Finance tax registration public query website for MVP.

## Settings

The settings page must include a `稅籍快取管理` section.

Fields:

- 查詢模式
  - `僅使用本機快取` default
  - `允許線上下載更新`
- 財政部資料集頁 URL
- 財政部下載 URL
- GCIS Swagger URL
- 目前快取資料日期
- 目前快取筆數
- 最後下載時間
- 最後匯入時間
- 來源 URL
- 檔案 SHA-256
- 檔案大小

Buttons:

- `下載財政部稅籍資料`
- `從 ZIP 匯入稅籍資料`
- `匯入稅籍快取包`
- `匯出稅籍快取包`
- `驗證快取`
- `重新產生客戶對照結果`

If mode is `僅使用本機快取`, online download is disabled and the UI shows:

```text
目前為僅使用本機快取模式。若要線上下載，請先切換為允許線上下載更新。
```

## URL Safety

Built-in defaults:

- Dataset page: `https://data.gov.tw/dataset/9400`
- Download URL: `https://eip.fia.gov.tw/data/BGMOPEN1.zip`

Allowed official domains by default:

- `https://eip.fia.gov.tw/`
- `https://data.gov.tw/`
- `https://data.gcis.nat.gov.tw/`

Changing a URL requires:

- Domain allowlist validation.
- Two-step confirmation.
- Audit log entry.
- Displaying the actual URL before download.

Non-official domains are blocked by default for MVP.

## Online Download Flow

User flow:

1. Open settings.
2. Switch query mode to `允許線上下載更新`.
3. Click `下載財政部稅籍資料`.
4. Confirm the official source URL and warning.
5. Download `BGMOPEN1.zip`.
6. Compute SHA-256 and file size.
7. Store download metadata.
8. Import into staging tables.
9. Validate columns, row count, and parseability.
10. Replace formal cache only after validation succeeds.
11. Write audit log.
12. Show a concrete success message.

Warning before download:

```text
系統將連線至財政部官方開放資料來源下載稅籍資料。檔案可能較大，請確認網路穩定。下載與匯入期間請勿關閉程式。查詢結果僅供內部核對，不會自動覆蓋客戶主檔。
```

Download failure message:

```text
無法連線至財政部資料來源，請確認此電腦可上網，或改用匯入稅籍快取包。
```

Failure must not overwrite the existing cache.

## ZIP Import Flow

User flow:

1. Click `從 ZIP 匯入稅籍資料`.
2. Select `BGMOPEN1.zip`.
3. Validate path safety.
4. Validate extension and file size.
5. Compute SHA-256.
6. Import to staging tables.
7. Validate expected fields.
8. Replace formal cache only after validation succeeds.
9. Record metadata and audit log.

The UI must show:

- Source file path.
- File size.
- SHA-256.
- Estimated or actual row count.
- Import time.

## Cache Bundle Rules

Tax cache bundles are not encrypted.

They may contain:

- Government public tax registration cache.
- Government public business registry cache.
- Metadata:
  - source URL
  - downloaded time
  - imported time
  - source SHA-256
  - row count
  - cache version

They must not contain:

- Customer master data.
- Customer match results.
- Internal notes.
- Audit logs.
- System logs.
- API keys.
- Passwords.
- Attachments.

Suggested filename:

```text
tax_registry_public_cache_YYYYMMDD.taxops-cache.zip
```

## Offline Import Flow

User flow on offline office machine:

1. Open settings.
2. Click `匯入稅籍快取包`.
3. Select cache bundle.
4. Validate manifest and SHA-256.
5. Show source, date, row count, and cache version.
6. Confirm import.
7. Import into staging tables.
8. Replace formal cache only after validation succeeds.
9. Offer to run `重新產生客戶對照結果`.

Import failure must not corrupt the existing cache.

## Customer Match Results

Customer match results are local data and are not exported in cache bundles.

They must be saved in SQLite and regenerable after cache changes.

Suggested table:

```text
registry_match_results
```

Suggested fields:

- `id`
- `client_id`
- `tax_id`
- `registry_source`
- `cache_version`
- `match_status`
- `matched_name`
- `matched_address`
- `matched_business_status`
- `differences_json`
- `review_status`
- `generated_at`
- `reviewed_at`
- `reviewed_by`

`reviewed_by` defaults to `local_user`.

## Match Rules

Use tax ID as the primary match key.

- Empty or invalid tax ID:
  - `needs_manual_review`
  - Show `客戶統一編號未填或格式不正確，請人工確認。`
- Tax ID not found in both tax and business caches:
  - `not_found`
  - Show `本地快取查無此統一編號，可能是快取未更新或資料來源未涵蓋。`
  - Do not show `公司不存在`.
- Tax ID found and name exactly matches:
  - `matched`
- Tax ID found and name differs:
  - `mismatch`
  - Show differences.
  - Do not overwrite client data automatically.
- Address differs:
  - Record in `differences_json`.
  - Show `地址與快取資料不同，請確認是否需要更新。`
- Tax cache and GCIS cache disagree:
  - `needs_manual_review`
  - Show `稅籍資料與商工登記資料不一致，請人工確認。`
- MOF tax cache not found but GCIS found:
  - `needs_manual_review`
  - Do not infer business closure.

Applying differences to a client master record requires user confirmation, `client_status_snapshots`, and `audit_logs`.

## Tests

Required tests:

- Download URL allowlist.
- URL change audit log.
- ZIP path safety.
- ZIP import staging rollback on failure.
- Bundle manifest validation.
- Tampered bundle rejection.
- Cache import does not include customer match results.
- Regenerating match results after cache import.
- `not_found` does not display `公司不存在`.
- Cache import failure preserves existing cache.
