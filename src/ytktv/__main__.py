from __future__ import annotations

import sys


def main() -> None:
    from ytktv.app import main as run

    sys.exit(run())


if __name__ == "__main__":
    main()
