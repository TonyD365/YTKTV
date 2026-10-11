"""Entry point for frozen (PyInstaller) builds."""

import multiprocessing

from ytktv.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
