# Single-EXE and recombination acceptance contracts

This describes the Phase B implementation and required evidence. It does not
supersede historical one-directory artifacts or label an untested EXE accepted.
The build remains a candidate until its exact final tree passes all gates.

| Requirement | Implementation | Required real acceptance | Current boundary |
|---|---|---|---|
| One EXE, no target prerequisites | Standard PyInstaller `EXE` includes binaries and data; no `COLLECT`, external loader, installer or activation | Copy only EXE into a Chinese/space path; native launch, embedded inventory and clean offline target | Source/spec contracts exist; final Windows EXE and clean target pending |
| Core offline operation | Existing local SQLite/services and full synthetic frozen suite | Native Windows self-test has no network attempts; disconnected target test | An audit hook is not an OS firewall or clean-target proof |
| Functional and data retention | All 28 migrations and original services/assets remain | Complete source regression; real-profile service-created client retains ID/code/name after normal restart, race and owned crash recovery | No production data in these tests; actual EXE persistence must pass |
| Chinese, assets, notices | Embedded icon, real Qt Traditional Chinese catalogue, offline settings notice viewer/export | Real 18-check EXE suite validates catalogue, widget, complete byte-preserved notice corpus and exported ZIP | Manual IME, DPI, accessibility and print interaction remain separate |
| Exact Windows system policy | Fixed 43 possible API-set/UCRT exclusions; present exact hashes and explicit absence with linked schema-2 native proof | Extract original EXE payload for full normal/delay PE import, export-forwarder and native OS-provider gates; compare full parsed inventory to staging | Target: Windows 10 1809+ / Windows 11 x64; no broad DLL-name wildcard removal; see bounded input policy |
| Ten retained VC destinations | Five fixed official Microsoft members replace eight Qt/Shiboken locations in isolated staging; two CPython files retained | Package/member SHA-256 plus valid Microsoft Authenticode on Windows; final payload matches receipt | Dynamic catalog SHA/size discrepancy stays explicit; notices do not alone establish all redistribution conditions |
| Normal bootloader lifecycle | Exact child `_MEIPASS` and native hashes reported; external parent checks after bootloader exit | Four normal GUI launches, two duplicate attempts, no normal extraction left behind, data outside MEI | Forced outer-process termination/power loss may leave temporary files; no broad `_MEI*` deletion |
| Startup contention and recovery | Atomic per-user ownership before database bootstrap; IPC only activation | Two warmed EXE children meet a barrier and start acquisition together; exactly one opens DB/window; owned child crash then recovery | Stale/live/PID-reuse behavior needs source and Windows tests; never force-delete a live lock |
| Unusable TEMP / storage errors | Gate owns a synthetic profile; invalid TEMP is an ordinary file, no ACL change | Bootloader returns nonzero/no DB, normal TEMP retry; blocked data-root file produces actual Chinese error/no bootstrap, then the same repaired profile starts | This is not a full-disk hardware fault or permission-change test |
| Genuine LGPL recombination | Actual modified `PySide6/support/__init__.py` keeps package semantics; actual source-compiled qgif metadata and GIF decode | Fresh DLL probe and actual rebuilt EXE execute both modifications, plus all original acceptance gates | A local Qt 6.10.2 qgif source compile/load/decode has been observed; final modified single EXE pending |
| Exact Application Code kit | Source/spec/hooks/assets/migrations/pins/hash inventory/notices plus limited permission and executable recipe | Export matches accepted EXE source commit/tree/hash; modified recipient source has distinct identity | Narrow permission does not relicense the project MIT/GPL; full source-access obligations remain |
| Immutable complete regression | Every test file in a separate process, no skipped/missing tests in release acceptance, raw combined line/branch coverage >=90% | Exact final Windows source matrix plus 17 existing + 1 notice frozen check | Focused tests and Linux platform limitations are not Windows acceptance |

## Trust and data boundaries

- Source and synthetic test inputs may be inspected and built. Business data,
  personal logs, credentials and private execution handoffs are not kit contents.
- Microsoft files retain proprietary terms. The limited LGPL Application Code
  grant does not authorize changing them. Global wheels remain untouched.
- The runtime diagnostic requires an explicit harness-owned profile token and
  exact isolated environment paths before Qt/application imports. It exercises
  the real application entry and services; it does not substitute a second app.
- Public-source archive/member hashes, notice hashes, source-tree identity,
  compiler evidence and actual executable evidence are distinct checks.
