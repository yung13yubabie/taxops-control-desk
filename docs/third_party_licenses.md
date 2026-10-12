# Windows dependency notices

The distributable notice index is `assets/third_party_licenses/README.txt`.
PyInstaller includes the complete directory under
`_internal/third_party_licenses` and places the same index at the bundle root
as `THIRD_PARTY_NOTICES.txt`. All license text assets are copied verbatim from
upstream; excerpts are explicitly identified in the manifest. This is a
reviewed notice corpus and packaging boundary, not a legal compliance opinion.

## Pinned sources and component mapping

`manifest.json` records the exact Windows PyPI wheel URL and SHA-256 for every
release requirement, original notice paths, and per-notice SHA-256 values.
Jinja2, MarkupSafe, openpyxl and et_xmlfile notices come from the actual wheels.
A path-scoped `.gitattributes` rule disables line-ending conversion for these
assets, so their hashes remain valid after a Windows checkout.
The full PyInstaller license includes its bootloader exception. Build-tool
notices are retained conservatively and identified as such.

The PySide wheels contain only a commercial-license reference file, which does
not establish entitlement or replace open-source license text. The LGPL/GPL
texts and third-party attributions here come from the official `v6.10.2`
Qt/PySide source tags instead. QtGui/Core/Network, SVG and image-format source
attributions preserve their own component versions and copyright notices.
The exact QtTranslations `licenseRule.json` supplies the LGPL-capable default
for the bundled translation catalogues; its build-tool licensing is separate.
Generic license definitions and conditional source notices are a superset of
the Windows runtime; their inclusion does not mean every component is linked.

Qt PDF uses the `qtwebengine` tag `v6.10.2`, whose `src/3rdparty` submodule is
`c971c6841dd6beab9f54aeaf9a53be413273039e` in `qt/qtwebengine-chromium`.
The corpus covers Chromium, PDFium and its nested license files, Abseil,
fast_float, FreeType, HarfBuzz, ICU, libjpeg-turbo, libpng and zlib. Original
README attribution files retain revision/version and `Shipped` information.
PDFium's codec/font helpers such as AGG, FP16, Highway, Little CMS, OpenJPEG,
libtiff and Noto are included conservatively, rather than assuming the QtGui
copies' versions or merely supplying a blanket LGPL text. FreeType's FTL and
JPEG's referenced IJG license text are included as well as their index files.
The source corpus is not an exact GN-generated binary dependency report.
The manifest records the precise dependency-scope decisions: Qt disables
custom libc++ (including the host build), so PDFium's libc++-only llvm-libc
helper is not treated as a missing Windows license or replaced with a newer
LLVM license. PartitionAlloc is enabled and uses the included Chromium BSD
notice on the reviewed Windows path. This is not a reason to collect unrelated
Chromium base libraries such as CityHash. PDFium's nested fast_float 6.1.4
README points to an absent source path; its full official upstream MIT license
is supplied separately and explicitly mapped, alongside Chromium's 7.0.0 copy.

Current `/qt-6.10/` web documentation can describe 6.10.3 and must not be used
to silently replace these 6.10.2 source versions.

Python uses the official 3.11.9 Windows embedded distribution's full license,
its source licensing appendix, and exact incorporated-software notices.
The baseline Windows native libraries include SQLite 3.45.1, Python's OpenSSL
3.0.13 and Qt's separate OpenSSL 3.5.5. The software-renderer notices use Mesa
11.2.2 and LLVM 3.6.2, including the latter's nested source license files;
Qt's exact `v6.10.2` distribution documentation supplies the Mesa MIT/Khronos/
Boost notices. These versions are deliberately not replaced by latest releases.

## Why the virtual keyboard is excluded

The application imports the Qt Widgets/PDF/image modules and has no QML,
QtQuick, VirtualKeyboard or `QT_IM_MODULE` use. PyInstaller 6.11.1's QtGui hook
collects the `platforminputcontexts` plugin directory. Its automatically
collected `qtvirtualkeyboardplugin.dll` imports `Qt6VirtualKeyboard.dll`, which
imports QtQuick and QtQml. The other selected native modules do not import
VirtualKeyboard. Its exact `v6.10.2` library and plugin source headers offer
commercial or GPL-3.0-only terms; they do not offer LGPLv3.

The custom QtGui hook calls the upstream dependency collector and filters only
that specific plugin before binary dependency collection. It does not remove
the whole input-context directory or patch application input handling. The
upstream hidden imports, data, PDF, PrintSupport, qwindows and other reviewed
plugins are retained. The resulting bundle must match an explicit allowlist of
Qt module, binding and plugin files. Unexpected modules (including Charts,
DataVisualization, Quick/QML or VirtualKeyboard) block the ZIP; absence from
source imports alone never proves the actual packaged artifact is clean.

This change does not claim that touch input, native Windows IME composition,
file dialogs or PDF printing have passed manual Windows acceptance. Frozen
checks and separate native/manual acceptance remain required.

## Gates and updates

`build_tools.dependency_licenses` checks the notice file inventory and bytes,
all release requirement pins and installed versions, and Python 3.11.9 before
packaging. The spec invokes it even when called directly. ZIP verification
compares notice bytes against the reviewed source manifest, rejects unexpected
Qt binaries/plugins, and records the notice-manifest hash and outstanding
release review in bundle provenance. The root index is checked too.

