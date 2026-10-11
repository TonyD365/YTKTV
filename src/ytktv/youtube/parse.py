"""Pure functions that turn yt-dlp JSON into app models (no network)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ytktv.core.models import Song

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(text: str) -> str | None:
    """Return the video id if *text* is a YouTube URL or a bare id."""
    text = text.strip()
    if _ID_RE.match(text):
        return text
    match = _URL_RE.search(text)
    return match.group(1) if match else None


def _pick_thumbnail(entry: dict[str, Any], video_id: str) -> str:
    best_url = ""
    best_width = -1
    for thumb in entry.get("thumbnails") or []:
        url = thumb.get("url")
        width = thumb.get("width") or 0
        # Cards are small; anything wider than 480px is wasted bandwidth.
        if url and best_width < width <= 480:
            best_url, best_width = url, width
    return best_url or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def entry_to_song(entry: dict[str, Any] | None) -> Song | None:
    """Convert one yt-dlp entry (flat or full) to a Song; None if unusable."""
    if not entry:
        return None
    video_id = entry.get("id")
    if not isinstance(video_id, str) or not _ID_RE.match(video_id):
        return None  # channels and playlists show up in search results too
    if entry.get("live_status") in ("is_live", "is_upcoming"):
        return None
    return Song(
        video_id=video_id,
        title=str(entry.get("title") or video_id),
        channel=str(entry.get("channel") or entry.get("uploader") or ""),
        duration=int(entry.get("duration") or 0),
        thumbnail=_pick_thumbnail(entry, video_id),
    )


def parse_search_results(info: dict[str, Any] | None) -> list[Song]:
    songs: list[Song] = []
    seen: set[str] = set()
    for entry in (info or {}).get("entries") or []:
        song = entry_to_song(entry)
        if song and song.video_id not in seen:
            seen.add(song.video_id)
            songs.append(song)
    return songs


@dataclass(frozen=True, slots=True)
class MediaSource:
    """Direct stream URLs for one video, ready to hand to the player."""

    video_url: str
    audio_url: str | None = None  # None when video_url is a muxed stream
    headers: dict[str, str] = field(default_factory=dict)
    duration: float = 0.0


def parse_media_source(info: dict[str, Any]) -> MediaSource:
    """Extract stream URLs from a full yt-dlp info dict."""
    formats = info.get("requested_formats") or [info]
    video_url: str | None = None
    audio_url: str | None = None
    headers: dict[str, str] = {}
    for fmt in formats:
        url = fmt.get("url")
        if not url:
            continue
        has_video = fmt.get("vcodec") not in (None, "none")
        has_audio = fmt.get("acodec") not in (None, "none")
        if has_video and video_url is None:
            video_url = url
            headers = dict(fmt.get("http_headers") or {})
            if has_audio:
                audio_url = None
                break
        elif has_audio and audio_url is None:
            audio_url = url
    if video_url is None:
        if audio_url is None:
            raise ValueError("no playable stream found")
        video_url, audio_url = audio_url, None
    return MediaSource(
        video_url=video_url,
        audio_url=audio_url,
        headers=headers,
        duration=float(info.get("duration") or 0.0),
    )
