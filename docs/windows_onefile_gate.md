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

## Bounded trace of an existing crash-probe EXE

If the owned crash probe reaches GUI-ready but its outer process does not return
77, do not accept another nonzero code as an equivalent controlled crash. The
PyInstaller 6.11.1 Windows parent normally reads its child's process exit code;
a strict extraction-cleanup failure can replace that result. See the fixed
[child-code implementation](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.11.1/bootloader/src/pyi_utils_win32.c)
and [parent cleanup implementation](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.11.1/bootloader/src/pyi_main.c).
Record the actual result before deciding the cause.

From a matching source checkout, with an existing Windows Python interpreter:

```text
python -m build_tools.trace_owned_crash --exe "<existing exact EXE>" --exe-sha256 "<independently verified SHA-256>" --output "<new diagnostic directory>"
```

This does not rebuild or modify the EXE. It verifies the input hash, copies only
the EXE, initializes a new token-owned synthetic profile once, closes that normal
run, then requests one crash using the same synthetic database and instance name.
It records the retained outer Popen PID, actual return code (decimal and hex),
raw stdout/stderr files, the ready report's self-reported inner PID, and remaining
extraction directories. The original immediate-exit probe offers no handshake
for retaining an inner process handle: its actual inner exit code is explicitly
unobserved. The harness never opens a stale PID, scans other processes or treats
an empty windowed-program stream as proof that no error occurred. Failure cleanup
uses only the existing retained-owned-process helper; it does not erase residual
files or count forced termination as normal cleanup. This focused trace does not
replace the full source, loader, frozen self-test or lifecycle gate.

### Native Qt source exit controls

When an intentional `os._exit(77)` does not produce the requested exit value,
run the separate source control only in an existing Windows CPython **3.11.9
x64** virtual environment containing **PySide6 6.10.2 / Qt 6.10.2**:

```powershell
& '<existing venv>\Scripts\python.exe' -m build_tools.qt_exit_contrast `
  --python '<existing venv>\Scripts\python.exe' `
  --output '<new diagnostic directory>'
```

Run from the fixed source checkout. The output must not already exist. No
packages are installed, application modules imported, or databases opened.
Five fresh processes use separate synthetic profiles. The original three are: no Qt import followed
by `os._exit(77)`; `QApplication` plus `QWidget.show()` followed synchronously
by `os._exit(77)` before `exec()`; and the same widget closed normally through
its event loop with expected exit 0. The final two use the same `QWidget`
subclass and child `QPushButton`: `clicked` connects to an undecorated Python
bound method, one real `click()` must increment its counter exactly once,
and strong sender/receiver references remain alive. One calls `_exit(77)`
synchronously after that ready checkpoint; the other closes normally through
the event loop with expected exit 0. The connection shape is identical in
this pair; no disconnection, cleanup, alternative termination API or
`@Slot` variation is inserted before abrupt exit. Each receipt records the
callback count and readiness. A missing callback or case mismatch fails.
These controls test a narrow signal-connection hypothesis; they do not
establish the cause of a different frozen failure.

Wrong versions stop before further exit
injection. An exit-code mismatch remains a failure while the remaining
controls run. Schema-2 receipts preserve the retained `Popen` outer process's actual exit
value, hexadecimal value, raw streams, runtime versions and module-file
identities. The child must report either that exact PID with the harness as
its parent, or one different PID whose exact parent is the owned outer PID
and whose runtime is the pinned Windows virtual environment. This relation
also requires exact launcher and base-interpreter path/hash/size identities
from the specified venv's `pyvenv.cfg` home. The child records its own true
image through `GetModuleFileNameW(NULL)`, plus `sys.executable`,
`sys._base_executable`, `sys.prefix` and `sys.base_prefix`; all must match
the configured expectations. Only the current process image is queried.
[CPython 3.11.9's venv launcher project](https://github.com/python/cpython/blob/v3.11.9/PCbuild/venvlauncher.vcxproj)
builds `PC/launcher.c` with `VENV_REDIRECT`;
[that launcher](https://github.com/python/cpython/blob/v3.11.9/PC/launcher.c)
creates one interpreter child, waits and forwards its exit code. This
explains the permitted single-level relationship, but its inner exit code
remains explicitly unobserved by this harness. No exited PID is reopened
and unrelated or deeper parent chains are rejected. Timeout cleanup applies only to the retained owned process tree.

These are **source native-Qt controls, not frozen EXE acceptance**. In
particular, source wheels may contain different VC DLL bytes from the
reviewed official VC replacements in the EXE. Module-file origins do not
prove actual loaded native VC paths; this small control does not collect
that inventory. A source failure can establish that TaxOps and the onefile
bootloader are not necessary to reproduce that source failure. A source pass
cannot rule out a frozen-only DLL or loader difference.

[CPython 3.11.9](https://github.com/python/cpython/blob/v3.11.9/Modules/posixmodule.c)
calls CRT `_exit` directly.
[Microsoft documents](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/cwait?view=msvc-170)
that `_exit` calls `ExitProcess`, which still performs
[DLL process-detach notifications](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-exitprocess).
That makes native termination a hypothesis to test, not an attribution to
Qt or a reason to accept an arbitrary nonzero value instead of 77.
