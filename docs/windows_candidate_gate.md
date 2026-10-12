# Windows candidate build and artifact self-test

## Status and scope

The workflow and test code are implemented. They were locally validated as
source and synthetic contracts on Linux; **the new Windows workflow and a real
frozen Windows EXE have not yet been run or accepted in this change**.

`.github/workflows/windows-candidate.yml` runs only for pull requests or an
explicit manual dispatch. It has `contents: read`, does not request secrets,
does not persist checkout credentials, and cannot publish a GitHub Release.
GitHub-maintained actions are pinned to full commit IDs. Candidate artifacts
and diagnostics expire after 14 days. Failed runs can still upload diagnostics;
check the workflow result and `bundle-provenance.json`, not merely whether an
artifact link exists.

The hosted `windows-2022` runner is a build/test machine with developer tools.
It is **not** a clean, disconnected end-user Windows computer. No publisher
signing is performed, and no SmartScreen or signature acceptance is claimed.

## Build inputs

This gate is ported onto feature base `f02dc5d62ab06b4cd1214ca2044477b5a78e4420`
(version 0.32.0, preserving all 28 migrations and the published v0.31 domains).
The runtime version is reported by the application; version metadata is not
rewritten by this workflow. Windows version resources and setuptools 83.0.0
remain in the existing release inputs. Historical Windows build results in
other documents do not qualify this candidate.

- Python 3.11.9 x64, matching the previously documented Windows build baseline
- Exact runtime/build dependencies in `requirements-release.txt`
- Separate exact test dependencies in `requirements-ci.txt`
- Fresh `.venv-test` and `.venv-release`; test tools are not installed in the
  release environment
- PyInstaller one-directory layout; UPX disabled to avoid host-dependent
  compression; explicit QtPdf/QtPdfWidgets collection
- Complete source regression, one fresh process per test file, with combined
  unrounded branch-aware coverage of at least 90%

This pins the procedure and dependencies, not a bit-for-bit reproducible binary.
Runner images, package-index availability, wheel hashes, code signing, and a
verified offline wheelhouse are separate concerns. Build/install steps need
network access. That requirement does not make core EXE operation online.

## Source regression and coverage gate

```powershell
.\.venv-test\Scripts\python.exe -m build_tools.run_test_matrix --output artifacts\source-tests
```

The runner enumerates every `tests/test_*.py` file. Each file gets its own
coverage/pytest process, log and JUnit XML; `matrix.json` records every process
exit, test totals, unrun files and the combined raw coverage percentage. There
is no built-in exclusion for Qt, IPC, real-data tests or failing tests. A native
crash or timeout stops the matrix and records the remaining files as unrun.
Other failures are retained while the remaining files run.

Fresh parallel coverage data are combined only from this invocation. Passing
requires all selected processes, JUnit results and coverage commands to pass,
plus JSON `totals.percent_covered >= 90.0` with branch measurement enabled.
A rounded display of 90% is insufficient. `--files` is for diagnosis and marks
`full_suite: false`; the workflow never uses it. A skipped platform/fixture test
is visible in the totals and must not be described as executed acceptance.
The full run is expected to take much longer than a focused unit-test run.

## What executes inside the EXE

The existing PyInstaller entry point recognizes:

```powershell
.\TaxOpsControlDesk.exe --self-test --require-frozen --report C:\Temp\taxops-self-test.json
```

The flag selects `taxops.diagnostics`, compiled into the same application. It
never accepts a caller-selected business-data root. It creates temporary
synthetic data and removes it before reporting success. Normal launches remain
unchanged.

Required native/runtime and service checks:

1. QApplication, packaged icon, and image codecs
2. Qt-generated PDF loaded and rendered by QtPdf; QtPdfWidgets construction
3. SSL import and certificate-verification defaults, without calling any URL
4. Every registered migration and SQLite FTS query
5. MainWindow construction/show/close, without claiming visual correctness
6. Client with distinct registered/contact addresses, case, document request/items,
   and task creation