For an update, retrieve the exact official distribution/source version, inspect
its metadata and license references (including nested licenses and NOTICE
files), preserve original bytes, and update the manifest source URL, component
mapping and hashes. Review required end-user attributions such as JPEG/FreeType.
Do not substitute a generic SPDX license for an upstream copyright/NOTICE file,
a commercial-reference placeholder for an open-source license, or a newer
source version for the binary version. The generic hash checker cannot discover
a new legal obligation; substantive dependency review remains necessary.

Run affected complete test files in separate processes, then the complete
Windows test matrix without exclusions or lowered coverage, a new PyInstaller
build, and the existing extracted frozen-EXE checks. A previously tested ZIP
must not be edited and presented under its old hash.

## Source access beside the candidate download

Download the source for Qt/PySide/Shiboken 6.10.2 using the
[packaged source-access directions](../assets/third_party_licenses/SOURCE_ACCESS.txt).
They provide the complete official Qt release source archive, individual
module archives, the PySide/Shiboken source archive, fixed-version build
instructions, and DLL replacement steps. These directions belong beside the
candidate ZIP download and in its accompanying guide, with a link pinned to
that candidate's TaxOps source revision. They are also inside the ZIP.

The selected network source-delivery route is **GPLv3 section 6(d)** for the
LGPL-covered libraries, with equivalent copying access at no additional charge.
The combined-work mechanism is separately **LGPLv3 section 4(d)(1)**: the
one-directory bundle loads replaceable shared DLL/PYD libraries. This does not
select GPL for the TaxOps application or claim that every modified library is
interface-compatible. There is no TaxOps runtime hash lock on replacements.

All seven source archive URLs returned archive bytes on 2026-10-12. The Qt
`download.qt.io` archives were range-checked; the PySide archive and GitHub Qt
tag archives used for notices were fully downloaded and hashed. The latter
hashes do not describe the different official `.tar.xz` files. Use the full
Qt release archive for Qt PDF: a GitHub-generated `qtwebengine` archive alone
does not include its Chromium/PDFium git submodule.

TaxOps applies no Qt/PySide/Shiboken source patches. The pinned sources include
CMake/setup.py build scripts, headers, COIN build options and Windows MSVC2022
instructions. Source configuration identifies the Qt PDF partition allocator
and disabled custom libc++ choices. The precise vendor-generated CMake cache,
complete GN arguments and wheel build log were not recovered, and a modified
replacement build has not been independently tested. No specific additional
source patch is identified as missing. These are reproducibility/validation
limits, not an unselected delivery method or a demand for bit-identical output.
Any subsequently discovered necessary patch or source mismatch must be fixed
in the source directions before claiming completeness for that library.

The publisher must check the source links at distribution and maintain clear
directions beside the binary, plus equivalent source access for as long as
section 6(d) requires, including when another server hosts it. Restore missing
access to the same source before continuing to rely on this route. This is
not a section 6(b) written offer, a new commercial agreement, or a separate
long-term source-offer commitment. Offline-only redistributors need an
applicable source-delivery route. Microsoft runtime questions below are
independent of this completed choice and documented procedure.

## Remaining distributor decisions

All identified open-source notice texts for the reviewed scope have been
obtained. No new commercial agreement or purchase is identified as required
by this repair. The following are concrete distribution conditions, not
missing generic license files:

- Resolve the source/terms questions for the eight Qt-supplied VC files and
  the unmatched API-set/UCRT group identified below. Microsoft's generic runtime
  redistribution guidance is a reason to check their applicable terms, not a
  basis to discard the explicit downstream route in CPython's own Windows
  license. Neither a new purchase nor universal Visual Studio licensing for
  Python end users is inferred here. See [Microsoft's redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files).

The build remains a candidate: packaging integrity and executable runtime
checks do not authorize publication or guarantee legal compliance.

## Microsoft file-level provenance boundary

The manifest maps every reviewed Microsoft runtime file by bundle path, PE
version and SHA-256 to the exact downloaded official distributions:

- Two root VCRUNTIME 14.38.33126.1 files match the official Python 3.11.9
  embedded distribution byte-for-byte. Its full Windows license expressly
  states a downstream redistribution route, with four restrictions: preserve
  notices, do not imply Microsoft endorsement, distribute on Microsoft
  platforms, and do not include the code in malicious/deceptive/unlawful
  programs. The original text also addresses downstream protective terms.
  This is not a claim that ordinary Python users must buy Visual Studio.
- Five files under PySide6 and three under shiboken6 are VC runtime
  14.44.35211.0 and match the respective pinned official wheels byte-for-byte.
  No separate Microsoft downstream terms were found in those wheels; their
  Qt commercial-reference file is not such a grant. The CPython notice cannot
  silently be extended to different Qt-supplied binaries.
- Forty-two `api-ms-win-*` files and `ucrtbase.dll`, version 10.0.26100.1742,
  have no matching bytes in the reviewed 15 release wheels or Python embedded
  distribution. Their build source and corresponding SDK/system redistribution
  terms must be identified before asserting their redistribution clearance.

The byte mapping is a provenance check, not a determination of entitlement or
noncompliance. These limited questions do not prevent local repair or candidate
CI. No newly required purchase or agreement has been established, and none is
accepted here. The ZIP gate detects a changed or additional Microsoft binary
so its recorded provenance cannot silently become stale.
