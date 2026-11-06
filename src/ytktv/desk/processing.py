"""The Desk processes songs for its rooms: download, vocal separation and AI lyrics.

One computer with a GPU does the heavy work once for every room. Each room tells the
Desk which songs it needs, in its own order; the Desk works on them most urgent first
across all rooms (every room's current song, then every room's next one, ...), keeps the
results in one cache shared by all rooms, and the rooms download what is ready. A song
sung in two rooms is processed once.

Requests and downloads are signed with the room's key, so only paired rooms can use it.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ytktv.core.models import StemStatus
from ytktv.desk.store import DeskStore
from ytktv.rooms import crypto

log = logging.getLogger(__name__)

SETTING = "process_songs"  # "1": this Desk separates songs and writes lyrics for rooms
KINDS = ("instrumental", "melody", "lyrics")
CLOCK_SLACK = 120  # seconds a signed request may be old (rooms' clocks drift a little)
UPLOAD_LIMIT = 300 * 2**20  # a song's audio, sent by a room when the Desk cannot download it


def signature(key: str, room_id: str, at: str, method: str, path: str) -> str:
    """What a room puts in X-YTKTV-Mac: proves the request is from that paired room."""
    return crypto.mac(key, f"process|{room_id}|{at}|{method}|{path}".encode())


def merged_order(orders: dict[str, list[str]]) -> list[str]:
    """Every room's first song, then every room's second, ...: nobody waits behind a list."""
    merged: list[str] = []
    for position in range(max((len(o) for o in orders.values()), default=0)):
        for room in sorted(orders):
            songs = orders[room]
            if position < len(songs) and songs[position] not in merged:
                merged.append(songs[position])
    return merged


class SongProcessor:
    """Separates and writes lyrics for the songs the rooms ask for.

    *stems* is a StemManager (its own cache), *lyrics* an AiLyrics writer or None.
    """

    def __init__(self, stems: Any, lyrics: Any = None, uploads: Path | None = None) -> None:
        self.stems, self.lyrics = stems, lyrics
        self.uploads = uploads
        self._lock = threading.Lock()
        self._orders: dict[str, list[str]] = {}
        self._hints: dict[str, str] = {}
        self._timings: dict[str, float] = {}  # video id -> when work on it began
        self.on_event: Callable[[str, str], None] = lambda _kind, _text: None
        stems.order = self.order
        stems.on_change = self._stem_changed
        stems.want_pitch = True  # rooms score with the melody

    def order(self) -> list[str]:
        with self._lock:
            return merged_order(self._orders)

    def ask(self, room_id: str, songs: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        """A room's songs, most urgent first: start what is new, say how each one is doing."""
        ids = [str(s.get("id", "")) for s in songs if s.get("id")][:20]
        with self._lock:
            self._orders[room_id] = ids
            for song in songs:
                if song.get("hint"):
                    self._hints[str(song["id"])] = str(song["hint"])[:2000]
            wanted = set(merged_order(self._orders))
        self.stems.retain(wanted)
        return {video_id: self.status(video_id, start=True) for video_id in ids}

    def forget(self, room_id: str) -> None:
        with self._lock:
            self._orders.pop(room_id, None)

    def status(self, video_id: str, start: bool = False) -> dict[str, Any]:
        state = self.stems.request(video_id) if start else self.stems.status(video_id)
        lyrics = self.lyrics is not None and self.lyrics.cached(video_id) is not None
        return {"stems": str(state), "lyrics": lyrics}

    def file(self, video_id: str, kind: str) -> Path | None:
        if kind == "instrumental":
            return self.stems.path(video_id)
        if kind == "melody":
            return self.stems.pitch(video_id)
        if kind == "lyrics" and self.lyrics is not None:
            path = self.lyrics.path(video_id)
            return path if path.exists() else None
        return None

    def _stem_changed(self, video_id: str, status: StemStatus) -> None:
        if status == StemStatus.DOWNLOADING:
            self._timings[video_id] = time.monotonic()
        elif status == StemStatus.READY:
            began = self._timings.pop(video_id, None)
            took = f" in {time.monotonic() - began:.0f} s" if began is not None else ""
            self.on_event("gpu", f"Separated {video_id}{took}")
            if self.lyrics is not None and self.lyrics.installed:
                with self._lock:
                    hint = self._hints.get(video_id, "")
                    first = video_id in merged_order(self._orders)[:2]
                self.lyrics.request(video_id, hint=hint, first=first)
        elif status == StemStatus.FAILED:
            self._timings.pop(video_id, None)
            self.on_event("error", f"Could not separate {video_id}")

    def lyrics_written(self, video_id: str, lines: list[Any]) -> None:
        self.on_event("gpu", f"Wrote lyrics for {video_id} ({len(lines)} lines)")

    def receive_audio(self, video_id: str, data: bytes) -> None:
        """A room sent the song's audio: the Desk could not download it (YouTube said no)."""
        if self.uploads is None:
            raise HTTPException(404, "uploads are not accepted here")
        self.uploads.mkdir(parents=True, exist_ok=True)
        (self.uploads / f"{video_id}.wav").write_bytes(data)
        self.stems.request(video_id)

    def queue(self) -> list[str]:
        return [v for v in self.order() if str(self.stems.status(v)) != "ready"]


class AskIn(BaseModel):
    songs: list[dict[str, str]] = []


