"""Download upcoming songs ahead of time so they play from disk without buffering."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

Downloader = Callable[[str, Path], Path]  # (video_id, dest_dir) -> media file
ChangeCallback = Callable[[str], None]


class MediaPreloader:
    """Keeps the next few queued songs downloaded; everything else is deleted.

    One download runs at a time, in queue order. A song that is not ready when
    its turn comes is simply streamed instead.
    """

    def __init__(
        self, root: Path, downloader: Downloader, on_change: ChangeCallback | None = None
    ) -> None:
        self.root = root
        self._downloader = downloader
        self.on_change = on_change
        self._cond = threading.Condition()
        self._wanted: list[str] = []
        self._keep: set[str] = set()
        self._ready: dict[str, Path] = {}
        self._failed: set[str] = set()
        self._active: str | None = None
        self._stop = False
        self._thread: threading.Thread | None = None
        # Files from a previous run are useless: stream URLs and queue are gone.
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ytktv-preload", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, video_id: str) -> Path | None:
        with self._cond:
            path = self._ready.get(video_id)
        return path if path is not None and path.exists() else None

    def status(self, video_id: str) -> str:
        """``ready``, ``loading`` (queued or downloading) or ``none``."""
        with self._cond:
            if video_id in self._ready:
                return "ready"
            if video_id == self._active or video_id in self._wanted:
                return "none" if video_id in self._failed else "loading"
        return "none"

    def sync(self, upcoming: list[str], keep: set[str] | None = None) -> None:
        """Declare which songs should be on disk, most urgent first.

        *keep* are songs whose files must not be deleted even though they are
        no longer upcoming (the one playing right now).
        """
        with self._cond:
            self._wanted = list(dict.fromkeys(upcoming))
            self._keep = set(keep or ())
            needed = set(self._wanted) | self._keep
            stale = [video_id for video_id in self._ready if video_id not in needed]
            for video_id in stale:
                del self._ready[video_id]
            self._failed &= needed
            self._cond.notify_all()
        for video_id in stale:
            shutil.rmtree(self.root / video_id, ignore_errors=True)

    def _next(self) -> str | None:
        with self._cond:
            while not self._stop:
                for video_id in self._wanted:
                    if video_id not in self._ready and video_id not in self._failed:
                        self._active = video_id
                        return video_id
                self._cond.wait()
        return None

    def _run(self) -> None:
        while True:
            video_id = self._next()
            if video_id is None:
                return
            folder = self.root / video_id
            try:
                path = self._downloader(video_id, folder)
            except Exception as exc:
                log.info("preload failed for %s (%s); it will be streamed", video_id, exc)
                path = None
            with self._cond:
                self._active = None
                still_needed = video_id in self._wanted or video_id in self._keep
                if path is not None and still_needed:
                    self._ready[video_id] = path
                elif path is None:
                    self._failed.add(video_id)
            if path is None or not still_needed:
                shutil.rmtree(folder, ignore_errors=True)
            if self.on_change:
                try:
                    self.on_change(video_id)
                except Exception:
                    log.exception("preload change callback failed")
