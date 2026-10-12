# Isolated Windows Shell icon observation

This standalone, standard-library-only experiment observes whether a Windows
Shell icon query loads additional native modules in its own child process. It
imports neither TaxOps nor Qt, reads no other process, and does not change the
application, native-module acceptance gate, registry, or security settings.

Run from the fixed source checkout with an existing 64-bit Windows Python:

```text
python -m build_tools.shell_icon_probe --output "C:\synthetic-tests\new-shell-observation" --timeout 90
```

The output directory must not exist. The parent creates only a synthetic text
file, empty folder, profile and temporary directory there. The child receives
isolated `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `TEMP` and `TMP`, plus a required
experiment token. These process environment values do not virtualize the host's
registry, Shell extensions or Windows account. No software is installed.

The child initializes COM with `CoInitializeEx(NULL, COINIT_MULTITHREADED)` and
uses the existing-file/directory small-icon flags from Qt 6.10.2:
`SHGFI_ICON | SHGFI_SMALLICON | SHGFI_SYSICONINDEX | SHGFI_ADDOVERLAYS |
SHGFI_OVERLAYINDEX` (`0x4161`), with `dwFileAttributes=0`. It does not use
`SHGFI_USEFILEATTRIBUTES`. Each returned nonzero `HICON` is destroyed once; the
returned system image-list handle is never destroyed. Both successful COM
initialization results, `S_OK` and `S_FALSE`, are balanced with one uninitialize.

Collector, hash implementation and required Windows API libraries are loaded
before the baseline. The baseline, post-file and post-folder snapshots enumerate
only `GetCurrentProcess()` modules. Every observed path, file size and SHA-256 is
retained; each comparison records additions, removals and changed on-disk bytes.
Hash/path/enumeration failures remain failures with available raw error values.
The final snapshot precedes COM teardown. No module is treated as trusted merely
because it appears in a delta. In particular, this experiment cannot excuse a
missing or mismatched application, Qt, Python or VC dependency in the EXE gate.

API return values, HRESULTs, immediate WinAPI last-error values, icon cleanup,
source/input hashes, child PID/parent PID and outer return code are retained.
A Windows venv launcher can be the retained outer process; a one-level child PID
relationship is reported separately, without claiming its exit code was directly
observed. The parent waits at most the requested bound (1–180 seconds). Only a
still-owned Popen process tree is eligible for failure cleanup, which is recorded
and never counted as normal success. Failed experiment directories are retained.

Upload only `report.json`, `child.json`, `stdout.bin`, `stderr.bin`, and, if created,
`owned-cleanup.json`. The report status `observed` means the experiment's calls and
observations completed; it is not application acceptance. A successful query with
no added module is inconclusive: Shell caching/background behavior and other Qt
icon paths are not exhausted by these two calls. Loaded-file hashes are not a
memory-integrity or publisher-signature check. A hosted observation is not proof
for every Windows installation.

Primary sources:
- [Qt 6.10.2 icon flags and existing-file branches](https://github.com/qt/qtbase/blob/v6.10.2/src/plugins/platforms/windows/qwindowstheme.cpp#L1135-L1204)
- [SHGetFileInfoW contract](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shgetfileinfow)
- [SHFILEINFOW layout](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-shfileinfow)
- [CoInitializeEx balancing](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex)
- [DestroyIcon ownership](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-destroyicon)
