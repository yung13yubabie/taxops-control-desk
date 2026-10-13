# Recompile a modified Qt 6.10.2 GIF plugin

This standalone harness builds the four upstream GIF inputs using the public
Qt CMake packages. It does not require Qt's private build-system commands, a full
Qt checkout build, or Qt Creator. The plugin uses Qt's private GUI headers, so
use the exact 6.10.2 SDK, not an ABI-compatible guess. The checked-in harness is
not evidence of a successful Windows compile; retain the actual build output.

Prerequisites on the **build** machine only: Python 3.11.9 x64, CMake >=3.22,
Ninja, Visual Studio 2022 x64 C++ build tools and Windows SDK >=10.0.17763.
Use an x64 Native Tools command prompt, or discover Visual Studio with vswhere
and call its VC/Auxiliary/Build/vcvarsall.bat x64. Record `cl /Bv`, CMake/Ninja
versions and the selected Windows SDK. Do not guess compiler installation paths.

1. Obtain the official source and SDK from the exact links below. Verify both
   SHA-256 values before extraction. Never run an unverified archive's tools.
2. Extract the SDK so `<QT_PREFIX>/bin/moc.exe`, `<QT_PREFIX>/lib/cmake/Qt6`
   and `<QT_PREFIX>/include/QtGui/6.10.2/QtGui/private` exist. These are build
   inputs, not end-user installations. Use a new dedicated directory.
3. From the repository root, prepare sources and compile (quote paths):

```text
python build_tools/qgif_rebuild/prepare_source.py --archive "<qtbase source.tar.xz>" --output "<work>/modified-qgif-source"
cmake -S build_tools/qgif_rebuild -B "<work>/qgif-build" -G Ninja -DCMAKE_BUILD_TYPE=Release "-DCMAKE_PREFIX_PATH:PATH=<QT_PREFIX>" "-DQGIF_SOURCE_DIR:PATH=<work>/modified-qgif-source"
cmake --build "<work>/qgif-build" --verbose
```

Use absolute, forward-slash paths for the two `-D...:PATH=` values, including
on Windows (for example `D:/build work/modified-qgif-source`). Keep each full
argument quoted. The automated recombination script normalizes these paths and
rejects unsupported single-path syntax before doing work; see the supported
path boundary in `BUILD_RECOMBINE.txt`. In particular, a semicolon is a CMake
list delimiter, not an additional supported SDK prefix in this procedure.

The output is `<work>/qgif-build/plugins/imageformats/qgif.dll`. Preserve it,
its SHA-256, all four prepared source files, `source-receipt.json`, copied
LICENSES, CMakeCache.txt, compiler/linker commands and version output. No source
DLL or package is modified in place. The only upstream change is an added
`TaxOpsRecombineMarker` property in gif.json. moc compiles that property into
the rebuilt plugin's real metadata.

4. In a fresh process with the pinned PySide6 runtime, use the recombination
   probe to require that exact plugin's metadata marker and decode a synthetic
   1x1 GIF. A successful compiler exit alone is insufficient. Then build the
   recombined application and require the same two checks inside that EXE.
   The probe and packaging gate are maintained in the build_tools package.

Source:
https://download.qt.io/archive/qt/6.10/6.10.2/submodules/qtbase-everywhere-src-6.10.2.tar.xz

SHA-256: aeb78d29291a2b5fd53cb55950f8f5065b4978c25fb1d77f627d695ab9adf21e

SDK:
https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6102/qt6_6102/qt.qt6.6102.win64_msvc2022_64/6.10.2-0-202601261212qtbase-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z

SHA-256: c4cedcc54d2036ab20b193db113cf324d90f390647f831a522952cc9b158f38b

The SDK's official SHA-1 sidecar also identifies
5d89fd111a57ebdabe4e2122d747ae891f5d98c3. The Qt LGPL source/license notices
remain applicable; no TaxOps project-wide license change is made by this
experiment. This does not prove clean offline end-user operation.