- Qt's official complete WebEngine source is necessary for the matching
  PDF/Chromium source; a GitHub tag archive without submodules is insufficient. The official full
  6.10.2 archive, size and publisher-declared SHA-256 are now recorded in
  SOURCE_ACCESS and the manifest. This identifies an available source route;
  the publisher must maintain availability. The qgif experiment does not need
  to download or rebuild the 881 MB WebEngine source.
- Build machines may need tools/network. Ordinary target execution must not.
  Existing verified local SDK/source/compiler inputs can be reused; no SDK tool
  execution is silently moved to another environment.
- Candidate CI does not publish a Release, sign an EXE, install target runtimes,
  change system security settings, accept agreements or prove SmartScreen trust.

Use [BUILD_RECOMBINE](../BUILD_RECOMBINE.txt) for exact commands. Failed gates
retain evidence and remain failures. A source commit, test count or hash receipt
is never a substitute for executing the matching final artifact.

## Actual loaded-module origins

The isolated onefile GUI probe now samples its own process after the real main
window is shown, and frozen diagnostics sample after all 18 existing checks.
The ordinary application entry does not collect or upload this information.
`native_files` remains an extracted-file inventory; it is not loader evidence.
The host's logical inspection/native-import resolver is also kept separate.

The diagnostic helper uses `GetCurrentProcess`, `K32EnumProcessModulesEx` and
`GetModuleFileNameW`, with explicit ctypes signatures and bounded buffers. It
opens no other process, changes no DLL/Qt search path, and does not preload Qt,
plugins or VC libraries to satisfy the gate. It hashes files reached from the
observed module handles. A changing module list, unreadable file or truncated
path fails the sample. This records on-disk file identity, not mapped-memory
integrity. The collector's own standard-library dependencies are included.

The external onefile gate checks each observed path and SHA-256 against the
actual EXE and embedded inventory. The main EXE is its own exact executable
identity outside `_MEIPASS`. Python, Qt, PySide, Shiboken and required VC modules
must be inside `_MEIPASS`. The pinned Python/Qt/binding core and basic VC imports
must actually appear. Distinct VC destinations sharing a basename retain their
individual path/hash evidence; duplicate exact paths are rejected. Missing
fields, missing core modules, unknown embedded files, changed hashes and foreign
paths fail acceptance.

OS-location classification uses independently queried Windows API roots and the
same narrow locations as the existing native resolver: directly in System32 or
beneath WinSxS. Unknown locations still fail. The candidate now adds a separate
[same-run Shell observation contract](windows_shell_module_classification.md):
a fresh isolated stdlib child must independently add each exact external file,
with live source/run/path/hash/size bindings. Protected payload, core and PE
dependency names cannot qualify. This is an observation classification, not a
trusted-extension designation or a claim that no dynamic dependency exists.
A separate exact `System32/msvcp110_win.dll` rule requires fresh Microsoft
signature and matching OriginalFilename evidence; generic VC families are not
exempted. These candidate rules require fresh Windows acceptance. The original
OS-location rule alone remains neither a signature nor a clean-machine claim.

`loaded_embedded` and `not_observed_embedded` are reported separately for each
sample. A plugin not loaded at that instant, an untriggered delay import, or a
`LOAD_LIBRARY_AS_DATAFILE` mapping is outside this evidence. File existence is
never substituted for actual loading. Linux/source runs explicitly report this
native evidence as unsupported, without adding test skips or changing the 18
checks or raw 90% coverage gate. Synthetic contract tests are not Windows EXE
acceptance. The next rebuilt Windows artifact must supply these snapshots;
previous artifact evidence does not retroactively satisfy the new requirement.

Microsoft API references:
- [EnumProcessModulesEx](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-enumprocessmodulesex)
- [GetModuleFileNameW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulefilenamew)
- [GetSystemDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemdirectoryw)

The modified-plugin probe additionally reads `PySide6.__version__` and the real
Qt `qVersion()` independently. Both must be the pinned 6.10.2 and appear in the
report; plugin metadata does not stand in for runtime version evidence. The
existing compiled-metadata marker, red GIF decode and modified Python package
checks remain required. Reused compiled DLL hashes remain caller-supplied; the
generic recipe does not embed a particular local compilation's hash.

## Explicit abrupt-termination model

The isolated frozen `--onefile-probe --crash-after-ready` control uses
`TerminateProcess(GetCurrentProcess(), 77)` after the real GUI-ready report,
loaded-module snapshot and synthetic persistent record have been written.
It rechecks the owned profile token and isolation environment before loading
the native API. The helper accepts neither a PID nor a process handle, opens
no other process and uses no alternative exit fallback. A failed call or an
unexpected return is a failed injection. Normal application startup and
shutdown do not call this helper.

