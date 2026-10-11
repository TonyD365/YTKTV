from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--separation-worker":
        # A child process started by the app to separate vocals; no GUI.
        from ytktv.separation.sep_worker import main as worker

        worker(sys.argv[2:])
        return
    from ytktv.app import main as run

    sys.exit(run())


if __name__ == "__main__":
    main()
