"""Locate (and, when missing, install) the native pieces: libmpv and ffmpeg."""

from __future__ import annotations

import ctypes.util
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.config import data_dir
from ytktv.net import urlopen

log = logging.getLogger(__name__)

MPV_WINDOWS_REPO = "shinchiro/mpv-winbuild-cmake"
_WIN_ASSET_RE = re.compile(r"^mpv-dev-x86_64-\d.*\.7z$")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def lib_dir() -> Path:
    path = data_dir() / "lib"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _libmpv_names() -> list[str]:
    system = platform.system()
    if system == "Windows":
        return ["libmpv-2.dll", "mpv-2.dll"]
    if system == "Darwin":
        return ["libmpv.2.dylib", "libmpv.dylib"]
    return ["libmpv.so.2", "libmpv.so.1", "libmpv.so"]


def _search_dirs() -> list[Path]:
    dirs: list[Path] = []
    bundled = bundle_dir()
    if bundled:
        dirs.append(bundled)
    dirs.append(lib_dir())
    if platform.system() == "Darwin":
        dirs += [Path("/opt/homebrew/lib"), Path("/usr/local/lib")]
    return dirs


def find_libmpv() -> str | None:
    for directory in _search_dirs():
        for name in _libmpv_names():
            candidate = directory / name
            if candidate.exists():
                return str(candidate)
    if platform.system() == "Windows":
        for name in _libmpv_names():
            found = ctypes.util.find_library(name)
            if found:
                return found
        return None
    return ctypes.util.find_library("mpv")


def import_mpv() -> Any:
    """Import python-mpv, pointing it at the libmpv we located.

    python-mpv only asks ``ctypes.util.find_library``, which does not look in
    Homebrew's prefix, our data dir, or a frozen bundle.
    """
    path = find_libmpv()
    if path is None:
        raise OSError("libmpv was not found")
    if platform.system() == "Windows":
        folder = str(Path(path).parent)
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(folder)
    original = ctypes.util.find_library

    def patched(name: str) -> str | None:
        return path if "mpv" in name else original(name)

    ctypes.util.find_library = patched
    try:
        import mpv

        return mpv
    finally:
        ctypes.util.find_library = original


def _linux_install_command() -> list[str] | None:
    if shutil.which("apt-get"):
        script = "apt-get install -y libmpv2 || apt-get install -y libmpv1"
    elif shutil.which("dnf"):
        script = "dnf install -y mpv-libs"
    elif shutil.which("pacman"):
        script = "pacman -S --noconfirm mpv"
    elif shutil.which("zypper"):
        script = "zypper install -y libmpv2"
    else:
        return None
    elevate = "pkexec" if shutil.which("pkexec") else "sudo"
    return [elevate, "sh", "-c", script]


def install_plan() -> str | None:
    """Human-readable description of what :func:`install_libmpv` would do."""
    system = platform.system()
    if system == "Darwin":
        return "brew install mpv" if shutil.which("brew") else None
    if system == "Windows":
        return f"Download libmpv from github.com/{MPV_WINDOWS_REPO} into {lib_dir()}"
    command = _linux_install_command()
    return " ".join(command) if command else None


def _install_windows(report: Callable[[str], None]) -> None:
    import py7zr

    api = f"https://api.github.com/repos/{MPV_WINDOWS_REPO}/releases/latest"
    request = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next((a for a in release.get("assets", []) if _WIN_ASSET_RE.match(a["name"])), None)
    if asset is None:
        raise RuntimeError("no libmpv build found in the latest mpv release")
    archive = lib_dir() / asset["name"]
    report(f"Downloading {asset['name']}...")
    with urlopen(asset["browser_download_url"], timeout=60) as response, archive.open("wb") as out:
        shutil.copyfileobj(response, out)
    report("Extracting libmpv...")
    with py7zr.SevenZipFile(archive) as bundle:
        bundle.extract(path=lib_dir(), targets=["libmpv-2.dll"])
    archive.unlink(missing_ok=True)


def install_libmpv(report: Callable[[str], None] = lambda _msg: None) -> bool:
    """Install libmpv for this platform. Returns True when it is usable afterwards."""
    system = platform.system()
    try:
        if system == "Darwin":
            brew = shutil.which("brew")
            if not brew:
                return False
            report("Running: brew install mpv (this can take a few minutes)...")
            subprocess.run([brew, "install", "mpv"], check=True)
        elif system == "Windows":
            _install_windows(report)
        else:
            command = _linux_install_command()
            if not command:
                return False
            report("Running: " + " ".join(command))
            subprocess.run(command, check=True)
    except Exception:
        log.exception("libmpv installation failed")
        return False
    return find_libmpv() is not None


def ensure_ffmpeg() -> str | None:
    """Make an ``ffmpeg`` executable reachable on PATH and return its path."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        log.warning("no ffmpeg available", exc_info=True)
        return None
    # imageio's binary has a versioned file name; tools look for plain "ffmpeg".
    bin_dir = data_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
    try:
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
            target.chmod(0o755)
    except OSError:
        log.exception("could not stage ffmpeg")
        return str(source)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return str(target)
