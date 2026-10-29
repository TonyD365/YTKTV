"""Songs downloaded to keep: they play, with lyrics and the instrumental, without internet."""

from __future__ import annotations

import json
import logging
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.core.models import Song

log = logging.getLogger(__name__)

Downloader = Callable[[str, Path], Path]  # (video_id, dest_dir) -> media file
LyricsFetcher = Callable[[str], list[dict[str, Any]]]
SONG_FILE = "song.json"
LYRICS_FILE = "lyrics.json"
MEDIA_NAME = "media"  # the downloaded file is media.<ext>


class OfflineSongs:
    """One folder per song: the video, its details and its lyrics.

    Downloads run one at a time in the order they were asked for. The instrumental
    stays in the separation cache, which never evicts these songs (see ``ids``).
    """

    def __init__(
        self,
        root: Path,
        downloader: Downloader,
        lyrics: LyricsFetcher | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self._downloader = downloader
        self._lyrics = lyrics
        self.on_change = on_change
        self._cond = threading.Condition()
        self._waiting: list[Song] = []
        self._active: str | None = None
        self._failed: set[str] = set()
        self._stop = False
        self._thread: threading.Thread | None = None
        root.mkdir(parents=True, exist_ok=True)
        # A download cut short last time has a folder but no song file: try it again.
        for folder in root.iterdir():
            if folder.is_dir() and not (folder / SONG_FILE).exists():
                shutil.rmtree(folder, ignore_errors=True)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ytktv-offline", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # -- what is there --------------------------------------------------------

    def songs(self) -> list[Song]:
        """Downloaded songs, newest first."""
        found = []
        for folder in self.root.iterdir():
            song_file = folder / SONG_FILE
            if song_file.exists():
                try:
                    song = Song.from_dict(json.loads(song_file.read_text(encoding="utf-8")))
                except (OSError, ValueError, KeyError):
                    continue
                found.append((song_file.stat().st_mtime, song))
        return [song for _, song in sorted(found, key=lambda pair: pair[0], reverse=True)]

    def ids(self) -> set[str]:
        """Every song kept or on its way, so its instrumental is kept too."""
        with self._cond:
            waiting = {song.video_id for song in self._waiting}
            active = {self._active} if self._active else set()
        return waiting | active | {song.video_id for song in self.songs()}

    def path(self, video_id: str) -> Path | None:
        folder = self.root / video_id
        if not (folder / SONG_FILE).exists():
            return None
        return next(iter(sorted(folder.glob(f"{MEDIA_NAME}.*"))), None)

    def lyrics(self, video_id: str) -> list[dict[str, Any]] | None:
        try:
            return json.loads((self.root / video_id / LYRICS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def status(self, video_id: str) -> str:
        """``ready``, ``downloading``, ``waiting``, ``failed`` or ``none``."""
        with self._cond:
            state = self._state(video_id)
            return "failed" if state == "none" and video_id in self._failed else state

    def size(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    # -- changes --------------------------------------------------------------

    def add(self, song: Song) -> bool:
        """Download *song* to keep; False when it is already kept or on its way."""
        with self._cond:
            if self._state(song.video_id) in ("ready", "downloading", "waiting"):
                return False
            self._failed.discard(song.video_id)
            self._waiting.append(song)
            self._cond.notify_all()
        self._changed()
        return True

    def _state(self, video_id: str) -> str:
        """Call with the lock held."""
        if video_id == self._active:
            return "downloading"
        if any(song.video_id == video_id for song in self._waiting):
            return "waiting"
        return "ready" if self.path(video_id) else "none"

    def remove(self, video_id: str) -> None:
        with self._cond:
            self._waiting = [s for s in self._waiting if s.video_id != video_id]
            self._failed.discard(video_id)
            if video_id == self._active:
                self._active = None  # the download finishes, then sees it is unwanted
        shutil.rmtree(self.root / video_id, ignore_errors=True)
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                log.exception("offline change callback failed")

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._waiting and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                song = self._waiting.pop(0)
                self._active = song.video_id
            self._changed()
            folder = self.root / song.video_id
            try:
                self._download(song, folder)
            except Exception as exc:
                log.info("could not download %s to keep: %s", song.video_id, exc)
                shutil.rmtree(folder, ignore_errors=True)
                with self._cond:
                    self._failed.add(song.video_id)
            with self._cond:
                if self._active != song.video_id:  # removed while it downloaded
                    shutil.rmtree(folder, ignore_errors=True)
                self._active = None
            self._changed()

    def _download(self, song: Song, folder: Path) -> None:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        media = self._downloader(song.video_id, folder / "download")
        media.rename(folder / f"{MEDIA_NAME}{media.suffix}")
        shutil.rmtree(folder / "download", ignore_errors=True)
        if self._lyrics is not None:
            try:
                lines = self._lyrics(song.video_id)
                (folder / LYRICS_FILE).write_text(json.dumps(lines), encoding="utf-8")
            except Exception:
                log.info("no lyrics kept for %s", song.video_id, exc_info=True)
        # Written last: a folder with a song file is a finished download.
        (folder / SONG_FILE).write_text(json.dumps(song.to_dict()), encoding="utf-8")
