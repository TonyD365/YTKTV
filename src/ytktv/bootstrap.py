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


def _windows_mpv_asset() -> re.Pattern[str]:
    """The libmpv build for this PC: x86_64, or aarch64 on Windows on ARM."""
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    return re.compile(rf"^mpv-dev-{arch}-\d.*\.7z$")


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
    legacy = data_dir() / "mpv"
    if (legacy / "INSTALLED").exists():
        dirs.append(legacy)  # downloaded by YTKTV 1.4 and 1.5, which shipped mpv separately
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


def homebrew() -> str | None:
    """Path of Homebrew's ``brew``, if installed.

    An app opened from the Finder has a short PATH without Homebrew's folders, so
    the usual places are checked as well.
    """
    for candidate in (shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def install_plan() -> str | None:
    """Human-readable description of what :func:`install_libmpv` would do."""
    system = platform.system()
    if system == "Darwin":
        return "brew install mpv" if homebrew() else None
    if system == "Windows":
        return f"Download libmpv from github.com/{MPV_WINDOWS_REPO} into {lib_dir()}"
    command = _linux_install_command()
    return " ".join(command) if command else None


def _extract_7z(archive: Path, member: str, dest: Path) -> None:
    """Extract one file from a .7z with the system's tools.

    mpv's archives use the BCJ2 filter, which pure-Python extractors cannot
    read. Windows 10+ ships bsdtar as ``tar.exe``, which can; 7-Zip also works.
    """
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    candidates = [
        [str(Path(system_root) / "System32" / "tar.exe"), "-xf", str(archive), "-C", str(dest)],
        ["7z", "e", "-y", f"-o{dest}", str(archive)],
        ["tar", "-xf", str(archive), "-C", str(dest)],
    ]
    errors: list[str] = []
    for command in candidates:
        if shutil.which(command[0]) is None:
            continue
        result = subprocess.run([*command, member], capture_output=True, text=True)
        if result.returncode == 0 and (dest / member).exists():
            return
        errors.append(f"{command[0]}: {(result.stderr or result.stdout).strip()[-200:]}")
        (dest / member).unlink(missing_ok=True)
    raise RuntimeError("could not extract libmpv: " + ("; ".join(errors) or "no tar or 7z found"))


def install_windows_libmpv(report: Callable[[str], None]) -> None:
    api = f"https://api.github.com/repos/{MPV_WINDOWS_REPO}/releases/latest"
    request = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    pattern = _windows_mpv_asset()
    asset = next((a for a in release.get("assets", []) if pattern.match(a["name"])), None)
    if asset is None:
        raise RuntimeError("no libmpv build found in the latest mpv release")
    target = lib_dir() / "libmpv-2.dll"
    archive = lib_dir() / asset["name"]
    try:
        report(f"Downloading {asset['name']}...")
        with (
            urlopen(asset["browser_download_url"], timeout=60) as response,
            archive.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
        report("Extracting libmpv...")
        target.unlink(missing_ok=True)
        _extract_7z(archive, target.name, lib_dir())
        if target.stat().st_size < 1_000_000:
            raise RuntimeError("extracted libmpv is truncated")
        # Which build this is, for anyone who needs its source.
        (lib_dir() / "libmpv-source.txt").write_text(
            asset["browser_download_url"] + "\n", encoding="utf-8"
        )
    except Exception:
        # Never leave a partial DLL behind: it would be found and fail to load later.
        target.unlink(missing_ok=True)
        raise
    finally:
        archive.unlink(missing_ok=True)


def install_libmpv(report: Callable[[str], None] = lambda _msg: None) -> bool:
    """Install libmpv for this platform. Returns True when it is usable afterwards."""
    system = platform.system()
    try:
        if system == "Darwin":
            brew = homebrew()
            if not brew:
                return False
            report("Running: brew install mpv (this can take a few minutes)...")
            # Homebrew needs its own folders on PATH, which an app from the Finder lacks.
            env = dict(os.environ)
            env["PATH"] = f"{Path(brew).parent}:{env.get('PATH', '/usr/bin:/bin')}"
            subprocess.run([brew, "install", "mpv"], check=True, env=env)
        elif system == "Windows":
            install_windows_libmpv(report)
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
