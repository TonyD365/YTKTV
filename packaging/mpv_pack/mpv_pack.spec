# PyInstaller spec that collects libmpv and every library it needs into one folder.
#
# Nothing here is shipped as a program. build_mpv_pack.py runs this to let
# PyInstaller do what it is good at (finding the libraries libmpv depends on,
# and on macOS rewriting their load paths and signing them), then zips the
# libraries as the separate mpv download.

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

from ytktv import bootstrap

HERE = Path(SPECPATH)

libmpv = bootstrap.find_libmpv()
if libmpv is None:
    sys.exit("libmpv was not found; install mpv before building the mpv pack.")
if not os.path.isabs(libmpv):
    # On Linux the lookup returns a bare soname ("libmpv.so.2"); PyInstaller needs the file.
    listing = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
    match = re.search(rf"^\s*{re.escape(libmpv)}\s.*=>\s*(\S+)$", listing, re.MULTILINE)
    if match is None:
        sys.exit(f"could not locate {libmpv} on disk")
    libmpv = match.group(1)
try:
    ctypes.CDLL(libmpv)
except OSError as exc:
    sys.exit(f"libmpv at {libmpv} cannot be loaded: {exc}")

# The stub's own Python must bring no libraries of its own. Python's OpenSSL in
# particular has the same file names as the one mpv was built against: with both
# collected, the pack would end up with libssl from one and libcrypto from the other.
excludes = ["tkinter", "ssl", "_ssl", "_hashlib", "sqlite3", "_sqlite3", "curses", "_curses",
            "readline", "lzma", "_lzma", "bz2", "_bz2"]
analysis = Analysis([str(HERE / "stub.py")], binaries=[(libmpv, ".")], excludes=excludes)
exe = EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True, name="stub", console=True)
COLLECT(exe, analysis.binaries, analysis.datas, name="mpvpack")
