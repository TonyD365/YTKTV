"""Favorites and sung-history persistence."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ytktv.core.models import Song

log = logging.getLogger(__name__)


class Library:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._favorites: list[Song] = []
        self.history: list[Song] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._favorites = [Song.from_dict(s) for s in data.get("favorites", [])]
            self.history = [Song.from_dict(s) for s in data.get("history", [])]
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
