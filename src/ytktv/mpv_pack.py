"""The mpv libraries as a separate download for packaged builds.

mpv and the FFmpeg it uses are licensed under the GPL, which YTKTV's own license is
not compatible with, so the installers do not contain them. A packaged YTKTV fetches
them once, on first start, as a zip published next to the installers of each release.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import os
import platform
import shutil
import struct
import tempfile
import time
import wave
import zipfile
from collections.abc import Callable
from pathlib import Path

from ytktv import GITHUB_REPO, __version__
from ytktv.config import data_dir

log = logging.getLogger(__name__)

REPO = GITHUB_REPO
CHECKSUM_ASSET = "SHA256SUMS"
MARKER = "INSTALLED"

Fetch = Callable[[str], bytes]
Report = Callable[[str], None]


def platform_name(system: str | None = None, machine: str | None = None) -> str | None:
    """The name of this platform's pack, or None when there is no pack for it."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x86_64"
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "windows-x64"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    return None


def asset_name(name: str | None = None) -> str | None:
    name = name or platform_name()
    return f"YTKTV-mpv-{name}.zip" if name else None


def pack_dir() -> Path:
    """Where the downloaded libraries live. Not created until something is installed."""
    override = os.environ.get("YTKTV_MPV_ROOT")  # the build's self-test uses a scratch folder
    return Path(override) if override else data_dir() / "mpv"


def installed() -> bool:
    return (pack_dir() / MARKER).exists()


def download_urls(asset: str, version: str = __version__) -> list[tuple[str, str]]:
    """(pack URL, checksum URL) pairs to try: this version's release, then the latest."""
    base = f"https://github.com/{REPO}/releases"
    urls = []
    if "+" not in version and ".dev" not in version:  # a real release has its own pack
        urls.append(f"{base}/download/v{version}")
    urls.append(f"{base}/latest/download")
    return [(f"{folder}/{asset}", f"{folder}/{CHECKSUM_ASSET}") for folder in urls]


def _default_fetch(url: str) -> bytes:
    from ytktv.net import urlopen

    with urlopen(url, timeout=120) as response:
        data: bytes = response.read()
    return data


def unpack(archive: Path, destination: Path | None = None) -> Path:
    """Replace the installed libraries with the contents of the zip at *archive*."""
    destination = destination or pack_dir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="mpv-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                # The pack is a flat folder of libraries; anything else is not ours.
                if member.is_dir() or "/" in member.filename or "\\" in member.filename:
                    raise RuntimeError(f"unexpected entry in the mpv pack: {member.filename}")
            bundle.extractall(staging)
        (staging / MARKER).write_text(__version__ + "\n", encoding="utf-8")
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def install(report: Report = lambda _message: None, fetch: Fetch | None = None) -> Path:
    """Download this platform's pack, check it against the release's checksums, unpack it."""
    asset = asset_name()
    if asset is None:
        raise RuntimeError("there is no mpv download for this platform")
    from ytktv.updater import expected_checksum  # imports bootstrap, which imports this

    fetch = fetch or _default_fetch
    errors: list[str] = []
    for pack_url, checksum_url in download_urls(asset):
        try:
            expected = expected_checksum(fetch(checksum_url).decode("utf-8", "replace"), asset)
            if expected is None:
                raise RuntimeError(f"no checksum listed for {asset}")
            report(f"Downloading {asset}...")
            data = fetch(pack_url)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("the download does not match its checksum")
        except Exception as exc:
            log.info("mpv pack not taken from %s: %s", pack_url, exc)
            errors.append(f"{pack_url}: {exc}")
            continue
        report("Unpacking mpv...")
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / asset
            archive.write_bytes(data)
            return unpack(archive)
    raise RuntimeError("could not download mpv: " + "; ".join(errors))


