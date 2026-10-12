TaxOps Control Desk — third-party software notices
=================================================

This application uses Python 3.11.9, Qt/PySide6/Shiboken 6.10.2,
Jinja2 3.1.6, MarkupSafe 3.0.3, openpyxl 3.1.5 and et_xmlfile 2.0.0.
The packaged executable also contains a PyInstaller 6.11.1 bootloader.
The original copyright and license texts are retained under:

    _internal/third_party_licenses/

The manifest.json in that directory identifies exact upstream distributions,
source URLs, versions, component mappings and SHA-256 hashes of these notices.
License terms remain with their respective copyright holders. This document
is an attribution index; it does not grant a commercial Qt or Microsoft license
or relicense TaxOps, and is not a legal compliance warranty.

Qt, PySide6 and Shiboken
-----------------------
The reviewed Qt modules have LGPLv3 open-source licensing alternatives. The
complete LGPLv3 and GPLv3 texts and upstream attribution files are included.
Do not remove notices or prevent the rights granted for the covered libraries,
including modification and reverse engineering for debugging modifications.
The libraries are separate DLLs in the one-directory distribution, using the
shared-library mechanism in LGPLv3 section 4(d)(1). SOURCE_ACCESS.txt supplies
fixed-version source downloads, build inputs and replacement instructions. The
selected source-delivery route for the network download is GPLv3 section 6(d):
clear directions beside the binary and equivalent no-additional-charge source
access. That file explains the publisher's availability responsibility and the
specific build-verification limits, separately from Microsoft runtime review.

Qt Virtual Keyboard is a separate GPL-only/commercial module. TaxOps does not
use it. Its automatically discovered plugin and dependency chain are not
approved for this distribution. Native Windows text input is supplied through
the retained qwindows platform plugin; this is not a native IME acceptance test.

Qt PDF and native third-party code
---------------------------------
Qt PDF remains included. The qt-pdf-chromium directory contains license texts
from the exact Qt 6.10.2 Chromium source revision, including PDFium and nested
third-party notices. Qt's core/image/SVG source attributions are in qt-6.10.2.
These are conservative source notice corpora: conditional, non-Windows and
build/test-only notices can be present without the associated code being in
the executable. They are not an exact binary Software Bill of Materials.
Qt Network includes Public Suffix List data covered by MPL-2.0. Its source
form is available in the matching Qt source distribution and at:
https://github.com/qt/qtbase/tree/v6.10.2/src/3rdparty/libpsl
The included MPL-2.0 text describes the rights to that covered source.

The separate QtGui and PDFium FreeType, HarfBuzz, JPEG, PNG and zlib versions
must not be conflated; the original attribution files retain their versions.

This software is based in part on the work of the Independent JPEG Group.
Portions of this software are copyright The FreeType Project
(https://www.freetype.org). All rights reserved. See the included FreeType
copyright and FTL texts for the respective versions and contributors.
This software includes code from XZ Utils (https://tukaani.org/xz/).

OpenSSL 3.0.13 (Python) and OpenSSL 3.5.5 (Qt) have separate entries, even
though both carry Apache-2.0 terms. SQLite 3.45.1 is public domain. Python's
Windows build conditions and additional incorporated-software notices are
preserved. Mesa 11.2.2 and LLVM 3.6.2 support the software OpenGL DLL; their
licenses are included independently from current Mesa/LLVM releases.

Microsoft runtime conditions
----------------------------
The included Python Windows license explicitly provides a downstream route
for that Windows build, subject to its four stated restrictions. The two root
VCRUNTIME DLLs match that official Python distribution. This does not mean
Python users must purchase Visual Studio.

The separate Qt/PySide/Shiboken VC DLLs match their official wheels, but those
wheels do not supply separate Microsoft redistribution terms. The API-set and
UCRT files do not match the reviewed wheels or Python embedded distribution.
The manifest identifies every file, version, hash, match and remaining source/
terms question. Those questions concern final redistribution, not permission
to perform this local packaging repair or CI. Qt LGPL does not license these
Microsoft components.
This bundle does not accept terms or assert a commercial entitlement for you.

Maintenance
-----------
Any Python, package, Qt module, plugin or native dependency change requires a
fresh review. Packaging checks asset hashes, release versions and the approved
Qt native inventory. It does not publish a release. A new bundle must pass the
unchanged full source/coverage gate and be extracted and self-tested as that
same frozen executable. Notices must travel with the entire extracted folder.
