"""Songs from video files on this computer: folders you add in Settings.

A karaoke MKV often carries two audio tracks, the original and the instrumental. For those
the instrumental is simply copied out of the file (seconds, no AI); other files go through
vocal separation like any YouTube song. An .lrc file next to a video gives its lyrics.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ytktv.core.models import Song, StemStatus
from ytktv.youtube.lyrics import LyricLine, parse_lrc

log = logging.getLogger(__name__)

PREFIX = "local-"  # video ids of local songs start with this
VIDEO_TYPES = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".mpg", ".mpeg", ".vob", ".ts", ".m4v"}
# Words in an audio track's title or language tag that mark the instrumental one.
_INSTRUMENTAL = re.compile(r"伴奏|伴唱|卡拉|karaoke|instrumental|off.?vocal|minus|music|ktv|伴",
                           re.IGNORECASE)  # fmt: skip
_STREAM = re.compile(r"Stream #0:\d+(?:\[[^\]]*\])?(?:\((?P<lang>[^)]*)\))?: Audio:")
_TITLE = re.compile(r"^\s+title\s*:\s*(?P<title>.+)$")


def is_local(video_id: str) -> bool:
    return video_id.startswith(PREFIX)


def song_id(path: Path) -> str:
    return PREFIX + hashlib.sha1(str(path).encode()).hexdigest()[:16]


def song_for(path: Path) -> Song:
    """A song card for a file: "Artist - Title.mkv" shows the artist under the title."""
    name = path.stem.replace("_", " ").strip()
    artist, title = "", name
    if " - " in name:
        artist, title = (part.strip() for part in name.split(" - ", 1))
    return Song(video_id=song_id(path), title=title or name, channel=artist or "Local song")


@dataclass
class AudioTrack:
    index: int  # among the file's audio tracks, from 0
    label: str  # its title and language, for picking the instrumental


def audio_tracks(
    ffmpeg: str, path: Path, run: Callable[..., Any] = subprocess.run
) -> list[AudioTrack]:
    """The audio tracks of *path*, from what ffmpeg prints about it."""
    try:
        out = run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                  timeout=30, check=False).stderr  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return []
    tracks: list[AudioTrack] = []
    current: AudioTrack | None = None
    for line in out.splitlines():
        stream = _STREAM.search(line)
        if stream:
            current = AudioTrack(len(tracks), stream.group("lang") or "")
            tracks.append(current)
            continue
        if "Stream #" in line:
            current = None
        title = _TITLE.match(line)
        if title and current is not None:
            current.label = f"{title.group('title').strip()} {current.label}".strip()
    return tracks


def instrumental_track(tracks: list[AudioTrack], swapped: bool = False) -> int | None:
    """Which track is the instrumental: one whose title says so, else the second one.

    *swapped* is set for a file whose tracks turned out to be the other way round.
    """
    if len(tracks) < 2:
        return None
    named = [t.index for t in tracks if _INSTRUMENTAL.search(t.label)]
    pick = named[0] if len(named) == 1 else 1
    if swapped:
        pick = 0 if pick != 0 else 1
    return pick


class LocalSongs:
    """Every video file in the chosen folders, found by a background scan."""

    def __init__(
        self,
        folders: Callable[[], list[str]],
        ffmpeg: str | None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.folders = folders
        self.ffmpeg = ffmpeg
        self.on_change = on_change
        self._lock = threading.Lock()
        self._paths: dict[str, Path] = {}
        self._songs: list[Song] = []
        self._tracks: dict[str, list[AudioTrack]] = {}
        self.swapped: set[str] = set()  # songs whose instrumental is the other track
        self.scanning = False

    # -- the library ---------------------------------------------------------------

    def scan(self) -> int:
        """Look through the folders again; returns how many songs were found."""
        self.scanning = True
        found: dict[str, Path] = {}
        for folder in self.folders():
            root = Path(folder).expanduser()
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() in VIDEO_TYPES and path.is_file():
                    found[song_id(path)] = path
        songs = sorted((song_for(p) for p in found.values()), key=lambda s: s.title.casefold())
        with self._lock:
            self._paths, self._songs = found, songs
        self.scanning = False
        if self.on_change:
            self.on_change()
        return len(songs)

    def scan_soon(self) -> None:
        threading.Thread(target=self.scan, name="ytktv-local-scan", daemon=True).start()

    def songs(self, query: str = "") -> list[Song]:
        with self._lock:
            songs = list(self._songs)
        words = query.casefold().split()
        if not words:
            return songs
        return [s for s in songs if all(w in f"{s.title} {s.channel}".casefold() for w in words)]

    def path(self, video_id: str) -> Path | None:
        with self._lock:
            return self._paths.get(video_id)

    def song(self, video_id: str) -> Song | None:
        with self._lock:
            return next((s for s in self._songs if s.video_id == video_id), None)

    # -- playing one -----------------------------------------------------------------

    def tracks(self, video_id: str) -> list[AudioTrack]:
        path = self.path(video_id)
        if path is None or self.ffmpeg is None:
            return []
        with self._lock:
            known = self._tracks.get(video_id)
        if known is None:
            known = audio_tracks(self.ffmpeg, path)
            with self._lock:
                self._tracks[video_id] = known
        return known

    def has_instrumental_track(self, video_id: str) -> bool:
        return instrumental_track(self.tracks(video_id)) is not None

    def extract_track(self, video_id: str, out: Path) -> None:
        """Copy the instrumental track out of a two-track file, as FLAC."""
        path = self.path(video_id)
        index = instrumental_track(self.tracks(video_id), video_id in self.swapped)
        if path is None or index is None or self.ffmpeg is None:
            raise FileNotFoundError(f"no instrumental track in {video_id}")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
             "-map", f"0:a:{index}", "-vn", "-c:a", "flac", str(out)],
            check=True, capture_output=True, timeout=600,
        )  # fmt: skip

    def extract_audio(self, video_id: str, dest: Path) -> Path:
        """The sound of a one-track file, for vocal separation."""
        path = self.path(video_id)
        if path is None or self.ffmpeg is None:
            raise FileNotFoundError(video_id)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "audio.wav"
        subprocess.run(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
             "-map", "0:a:0", "-vn", str(out)],
            check=True, capture_output=True, timeout=600,
        )  # fmt: skip
        return out

    def lyrics(self, video_id: str) -> list[LyricLine]:
        """Lyrics from an .lrc file with the same name as the video, if there is one."""
        path = self.path(video_id)
        if path is None:
            return []
        for candidate in (path.with_suffix(".lrc"), path.with_suffix(".LRC")):
            if candidate.exists():
                try:
                    return parse_lrc(candidate.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    return []
        return []


class StemRouter:
    """The instrumentals of every song, from two places.

    Local files with their own instrumental track get it copied out by *tracks*; every
    other song goes to *ai*, the vocal separation (None when it is not installed).
    Looks like a StemManager to the controller.
    """

    def __init__(self, local: LocalSongs, tracks: Any, ai: Any | None) -> None:
        self.local, self.tracks, self.ai = local, tracks, ai

    def _for(self, video_id: str) -> Any | None:
        if is_local(video_id) and self.local.has_instrumental_track(video_id):
            return self.tracks
        return self.ai

    @property
    def separating(self) -> bool:
        return self.ai is not None

    def _both(self) -> list[Any]:
        return [m for m in (self.tracks, self.ai) if m is not None]

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("on_change", "order", "pinned", "want_pitch"):
            for manager in self._both():
                setattr(manager, name, value)
        object.__setattr__(self, name, value)

    def attach_ai(self, ai: Any) -> None:
        """Vocal separation became available (its runtime was just downloaded)."""
        for name in ("on_change", "order", "pinned", "want_pitch"):
            if name in self.__dict__:
                setattr(ai, name, self.__dict__[name])
        previous, self.ai = self.ai, ai
        if previous is not None:
            previous.stop()

    def request(self, video_id: str) -> Any:
        manager = self._for(video_id)
        return manager.request(video_id) if manager else StemStatus.NONE

    def status(self, video_id: str) -> Any:
        manager = self._for(video_id)
        return manager.status(video_id) if manager else StemStatus.NONE

    def path(self, video_id: str) -> Path | None:
        manager = self._for(video_id)
        return manager.path(video_id) if manager else None

    def pitch(self, video_id: str) -> Path | None:
        manager = self._for(video_id)
        return manager.pitch(video_id) if manager else None

    def retain(self, wanted: set[str]) -> None:
        for manager in self._both():
            manager.retain(wanted)

    def start(self) -> None:
        for manager in self._both():
            manager.start()

    def stop(self) -> None:
        for manager in self._both():
            manager.stop()


class CopySeparator:
    """The "separator" for files that bring their own instrumental: it is already there."""

    def separate(self, source: Path, output: Path, melody: Path | None = None) -> None:
        import shutil

        shutil.copyfile(source, output)


def make_track_stems(local: LocalSongs, cache_root: Path, limit_bytes: int) -> Any:
    """A StemManager that copies instrumental tracks out of local files."""
    from ytktv.separation.cache import StemCache
    from ytktv.separation.worker import StemManager

    def take_track(video_id: str, work: Path) -> Path:
        out = work / "track.flac"
        local.extract_track(video_id, out)
        return out

    manager = StemManager(StemCache(cache_root, limit_bytes), CopySeparator(), take_track)
    manager.start()
    return manager
