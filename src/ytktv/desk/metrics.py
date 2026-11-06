"""What the server console shows: requests, errors, room connections and this process's load.

Nothing here needs Qt, so the server records into it from any thread.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

KEEP_EVENTS = 7 * 86400  # server events are kept for a week


@dataclass
class Event:
    at: float
    kind: str  # "room", "terminal", "error" or "server"
    text: str


class Metrics:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.started = clock()
        self._lock = threading.Lock()
        self._requests: deque[float] = deque()
        self._errors: deque[float] = deque()
        self._events: deque[Event] = deque(maxlen=5000)
        self._cpu_at = (time.monotonic(), time.process_time())

    def request(self, status: int) -> None:
        now = self.clock()
        with self._lock:
            self._requests.append(now)
            if status >= 400:
                self._errors.append(now)
            self._prune(now)

    def event(self, kind: str, text: str) -> None:
        with self._lock:
            self._events.append(Event(self.clock(), kind, text))

    def _prune(self, now: float) -> None:
        while self._requests and self._requests[0] < now - 3600:
            self._requests.popleft()
        while self._errors and self._errors[0] < now - 3600:
            self._errors.popleft()
        while self._events and self._events[0].at < now - KEEP_EVENTS:
            self._events.popleft()

    def per_minute(self) -> int:
        now = self.clock()
        with self._lock:
            self._prune(now)
            return sum(1 for at in self._requests if at >= now - 60)

    def errors_last_hour(self) -> int:
        with self._lock:
            self._prune(self.clock())
            return len(self._errors)

    def events(self) -> list[Event]:
        with self._lock:
            self._prune(self.clock())
            return list(self._events)

    def uptime(self) -> float:
        return self.clock() - self.started

    def cpu_percent(self) -> float:
        """This process's CPU use since the last call, as a share of one core."""
        wall, cpu = time.monotonic(), time.process_time()
        last_wall, last_cpu = self._cpu_at
        self._cpu_at = (wall, cpu)
        return 100.0 * (cpu - last_cpu) / (wall - last_wall) if wall > last_wall else 0.0


def memory_mb() -> float | None:
    """This process's memory in MB, or None where it cannot be read."""
    try:
        import psutil  # type: ignore[import-untyped,unused-ignore]

        return float(psutil.Process(os.getpid()).memory_info().rss) / 2**20
    except ImportError:
        pass
    try:
        import resource
    except ImportError:  # Windows without psutil
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if os.uname().sysname == "Darwin" else peak / 1024  # bytes vs KB


def uptime_text(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}d {hours}h {minutes:02d}m" if days else f"{hours}h {minutes:02d}m"
