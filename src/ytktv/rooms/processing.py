"""A bound room has its songs processed on the Desk, falling back to this computer.

:class:`DeskStems` looks like a StemManager to the controller. While the Desk offers
processing, the room's songs go there, most urgent first, and finished instrumentals,
melodies and AI lyrics are downloaded into this room's cache. When the Desk is off,
does not process songs, fails a song, or has not finished the song that is about to
be sung, the room does it itself, as before.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.config import SettingsStore
from ytktv.core.local import is_local
from ytktv.core.models import StemStatus
from ytktv.rooms import binding, crypto
from ytktv.separation.cache import StemCache

log = logging.getLogger(__name__)

POLL = 2.0  # seconds between asking the Desk how the songs are doing
GIVE_UP = 120.0  # the song singing now not ready on the Desk this long: do it here
FORWARDED = ("on_change", "order", "pinned", "want_pitch", "on_chunk")


def signed_headers(settings: Any, method: str, path: str) -> dict[str, str]:
    at = str(int(time.time()))
    mac = crypto.mac(settings.room_key, f"process|{settings.room_id}|{at}|{method}|{path}".encode())
    return {"X-YTKTV-Room": settings.room_id, "X-YTKTV-Time": at, "X-YTKTV-Mac": mac}


def content_type(path: str) -> str:
    """The song list is JSON; a song's audio (sent when the Desk cannot get it) is bytes."""
    return "application/json" if path == "/api/process" else "application/octet-stream"


class DeskOff(Exception):
    """The Desk cannot be reached or does not process songs."""


def http(settings: Any, method: str, path: str, body: bytes | None = None) -> bytes:
    """One signed request to the Desk."""
    url = settings.desk_url.rstrip("/") + path
    headers = signed_headers(settings, method, path)
    if body is not None:
        headers["Content-Type"] = content_type(path)
    request = urllib.request.Request(url, body, headers, method=method)
    context = binding.tls_context() if url.startswith("https") else None
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:  # noqa: S310
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 503):
            raise DeskOff(f"HTTP {exc.code}") from exc
        raise
    except OSError as exc:
        raise DeskOff(str(exc)) from exc


