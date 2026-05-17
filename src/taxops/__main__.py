"""``python -m taxops`` entry point."""

from __future__ import annotations

import sys

from .ui.app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
