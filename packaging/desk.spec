# PyInstaller spec for YTKTV Desk, the staff terminal that manages YTKTV rooms.
#
#   pyinstaller packaging/desk.spec --noconfirm
#
# It needs none of YTKTV's player, microphones or vocal separation, so those stay out.
# Environment: YTKTV_ICON_DIR (icon.icns / icon.ico), CODESIGN_IDENTITY (macOS).

import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

import ytktv

ROOT = Path(SPECPATH).parent
SYSTEM = platform.system()
VERSION = ytktv.__version__
CODESIGN_IDENTITY = os.environ.get("CODESIGN_IDENTITY") or None
ICON_DIR = Path(os.environ.get("YTKTV_ICON_DIR", ROOT / "build" / "desk-icon"))
PACKAGE = Path(ytktv.__file__).parent

datas = [
    (str(PACKAGE / "desk" / "assets"), "ytktv/desk/assets"),
    (str(PACKAGE / "ui" / "assets"), "ytktv/ui/assets"),
    (str(PACKAGE / "server" / "static"), "ytktv/server/static"),
]
datas += collect_data_files("certifi")
datas += copy_metadata("ytktv")
hiddenimports = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
                 "zeroconf._utils.ipaddress", "zeroconf._handlers.answers"]

analysis = Analysis(
    [str(PACKAGE / "desk" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "onnxruntime", "audio_separator", "librosa", "mpv", "sounddevice",
              "tkinter", "matplotlib"],
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
    name="YTKTV Desk",
    console=False,
    icon=icon,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=str(ROOT / "packaging" / "macos" / "entitlements.plist")
    if CODESIGN_IDENTITY
    else None,
)
collected = COLLECT(exe, analysis.binaries, analysis.datas, name="YTKTV Desk")

if SYSTEM == "Darwin":
    app = BUNDLE(
        collected,
        name="YTKTV Desk.app",
        icon=icon,
        bundle_identifier="com.tonyd365.ytktv.desk",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "NSLocalNetworkUsageDescription": "YTKTV Desk talks to the YTKTV rooms on your network.",
            "NSBonjourServices": ["_ytktv-desk._tcp"],
            "LSApplicationCategoryType": "public.app-category.business",
            "LSMinimumSystemVersion": platform.mac_ver()[0].split(".")[0] + ".0",
        },
    )
