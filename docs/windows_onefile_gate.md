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
| Exact Windows system policy | Original exact 43 API-set/UCRT filter and before/after receipt remain | Extract original EXE payload for full normal/delay PE import, export-forwarder and native OS-provider gates | Target: Windows 10 1809+ / Windows 11 x64; no broad DLL-name wildcard removal |
| Ten retained VC destinations | Five fixed official Microsoft members replace eight Qt/Shiboken locations in isolated staging; two CPython files retained | Package/member SHA-256 plus valid Microsoft Authenticode on Windows; final payload matches receipt | Dynamic catalog SHA/size discrepancy stays explicit; notices do not alone establish all redistribution conditions |
| Normal bootloader lifecycle | Exact child `_MEIPASS` and native hashes reported; external parent checks after bootloader exit | Four normal GUI launches, two duplicate attempts, no normal extraction left behind, data outside MEI | Forced outer-process termination/power loss may leave temporary files; no broad `_MEI*` deletion |
| Startup contention and recovery | Atomic per-user ownership before database bootstrap; IPC only activation | Two warmed EXE children meet a barrier and start acquisition together; exactly one opens DB/window; owned child crash then recovery | Stale/live/PID-reuse behavior needs source and Windows tests; never force-delete a live lock |
| Unusable TEMP / storage errors | Gate owns a synthetic profile; invalid TEMP is an ordinary file, no ACL change | Bootloader returns nonzero/no DB, normal TEMP retry; blocked data-root file produces actual Chinese error/no bootstrap, then the same repaired profile starts | This is not a full-disk hardware fault or permission-change test |
| Genuine LGPL recombination | Actual modified `PySide6/support/__init__.py` keeps package semantics; actual source-compiled qgif metadata and GIF decode | Fresh DLL probe and actual rebuilt EXE execute both modifications, plus all original acceptance gates | A local Qt 6.10.2 qgif source compile/load/decode has been observed; final modified single EXE pending |
| Exact Application Code kit | Source/spec/hooks/assets/migrations/pins/hash inventory/notices plus limited permission and executable recipe | Export matches accepted EXE source commit/tree/hash; modified recipient source has distinct identity | Narrow permission does not relicense the project MIT/GPL; full source-access obligations remain |
| Immutable complete regression | Every test file in a separate process, no skipped/missing tests in release acceptance, raw branch coverage >=90% | Exact final Windows source matrix plus 17 existing + 1 notice frozen check | Focused tests and Linux platform limitations are not Windows acceptance |

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
actual EXE and embedded inventory. The main EXE is the sole exact executable
exception outside `_MEIPASS`. Python, Qt, PySide, Shiboken and loaded VC modules
must be inside `_MEIPASS`. The pinned Python/Qt/binding core and basic VC imports
must actually appear. Distinct VC destinations sharing a basename retain their
individual path/hash evidence; duplicate exact paths are rejected. Missing
fields, missing core modules, unknown embedded files, changed hashes and foreign
paths fail acceptance.

OS-location classification uses independently queried Windows API roots and the
same narrow locations as the existing native resolver: directly in System32 or
beneath WinSxS. Other locations, including unreviewed system subdirectories or
third-party injected libraries, are reported and fail this gate; there is no
silent allowlist expansion. This is not an OS-signature or clean-machine claim.

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
