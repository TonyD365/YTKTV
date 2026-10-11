"""Background worker that prepares instrumental tracks ahead of playback."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from ytktv.core.models import StemStatus
from ytktv.separation.base import Separator
from ytktv.separation.cache import StemCache

log = logging.getLogger(__name__)

Downloader = Callable[[str, Path], Path]  # (video_id, dest_dir) -> audio file
ChangeCallback = Callable[[str, StemStatus], None]
OrderProvider = Callable[[], list[str]]  # video ids, most urgent first


class StemManager:
    """Downloads audio and separates it, one song at a time, most urgent first."""

    def __init__(
        self,
        cache: StemCache,
        separator: Separator,
        downloader: Downloader,
        on_change: ChangeCallback | None = None,
        order: OrderProvider | None = None,
    ) -> None:
        self.cache = cache
        self._separator = separator
        self._downloader = downloader
        self.on_change = on_change
        self.order = order
        self._cond = threading.Condition()
        self._status: dict[str, StemStatus] = {}
        self._pending: list[str] = []
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ytktv-stems", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def status(self, video_id: str) -> StemStatus:
        with self._cond:
            known = self._status.get(video_id)
        if known is not None:
            return known
        return StemStatus.READY if self.cache.get(video_id) else StemStatus.NONE

    def path(self, video_id: str) -> Path | None:
        return self.cache.get(video_id)

    def request(self, video_id: str) -> StemStatus:
        """Ask for a stem; returns immediately with the current status."""
        if self.cache.get(video_id):
            with self._cond:
                self._status[video_id] = StemStatus.READY
            return StemStatus.READY
        with self._cond:
            current = self._status.get(video_id)
            if current in (StemStatus.QUEUED, StemStatus.DOWNLOADING, StemStatus.SEPARATING):
                return current
            self._status[video_id] = StemStatus.QUEUED
            self._pending.append(video_id)
            self._cond.notify_all()
        self._notify(video_id, StemStatus.QUEUED)
        return StemStatus.QUEUED

    def _notify(self, video_id: str, status: StemStatus) -> None:
        if self.on_change:
            try:
                self.on_change(video_id, status)
            except Exception:
                log.exception("stem change callback failed")

    def _set(self, video_id: str, status: StemStatus) -> None:
        with self._cond:
            self._status[video_id] = status
        self._notify(video_id, status)

    def _take(self) -> str | None:
        with self._cond:
            while not self._pending and not self._stop:
                self._cond.wait()
            if self._stop:
                return None
            pending = list(self._pending)
        chosen = pending[0]
        if self.order:
            try:
                wanted = next((v for v in self.order() if v in pending), None)
                chosen = wanted or chosen
            except Exception:
                log.exception("order provider failed")
        with self._cond:
            self._pending.remove(chosen)
        return chosen

    def _run(self) -> None:
        while True:
            video_id = self._take()
            if video_id is None:
                return
            self.process(video_id)

    def process(self, video_id: str) -> None:
        """Download + separate one song synchronously (the worker's unit of work)."""
        work = self.cache.folder(video_id) / "work"
        try:
            self._set(video_id, StemStatus.DOWNLOADING)
            source = self._downloader(video_id, work)
            self._set(video_id, StemStatus.SEPARATING)
            partial = work / "instrumental.partial.flac"
            self._separator.separate(source, partial)
            partial.replace(self.cache.target(video_id))
        except Exception:
            log.exception("separation failed for %s", video_id)
            shutil.rmtree(self.cache.folder(video_id), ignore_errors=True)
            self._set(video_id, StemStatus.FAILED)
            return
        shutil.rmtree(work, ignore_errors=True)
        keep = set(self.order()) if self.order else set()
        self.cache.prune(keep | {video_id})
        self._set(video_id, StemStatus.READY)
