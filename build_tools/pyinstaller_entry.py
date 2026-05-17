"""PyInstaller entry point for the Windows bundle.

PyInstaller executes the configured script as a top-level script, so package
relative imports from ``taxops.__main__`` are not reliable in the frozen app.
Keep this entry point tiny and use absolute imports only.
"""

from __future__ import annotations

import sys

from taxops.ui.app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
