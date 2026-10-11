"""Network access to YouTube through yt-dlp."""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ytktv.core.models import Song
from ytktv.net import urlopen
from ytktv.youtube.lyrics import LyricLine, parse_json3, pick_track
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
# yt-dlp player clients to try in order; None means yt-dlp's own default choice.
_CLIENT_ATTEMPTS: tuple[tuple[str, ...] | None, ...] = (None, ("android",))
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


def _video_format(max_height: int) -> str:
    # Prefer H.264 + AAC: hardware-decoded everywhere and gapless to start.
    return (
        f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
    )


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
        self._audio_cache = _TTLCache(_STREAM_TTL)  # video id -> any resolved source
        self._song_cache = _TTLCache(_STREAM_TTL)
        self._info_cache = _TTLCache(_STREAM_TTL, size=16)  # full yt-dlp info, for downloads
        self._lyrics_cache = _TTLCache(_STREAM_TTL)
        self._extract_lock = threading.Lock()

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
        """Details for one video. Also warms the stream cache, so playing it is instant."""
        try:
            self.resolve(video_id)
        except Exception:
            log.warning("lookup failed for %s", video_id, exc_info=True)
            return None
        song: Song | None = self._song_cache.get(video_id)
        return song

    def resolve(self, video_id: str, max_height: int = 1080) -> MediaSource:
        """Resolve direct stream URLs. Raises on failure.

        Extractions are serialised and cached: asking YouTube about the same
        video several times in a burst (lookup, playback, separation) makes it
        answer some of the resulting stream URLs with 403.
        """
        key = (video_id, max_height)
        cached = self._stream_cache.get(key)
        if cached is not None:
            return cached
        with self._extract_lock:
            cached = self._stream_cache.get(key)
            if cached is not None:
                return cached
            info, ydl = self._extract(video_id, max_height)
            source: MediaSource = parse_media_source(info)
            self._stream_cache.put(key, source)
            self._info_cache.put(key, ydl.sanitize_info(info))
            self._audio_cache.put(video_id, source)
            song = entry_to_song(info)
            if song is not None:
                self._song_cache.put(video_id, song)
            return source

    def _extract(self, video_id: str, max_height: int) -> tuple[dict[str, Any], Any]:
        """Extract stream info, trying yt-dlp's default clients first, then the fallbacks.

        Some videos (notably "made for kids" ones) are refused by the default
        clients with "This video is not available". The Android client still
        serves them, though only as a single 360p stream, so it is the last resort.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        first_error: Exception | None = None
        for clients in _CLIENT_ATTEMPTS:
            options: dict[str, Any] = {"format": _video_format(max_height)}
            if clients:
                options["extractor_args"] = {"youtube": {"player_client": list(clients)}}
            try:
                with _ydl(**options) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc:
                first_error = first_error or exc
                continue
            if clients:
                log.info("%s is only available through the %s client", video_id, "/".join(clients))
            return info, ydl
        assert first_error is not None
        raise first_error

    def forget_stream(self, video_id: str, max_height: int = 1080) -> None:
        self._stream_cache.drop((video_id, max_height))
        self._info_cache.drop((video_id, max_height))
        self._audio_cache.drop(video_id)

    def lyrics(
        self, video_id: str, max_height: int = 1080, allow_auto: bool = False
    ) -> list[LyricLine]:
        """Timed lyrics from the video's subtitles; an empty list when it has none."""
        key = (video_id, allow_auto)
        cached = self._lyrics_cache.get(key)
        if cached is not None:
            return list(cached)
        if self._info_cache.get((video_id, max_height)) is None:
            self.resolve(video_id, max_height)
        info = self._info_cache.get((video_id, max_height)) or {}
        url = pick_track(info, allow_auto)
        lines: list[LyricLine] = []
        if url:
            with urlopen(url, timeout=20) as response:
                lines = parse_json3(json.loads(response.read()))
        self._lyrics_cache.put(key, lines)
        return lines

    def download_media(
        self,
        video_id: str,
        dest_dir: Path,
        max_height: int = 1080,
        ffmpeg: str | None = None,
    ) -> Path:
        """Download the whole song (video and audio in one file) for stutter-free playback."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        key = (video_id, max_height)
        if self._info_cache.get(key) is None:
            self.resolve(video_id, max_height)
        info = self._info_cache.get(key)
        if info is None:
            raise RuntimeError("no stream information available")
        options: dict[str, Any] = {
            "skip_download": False,
            "format": _video_format(max_height),
            "outtmpl": str(dest_dir / "media.%(ext)s"),
            "merge_output_format": "mkv",
            "noprogress": True,
            "noplaylist": True,
        }
        if ffmpeg:
            options["ffmpeg_location"] = ffmpeg
        with _ydl(**options) as ydl:
            # Reuses the URLs from the earlier extraction instead of asking YouTube again.
            ydl.process_ie_result(copy.deepcopy(info), download=True)
        files = [f for f in dest_dir.glob("media.*") if f.suffix not in (".part", ".ytdl")]
        if not files:
            raise RuntimeError("the download produced no file")
        return max(files, key=lambda f: f.stat().st_size)

    def download_audio(
        self,
        video_id: str,
        dest_dir: Path,
        ffmpeg: str | None = None,
    ) -> Path:
        """Fetch the song's audio as ``source.wav`` for the vocal separator."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        output = dest_dir / "source.wav"
        if ffmpeg:
            try:
                self._ffmpeg_audio(video_id, output, ffmpeg)
                return output
            except Exception as exc:
                log.info("direct audio fetch failed for %s (%s); using yt-dlp", video_id, exc)
                output.unlink(missing_ok=True)
        self._ytdlp_audio(video_id, dest_dir, ffmpeg)
        if not output.exists():
            raise RuntimeError("audio download produced no file (is ffmpeg available?)")
        return output

    def _ffmpeg_audio(self, video_id: str, output: Path, ffmpeg: str) -> None:
        """Convert the already-resolved audio stream; no second YouTube extraction."""
        source: MediaSource | None = self._audio_cache.get(video_id)
        if source is None:
            source = self.resolve(video_id)
        command = [ffmpeg, "-nostdin", "-y", "-loglevel", "error"]
        agent = source.headers.get("User-Agent")
        if agent:
            command += ["-user_agent", agent]
        command += ["-i", source.audio_url or source.video_url, "-vn", "-ac", "2"]
        command += ["-ar", "44100", str(output)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(command, capture_output=True, timeout=600, creationflags=flags)
        if result.returncode != 0 or not output.exists() or output.stat().st_size < 1024:
            detail = result.stderr.decode("utf-8", "replace").strip()[-200:]
            raise RuntimeError(detail or "ffmpeg failed")

    def _ytdlp_audio(self, video_id: str, dest_dir: Path, ffmpeg: str | None) -> None:
        options: dict[str, Any] = {
            "skip_download": False,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(dest_dir / "source.%(ext)s"),
            "noplaylist": True,
            "noprogress": True,
            # The separator reads audio with libsndfile, which cannot open m4a/webm.
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        }
        if ffmpeg:
            options["ffmpeg_location"] = ffmpeg
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                with self._extract_lock, _ydl(**options) as ydl:
                    ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                return
            except Exception as exc:
                if attempt == _DOWNLOAD_ATTEMPTS - 1:
                    raise
                log.info("audio download attempt %d failed (%s); retrying", attempt + 1, exc)
                time.sleep(2.0 * (attempt + 1))
