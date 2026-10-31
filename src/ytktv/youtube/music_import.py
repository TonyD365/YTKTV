"""Playlists from Spotify and Apple Music, sung from YouTube.

A public playlist's own web page lists its songs (no sign-in, no API key). Each song is
then looked up on YouTube, preferring a karaoke version. A plain list of songs, one per
line, works the same way, for private playlists.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ytktv.core.models import Song
from ytktv.net import urlopen

LIMIT = 100  # songs taken from one playlist
_SPOTIFY = re.compile(r"open\.spotify\.com/(?:[a-z-]+/)?(?:embed/)?playlist/([A-Za-z0-9]+)")
_APPLE = re.compile(r"music\.apple\.com/[a-z]{2}/playlist/")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_APPLE_DATA = re.compile(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', re.S)
_APPLE_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)

Track = tuple[str, str]  # (title, artist)


def is_music_link(url: str) -> bool:
    return bool(_SPOTIFY.search(url) or _APPLE.search(url))


def spotify_tracks(html: str) -> tuple[str, list[Track]]:
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("could not read that Spotify page")
    entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    tracks = [(str(t.get("title", "")), str(t.get("subtitle", ""))) for t in entity["trackList"]]
    return str(entity.get("name") or entity.get("title") or "Spotify playlist"), tracks


def apple_tracks(html: str) -> tuple[str, list[Track]]:
    name = "Apple Music playlist"
    for match in _APPLE_LD.finditer(html):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "MusicPlaylist":
            name = str(data.get("name") or name)
    data_match = _APPLE_DATA.search(html)
    if not data_match:
        raise ValueError("could not read that Apple Music page")
    found: list[Track] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if "artistName" in item and ("title" in item or "name" in item):
                found.append((str(item.get("title") or item.get("name")), str(item["artistName"])))
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(json.loads(data_match.group(1)))
    return name, list(dict.fromkeys(found))


def text_tracks(text: str) -> list[Track]:
    """One song per line: "Title - Artist", "Artist - Title" or just a title."""
    tracks = []
    for line in text.splitlines():
        line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
        if not line:
            continue
        title, _, artist = line.partition(" - ")
        tracks.append((title.strip(), artist.strip()))
    return tracks


def fetch_page(url: str) -> str:
    match = _SPOTIFY.search(url)
    if match:  # the embed page carries the track list without signing in
        url = f"https://open.spotify.com/embed/playlist/{match.group(1)}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 YTKTV"})
    with urlopen(request, timeout=20) as response:
        return str(response.read().decode("utf-8", "replace"))


def playlist_tracks(url: str, fetch: Callable[[str], str] | None = None) -> tuple[str, list[Track]]:
    html = (fetch or fetch_page)(url)
    return spotify_tracks(html) if _SPOTIFY.search(url) else apple_tracks(html)


def find_on_youtube(
    tracks: list[Track], search: Callable[[str, int], list[Song]], limit: int = LIMIT
) -> list[Song]:
    """A YouTube video for each song, a karaoke version when there is one; misses are skipped."""

    def one(track: Track) -> Song | None:
        title, artist = track
        try:
            results = search(f"{title} {artist} karaoke".strip(), 3)
        except Exception:
            return None
        return results[0] if results else None

    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(one, tracks[:limit]))
    return [song for song in dict.fromkeys(s for s in found if s is not None)]
