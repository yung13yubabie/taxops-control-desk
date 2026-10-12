# Bounded Windows packaging input separation

Use `python -m build_tools.package_windows` from the pinned, separate Windows
release virtual environment. Direct spec invocation does not establish the
required package-environment receipt. The wrapper invokes the absolute current
Python for both PyInstaller checks and the build.

## Packaging and compilation are separate inputs

Only PyInstaller children receive the bounded PATH: release/base Python
executable directories, WinAPI-derived System32/Windows directories, Windows
PowerShell's system directory and the existing Git for Windows `cmd` launcher.
Git's broader `mingw64/bin`, Qt SDK, JDK and unrelated inherited PATH directories
are not appended. Conflicting case-insensitive PATH keys, missing tools or a Git
launcher directory containing DLLs fail explicitly. No software is installed.

Child-only Python/Qt import-path variables are removed and user-site imports are
disabled. PySide6, Shiboken and PyInstaller must resolve inside the pinned release
venv. Existing version/notice validation remains mandatory. This is bounded
input separation, not a hermetic-build or executable-signature claim. PyInstaller
can still add importing/package directories to its own dependency searches;
every resulting staged native source is recorded and checked.

Parent/system PATH, registry, security settings and compiler `INCLUDE`, `LIB` and
`LIBPATH` are unchanged. CMake/Ninja/Qt SDK compilation continues in its original
compiler environment. An already verified modified qgif remains an explicit
replacement input, not a reason to collect the compilation SDK's Qt libraries.

## Exactly 43 possible exclusions, not 43 required physical files

The fixed exclusion destinations remain the 29 reviewed core contracts, 13 CRT
contracts and `ucrtbase.dll`. Every destination is recorded exactly once as
removed or absent. Present files still require their historical reviewed hash,
the original root destination, BINARY type and complete x64 PE parsing. The
forwarder-only parser-warning exception applies only after exact hash matching,
with zero entrypoint, all exports forwarded and the two reviewed warnings.
Different bytes, nested destinations, native files collected as data and
unreviewed collected `api-`/`ext-` DLLs fail. No wildcard exclusion is introduced.

An absent optional physical file is allowed only after all kept native inputs,
including the mandatory Python/Qt core and all ten exact VC DLLs, pass complete
normal/delay import, imported-symbol and export-forwarder checks. A fresh process
parses candidate files without executing them. The existing native resolver
loads bare dependency names with system-only search and verifies actual module
and forwarded-symbol providers in Windows System32/WinSxS roots. Unsafe names
fail before a loader call. Ordinary imported OS contracts outside the fixed 43
are resolved normally; their names do not authorize collecting or excluding a
new physical file. Unresolved required OS modules/contracts or imported symbols
fail. Successful binding alone does not prove the implementation's behavior;
the actual frozen checks and minimum-OS acceptance remain separate.

Microsoft describes API sets as OS-mapped contracts whose physical files need
not exist. UCRT is an OS component on Windows 10 and later. These facts justify
checking actual imported APIs rather than requiring an incidental physical
forwarder inventory. They do not authorize trusting arbitrary same-name files.
See [Windows API sets](https://learn.microsoft.com/en-us/windows/win32/apiindex/windows-apisets),
[UCRT deployment](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170)
and [DLL search order](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order).

This bounded policy can still reject a legitimate builder if it stages a
same-name Windows/Python-local file with different bytes. No new OS hashes are
accepted automatically. Such a failure needs separate provenance review; do
not install an unrelated JDK or add its directory to reproduce historical bytes.

## Relocatable evidence and final validation

Keep these five original receipts together:

- `official-vc.json`
- `windows-system-runtime.json` (schema 2)
- `package-environment.json`
- `windows-staging-input.json`
- `windows-staging-dependencies.json`

The schema-2 runtime receipt binds sibling filenames and hashes to source
commit/tree, notice identity, ordered before/after inventory, actual removals,
explicit absence and every retained VC file. Removed and absent states exactly
partition the fixed 43; removed is precisely before minus after. The kept native
inventory and complete parsed dependency graph are cross-linked. Absolute
original source paths remain diagnostic metadata, not required paths on another
validation host.

Final extracted-payload validation checks all native paths, hashes and sizes
against staging, creates a fresh current-host validation environment and reruns
native resolution. Its full parsed inventory must match the original staged
imports, exports, warnings, architecture and hashes. New validation receipts
have `windows-final-` names; original build receipts are not rewritten. Keep the
validation receipts alongside provenance. Historical schema-1 evidence remains
historical; it is not accepted as a new schema-2 build.

None of this replaces official VC source/signature checks, notice/Qt inventory,
actual loaded-module gates, modified-component probes, the complete raw 90%
source matrix, synchronized-instance race, strict exit 77/recovery or all 18
real frozen checks. Native host evidence is separate from supported-oldest and
clean offline Windows acceptance. A Linux synthetic/static pass cannot qualify
a Windows EXE or prove the child PATH experiment succeeds on Windows.
