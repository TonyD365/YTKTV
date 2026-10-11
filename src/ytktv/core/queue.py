"""The song queue: what a KTV box calls "Selected" and "Sung"."""

from __future__ import annotations

import random
import threading
from collections import deque

from ytktv.core.models import QueueItem, Song

HISTORY_LIMIT = 200


class SongQueue:
    """Thread-safe queue of upcoming songs plus a bounded history of sung ones."""

    def __init__(self, history_limit: int = HISTORY_LIMIT) -> None:
        self._lock = threading.RLock()
        self._items: list[QueueItem] = []
        self._history: deque[Song] = deque(maxlen=history_limit)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def add(
        self, song: Song, singer: str = "", priority: bool = False, owner: str = ""
    ) -> QueueItem:
        item = QueueItem(song=song, singer=singer, owner=owner)
        with self._lock:
            if priority:
                self._items.insert(0, item)
            else:
                self._items.append(item)
        return item

    def _index(self, item_id: str) -> int:
        for i, item in enumerate(self._items):
            if item.id == item_id:
                return i
        return -1

    def remove(self, item_id: str) -> bool:
        with self._lock:
            i = self._index(item_id)
            if i < 0:
                return False
            del self._items[i]
            return True

    def prioritize(self, item_id: str) -> bool:
        """Move an item to the top of the queue so it plays next."""
        return self.move(item_id, 0)

    def move(self, item_id: str, index: int) -> bool:
        with self._lock:
            i = self._index(item_id)
            if i < 0:
                return False
            item = self._items.pop(i)
            index = max(0, min(index, len(self._items)))
            self._items.insert(index, item)
            return True

    def pop_next(self) -> QueueItem | None:
        with self._lock:
            return self._items.pop(0) if self._items else None

    def peek(self) -> QueueItem | None:
        with self._lock:
            return self._items[0] if self._items else None

    def shuffle(self) -> None:
        with self._lock:
            random.shuffle(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def snapshot(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items)

    def add_history(self, song: Song) -> None:
        with self._lock:
            if self._history and self._history[0].video_id == song.video_id:
                return
            self._history.appendleft(song)

    def history(self) -> list[Song]:
        with self._lock:
            return list(self._history)

    def load_history(self, songs: list[Song]) -> None:
        with self._lock:
            self._history.clear()
            self._history.extend(songs)
