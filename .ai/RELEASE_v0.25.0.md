# TaxOps Control Desk v0.25.0

## Highlights

- Hardened backup/restore, registry import/download, bulk task operations, FTS
  consistency, attachment handling, workflow images, and deleted-owner
  isolation.
- Fixed multiple UI state and responsive-layout defects across cases, tasks,
  templates, work records, folders, recurring billing, settings, and late-fee
  calculation.
- Added decoded-pixel limits before attachment image preview.
- Added real registry QThread lifecycle tests and blocked application close
  during active registry operations.
- Added callable resolution checks for every enabled UI action contract.
- Added exact Windows release dependency pins.

## Verification

- Full test suite: 1108 passed.
- Release dependency audit: 0 known vulnerabilities across 15 pinned packages.
- Fresh-environment PyInstaller build: passed.
- Isolated EXE startup and SQLite creation smoke test: passed.
- ZIP readback: passed.
- SHA-256:
  `da5e034248867a8c72dcf79b5d2718e062cdd1ae9d1a3bcb93d04ca2ad6aad76`.

## Known residual risk

Real desktop acceptance at 1366x768 and 100/125/150/200 percent DPI is not
recorded in this release session because the Windows Computer Use connector
failed to initialize. Automated layout regression tests and EXE smoke passed.
