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


class _Cancelled(Exception):
    pass


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
        self._active: str | None = None
        self._cancelled: set[str] = set()
        self._no_pitch: set[str] = set()  # melody extraction was tried and did not work
        self._stop = False
        self._thread: threading.Thread | None = None
        # Also extract the singer's melody (needed for scoring). Songs separated without
        # it are processed again when it is switched on.
        self.want_pitch = False

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

    def pitch(self, video_id: str) -> Path | None:
        """The melody file for a song, if it has been extracted."""
        return self.cache.pitch(video_id)

    def request(self, video_id: str) -> StemStatus:
        """Ask for a stem; returns immediately with the current status."""
        if self.cache.get(video_id):
            with self._cond:
                self._status[video_id] = StemStatus.READY
                # The instrumental is there but the melody is not: redo the song quietly.
                redo = (
                    self.want_pitch
                    and self.cache.pitch(video_id) is None
                    and video_id not in self._pending
                    and video_id != self._active
                    and video_id not in self._no_pitch
                )
                if redo:
                    self._pending.append(video_id)
                    self._cond.notify_all()
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

    def retain(self, wanted: set[str]) -> None:
        """Drop work for songs nobody is waiting for any more (removed or skipped).

        Queued songs are forgotten; the one being separated right now is aborted
        so the next wanted song starts immediately. Finished stems stay cached.
        """
        dropped: list[str] = []
        abort = False
        with self._cond:
            for video_id in list(self._pending):
                if video_id not in wanted:
                    self._pending.remove(video_id)
                    self._status.pop(video_id, None)
                    dropped.append(video_id)
            if self._active is not None and self._active not in wanted:
                self._cancelled.add(self._active)
                abort = True
        if abort:
            cancel = getattr(self._separator, "cancel", None)
            if cancel is not None:
                cancel()
        for video_id in dropped:
            self._notify(video_id, StemStatus.NONE)

    def _notify(self, video_id: str, status: StemStatus) -> None:
        if self.on_change:
            try:
                self.on_change(video_id, status)
            except Exception:
                log.exception("stem change callback failed")

    def _is_cancelled(self, video_id: str) -> bool:
        with self._cond:
            return video_id in self._cancelled

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
        # A song that already has its instrumental is only here to gain a melody file;
        # it stays READY throughout and a failure must not take the instrumental away.
        refresh = self.cache.get(video_id) is not None
        with self._cond:
            self._active = video_id
            self._cancelled.discard(video_id)
        try:
            if not refresh:
                self._set(video_id, StemStatus.DOWNLOADING)
            source = self._downloader(video_id, work)
            if self._is_cancelled(video_id):
                raise _Cancelled
            if not refresh:
                self._set(video_id, StemStatus.SEPARATING)
            partial = work / "instrumental.partial.flac"
            melody = work / "melody.partial.json" if self.want_pitch else None
            self._separator.separate(source, partial, melody)
            if melody is not None and melody.exists():
                melody.replace(self.cache.pitch_target(video_id))
            elif melody is not None:
                with self._cond:
                    self._no_pitch.add(video_id)  # do not retry forever
            if not refresh:
                partial.replace(self.cache.target(video_id))
        except Exception as exc:
            cancelled = self._is_cancelled(video_id)
            with self._cond:
                self._active = None
                self._cancelled.discard(video_id)
                if cancelled and not refresh:
                    self._status.pop(video_id, None)
                if refresh and not cancelled:
                    self._no_pitch.add(video_id)
            if refresh:
                shutil.rmtree(work, ignore_errors=True)
                log.info("melody extraction for %s did not finish: %s", video_id, exc)
                return
            shutil.rmtree(self.cache.folder(video_id), ignore_errors=True)
            if cancelled:
                log.info("separation of %s cancelled: no longer in the queue", video_id)
                self._notify(video_id, StemStatus.NONE)
            else:
                log.error("separation failed for %s: %s", video_id, exc, exc_info=True)
                self._set(video_id, StemStatus.FAILED)
            return
        with self._cond:
            self._active = None
        shutil.rmtree(work, ignore_errors=True)
        keep = set(self.order()) if self.order else set()
        self.cache.prune(keep | {video_id})
        self._set(video_id, StemStatus.READY)