This deliberately models an unexpected stop without application/CRT cleanup.
[GetCurrentProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getcurrentprocess)
provides the current-process pseudo-handle;
[TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)
does not return when successfully terminating the caller. The external gate
still requires the observed outer bootloader exit value to be exactly 77,
records the inner exit as unobserved, validates the injection marker, and
requires the subsequent normal launch, lock recovery and synthetic record
survival. Normal repeated launches, simultaneous startup, extraction cleanup
and all 18 frozen self-tests remain required.

The prior control was `os._exit(77)` in
`build_tools/onefile_runtime_probe.py`, immediately after writing the ready
report in the `MainWindow.show` wrapper, before `app.exec()`.
EXE SHA-256
`38f65d389373fabd458625e27503c8e28851b867d338fdfed427c47b6f0d7214`
returned outer `0xc0000005` instead of 77; a corresponding Windows application
error identified the inner process and `pyside6.abi3.dll`. That counterexample
remains a failure of the old control. The fault module alone does not prove a
particular DLL-detach mechanism, and this test-model correction is not a
claim to have repaired PySide6. CRT `_exit` can still invoke native DLL
termination routines through `ExitProcess`; it was therefore not a clean
model of bypassing all such routines. No passing result for this corrected
injection retroactively changes the earlier evidence.


## Adjacent cache verification recovery

`verify_cache` owns a `BEGIN IMMEDIATE` transaction when its shared container
connection is idle, covering metadata/count reads and the audit row. Success
commits and releases the writer; failure rolls back. An existing caller
transaction is protected by an inner SQLite savepoint, without committing or
rolling back the caller's other changes. Fresh-connection persistence, a
second writer, nested success/failure and cleanup-error cases are synthetic
regression contracts. The prior missing commit could lose the verification
audit on close and hold a write lock; it is separate from test import cost.

The settings smoke tests previously parsed the complete tracked government
ZIP twice. The measured Windows run completed the first import check after
482.015 seconds, then timed out during the second parse at the unchanged
900-second file limit. Its result remains failed. The replacement prepares
that full import once, records the original live page transition, and gives
each test its own database through SQLite backup. The original case names,
assertions and full 1,705,060-row input remain. Linux success, including
reversed and individually selected cases, does not establish the final
Windows elapsed time; that must be measured again on the fixed candidate.


## Observed simultaneous-start failure

[Run 38293931640](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38293931640)
passed all 153 source files / 3838 tests, with raw combined line/branch coverage
91.05698731866956%, and built a fresh onefile EXE. Its exact source tree was
`44f0214d10754dcd598a9a2b76eeddbfb8170489`. During the actual two-process
start barrier, exactly one process acquired ownership and opened schema 28;
the other process did not bootstrap and exited normally after reporting that
it sent an activation notification. Both exited with zero, but the winning
window recorded no activation. The strict gate failed. No owned-crash report
was produced, so this run supplies no result for the corrected termination
control, crash recovery, or the final 18-check frozen suite.

The reports identify a startup-notification failure, not a double database
owner. Notification timing, transport delivery and readiness must be checked
without weakening the activation requirement or treating a sender's success
message as proof that the winning window was activated.

The candidate now retains early activation requests until the real window is
fully shown and checks complete local-socket submission. See the
[startup activation contract](instance_activation.md). The constructor-event
regression fails on the earlier source and passes on the corrected source;
only a fresh Windows EXE run can close the observed frozen race failure.


## Hosted isolated build passed; a later startup race remains

[Run 38324859380](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38324859380)
checked out `112da65855c24cf9f06d9dbb44785cf8b9389a73`, with tree
`0aa15ec270b34a662d518e6b8c5f26f10f0a1517`, equal to reviewed local
`4453a8f7a3781e91324dc1b54b224731ee26b463`. All 158 source files / 4104 tests
passed, with no failures, errors, skips or unrun files and raw combined line/branch coverage
91.1487758945386%. The release environment and actual PyInstaller build passed.
The new EXE is 45,109,116 bytes with SHA-256
`1089e571517e16dfd34fb20fb3fad16ad49fffb01d3a586e47627fd19c45a74c`.

The schema-2 receipts report all 43 historical system DLLs absent and zero
removed, with the ten retained VC entries preserved. The payload dependency gate
completed before lifecycle execution; it did not require arbitrary copies of
those 43 files. This hosted result does not establish compatibility with every
SDK or clean end-user Windows installation.

