# PyInstaller spec for YTKTV.
#
#   pyinstaller packaging/ytktv.spec --noconfirm
#
# Environment:
#   YTKTV_SEPARATION_MODE       how the build gets vocal separation:
#                                 bundle    ship torch inside the app (default; macOS)
#                                 download  ship the uv installer; the app fetches the right
#                                           GPU or CPU runtime on first run (Windows, Linux)
#                                 none      no separation at all
#   YTKTV_MPV_MODE              how the build gets mpv:
#                                 download  leave it out; the app offers to install mpv on
#                                           first start (default: mpv is under
#                                           the GPL and must not ship inside YTKTV)
#                                 bundle    copy libmpv into the app (private builds only)
#   YTKTV_ICON_DIR=path         folder with icon.icns / icon.ico (optional)
#   CODESIGN_IDENTITY=name      macOS Developer ID Application identity (optional)

import os
import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

import ytktv
from ytktv import bootstrap

ROOT = Path(SPECPATH).parent
SYSTEM = platform.system()
VERSION = ytktv.__version__
SEPARATION_MODE = os.environ.get("YTKTV_SEPARATION_MODE", "bundle")
if SEPARATION_MODE not in ("bundle", "download", "none"):
    sys.exit(f"unknown YTKTV_SEPARATION_MODE {SEPARATION_MODE!r}")
CODESIGN_IDENTITY = os.environ.get("CODESIGN_IDENTITY") or None
ICON_DIR = Path(os.environ.get("YTKTV_ICON_DIR", ROOT / "build" / "icon"))

MPV_MODE = os.environ.get("YTKTV_MPV_MODE", "download")
if MPV_MODE not in ("download", "bundle"):
    sys.exit(f"unknown YTKTV_MPV_MODE {MPV_MODE!r}")

libmpv = bootstrap.find_libmpv() if MPV_MODE == "bundle" else None
if MPV_MODE == "bundle" and libmpv is None:
    sys.exit("libmpv was not found; install mpv before building (see README).")
if libmpv is not None and not os.path.isabs(libmpv):
    # On Linux the lookup returns a bare soname ("libmpv.so.2"); PyInstaller needs the file.
    import re
    import subprocess

    listing = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
    match = re.search(rf"^\s*{re.escape(libmpv)}\s.*=>\s*(\S+)$", listing, re.MULTILINE)
    if match is None:
        sys.exit(f"could not locate {libmpv} on disk")
    libmpv = match.group(1)

# Refuse to package a library that cannot be loaded (e.g. a truncated download).
import ctypes

if libmpv is not None:
    try:
        ctypes.CDLL(libmpv)
    except OSError as exc:
        sys.exit(f"libmpv at {libmpv} cannot be loaded: {exc}")

PACKAGE = Path(ytktv.__file__).parent
datas = [
    (str(PACKAGE / "server" / "static"), "ytktv/server/static"),
    (str(PACKAGE / "ui" / "assets"), "ytktv/ui/assets"),  # the window icon
    # Run as a plain script by the downloaded runtime, so it must exist as a file.
    (str(PACKAGE / "separation" / "sep_worker.py"), "ytktv/separation"),
    (str(PACKAGE / "lyrics_ai" / "whisper_worker.py"), "ytktv/lyrics_ai"),
    (str(PACKAGE / "separation" / "pitch_core.py"), "ytktv/separation"),
]
datas += collect_data_files("imageio_ffmpeg")
datas += collect_data_files("certifi")
# HD unlock: yt-dlp finds plugins by scanning sys.path for yt_dlp_plugins folders with
# real .py files, and its challenge solver needs its JavaScript files.
datas += collect_data_files("yt_dlp_plugins", include_py_files=True)
datas += collect_data_files("yt_dlp_ejs")
datas += copy_metadata("bgutil-ytdlp-pot-provider")
datas += copy_metadata("ytktv")
binaries = [(libmpv, ".")] if libmpv is not None else []
hiddenimports = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
excludes = ["tkinter", "pytest", "IPython", "matplotlib"]

if SEPARATION_MODE == "bundle":
    # torchvision registers its operators from a compiled extension that static
    # analysis misses; without collect_all the frozen app fails at "torchvision::nms".
    for package in ("audio_separator", "torch", "torchvision", "onnxruntime", "onnx2torch",
                    "librosa", "soundfile"):
        try:
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        except Exception:
            continue
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
else:
    excludes += ["audio_separator", "torch", "torchvision", "onnxruntime", "onnx", "librosa",
                 "onnx2torch", "numba", "llvmlite", "sklearn", "pydub"]
# uv installs the downloadable runtimes: vocal separation (in "download" builds) and AI
# lyrics (everywhere, macOS included).
from uv import find_uv_bin

binaries.append((find_uv_bin(), "."))

analysis = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
if MPV_MODE != "bundle":
    # python-mpv looks libmpv up by name, and PyInstaller follows that to whatever mpv
    # the build machine has installed. It must not ship: mpv is under the GPL and is
    # installed separately (see bootstrap.install_libmpv).
    def _is_mpv(entry):
        name = Path(entry[0]).name.lower()
        return name.startswith(("libmpv", "mpv-")) and (".so" in name or name.endswith((".dll", ".dylib")))

    analysis.binaries = [entry for entry in analysis.binaries if not _is_mpv(entry)]

pyz = PYZ(analysis.pure)

icon = None
if SYSTEM == "Darwin" and (ICON_DIR / "icon.icns").exists():
    icon = str(ICON_DIR / "icon.icns")
elif SYSTEM == "Windows" and (ICON_DIR / "icon.ico").exists():
    icon = str(ICON_DIR / "icon.ico")

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="YTKTV",
    console=False,
    icon=icon,
    target_arch=None,
    # With a Developer ID in CODESIGN_IDENTITY, PyInstaller signs every bundled
    # binary with the hardened runtime; otherwise it applies an ad-hoc signature.
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=str(ROOT / "packaging" / "macos" / "entitlements.plist")
    if CODESIGN_IDENTITY
    else None,
)
collected = COLLECT(exe, analysis.binaries, analysis.datas, name="YTKTV")

if SYSTEM == "Darwin":
    app = BUNDLE(
        collected,
        name="YTKTV.app",
        icon=icon,
        bundle_identifier="com.tonyd365.ytktv",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "YTKTV mixes your microphones into the karaoke sound.",
            "NSLocalNetworkUsageDescription": "YTKTV lets phones on your network pick songs.",
            "LSApplicationCategoryType": "public.app-category.music",
            # The bundled libraries only run on the macOS they were built on or newer.
            "LSMinimumSystemVersion": platform.mac_ver()[0].split(".")[0] + ".0",
        },
    )