def _tone(path: Path, frequency: float, seconds: float = 1.0, rate: int = 48000) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        noise = 1
        frames = bytearray()
        for i in range(int(seconds * rate)):
            # A little noise on top: a perfectly repeating tone can be mistaken for
            # a compressed stream when the file is probed.
            noise = (noise * 1103515245 + 12345) & 0x7FFFFFFF
            value = int(12000 * math.sin(2 * math.pi * frequency * i / rate)) + (noise >> 24) - 64
            frames += struct.pack("<hh", value, value)
        out.writeframes(bytes(frames))


def self_test(report: Report = print) -> int:
    """Check that the mpv libraries can do everything YTKTV asks of them. 0 = fine.

    With YTKTV_MPV_PACK set to a zip, that pack is unpacked first (into YTKTV_MPV_ROOT
    when given), which is how a build checks the pack it has just made. Nothing is
    shown or played: video goes nowhere and the sound is written to a file.
    """
    from ytktv import bootstrap
    from ytktv.player import mpv_player

    try:
        local = os.environ.get("YTKTV_MPV_PACK")
        if local:
            report(f"Unpacking {local} into {pack_dir()}")
            unpack(Path(local))
        elif bootstrap.find_libmpv() is None:
            install(report)
        library = bootstrap.find_libmpv()
        report(f"libmpv: {library}")
        if local and (library is None or Path(library).parent != pack_dir()):
            raise RuntimeError("libmpv was not taken from the pack that was just unpacked")
        mpv = bootstrap.import_mpv()
        with tempfile.TemporaryDirectory() as folder:
            original, backing, result = (Path(folder) / n for n in ("a.wav", "b.wav", "out.wav"))
            _tone(original, 440.0)
            _tone(backing, 677.0)
            problems: list[str] = []

            def note(level: str, component: str, message: str) -> None:
                if level in ("error", "fatal"):
                    problems.append(f"{component}: {message.strip()[:200]}")

            player = mpv.MPV(
                vo="null",
                ao="pcm",
                ao_pcm_file=str(result),
                audio_display="no",
                idle="yes",
                ytdl=False,
                log_handler=note,
                loglevel="warn",
            )
            try:
                report(f"mpv {player.mpv_version}")
                # The same chain as during a song: both tracks merged and mixed, a
                # channel mode, the level meter, and the key change without rubberband.
                player["audio-files"] = [str(backing)]
                player["lavfi-complex"] = mpv_player._DUAL_GRAPH.format(original=1, instrumental=2)
                player.af = ",".join(
                    [
                        mpv_player._MIX_FILTER.format(original=0.5, instrumental=0.5),
                        mpv_player._PAN_FILTERS[mpv_player.VocalMode.LEFT],
                        "lavfi=[asetrate=48000*1.059463,aresample=48000,atempo=0.943874]",
                        mpv_player._LEVEL_FILTER,
                    ]
                )
                player.loadfile(str(original))
                deadline = time.monotonic() + 30
                levels, started = None, False
                while time.monotonic() < deadline:
                    if not player.idle_active:
                        started = True
                    elif started:
                        break  # played to the end
                    if levels is None:
                        # The meter has nothing to report until sound has gone through it.
                        with contextlib.suppress(Exception):
                            levels = player._get_property("af-metadata/" + mpv_player._LEVEL_LABEL)
                    time.sleep(0.01)
            finally:
                player.terminate()
            size = result.stat().st_size if result.exists() else 0
            if problems:
                raise RuntimeError("mpv reported: " + " | ".join(problems[:4]))
            if size < 48000:  # a second of stereo sound is about 190 kB
                raise RuntimeError(f"no sound came out ({size} bytes written)")
            if not levels:
                raise RuntimeError("the level meter filter gave no readings")
            report(f"Played two tracks through the full filter chain ({size // 1024} kB written).")
    except Exception as exc:
        log.exception("mpv self-test failed")
        report(f"FAILED: {exc}")
        return 1
    report("mpv self-test passed")
    return 0