The full gate still failed during the synchronized two-process launch. The loser
recorded no lock ownership or bootstrap, displayed the existing not-ready message,
and returned 1 normally. The winner's ready report recorded ownership, schema 28
and a shown window, but zero activations. It has no final normal-exit report: the
gate stopped and invoked its retained-process failure cleanup. This result is
not evidence of a new access violation. It also provides no result for the later
self-termination, recovery, 18-check suite or kit export.

The captured reports do not identify the exact connection phase. A potential gap
between lock acquisition and socket listening is under review; no return code,
notification requirement or readiness assertion is relaxed to mask the failure.


## Later source pass and transport-phase evidence

[Run 38330485769](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38330485769)
checked out `315db2d2b18400b97abf4129b4c54d86ba1c9969`, tree
`6bd72a98c84c4b7d18f2b6f270a2da44ef73d135`. All 159 source files / 4136 tests
passed, with no failures, errors, skips or unrun files and raw combined line/branch coverage
91.17232302340885%. The actual newly built EXE is 45,110,608 bytes, SHA-256
`b34c3819e412b8ea01c52c7cd101a804f20ebf40782c061597f6cf39a9f827d0`.
Its payload and dependency gates passed; synchronized startup remained failed.

The losing process connected on its first attempt and Qt accepted nine bytes,
but the `drain` phase ended after 500 ms with submission false and no recorded
socket error. Its observed outer exit was 1; the inner exit was not directly
observed. The winner reported a shown schema-28 window and zero activations.
The gate retained failure cleanup; the later termination/recovery, 18-check
suite and kit export did not run. This result must remain failed.

The separate [source transport diagnostic, run 38334298605](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38334298605)
uses the unchanged sender implementation with five controlled real Windows
Qt/PySide 6.10.2 receiver/sender pairs. Its 30 contract tests and diagnostic
execution completed; that status does not mean every notification succeeded.
Immediate acceptance succeeded, with nine bytes written and one activation.
An 800 ms pre-accept hold reproduced failure at approximately 516 ms: nine
bytes remained queued, no `bytesWritten` signal, and no socket error. A peer
already accepted before an 800 ms dispatch hold completed the write, with
activation delivered after dispatch resumed. Never accepting kept the nine
bytes pending and failed; closing the peer emptied the queue with an error and
an invalid connection, correctly remaining failed. Timing has the granularity
of this Windows Python monotonic clock; a recorded zero is not zero duration.

These controls establish that listening alone does not guarantee an active
native reader. They do not establish the exact frozen winner's per-phase
causality. The minimal candidate removes only the extra 500 ms write sub-deadline
and uses the existing entry-time 3000 ms budget throughout. It retains one
write, remaining-budget accounting, complete draining, valid connected state,
error rejection and rejection of completion observed after the deadline. A
false result after submission is not proof that the peer received no bytes and
never permits replay. Qt's synchronous native connect may itself overrun the
budget; this is not a hard real-time bound. New controlled-source and strict
frozen evidence are both required before claiming the startup failure closed.


[Fixed-source diagnostic run 38335606087](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38335606087)
checked out `02a336eac35c0b45df5d65b6943c8fccd07f5474`, tree
`34b25b0ec47929036df184d98883f7cff9048d35`. It used the unchanged five-case
probe against the corrected production notifier. The delayed-accept case now
completed in the observed 797 ms with nine bytes written, zero pending bytes
and exactly one received activation. Immediate and accepted-but-not-dispatching
controls also succeeded once. Never-accept remained false with nine bytes pending
at the observed 3016 ms; peer-close remained false with a socket error, invalid
connection and empty queue. All senders issued one write only. The 30 probe
contracts passed and all ten actors exited normally; failed negative-control
notifications remain failed. The actual Windows source hashes matched the reviewed
product and probe after exact checkout line-ending conversion. This establishes
controlled source transport repair, not a repaired or accepted frozen executable.

The independent Linux full matrix at local `fcc61c3c6d50566bc58f49b7990ae40449c6201c`
(tree `1c89411e328621e5236ec0665ee7a1babd45b057`) ran all 159 files / 4148 cases:
4141 passed, six existing local IPC-environment cases failed, and one existing
Windows-shell case skipped; no errors or unrun files. Raw combined line/branch coverage was
91.1310288633301% and the source remained unchanged. Its overall result is failed.
Later documentation-only changes are not represented as that matrix's source tree;
the next Windows run must test and package its own exact checkout anew.


## Latest notification repair and remaining module-classification failure

