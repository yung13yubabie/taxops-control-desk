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
    if len(sys.argv) > 1 and sys.argv[1] == "--recombine-probe":
        from build_tools.recombine_probe import main as recombine_main

        sys.exit(recombine_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--onefile-probe":
        from build_tools.onefile_runtime_probe import main as onefile_main

        sys.exit(onefile_main(sys.argv[2:]))
    from taxops.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
