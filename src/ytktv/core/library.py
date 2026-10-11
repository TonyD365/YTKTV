"""Favorites and sung-history persistence."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ytktv.core.models import Song

log = logging.getLogger(__name__)

PLAYLIST_NAME_LENGTH = 60


class Library:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._favorites: list[Song] = []
        self._playlists: dict[str, list[Song]] = {}  # insertion order is display order
        self.history: list[Song] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._favorites = [Song.from_dict(s) for s in data.get("favorites", [])]
            self.history = [Song.from_dict(s) for s in data.get("history", [])]
            self._playlists = {
                str(name): [Song.from_dict(s) for s in songs]
                for name, songs in (data.get("playlists") or {}).items()
            }
        except Exception:
            log.exception("could not read library %s", self.path)

    def save(self, history: list[Song] | None = None) -> None:
        if self.path is None:
            return
        with self._lock:
            if history is not None:
                self.history = history
            data = {
                "favorites": [s.to_dict() for s in self._favorites],
                "history": [s.to_dict() for s in self.history],
                "playlists": {
                    name: [s.to_dict() for s in songs] for name, songs in self._playlists.items()
                },
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                log.exception("could not save library")

    def favorites(self) -> list[Song]:
        with self._lock:
            return list(self._favorites)

    def is_favorite(self, video_id: str) -> bool:
        with self._lock:
            return any(s.video_id == video_id for s in self._favorites)

    def add_favorite(self, song: Song) -> None:
        with self._lock:
            if not self.is_favorite(song.video_id):
                self._favorites.insert(0, song)
        self.save()

    def remove_favorite(self, video_id: str) -> None:
        with self._lock:
            self._favorites = [s for s in self._favorites if s.video_id != video_id]
        self.save()

    # -- playlists ----------------------------------------------------------

    @staticmethod
    def clean_playlist_name(name: str) -> str:
        """Normalise a name typed by a user; raises ValueError if nothing usable is left."""
        cleaned = " ".join(str(name).replace("/", " ").split())[:PLAYLIST_NAME_LENGTH]
        if not cleaned:
            raise ValueError("a playlist needs a name")
        return cleaned

    def playlist_names(self) -> list[str]:
        with self._lock:
            return list(self._playlists)

    def playlist(self, name: str) -> list[Song] | None:
        with self._lock:
            songs = self._playlists.get(name)
            return list(songs) if songs is not None else None

    def unique_playlist_name(self, wanted: str) -> str:
        """*wanted*, or "wanted (2)" and so on if that name is taken."""
        base = self.clean_playlist_name(wanted)
        with self._lock:
            name, counter = base, 2
            while name in self._playlists:
                suffix = f" ({counter})"
                name = base[: PLAYLIST_NAME_LENGTH - len(suffix)] + suffix
                counter += 1
            return name

    def create_playlist(self, name: str, songs: list[Song] | None = None) -> str:
        """Create a playlist and return its final name. Raises ValueError if it exists."""
        name = self.clean_playlist_name(name)
        with self._lock:
            if name in self._playlists:
                raise ValueError(f"there is already a playlist called {name!r}")
            unique: dict[str, Song] = {}
            for song in songs or []:
                unique.setdefault(song.video_id, song)
            self._playlists[name] = list(unique.values())
        self.save()
        return name

    def delete_playlist(self, name: str) -> bool:
        with self._lock:
            existed = self._playlists.pop(name, None) is not None
        if existed:
            self.save()
        return existed

    def add_to_playlist(self, name: str, song: Song) -> bool:
        """Returns False when the playlist does not exist or already has the song."""
        with self._lock:
            songs = self._playlists.get(name)
            if songs is None or any(s.video_id == song.video_id for s in songs):
                return False
            songs.append(song)
        self.save()
        return True

    def remove_from_playlist(self, name: str, video_id: str) -> bool:
        with self._lock:
            songs = self._playlists.get(name)
            if songs is None:
                return False
            kept = [s for s in songs if s.video_id != video_id]
            changed = len(kept) != len(songs)
            self._playlists[name] = kept
        if changed:
            self.save()
        return changed
