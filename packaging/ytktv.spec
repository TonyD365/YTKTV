# PyInstaller spec for YTKTV.
#
#   pyinstaller packaging/ytktv.spec --noconfirm
#
# Environment:
#   YTKTV_BUNDLE_SEPARATION=0   leave the vocal-separation runtime (torch) out
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
BUNDLE_SEPARATION = os.environ.get("YTKTV_BUNDLE_SEPARATION", "1") != "0"
CODESIGN_IDENTITY = os.environ.get("CODESIGN_IDENTITY") or None
ICON_DIR = Path(os.environ.get("YTKTV_ICON_DIR", ROOT / "build" / "icon"))

libmpv = bootstrap.find_libmpv()
if libmpv is None:
    sys.exit("libmpv was not found; install mpv before building (see README).")
if not os.path.isabs(libmpv):
    # On Linux the lookup returns a bare soname ("libmpv.so.2"); PyInstaller needs the file.
    import re
    import subprocess

    listing = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
    match = re.search(rf"^\s*{re.escape(libmpv)}\s.*=>\s*(\S+)$", listing, re.MULTILINE)
    if match is None:
        sys.exit(f"could not locate {libmpv} on disk")
    libmpv = match.group(1)

datas = [(str(Path(ytktv.__file__).parent / "server" / "static"), "ytktv/server/static")]
datas += collect_data_files("imageio_ffmpeg")
datas += collect_data_files("certifi")
datas += copy_metadata("ytktv")
binaries = [(libmpv, ".")]
hiddenimports = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
excludes = ["tkinter", "pytest", "IPython", "matplotlib"]

if BUNDLE_SEPARATION:
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

analysis = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
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
            # The bundled Homebrew libraries only run on the macOS they were built on or newer.
            "LSMinimumSystemVersion": platform.mac_ver()[0].split(".")[0] + ".0",
        },
    )
