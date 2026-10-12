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
