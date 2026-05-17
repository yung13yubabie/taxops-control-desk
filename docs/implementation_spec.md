# TaxOps Control Desk Implementation Spec

## Objective

Build a Windows-first desktop application for Taiwan accounting and tax office operations.

The product is:

- An office case operations console.
- A client document request and missing-item tracking system.
- A tax workflow management tool.
- A document evidence-chain manager.
- An internal review and quality-control workbench.
- An offline-first local data and task control desk.

The product is not:

- Accounting software.
- Formal tax filing software.
- A WSTP clone.
- A WSTP backup reader.
- An invoice platform.
- Automatic tax filing software.
- An AI tax-decision system.
- A cloud SaaS system.

## Source Of Truth

Primary source specification:

```text
C:\Users\LIN\Downloads\codex_readable_taxops_spec_compact.md
```

This file consolidates implementation decisions confirmed on 2026-05-08. If this file conflicts with the source specification, follow the newer confirmed decision recorded in `.ai/DECISIONS.md`.

## Tech Stack

- Python 3.11+
- PySide6
- SQLite
- SQLite FTS5
- Jinja2
- openpyxl
- pytest
- PyInstaller for Windows EXE packaging

Do not use npm, Vite, React, a web backend, cloud databases, or automatic outbound services for MVP.

## Commands

Commands are placeholders until project metadata is created:

```powershell
python -m pytest
python -m taxops
python -m build_tools.clean_package
python -m build_tools.package_windows
python -m build_tools.smoke_test_exe
```

Packaging commands must be made real before MVP can be marked complete.

## Project Structure

```text
taxops-control-desk/
  .ai/
  docs/
    implementation_spec.md
    registry_cache_workflow.md
    ui_action_contract.md
  src/
    taxops/
  tests/
```

The implementation should follow the source specification's module layout for `core`, `db`, `repositories`, `services`, `security`, and `ui`.

## Product Boundaries

Always do:

- Use Traditional Chinese for UI.
- Keep code, database tables, and fields in English.
- Store database dates as ISO `YYYY-MM-DD`.
- Use UI labels for enum and field display.
- Use parameterized SQL.
- Treat user input, imported data, template text, filenames, and API responses as untrusted.
- Write audit logs for business operations.
- Write system logs for technical errors.
- Show user-facing errors in plain Traditional Chinese.
- Disable unimplemented features with `此功能尚未開放`.
- Ensure enabled UI actions connect to service, repository, SQLite, audit log, and tests.

Ask first:

- Adding dependencies beyond the approved stack.
- Changing the official data-source strategy.
- Adding WSTP-related capabilities.
- Adding login, roles, or multi-user behavior.
- Changing packaging or data-directory strategy.

Never do:

- Create fake buttons or fake dashboard numbers.
- Display engineering enum values or database field names in UI.
- Store passwords or API keys in logs.
- Render untrusted HTML.
- Scrape the Ministry of Finance public query website for MVP.
- Include WSTP backup reading in MVP.
- Automatically send LINE or Email.
- Automatically file taxes.

## MVP Scope

MVP includes every item in section 24 of the source specification:

- PySide6 main window starts.
- SQLite schema initializes.
- Client management.
- Engagement management.
- Document request management.
- Task management.
- Message templates.
- Attachment evidence chain.
- Basic review notes.
- Business and tax registration cache UI.
- Late fee estimate.
- Excel export.
- Backup and restore.
- Audit log.
- XSS / HTML injection protection tests.
- CSV formula injection tests.
- Attachment security tests.
- Resource limit tests.
- README.
- Draft Traditional Chinese user manual.
- No WSTP backup reading.
- No automatic filing.
- No automatic LINE / Email sending.

Implementation may be phased internally, but MVP is not complete until every item above is implemented and verified.

## UI Requirements

Design direction:

- Follow `.ai/DESIGN.md`.
- Use a premium, simple, and clearly legible desktop workbench style.
- Prioritize Apple/Tesla-like restraint, Linear-like operational clarity, and Stripe-like form hierarchy.
- Do not copy brand identity, logos, or trademarked visual assets.
- Do not build a marketing-style interface.

