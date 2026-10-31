"""Hold back background downloads while a song has just started.

The first seconds of a stream are when its buffer is thinnest. Separation, AI lyrics and
preloading the next songs all download too; started at the same moment they take the
bandwidth the video needs, and playback stalls. They wait until the song has settled.
"""

from __future__ import annotations

import threading
import time

SETTLE_SECONDS = 20.0


class Warmup:
    def __init__(self, seconds: float = SETTLE_SECONDS) -> None:
        self.seconds = seconds
        self._until = 0.0
        self._lock = threading.Lock()

    def started(self) -> None:
        """A song began playing."""
        with self._lock:
            self._until = time.monotonic() + self.seconds

    def wait(self) -> None:
        """Block a background download until the playing song has settled."""
        while True:
            with self._lock:
                left = self._until - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 1.0))


PLAYBACK = Warmup()  # shared by the controller and the background downloaders
