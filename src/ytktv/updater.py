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
import re
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from ytktv import GITHUB_REPO, __version__, children, patching
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
    size: int = 0  # bytes of the installer
    patch_name: str | None = None  # only the changed files, for an update within a major
    patch_url: str | None = None
    patch_size: int = 0
    current: str = ""  # the version the patch applies to
    app: str = "YTKTV"


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


def platform_suffixes(system: str | None = None, machine: str | None = None) -> list[str]:
    """File-name endings of installers that run on this platform, best first."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return ["macos-universal.pkg", f"macos-{arch}.pkg"]
    if system == "Windows":
        if machine in ("arm64", "aarch64"):
            # The x64 build still runs on Windows on ARM, emulated, if there is no ARM one.
            return ["windows-arm64-setup.exe", "windows-x64-setup.exe"]
        return ["windows-x64-setup.exe"]
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return ["linux-x86_64.AppImage"]
    if system == "Linux" and machine in ("aarch64", "arm64"):
        return ["linux-aarch64.AppImage"]
    return []


def pick_asset(
    assets: list[dict[str, Any]], suffixes: list[str], app: str | None = "YTKTV"
) -> dict[str, Any] | None:
    """The first asset matching the earliest suffix in *suffixes*.

    *app* is the start of the file name ("YTKTV" or "YTKTV-Desk") followed by the
    version: YTKTV and YTKTV Desk installers end the same way, and a room must never
    install the desk (or the other way round). None matches any name.
    """
    prefix = re.compile(rf"^{re.escape(app)}-\d") if app else None
    for suffix in suffixes:
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.endswith(suffix) and (prefix is None or prefix.match(name)):
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
    suffixes: list[str] | None = None,
    app: str = "YTKTV",
    tag_for_patch: str | None = None,
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
    asset = pick_asset(assets, platform_suffixes() if suffixes is None else suffixes, app)
    if asset is None:
        return None
    checksums = pick_asset(assets, [CHECKSUM_ASSET], None)
    if checksums is None:
        # Installers are attached a while after the release is published; until the
        # checksums are there too, treat the release as not ready.
        return None
    new, mine = parse_version(tag), parse_version(current)
    patch = None
    if tag_for_patch is None:
        tag_for_patch = patching.patch_tag(platform.system(), platform.machine())
    if new is not None and mine is not None and new.major == mine.major and tag_for_patch:
        wanted = patching.patch_name(app, str(mine), str(new), tag_for_patch)
        patch = next((a for a in assets if a.get("name") == wanted), None)
    return UpdateInfo(
        version=str(new),
        tag=tag,
        asset_name=str(asset["name"]),
        asset_url=str(asset["browser_download_url"]),
        checksum_url=str(checksums["browser_download_url"]),
        notes=str(release.get("body") or ""),
        page_url=str(release.get("html_url") or f"https://github.com/{repo}/releases"),
        size=int(asset.get("size") or 0),
        patch_name=str(patch["name"]) if patch else None,
        patch_url=str(patch["browser_download_url"]) if patch else None,
        patch_size=int(patch.get("size") or 0) if patch else 0,
        current=str(mine),
        app=app,
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


def failed_marker(dest_dir: Path, version: str) -> Path:
    """Left by a patch that did not go in: that version then comes as the installer."""
    return dest_dir / f"{patching.FAILED_MARKER}-{version}"


def can_patch() -> bool:
    """Packaged macOS and Windows builds can take a patch; AppImages cannot."""
    return is_frozen() and patching.patch_tag(platform.system(), platform.machine()) is not None


def patch_usable(info: UpdateInfo, dest_dir: Path) -> bool:
    return (
        info.patch_url is not None
        and can_patch()
        and not failed_marker(dest_dir, info.version).exists()
    )


def download_size(info: UpdateInfo, dest_dir: Path) -> int:
    """What the update will download, in bytes (0 when the release does not say)."""
    return info.patch_size if patch_usable(info, dest_dir) else info.size


def size_label(info: UpdateInfo, dest_dir: Path) -> str:
    """ " (12 MB)" for a patch, " (full install, 480 MB)" for the installer."""
    size = download_size(info, dest_dir)
    if not size:
        return ""
    mb = max(1, round(size / 2**20))
    return f" ({mb} MB)" if patch_usable(info, dest_dir) else f" (full install, {mb} MB)"


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    fetch: Fetch = _http_get,
    progress: Callable[[float], None] | None = None,
    root: Path | None = None,
) -> Path:
    """Download and verify the update: a staged patch folder when one fits, else the installer.

    Raises if the checksum is missing or wrong. *root* is the installed app (for tests).
    """
    if info.checksum_url is None:
        raise RuntimeError("release has no SHA256SUMS; refusing to install it")
    sums = fetch(info.checksum_url).decode("utf-8", "replace")
    if info.patch_name and (root is not None or patch_usable(info, dest_dir)):
        try:
            return _download_patch(info, dest_dir, sums, progress, root)
        except Exception as exc:
            log.info(
                "the patch for %s cannot be used (%s): getting the installer", info.version, exc
            )
    return _download(info.asset_name, info.asset_url, dest_dir, sums, progress)


def _download_patch(
    info: UpdateInfo,
    dest_dir: Path,
    sums: str,
    progress: Callable[[float], None] | None,
    root: Path | None,
) -> Path:
    assert info.patch_name and info.patch_url
    archive = _download(info.patch_name, info.patch_url, dest_dir, sums, progress)
    staged = dest_dir / f"patch-{info.version}"
    manifest = patching.stage(archive, staged)
    archive.unlink(missing_ok=True)
    root = root or patching.app_root()
    if manifest.get("from") != info.current or manifest.get("to") != info.version:
        raise RuntimeError("the patch is for other versions")
    if not patching.check_base(manifest, root):
        raise RuntimeError("the installed files are not the ones the patch expects")
    if platform.system() == "Windows" and patching.needs_admin(manifest, root):
        raise RuntimeError("the install folder is not writable")
    return staged


def _download(
    name: str,
    url: str,
    dest_dir: Path,
    sums: str,
    progress: Callable[[float], None] | None,
) -> Path:
    expected = expected_checksum(sums, name)
    if expected is None:
        raise RuntimeError(f"no checksum listed for {name}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    if target.exists() and sha256_of(target) == expected:
        return target

    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
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


# An installer (YTKTV-4.0.2-...), a staged patch (patch-4.0.2) or a failed patch's marker.
_DOWNLOAD_NAME = re.compile(r"^(?:YTKTV-|patch-|patch-failed-)(\d[^-]*?)(?:-|$)")


def clean_old_downloads(dest_dir: Path, current: str = __version__) -> int:
    """Delete downloaded installers that are of no more use. Returns the bytes freed.

    An installer is kept only while it is newer than the running version, that is,
    downloaded and waiting to be installed. Every update used to leave its installer
    behind, half a gigabyte at a time.
    """
    freed = 0
    try:
        running = Version(current)
        files = list(dest_dir.iterdir())
    except (InvalidVersion, OSError):
        return 0
    for path in files:
        if path.is_dir() and not path.name.startswith("patch-"):
            continue  # only staged patches are ours
        match = _DOWNLOAD_NAME.match(path.name)
        try:
            waiting = match is not None and Version(match.group(1)) > running
        except InvalidVersion:
            waiting = False
        if waiting:
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
                continue
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            log.debug("could not delete %s", path, exc_info=True)
    if freed:
        log.info("deleted old update downloads: %d MB", freed // 1048576)
    return freed


def install_update(installer: Path) -> None:
    """Hand over to the platform installer. The caller must quit the app right after.

    *installer* may be a staged patch folder: then a script swaps the files once we quit.
    """
    system = platform.system()
    if installer.is_dir():
        apply_patch(installer, system)
        return
    if system == "Darwin":
        # Opens the standard macOS Installer, which asks for the admin password itself.
        children.launch_to_outlive(["open", str(installer)])
    elif system == "Windows":
        children.launch_to_outlive(
            [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
        )
    elif system == "Linux":
        current = os.environ.get("APPIMAGE")
        if not current:
            raise RuntimeError("not running from an AppImage")
        installer.chmod(0o755)
        shutil.move(str(installer), current)
        children.launch_to_outlive([current])
    else:
        raise RuntimeError(f"unsupported platform {system}")
    log.info("update handed to installer; exiting %s", sys.argv[0])


def apply_patch(staged: Path, system: str, root: Path | None = None) -> None:
    """Start the script that puts the staged patch in once this app has quit."""
    manifest = json.loads((staged / patching.MANIFEST).read_text())
    root = root or patching.app_root()
    marker = failed_marker(staged.parent, str(manifest["to"]))
    if system == "Windows":
        script = staged / "apply.ps1"
        script.write_text(
            patching.powershell_script(manifest, staged, root, marker, os.getpid()),
            encoding="utf-8-sig",
        )
        children.launch_to_outlive(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(script)]
        )  # fmt: skip
    elif system == "Darwin":
        apply = staged / "apply.sh"
        apply.write_text(patching.shell_script(manifest, staged, root, marker))
        launcher = staged / "launch.sh"
        admin = patching.needs_admin(manifest, root)
        launcher.write_text(patching.macos_launcher(apply, root, marker, os.getpid(), admin))
        children.launch_to_outlive(["/bin/sh", str(launcher)])
    else:
        raise RuntimeError(f"patches are not used on {system}")
    log.info("update %s handed to the patch script", manifest["to"])
