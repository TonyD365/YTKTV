"""Network access to YouTube through yt-dlp."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.core.models import Song
from ytktv.youtube.parse import (
    MediaSource,
    entry_to_song,
    extract_video_id,
    parse_media_source,
    parse_search_results,
)

log = logging.getLogger(__name__)

# Tiles on the "Hot Songs" page; each one is just a canned search.
HOT_CATEGORIES: dict[str, str] = {
    "Karaoke Hits": "karaoke hits",
    "Mandopop": "KTV 熱門 華語",
    "Cantopop": "KTV 粵語 經典",
    "K-Pop": "kpop karaoke",
    "J-Pop": "カラオケ 人気",
    "English Pop": "pop karaoke with lyrics",
    "Rock": "rock karaoke with lyrics",
    "Classics": "oldies karaoke with lyrics",
    "Duets": "duet karaoke with lyrics",
    "Party": "party karaoke songs",
}

_SEARCH_TTL = 600.0
_DOWNLOAD_ATTEMPTS = 3
_STREAM_TTL = 3600.0  # googlevideo URLs live ~6h; stay well inside that


class _TTLCache:
    def __init__(self, ttl: float, size: int = 128) -> None:
        self._ttl = ttl
        self._size = size
        self._lock = threading.Lock()
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            if time.monotonic() - hit[0] > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return hit[1]

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)

    def drop(self, key: Any) -> None:
        with self._lock:
            self._data.pop(key, None)


def _ydl(**options: Any) -> Any:
    import yt_dlp

    base: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
    base.update(options)
    return yt_dlp.YoutubeDL(base)


class YouTube:
    """Search, lookup and stream resolution with small in-memory caches."""

    def __init__(self) -> None:
        self._search_cache = _TTLCache(_SEARCH_TTL)
        self._stream_cache = _TTLCache(_STREAM_TTL)

    def search(self, query: str, limit: int = 24) -> list[Song]:
        query = query.strip()
        if not query:
            return []
        video_id = extract_video_id(query) if "/" in query or "." in query else None
        if video_id:
            song = self.lookup(video_id)
            return [song] if song else []
        key = (query.lower(), limit)
        cached = self._search_cache.get(key)
        if cached is not None:
            return list(cached)
        with _ydl(extract_flat=True) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        songs = parse_search_results(info)
        self._search_cache.put(key, songs)
        return songs

    def hot(self, category: str) -> list[Song]:
        return self.search(HOT_CATEGORIES.get(category, category))

    def lookup(self, video_id: str) -> Song | None:
        try:
            with _ydl(extract_flat=True) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False
                )
        except Exception:
            log.warning("lookup failed for %s", video_id, exc_info=True)
            return None
        return entry_to_song(info)

    def resolve(self, video_id: str, max_height: int = 1080) -> MediaSource:
        """Resolve direct stream URLs. Raises on failure."""
        key = (video_id, max_height)
        cached = self._stream_cache.get(key)
        if cached is not None:
            return cached
        # Prefer H.264 + AAC: hardware-decoded everywhere and gapless to start.
        fmt = (
            f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
        )
        with _ydl(format=fmt) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        source = parse_media_source(info)
        self._stream_cache.put(key, source)
        return source

    def forget_stream(self, video_id: str, max_height: int = 1080) -> None:
        self._stream_cache.drop((video_id, max_height))

    def download_audio(
        self,
        video_id: str,
        dest_dir: Path,
        ffmpeg: str | None = None,
        progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Download the best audio-only stream; returns the downloaded file."""
        dest_dir.mkdir(parents=True, exist_ok=True)

        def hook(status: dict[str, Any]) -> None:
            if progress and status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
                if total:
                    progress(min(1.0, status.get("downloaded_bytes", 0) / total))

        options: dict[str, Any] = {
            "skip_download": False,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(dest_dir / "source.%(ext)s"),
            "progress_hooks": [hook],
            "noplaylist": True,
            "noprogress": True,
            # The separator reads audio with libsndfile, which cannot open m4a/webm.
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        }
        if ffmpeg:
            options["ffmpeg_location"] = ffmpeg
        # YouTube sporadically answers 403 to a download; a fresh extraction fixes it.
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                with _ydl(**options) as ydl:
                    ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                break
            except Exception as exc:
                if attempt == _DOWNLOAD_ATTEMPTS - 1:
                    raise
                log.info("audio download attempt %d failed (%s); retrying", attempt + 1, exc)
                time.sleep(2.0 * (attempt + 1))
        output = dest_dir / "source.wav"
        if not output.exists():
            raise RuntimeError("audio download produced no file (is ffmpeg available?)")
        return output