[Run 38336220402](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38336220402)
checked out `7a57312368877914cfd180b1f61f41e58b41ef0c`, tree
`39a871e1b2e054e6e75bc531f7f08a0185e0d8c4`, from PR head
`47c29b8ce07d3b3e63fa4c8e9669eaf5b440f4cf`. All 159 source files / 4148 tests
passed with no failures, errors, skips or unrun files; raw combined line/branch coverage was
91.17176972014165%. The new single EXE is 45,110,534 bytes, SHA-256
`0730bdb33377354628e527eb51f6c8f742d7806539c792a10a95ced4371d6bd4`.

The actual synchronized launch now produced one database/window owner, exactly
one activation at the winning window, and normal zero exits for both processes.
The owned abrupt-termination control returned outer 77; subsequent normal startup
recovered the lock and retained the same service-created synthetic client in
schema 28. Inner exit codes were not directly observed. The 18 frozen checks
passed under native `qwindows`, with `network_attempts=[]`. Normal bootloader
cleanup and the independently inspected final SQLite record also matched.

The complete acceptance still failed at the after-18-check loader snapshot.
Its 157 rows contained one EXE, 53 extracted modules, 93 direct-System32 modules,
two WinSxS modules and eight external Tortoise components. Those eight match
exact paths, sizes and hashes from the earlier independent Shell experiment
on another VM; that historical observation is not same-run qualification.
Reviewing every row also exposed a second rejection hidden behind the first:
`System32/msvcp110_win.dll` matches the existing broad VC-name rule, despite
Microsoft documenting that exact filename as a Windows-integrated component.
No broad VC exemption follows: this needs its own narrow, live OS-origin and
Microsoft-signature evidence, separate from any external Shell classification.

The new payload retained 28 migrations, 264 notice files, Traditional Chinese
Qt catalogue, PDF support and all ten VC destinations. All 43 historical system
DLL exclusions were absent. Its 446 archive entries, schema-2 receipts, 78 final
PE files and fresh five-member Microsoft signature checks were independently
matched to actual bytes. Six GUI-ready snapshots had no external modules and
passed the embedded-core origin checks. These earlier successful phases do not
override the final loader rejection. No accepted kit was exported or Release
published. Later source changes require a fresh full Windows run.

Microsoft component reference: [Validation OS 2510 release notes](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/validation-os-release-notes/2510?view=windows-11).
That documentation identifies the component; it does not authenticate this
runner's particular file or prove every supported Windows installation was tested.

## Accepted Hosted candidate and exported kit path failure

[Run 38343015308](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38343015308)
completed both Windows jobs successfully. Its exact build source was
`36a90de4a4dc8767133961b512dfc5609998b3f3`, tree
`34cd3e0f11202c04b6b12ffc6c66fc7367816c1f`. All 164 source files / 4421
tests passed with no failures, errors, skips or unrun files; raw combined line/branch coverage
was 91.17176972014165%.

The actual onefile EXE was 44,922,684 bytes, SHA-256
`029a3bc84a663d78b5f5748dbc110a7d5a5cf5797c0a87d1e4e8b80c53a2e24f`.
Independent review matched its 446 payload entries, complete 78-PE dependency
graph, ten bundled VC destinations, 28 migrations and 264 notice files. All 18
frozen checks passed with `network_attempts=[]`; the two-process race produced
normal exits and one activation, and controlled exit 77 recovered the same
synthetic record. Fresh same-run Shell evidence and Microsoft inbox-component
signature checks passed without exempting core, VC or real PE dependencies.
All seven embedded icon resources matched the selected ledger ICO bytes.

The exported kit was 68,024,395 bytes, SHA-256
`bc2dc0db02c36557e9fa50e416863a61b150bdf19ab2b0ac1a781376168e5e3a`.
Its 720 source files and manifest were independently matched to the exact source
and accepted EXE. This establishes accurate material export, not a successful
modified-component rebuild.

[Run 38348191958](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38348191958)
materialized that fixed kit, passed four native CMD bootstrap controls, initialized
the existing x64 compiler, and reran all 164 / 4421 source tests with the same raw combined line/branch
coverage. Its genuine qgif configure then failed: the kit's untyped
`-DQGIF_SOURCE_DIR` argument retained Windows backslashes, and CMake interpreted
`D:\a\...` as an invalid `\a` escape in the source list. No modified EXE was
produced. The original kit remains unchanged and this result remains failed.

The build-path correction requires a new candidate and new kit with their own
matching source identity, followed by fresh modified qgif/PySide compilation and
the original complete EXE gates. The source-identity gate is not relaxed to label
an edited copy of the old kit as accepted. Release remains unpublished. Hosted
verification also does not establish clean offline Windows, manual DPI/IME,
desktop pinning, or publisher signing.