def add_processing_routes(
    app: FastAPI, store: DeskStore, processor: Callable[[], SongProcessor | None]
) -> None:
    """Rooms ask for songs and fetch the results here. *processor* is None while off."""

    def room_of(request: Request, room: str, at: str, mac: str) -> str:
        key = store.key(room)
        if key is None:
            raise HTTPException(401, "not a room of this Desk")
        try:
            age = abs(time.time() - float(at))
        except ValueError:
            age = CLOCK_SLACK + 1
        expected = signature(key, room, at, request.method, request.url.path)
        if age > CLOCK_SLACK or not hmac.compare_digest(mac, expected):
            raise HTTPException(401, "bad signature")
        return room

    def running() -> SongProcessor:
        current = processor()
        if current is None:
            raise HTTPException(503, "this Desk does not process songs")
        return current

    @app.post("/api/process")
    def ask(
        body: AskIn,
        request: Request,
        x_ytktv_room: str = Header(""),
        x_ytktv_time: str = Header(""),
        x_ytktv_mac: str = Header(""),
    ) -> dict[str, Any]:
        room = room_of(request, x_ytktv_room, x_ytktv_time, x_ytktv_mac)
        return {"songs": running().ask(room, body.songs)}

    @app.get("/api/process/{video_id}/{kind}")
    def fetch(
        video_id: str,
        kind: str,
        request: Request,
        x_ytktv_room: str = Header(""),
        x_ytktv_time: str = Header(""),
        x_ytktv_mac: str = Header(""),
    ) -> FileResponse:
        room_of(request, x_ytktv_room, x_ytktv_time, x_ytktv_mac)
        if kind not in KINDS or not video_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(404, "no such file")
        path = running().file(video_id, kind)
        if path is None:
            raise HTTPException(404, "not ready")
        return FileResponse(path)

    @app.post("/api/process/{video_id}/audio")
    async def upload(
        video_id: str,
        request: Request,
        x_ytktv_room: str = Header(""),
        x_ytktv_time: str = Header(""),
        x_ytktv_mac: str = Header(""),
    ) -> dict[str, bool]:
        room_of(request, x_ytktv_room, x_ytktv_time, x_ytktv_mac)
        if not video_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(404, "no such song")
        data = await request.body()
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(413, "too large")
        running().receive_audio(video_id, data)
        return {"ok": True}


def make_processor(folder: Path, cache_gb: float = 20.0) -> SongProcessor | None:
    """The Desk's processor, or None while the separation runtime is not downloaded."""
    from ytktv import lyrics_ai
    from ytktv.config import data_dir
    from ytktv.separation import runtime as separation_runtime
    from ytktv.separation.cache import StemCache
    from ytktv.separation.remote import SubprocessSeparator, runtime_launcher
    from ytktv.separation.worker import StemManager
    from ytktv.youtube.search import YouTube

    runtime = separation_runtime.Runtime()
    variant = runtime.installed_variant()
    if variant is None:
        return None
    separator = SubprocessSeparator(
        runtime_launcher(runtime.python),
        "UVR-MDX-NET-Inst_HQ_3.onnx",
        data_dir() / "models",
        folder / "separator",
        directml=separation_runtime.VARIANTS[variant].directml,
        log_path=folder / "separator.log",
    )
    youtube = YouTube()
    uploads = folder / "uploads"
    from ytktv.bootstrap import ensure_ffmpeg

    ffmpeg = ensure_ffmpeg()

    def download(video_id: str, dest: Path) -> Path:
        sent = uploads / f"{video_id}.wav"
        if sent.exists():  # a room sent it
            dest.mkdir(parents=True, exist_ok=True)
            return Path(sent.replace(dest / "source.wav"))
        return youtube.download_audio(video_id, dest, ffmpeg=ffmpeg)

    stems = StemManager(StemCache(folder / "stems", int(cache_gb * 1024**3)), separator, download)
    lyrics = lyrics_ai.AiLyrics(
        lyrics_ai.runtime(),
        lambda video_id, dest: download(video_id, dest),
        folder=folder / "lyrics",
        vocals=stems.vocals,
    )
    processor = SongProcessor(stems, lyrics, uploads)
    lyrics.on_done = processor.lyrics_written
    stems.start()
    return processor


def describe(processor: SongProcessor | None) -> dict[str, Any]:
    """What the server console's GPU card shows."""
    if processor is None:
        return {"on": False}
    stems = processor.stems
    cache = getattr(stems, "cache", None)
    separator = getattr(stems, "_separator", None)
    return {
        "device": getattr(separator, "device_label", ""),
        "on": True,
        "queue": len(processor.queue()),
        "active": getattr(stems, "_active", None),
        "cache_mb": cache.size() / 2**20 if cache is not None else 0.0,
        "lyrics": bool(processor.lyrics is not None and processor.lyrics.installed),
    }


def runtimes_text() -> str:
    """Which of the two downloads this computer has, for Settings."""
    from ytktv import lyrics_ai
    from ytktv.separation import runtime as separation_runtime

    separation = separation_runtime.Runtime().installed_variant()
    lyrics = lyrics_ai.runtime().installed_variant()
    parts = [
        f"Vocal separation: {separation or 'not downloaded'}",
        f"AI lyrics: {lyrics or 'not downloaded'}",
    ]
    return " · ".join(parts)
