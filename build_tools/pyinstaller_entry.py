"""PyInstaller entry point for the Windows bundle.

PyInstaller executes the configured script as a top-level script, so package
relative imports from ``taxops.__main__`` are not reliable in the frozen app.
Keep this entry point tiny and use absolute imports only.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from taxops.diagnostics import main as diagnostics_main

        sys.exit(diagnostics_main(sys.argv[2:]))
    from taxops.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
