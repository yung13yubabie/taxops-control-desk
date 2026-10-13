# Same-run Windows module classification

The onefile gate retains the original executable, embedded-file, actual loaded
core, native import/export, source coverage, frozen diagnostic, lifecycle,
activation-race and owned-crash requirements. Unknown external modules fail.
Existing failed artifacts are not reinterpreted as passing candidates.

## Independent Shell observation

After complete payload and PE verification, the verifier starts a fresh direct
child using the pinned base CPython 3.11.9 executable, `-I -S`, and an absolute
reviewed helper path. It does not use the venv redirector or add the checkout to
`sys.path`. The child loads only the exact adjacent stdlib module collector.
The verifier retains its Popen handle, observes exit zero, and requires exact
child/parent PIDs. A fresh nonce and acceptance-run identifier travel through
stdin. Neither a CLI option nor a persisted JSON receipt can supply a baseline.

Both sides record exact helper, interpreter and synthetic-input identities;
source commit/tree, bounded WinAPI host identity (without importing socket
support) and independently queried Windows roots must
remain equal. The helper uses isolated synthetic profile/temp paths. This does
not virtualize the Windows account, registry, native networking or installed
Shell extensions. No software is removed and no system settings are changed.

The before snapshot permits only the existing narrow OS roots and explicitly
listed, prehashed paths from the pinned CPython installation: the interpreter,
Python runtime DLLs, its VC runtime, and the collector's standard-library native
support files. This bootstrap inventory applies only to the observer. It never
grants the EXE permission to use host Python, Qt, VC or other dependencies.
Unknown external before modules and any Qt/TaxOps import or native-module
contamination reject the observation.

The child makes the Qt 6.10.2 existing-file small-icon Shell query (`0x4161`) for
a synthetic file and an empty folder. Every call, before/post-file/post-folder
snapshot, path, loader path, size, SHA-256 and error is retained. A failed query,
icon cleanup, COM balance, incomplete snapshot, changed/removed module or
unstable module list fails closed. Stable handles must also retain the same
canonical loader paths; reuse of a handle for another module invalidates the
sample. The verifier recomputes additions from full
snapshots; reported delta fields are not authority. A candidate must be absent
from before and present after the successful queries.

Classification is `independently_shell_observed_external`. Before comparing an
external module, the verifier rejects all payload basenames, Python/Qt/binding/
VC families, `.pyd` files, and names from the complete PE normal/delay imports
and export-forwarder inventory, including resolved OS module paths, symbol
providers and nested forwarder providers. Unknown resolution kinds fail closed. The observer's own System32 VC additions remain
visible as excluded evidence. Ordinary Windows OS dependencies continue through
the original narrow OS-location checks.

At each application phase the current live run/source/helper/runtime context is
rechecked. An external match requires the same canonical local-drive path,
SHA-256 and byte count, followed by a fresh stable on-disk read. Hashing compares
file identity and size/timestamps before and after the read. All module-row
violations are collected; a failure retains successful classifications as well
as every rejected row and still fails the whole gate.

This is evidence that an independent Shell query on this host/run also added
these exact files. It is not a trusted-extension designation, proof that the
application never dynamically needs them, a Qt call-stack attribution,
cryptographic host attestation, mapped-memory integrity scan, or clean Windows
acceptance. A compromised verifier/OS is outside this measurement boundary.
An empty delta grants no new classification. Missing core modules and unobserved
plugins are never made successful by the observation.

## Exact Windows-integrated runtime

A separate rule covers only `msvcp110_win.dll` at the independently queried
System32 root. Microsoft documents it as the Windows-integrated VC++ 11 STL;
it is distinct from redistributable `msvcp110.dll` and MSVC 14 runtime DLLs.
This is not a Shell-delta classification.

This exact name cannot intersect any payload or required PE dependency name.
The current phase's canonical path/hash/size must match a fresh stable file
read. The existing Microsoft Authenticode helper must return Valid, a Microsoft
Corporation signer, a signer thumbprint, zero process exit and complete raw
process evidence. OriginalFilename must exactly match `msvcp110_win.dll`
(case-insensitive); localized ProductName and FileVersion are recorded without
using them as policy strings. This prevents another Microsoft-signed component
from qualifying merely by being renamed. A second file identity after signature verification must
match the first. Signature errors retain their raw process diagnostics. No
persisted signature receipt can grant this classification. Other `msvcp*`
names, alternate directories, missing evidence or changed bytes remain failures.

## Product alternative and verification

Replacing the Qt file icon provider would change associated-file icons, custom
folder icons and overlays. `DontUseCustomDirectoryIcons` alone leaves existing
file queries unchanged. Installing a provider at the current Show-event hook
cannot establish that constructor/model work did not already request icons.
That product alternative therefore needs its own construction-timing and
open/save/directory, selection, localization and visual checks; this change does
not alter the product's provider.

Synthetic adversarial tests check receipt replay, wrong identities, polluted
before snapshots, forged/changed deltas, protected dependency names, duplicate
paths, source changes and live file changes. They are not Windows observations.
Acceptance requires a new complete Windows build: every original source test
plus the new tests, zero skips, raw branch coverage at least 90%, every frozen
check, all lifecycle/race checks and exact outer exit 77. A hosted pass still
leaves clean/offline standard-user Windows and manual GUI/DPI acceptance open.

Sources:
- [Qt 6.10.2 Windows file-icon queries](https://github.com/qt/qtbase/blob/v6.10.2/src/plugins/platforms/windows/qwindowstheme.cpp)
- [Qt 6.10.2 QFileDialog provider and model construction](https://github.com/qt/qtbase/blob/v6.10.2/src/widgets/dialogs/qfiledialog.cpp)
- [Microsoft Windows-integrated VC++ 11 STL documentation](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/validation-os-release-notes/2510?view=windows-11)