- Minimum main window size: 1280 x 720.
- Must support 1366 x 768 and 1920 x 1080.
- Must support Windows display scaling at 100%, 125%, and 150%.
- Use PySide6 layout systems instead of broad fixed geometry.
- Long forms must use `QScrollArea`.
- Bottom form actions must remain visible.
- Long table text must elide and show tooltip.
- Empty lists must show helpful empty states.
- Operations over 500ms must show loading state.
- Operations over 10 seconds must show long-running guidance.

Navigation labels:

- 首頁儀表板
- 客戶管理
- 案件管理
- 索件管理
- 待辦事項
- 訊息模板
- 工商 / 稅籍查詢
- 滯納金試算
- 附件管理
- 覆核意見
- 設定

## Data And User Mode

MVP is single local-user mode:

- No login.
- No roles.
- No permissions system.
- Audit actor is `local_user`.
- Settings may store an optional display name.
- `uploaded_by`, `reviewed_by`, and `accepted_by` default to `local_user`.

Default Windows paths:

- Data root: `%LOCALAPPDATA%\TaxOpsControlDesk\`
- Database: `%LOCALAPPDATA%\TaxOpsControlDesk\taxops.sqlite`
- Attachments: `%LOCALAPPDATA%\TaxOpsControlDesk\attachments\`
- Backups: `%USERPROFILE%\Documents\TaxOpsBackups\`
- Dev EXE data root: `%LOCALAPPDATA%\TaxOpsControlDeskDev\`

The settings page must display current paths with:

- Middle-elided visible path.
- Full path tooltip.
- Browse where applicable.
- Open folder.
- Copy path.

## Registry And Tax Cache

See `docs/registry_cache_workflow.md`.

Key decisions:

- Use official GCIS open data for business registry data.
- Use official MOF `BGMOPEN1.zip` for tax registration cache.
- Do not scrape `etax.nat.gov.tw` public query pages.
- Tax cache bundles are not encrypted and must not contain customer match results.
- Customer match results are stored locally and can be regenerated.

## Packaging

MVP requires Windows EXE packaging.

Development EXE:

- Uses `%LOCALAPPDATA%\TaxOpsControlDeskDev\`.
- Must be testable during development.

Production EXE:

- Uses `%LOCALAPPDATA%\TaxOpsControlDesk\`.

Packaging workflow:

1. Clean previous package outputs.
2. Run tests.
3. Build EXE.
4. Run smoke test.

Clean package output automatically:

- `build/`
- `dist/TaxOpsControlDesk/`
- old generated packaging artifacts

Do not automatically clean:

- SQLite data.
- Attachments.
- Cache bundles.
- Test data.
- Source code.
- Docs.

Provide a separate explicit `clean_dev_data` command with warnings.

## Testing Strategy

Required test files include the source specification list plus UI hardening tests:

- `test_i18n_labels.py`
- `test_status_labels.py`
- `test_ui_action_contracts.py`
- `test_settings_persistence.py`
- `test_form_validation.py`
- `test_table_pagination.py`
- `test_text_sanitizer.py`
- `test_file_guard.py`
- `test_resource_limits.py`
- `test_export_security.py`
- `test_clients.py`
- `test_engagements.py`
- `test_document_requests.py`
- `test_templates.py`
- `test_late_fee.py`
- `test_attachments.py`
- `test_review_notes.py`
- `test_backup.py`

Manual UI acceptance must include:

- Windows scaling 100%, 125%, and 150%.
- 1366 x 768.
- 1920 x 1080.
- Long client names.
- Long file paths.
- Long notes.
- Empty states.
- 1000-row data scenario.

EXE smoke test must include:

- EXE starts.
- Main window displays Traditional Chinese.
- SQLite schema initializes.
- Settings page opens.
- Data paths display correctly.
- New client can be created and persists after restart.
- Unimplemented features are disabled.
- Audit log is written.

## Success Criteria

The MVP is complete only when:

- All section 24 source-spec requirements are implemented.
- No enabled fake UI exists.
- Tests pass.
- EXE packaging and smoke test pass.
- README and Traditional Chinese user manual draft exist.
- Registry cache online/offline workflow is implemented and documented.