class DeskStems:
    """The room's stems: from the Desk when it can, else from *fallback* (a StemManager)."""

    def __init__(
        self,
        store: SettingsStore,
        cache: StemCache,
        lyrics_folder: Path,
        fallback: Any = None,
        audio: Callable[[str, Path], Path] | None = None,
        send: Callable[..., bytes] = http,
    ) -> None:
        """*audio* fetches a song's audio here, for when the Desk cannot download it."""
        self.store, self.cache, self.lyrics_folder = store, cache, lyrics_folder
        self.fallback, self._audio, self._send = fallback, audio, send
        self.hints: Callable[[str], str] = lambda _video_id: ""
        self.on_lyrics: Callable[[str, Path], None] = lambda _video_id, _path: None
        self._lock = threading.Lock()
        self._status: dict[str, StemStatus] = {}
        self._wanted: list[str] = []
        self._asked_at: dict[str, float] = {}
        self._local: set[str] = set()  # given to the fallback: done on this computer
        self._sent: set[str] = set()  # audio uploaded because the Desk could not get it
        self.desk_ok = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    # -- what the controller sets and calls --------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name in FORWARDED and self.__dict__.get("fallback") is not None:
            setattr(self.fallback, name, value)

    def on_change(self, _video_id: str, _status: StemStatus) -> None:  # replaced by the controller
        pass

    def order(self) -> list[str]:  # replaced by the controller
        return []

    @property
    def separating(self) -> bool:
        return True

    def attach_ai(self, ai: Any) -> None:
        """Separation became available here too (its runtime was just downloaded)."""
        attach = getattr(self.fallback, "attach_ai", None)
        if attach is not None:
            attach(ai)
        else:
            for name in FORWARDED:
                if name in self.__dict__:
                    setattr(ai, name, self.__dict__[name])
            self.fallback = ai

    def _use_desk(self, video_id: str) -> bool:
        settings = self.store.settings
        return (
            binding.is_bound(settings)
            and getattr(settings, "process_on_desk", True)
            and not is_local(video_id)
            and video_id not in self._local
        )

    def request(self, video_id: str) -> StemStatus:
        if self.cache.get(video_id) is not None:
            with self._lock:
                self._status[video_id] = StemStatus.READY
            return StemStatus.READY
        if not self._use_desk(video_id) or not self.desk_ok and self._asked_once():
            return self._local_request(video_id)
        with self._lock:
            if video_id not in self._wanted:
                self._wanted.append(video_id)
                self._asked_at.setdefault(video_id, time.monotonic())
            status = self._status.setdefault(video_id, StemStatus.QUEUED)
        self._wake.set()
        return status

    def _asked_once(self) -> bool:
        return "_checked" in self.__dict__

    def _local_request(self, video_id: str) -> StemStatus:
        with self._lock:
            self._local.add(video_id)
            if video_id in self._wanted:
                self._wanted.remove(video_id)
            self._status.pop(video_id, None)
        if self.fallback is None:
            return StemStatus.NONE
        return StemStatus(self.fallback.request(video_id))

    def status(self, video_id: str) -> StemStatus:
        with self._lock:
            mine = self._status.get(video_id)
        if mine is not None:
            return mine
        return self.fallback.status(video_id) if self.fallback is not None else StemStatus.NONE

    def path(self, video_id: str) -> Path | None:
        found = self.cache.get(video_id)
        if found is None and self.fallback is not None:
            return self.fallback.path(video_id)
        return found

    def pitch(self, video_id: str) -> Path | None:
        found = self.cache.pitch(video_id)
        if found is None and self.fallback is not None:
            return self.fallback.pitch(video_id)
        return found

    def vocals(self, video_id: str) -> Path | None:
        vocals = getattr(self.fallback, "vocals", None)
        return vocals(video_id) if vocals is not None else None

    def retain(self, wanted: set[str]) -> None:
        with self._lock:
            self._wanted = [v for v in self._wanted if v in wanted]
        if self.fallback is not None:
            self.fallback.retain(wanted)

    def start(self) -> None:
        if self.fallback is not None:
            self.fallback.start()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="room-desk-stems", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self.fallback is not None:
            self.fallback.stop()

    # -- talking to the Desk ------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:
                log.exception("asking the Desk about songs failed")
            self._wake.wait(POLL)
            self._wake.clear()

    def _set(self, video_id: str, status: StemStatus) -> None:
        with self._lock:
            changed = self._status.get(video_id) != status
            self._status[video_id] = status
        if changed:
            self.on_change(video_id, status)

    def poll(self) -> None:
        """Ask the Desk about the wanted songs once, and fetch what is ready."""
        with self._lock:
            wanted = list(self._wanted)
        try:
            order = [v for v in self.order() if v in wanted]
        except Exception:
            order = []
        order += [v for v in wanted if v not in order]
        if not order:
            return
        settings = self.store.settings
        songs = [{"id": v, "hint": self.hints(v)} for v in order]
        try:
            reply = json.loads(
                self._send(settings, "POST", "/api/process", json.dumps({"songs": songs}).encode())
            )
            self.desk_ok = True
        except DeskOff as exc:
            log.info("the Desk does not process songs now (%s): doing them here", exc)
            self.desk_ok = False
            object.__setattr__(self, "_checked", True)
            for video_id in order:
                self._hand_over(video_id)
            return
        object.__setattr__(self, "_checked", True)
        now = time.monotonic()
        for position, video_id in enumerate(order):
            state = reply.get("songs", {}).get(video_id, {})
            stems = str(state.get("stems", "none"))
            if stems == "ready":
                self._fetch(video_id)
                if state.get("lyrics"):  # else asked again until the Desk has written them
                    self._fetch_lyrics(video_id)
            elif stems == "failed":
                self._failed(video_id)
            else:
                self._set(video_id, StemStatus(stems) if stems in _STATES else StemStatus.QUEUED)
                late = now - self._asked_at.get(video_id, now) > GIVE_UP
                if position == 0 and late and self.fallback is not None:
                    log.info("the Desk is slow with %s: doing it here", video_id)
                    self._hand_over(video_id)

    def _hand_over(self, video_id: str) -> None:
        with self._lock:
            self._status.pop(video_id, None)
        status = self._local_request(video_id)
        self.on_change(video_id, status)

    def _failed(self, video_id: str) -> None:
        """The Desk could not do it, most likely because YouTube refused it the audio."""
        if self._audio is not None and video_id not in self._sent:
            self._sent.add(video_id)
            work = self.cache.folder(video_id) / "upload"
            try:
                source = self._audio(video_id, work)
                self._send(
                    self.store.settings, "POST", f"/api/process/{video_id}/audio",
                    Path(source).read_bytes(),
                )  # fmt: skip
                return  # the Desk separates it now
            except Exception:
                log.info("could not send %s to the Desk", video_id, exc_info=True)
            finally:
                import shutil

                shutil.rmtree(work, ignore_errors=True)
        self._hand_over(video_id)

    def _fetch(self, video_id: str) -> None:
        if self.cache.get(video_id) is not None:
            self._set(video_id, StemStatus.READY)
            return
        settings = self.store.settings
        folder = self.cache.folder(video_id)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            melody = self._send(settings, "GET", f"/api/process/{video_id}/melody")
            self.cache.pitch_target(video_id).write_bytes(melody)
        except Exception:
            log.info("no melody from the Desk for %s", video_id)
        data = self._send(settings, "GET", f"/api/process/{video_id}/instrumental")
        partial = folder / "instrumental.download"
        partial.write_bytes(data)
        partial.replace(self.cache.target(video_id))
        self._set(video_id, StemStatus.READY)
        keep = set(self.order())
        self.cache.prune(keep | {video_id})

    def _fetch_lyrics(self, video_id: str) -> None:
        target = self.lyrics_folder / f"{video_id}.json"
        if target.exists():
            self._done(video_id)
            return
        data = self._send(self.store.settings, "GET", f"/api/process/{video_id}/lyrics")
        json.loads(data)  # only keep what reads as lyrics
        self.lyrics_folder.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.on_lyrics(video_id, target)
        self._done(video_id)

    def _done(self, video_id: str) -> None:
        with self._lock:
            if video_id in self._wanted:
                self._wanted.remove(video_id)


_STATES = {s.value for s in StemStatus}
