"""Self-update from GitHub Releases.

Versions are git tags (``v1.2.3``). GitHub's ``/releases/latest`` endpoint
returns only the release flagged "Latest" (never drafts or pre-releases), so
publishing a release with that flag is what triggers an update on every
installed copy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from ytktv import GITHUB_REPO, __version__
from ytktv.bootstrap import is_frozen
from ytktv.net import urlopen

log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60
CHECKSUM_ASSET = "SHA256SUMS"
_USER_AGENT = f"YTKTV/{__version__}"

Fetch = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    tag: str
    asset_name: str
    asset_url: str
    checksum_url: str | None
    notes: str
    page_url: str


def parse_version(tag: str) -> Version | None:
    try:
        return Version(tag.strip().lstrip("vV"))
    except InvalidVersion:
        return None


def is_newer(tag: str, current: str) -> bool:
    latest, mine = parse_version(tag), parse_version(current)
    if latest is None or mine is None:
        return False
    return latest > mine


def platform_suffix(system: str | None = None, machine: str | None = None) -> str | None:
    """File-name ending of the installer built for this platform."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin":
        return "macos-arm64.pkg" if machine in ("arm64", "aarch64") else "macos-x86_64.pkg"
    if system == "Windows":
        return "windows-x64-setup.exe"
    if system == "Linux":
        return "linux-x86_64.AppImage" if machine in ("x86_64", "amd64") else None
    return None


def pick_asset(assets: list[dict[str, Any]], suffix: str | None) -> dict[str, Any] | None:
    if not suffix:
        return None
    for asset in assets:
        if str(asset.get("name", "")).endswith(suffix):
            return asset
    return None


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urlopen(request, timeout=20) as response:
        return bytes(response.read())


def check_for_update(
    current: str = __version__,
    repo: str = GITHUB_REPO,
    fetch: Fetch = _http_get,
    suffix: str | None = None,
) -> UpdateInfo | None:
    """Return the Latest release if it is newer than *current* and has an installer for us."""
    try:
        release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # the repository has no published release yet
            return None
        raise
    tag = str(release.get("tag_name") or "")
    if release.get("draft") or release.get("prerelease") or not is_newer(tag, current):
        return None
    assets = release.get("assets") or []
    asset = pick_asset(assets, suffix or platform_suffix())
    if asset is None:
        return None
    checksums = pick_asset(assets, CHECKSUM_ASSET)
    return UpdateInfo(
        version=str(parse_version(tag)),
        tag=tag,
        asset_name=str(asset["name"]),
        asset_url=str(asset["browser_download_url"]),
        checksum_url=str(checksums["browser_download_url"]) if checksums else None,
        notes=str(release.get("body") or ""),
        page_url=str(release.get("html_url") or f"https://github.com/{repo}/releases"),
    )


def expected_checksum(sums_text: str, asset_name: str) -> str | None:
    """Find *asset_name* in ``sha256sum`` output."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
            return parts[0].lower()
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    fetch: Fetch = _http_get,
    progress: Callable[[float], None] | None = None,
) -> Path:
    """Download and verify the installer. Raises if the checksum is missing or wrong."""
    if info.checksum_url is None:
        raise RuntimeError("release has no SHA256SUMS; refusing to install it")
    expected = expected_checksum(
        fetch(info.checksum_url).decode("utf-8", "replace"), info.asset_name
    )
    if expected is None:
        raise RuntimeError(f"no checksum listed for {info.asset_name}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / info.asset_name
    if target.exists() and sha256_of(target) == expected:
        return target

    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(info.asset_url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=30) as response, partial.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if sha256_of(partial) != expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError("downloaded update failed its checksum")
    partial.replace(target)
    return target


def can_self_install() -> bool:
    """Only packaged builds replace themselves; source checkouts just get told."""
    return is_frozen()


def install_update(installer: Path) -> None:
    """Hand over to the platform installer. The caller must quit the app right after."""
    system = platform.system()
    if system == "Darwin":
        # Opens the standard macOS Installer, which asks for the admin password itself.
        subprocess.Popen(["open", str(installer)])
    elif system == "Windows":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            creationflags=flags,
        )
    elif system == "Linux":
        current = os.environ.get("APPIMAGE")
        if not current:
            raise RuntimeError("not running from an AppImage")
        installer.chmod(0o755)
        shutil.move(str(installer), current)
        subprocess.Popen([current], start_new_session=True)
    else:
        raise RuntimeError(f"unsupported platform {system}")
    log.info("update handed to installer; exiting %s", sys.argv[0])
