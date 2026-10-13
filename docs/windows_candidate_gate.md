# Windows candidate build and artifact self-test

Current single-EXE evidence is in [the onefile gate record](windows_onefile_gate.md#latest-normal-candidate-and-modified-component-proof):
normal run 38352573945 and modified-component proof run 38355622300. The current
candidate uses PyInstaller onefile packaging. The remaining document records the
historical one-directory baseline and its procedures; instructions to extract and
retain an entire ZIP apply only to that older package, not the current single EXE.
See [current tryout instructions](candidate_tryout.md) before running the candidate.

## Historical verified one-directory candidate: run 38252711536

The seventh [Windows run](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38252711536) completed successfully on 2026-10-12. All **141/141 complete test files and 3461/3461 tests** passed, with zero failures, errors, skips or unrun files. Raw combined line/branch coverage is **91.06710039545861%**, above the unchanged 90% gate. The separate seven-file suite passed 193 overlapping tests; do not add those to the full-suite count.

Exact provenance:

- PR head: `3a338b1462e824c1a18c058fef22358a042b8cb3`
- Actual tested checkout: `466102a34b78eaafd9484b6e496afb9e0b3f2cb3`
- Tested tree: `4294c59124980fd3b6f29539e01271f51b9d4d24`
- [PR #2](https://github.com/yung13yubabie/taxops-control-desk/pull/2) merged into `feature/v030-annual-workbench` as `032333f1ea3efd96b48b2432ea9e96067ad0ef9c`, with the identical tree. This PR/manual-only workflow did not start a separate run for that merge commit.

The newly built app-only ZIP contains the real EXE and runtime dependencies: **48,549,420 bytes, 492 files**, SHA-256 **`3e13a51749fbe4b972dbd7f56c9da2b316062a20e8aad6552dab952a7289d2ec`**. The outer evidence artifact is 51,484,388 bytes with SHA-256 `83a37784dd8bb3688d9f1e859ddc799ce06aeaeb36792afb68448b60780cf1bd`. Preserve the tested app ZIP bytes; source archives and the older candidate ZIP are not substitutes.

The actual EXE extracted into the relocated Chinese/space path passed **17/17 required frozen checks**, with `frozen=true`, `platform=win32`, `qt_platform=windows`, version `0.33.0rc1`, and `network_attempts=[]`. The English-locale Chinese-widget check loaded the real catalogue and verified nonempty translated labels; its missing-catalogue negative case remained explicitly partial. PDF, printing-related dependencies, images, schema 28, annual/lease domains, complete backup and restore remained present. Separate native Windows synthetic glyph/PNG diagnostics passed; this is not full manual visual acceptance.

Independent artifact QA recomputed both ZIP hashes/CRCs and all 141 JUnit totals, checked 123 PE files/imports/version resources, and matched **263 notice files** against reviewed bytes. Notice manifest SHA-256 is `6bb046176dc0f7d6769be82eaaec32ac19db8c473943aae8eb73933ad3d61495`; all 53 recorded Microsoft runtime identities matched. VirtualKeyboard and the unused QML/Quick chain were absent; Qt6OpenGL also disappeared with that unused dependency chain. Required Qt PDF/Print/Windows/image/TLS components remained. Known private/business-data path checks found no such files; this is not an exhaustive secret scan.

**Technical acceptance supports the source merge, not a stable binary release.** The bundle still records the precise Microsoft redistribution questions for eight Qt-supplied VC DLLs and 43 API-set/UCRT files. Clean offline end-user Windows, manual DPI/IME/accessibility and signing remain unverified. See [distribution scope](third_party_licenses.md) and the [fixed source-access instructions](https://github.com/yung13yubabie/taxops-control-desk/blob/3a338b1462e824c1a18c058fef22358a042b8cb3/assets/third_party_licenses/SOURCE_ACCESS.txt).

This section is a documentation-only record added after the build. Its later documentation commit/tree is not claimed as the source of this ZIP; the exact tested/build tree above remains authoritative.

## Historical Windows runs

The sixth run [38228288029](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38228288029) is the first complete Windows candidate pass: **140/140 files, 3429/3429 tests**, no failed/error/skipped/unrun tests, and raw branch coverage **91.06710039545861%**. Head `74bc560ceeb34f6ce83483974af8eb1226c29c8c` and checkout merge `481b55058309366ae62b0f06a903f2ed8936d14d` have tree `06876d464c66d80160f8900e77ca2592f2065280`, identical to local source `8dd5369`. The separate seven-file quick suite passed 193 tests; those overlap the full suite and are not additive.

The actual built EXE, extracted from the candidate ZIP into a relocated Chinese/space path, passed all 17 required synthetic checks with `frozen=true`, `platform=win32`, `qt_platform=windows`, and app version `0.33.0rc1`. The app-only ZIP has SHA-256 `4a9782b058c7a236cfdbd987e08d2c690320638f0e55b4a8b3a31e5a3b457731`, 54,024,285 bytes and 236 entries. **Distribution of this ZIP is on hold:** independent package inventory found an unused Qt VirtualKeyboard plugin/library and incomplete third-party notices. A packaging fix requires a newly built ZIP, new provenance/hash, and a fresh frozen gate; the earlier ZIP must not be silently repacked and described as the tested artifact. Clean offline end-user Windows, DPI/IME/accessibility, and signing acceptance remain unverified.

The following runs are historical diagnosis, not the current source-gate status.

The first Windows run completed on the original candidate, but failed its source
test gate: **3223 passed / 4 failed, no EXE built**. See
[run 38206960124](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38206960124).
Its head was `20cdc1a`, with checkout merge `c314c6c`; both had the exact tree of
local source `bf1872b`. The four failures concerned receipt minimum width, a test
mock intercepting Windows platform detection, and two report-path assertions.
Their fixes and the later Chinese UI slice are included in source snapshot
`247fe2c`, whose complete Linux matrix has 3327 passed / 5 IPC-environment failed /
1 platform skipped across all 137 files, and raw branch coverage
90.93781920326865%. **This historical snapshot did not pass the Windows or frozen gate.**

The second run [38213344318](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38213344318) completed all 137 files at head `821d490` / merge `a931390`: **3325 passed / 8 failed**, no errors or skips, raw branch coverage 91.0367722165475%. It again correctly blocked the EXE. Follow-up fixes address date-width measurement and native path comparison; receipt/collaboration layout and the self-test-created profile directory remain under diagnosis.

The third run [38221303640](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38221303640) completed all 139 files at head `16865f0` / checkout `a6d0bd4`, exactly the `db27edc` tree: **3392 passed / 5 failed** (3397 total), no errors/skips/unrun files, raw branch coverage 91.03763046184291%. Date width and platform path assertions passed. The remaining failures covered two receipt widths, annual attachment pagination overflow, an external empty profile/cache directory from self-test, and a diagnostic assertion that incorrectly required a nonempty resolved font family. All retained failures blocked the EXE. This run predates integration of the new cleaned feature base and the subsequent fixes.

The fourth run [38224732979](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38224732979) used head `da328c7` / merge `2a3daf3`, exactly the local `a5ae038` tree. Its five-file Windows diagnostic suite passed **165/165**; the separate native Windows font probe rendered the sample Chinese text and passed its actual glyph checks. The complete matrix nevertheless stopped at file **64/140**: the new font-probe test hit a Windows access violation while reading raw-font metadata under the offscreen backend. The first 63 files recorded 1772 passing tests; the crashed file had no JUnit result, and 76 files were unrun. The resulting 68.3824467406557% coverage is an interrupted subset, not a final whole-project measurement. The EXE remained blocked. The raw-font validity fix and a new complete run are required; no test file is excluded.

The fifth run [38226805820](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38226805820), head `5b8a119` / merge `da103cf8`, showed that the initial invalid-font guard was insufficient: the offscreen font test still crashed at the metadata line. Six other quick-suite files passed 169 tests and the separate real Windows glyph probe passed again. The full matrix again stopped at 64/140 with 1772 completed JUnit tests and 76 unrun files; the same 68.3824467406557% was only a stopped subset. No EXE was built.

The diagnostic is now explicitly native-only at its capture entry: a non-Windows Qt backend or an empty font database returns `passed: false`, `stage: unsupported`, no samples and no PNG before text-layout/raw-font access. The complete source test file verifies this refusal and the invalid/empty/zero/missing-glyph contracts; it is not skipped and unsupported capture is not a successful probe. The independent qwindows job still must perform real shaping and screenshot checks. This narrows the diagnostic's capability contract; it does not claim offscreen raw-font support or a proven C++ root cause. Application source and the full gate remain unchanged.

A parallel `windows-ui-diagnostics` job runs seven complete files, each in a fresh process with the same pinned dependencies. It uploads synthetic PNG/geometry/JSON/JUnit evidence and preserves every failing exit. The native-font and geometry diagnostic test files run first so their own regressions are captured early. Its provenance records the head and actual checkout SHA/tree. Each completed file persists its exit code immediately. This smaller job never builds a bundle or substitutes for the full source/90% coverage gate.

A separate always-run process invokes `python -m build_tools.native_font_probe --output-dir <artifact-dir>/native-font`. Its child explicitly selects the Windows Qt plugin, records the actual platform, installed font families, QFontInfo, shaped glyph indexes and raw-font character coverage, and captures styled synthetic widgets. An unavailable native plugin, missing required glyph, or failed screenshot remains nonzero; there is no offscreen fallback. Rare-character samples are reported separately and do not establish universal CJK coverage. The child uses an ephemeral profile and does not open business data. No fonts are installed or downloaded by this diagnostic. The original offscreen test environment and full source/build gate remain unchanged.

The prior Windows offscreen screenshots contained square glyphs and empty resolved font names. They are evidence about that Qt backend, not proof that the Windows OS has no Chinese fonts. Native source diagnostics still do not replace frozen artifact or clean offline Windows visual acceptance.

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

## Dependency notices and package inventory

The spec and packaging wrapper validate the pinned Python/release-package versions and byte-preserved notice corpus before building. Original license text, copyright/credits, exact upstream source URLs and a shared-DLL replacement guide are included in the distribution; `THIRD_PARTY_NOTICES.txt` is discoverable beside the EXE. `.gitattributes` preserves those upstream bytes on Windows checkouts.

The custom QtGui hook retains upstream collection except the unused Qt VirtualKeyboard plugin. The application does not import that binding or use QML; the real bundle inventory rejects unreviewed Qt modules/plugins, including the unused VirtualKeyboard/Quick/QML chain. QtPdf, QtPdfWidgets, printing, Windows and image/TLS plugins remain required. Normal native IME is not claimed as manually verified by this change.

Before a ZIP can be tested/published locally, the host verifies the full notice manifest against reviewed source bytes and checks Microsoft runtime file identities. Provenance separately reports `license_review_complete: false` and the precise outstanding Microsoft distribution items. The selected exact-source access and shared-DLL replacement directions are included; they do not establish Microsoft redistribution eligibility. This flag does not weaken the runtime or coverage gates; it prevents a successful technical check being misreported as legal clearance. See [the exact scope and source mapping](third_party_licenses.md). No new commercial agreement is accepted by these build tools.

The earlier all-green ZIP is retained as evidence, not rewritten. A new packaging input requires a new actual ZIP hash and the same extracted frozen EXE verification, even when application source is unchanged.

## Exact Windows system-runtime policy

New candidates target x64 Windows 10 1809+ / Windows 11. After Analysis, the spec
has exactly 43 possible reviewed system-DLL exclusions (13 CRT contracts, 29 core
contracts and ucrtbase). Present candidates require reviewed destination and
historical SHA-256; absence requires complete native OS dependency proof. It retains the eight Qt-supplied
and two CPython-supplied VC files unchanged, as well as PDF, PrintSupport,
qwindows, image/TLS plugins and the Traditional Chinese catalogue. No wildcard
API/ext-DLL removal or application behavior change is part of this policy.

The schema-2 `artifacts/build-staging/windows-system-runtime.json` records original
source paths, before/after inventories, exact removals and explicit absence,
retained VC hashes, source commit/tree and notice-manifest identity. Missing
required or changed present inputs fail. Linked package-environment and complete
staged-native proof receipts are mandatory. See the [bounded packaging-input
policy](windows_build_input_portability.md), including its residual different-hash
limitation. These receipts are diagnostic evidence, never source material.
The exact extracted candidate is compared with this staging receipt before its
frozen checks. `windows-candidate/pe-dependencies.json` includes every native PE
hash, complete normal/delay imports, bundled export forwarding and required
OS-symbol resolution. Pinned pefile's conservative default symbol limits are
raised explicitly; incomplete parsing and unexpected warnings fail the gate.
Native resolution uses system-only LoadLibraryEx and records actual Windows
system providers, including forwarded exports. It does not prove every DLL
loaded by the application's process or clean end-user Windows acceptance.

The existing 17 frozen checks and full raw 90% source gate remain mandatory.
The earlier ZIP is not modified, and its prior passing result does not qualify
this new exclusion policy. The one-directory output remains a validation
control; a standalone single-EXE build requires its own packaging, lifecycle,
source/rebuild directions and artifact acceptance.

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
13. Real Traditional Chinese standard buttons, calendar month/weekdays, and
    open/save/directory Qt file dialogs, starting from an English locale;
    nonempty meaningful prompts and actual buttons, generated folder metadata,
    and unchanged selected paths/content. A genuinely missing-catalogue check
    verifies the limited button fallback and reports `fully_localized: false`,
    then restores the complete catalogue.

These flows produce 17 required named checks in the machine-readable report.
They are representative synthetic runtime checks, not exhaustive domain tests.
The bundle must contain `qtbase_zh_TW.qm`; a missing catalogue or a report that
claims complete localization for the fallback fails the gate. Source report
`247fe2c` passed these 17 checks, but is explicitly `frozen: false`.

CPython socket audit events are denied during these synthetic operations. A
caught/swallowed attempt still makes the final result fail. This guard does not
control native-library networking or replace an OS network boundary. These
flows do not invoke live registry downloads, GCIS, external file opening, or
an application updater. No customer data is used.

The self-test temporarily redirects LOCALAPPDATA, APPDATA, USERPROFILE, HOME,
XDG_CACHE_HOME, XDG_CONFIG_HOME and XDG_DATA_HOME into its own temporary root
before importing/creating the tested Qt objects. It restores prior values
(including absent keys) in finally and cleans the synthetic root. This prevents
environment-based shell cache creation from using the caller's profile paths;
it is not a native-registry or OS-wide sandbox. The machine report states this
boundary. No existing user directory is deleted to satisfy the test.

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
  (the baseline 320 px calendar still has slight sixth-row text-bottom clipping
  in Linux offscreen rendering; the source language checks do not waive this)
- A copied populated supported-version database plus assets upgraded by the
  candidate, with an intact pre-upgrade backup; an explicit refusal of unknown
  newer schema versions
- Graceful process/thread cleanup and long-running/interrupted/repeated flows
- Package scanning, dependency review, license notices, and either a verified
  publisher signature or a clear unsigned-build disclosure

Only then may an explicitly authorized release step publish this same tested
ZIP, checksum, provenance, and known limitations. A green hosted-runner smoke
alone does not satisfy the clean/offline delivery requirement.
