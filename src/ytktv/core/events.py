"""A tiny thread-safe publish/subscribe bus.

The controller publishes topics ("state", "position", "toast", "meters") and
the Qt UI and the WebSocket server subscribe. Callbacks run on the publishing
thread, so subscribers must hop to their own thread/loop themselves.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Listener = Callable[[str, Any], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def emit(self, topic: str, payload: Any = None) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(topic, payload)
            except Exception:
                log.exception("event listener failed for topic %r", topic)