7. Client lease and its client/lease-owned attachment, upload, acceptance, and
   byte-for-byte readback; case-owned attachment is checked separately
8. Annual compliance profile, six generated items, idempotent repeat generation,
   linked case/task, and four tax/fee transaction events with calculated balances
9. Workflow and canvas image assets
10. XLSX export and readback with openpyxl
11. Full `.taxops.zip` backup, restore to a different fresh root, close/reopen,
    and client address/lease ownership, annual records/links/transactions,
    attachment/workflow/canvas bytes, FTS, integrity, foreign keys and audit
12. Temporary-data cleanup

These flows produce 16 required named checks in the machine-readable report.
They are representative synthetic runtime checks, not exhaustive domain tests.

CPython socket audit events are denied during these synthetic operations. A
caught/swallowed attempt still makes the final result fail. This guard does not
control native-library networking or replace an OS network boundary. These
flows do not invoke live registry downloads, GCIS, external file opening, or
an application updater. No customer data is used.

Missing QtPdf is a failure, not a skipped check or silent preview fallback.
Each report identifies source versus frozen execution, OS, Qt platform, Python
and binding versions, individual checks, and explicit unverified boundaries.

## Test the exact candidate ZIP

```powershell
.\.venv-release\Scripts\python.exe -m build_tools.package_windows
.\.venv-release\Scripts\python.exe -m build_tools.verify_windows_bundle --output artifacts\windows-candidate
```

The second command requires Windows. The host uses only its standard library
to orchestrate the check; business checks run inside the extracted EXE:

- Inspect expected Windows runtime/plugin files and reject source, test, and
  obvious user-data files in the bundle
- Create and completely read back a ZIP of the full one-directory tree
- Extract that ZIP to a moved path containing spaces and Chinese characters
- Start the extracted EXE with isolated profile/temp folders, no inherited
  Python/Qt paths, and a PATH limited to Windows system folders
- Require successful process exit and every required frozen Windows check;
  reject source/offscreen/missing/skipped/failed reports
- Preserve the same tested ZIP with SHA-256, self-test JSON, process log, and
  build provenance; never rebuild different bytes after acceptance

Use a fresh output directory for each candidate. The `--require-frozen` flag
prevents host source execution from satisfying this gate. The original
`smoke_test_exe` remains available as a shallow launch diagnostic; it is not a
replacement for this artifact gate.

Source-only development check, which does not qualify as Windows evidence:

```powershell
$env:PYTHONPATH = 'src'
python -m taxops.diagnostics --report artifacts\source-self-test.json
```

## Remaining release acceptance

After the workflow genuinely passes, use its exact ZIP and hash on a separate
clean standard-user Windows image with no Python/developer tools and the network
disconnected. Extract the whole directory; copying the EXE alone is unsupported.

Record OS/version/architecture, commit, hash, and each outcome. Required manual
acceptance still includes:

- First launch and restart with standard-user permissions and read-only install
  folder; Chinese/spaced user paths and redirected Documents/backup destination
- Real GUI client dual-address/lease/attachment, annual profile/generation/
  transaction, case/document/task/fixed-billing workflows, local registry
  import/query, PDF/image preview, exports, complete backup/restore, and audit
- Traditional Chinese glyphs, actual dialogs, keyboard behavior, and
  100/125/150/200% scaling
- A copied populated supported-version database plus assets upgraded by the
  candidate, with an intact pre-upgrade backup; an explicit refusal of unknown
  newer schema versions
- Graceful process/thread cleanup and long-running/interrupted/repeated flows
- Package scanning, dependency review, license notices, and either a verified
  publisher signature or a clear unsigned-build disclosure

Only then may an explicitly authorized release step publish this same tested
ZIP, checksum, provenance, and known limitations. A green hosted-runner smoke
alone does not satisfy the clean/offline delivery requirement.
